"""Server-only Keycloak management, scoped in code to CAS client roles."""
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError
from django.conf import settings
from rest_framework.exceptions import APIException, ValidationError

class ManagementUnavailable(APIException):
    status_code = 503
    default_detail = "Chiro Auth management is temporarily unavailable. Check the CAS provisioner configuration."

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

class KeycloakAdmin:
    def __init__(self):
        self.base = settings.KEYCLOAK_URL.rstrip("/")
        self.realm = quote(settings.KEYCLOAK_REALM, safe="")
        self.opener = build_opener(NoRedirect())
        client = settings.KEYCLOAK_ADMIN_CLIENT_ID
        secret = settings.KEYCLOAK_ADMIN_CLIENT_SECRET
        if not client or not secret:
            raise ManagementUnavailable("CAS backend is missing KEYCLOAK_ADMIN_CLIENT_ID or KEYCLOAK_ADMIN_CLIENT_SECRET. Set them in the terminal that starts Django, then restart the backend.")
        token = self.request("POST", f"/realms/{self.realm}/protocol/openid-connect/token", form={"grant_type":"client_credentials", "client_id":client,"client_secret":secret})
        self.token = token["access_token"]
        self.api = f"/admin/realms/{self.realm}"
        clients = self.request("GET", self.api + "/clients?" + urlencode({"clientId": settings.KEYCLOAK_AUDIENCE}))
        matches = [c for c in clients if c.get("clientId") == settings.KEYCLOAK_AUDIENCE]
        if len(matches) != 1: raise ManagementUnavailable()
        self.client_id = matches[0]["id"]

    def request(self, method, path, data=None, form=None):
        headers = {"Accept":"application/json"}
        if hasattr(self, "token"): headers["Authorization"] = "Bearer " + self.token
        body = None
        if form is not None:
            body = urlencode(form).encode(); headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif data is not None:
            body = json.dumps(data).encode(); headers["Content-Type"] = "application/json"
        try:
            with self.opener.open(Request(self.base + path, data=body, headers=headers, method=method), timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            if error.code == 409: raise ValidationError({"email":"An account or role already exists in Chiro Auth. Link an existing identity explicitly rather than creating a duplicate."}) from error
            if error.code == 401:
                raise ManagementUnavailable("Keycloak rejected the CAS provisioner credentials. Check the cas-provisioner client secret and enable service accounts.") from error
            if error.code == 403:
                raise ManagementUnavailable("The CAS provisioner lacks Keycloak management permissions. Check its service-account roles in the chirocity realm.") from error
            raise ManagementUnavailable() from error
        except (URLError, TimeoutError, ValueError, KeyError) as error: raise ManagementUnavailable() from error

    def roles(self):
        result = []
        while True:
            page = self.request("GET", self.api + f"/clients/{self.client_id}/roles?first={len(result)}&max=100")
            result.extend(page)
            if len(page) < 100: return result

    def ensure_role(self, name):
        if not any(r["name"] == name for r in self.roles()):
            self.request("POST", self.api + f"/clients/{self.client_id}/roles", {"name":name})

    def user_path(self, subject): return self.api + "/users/" + quote(subject, safe="")

    def create(self, data, password=None):
        self.request("POST", self.api + "/users", data)
        users = self.request("GET", self.api + "/users?" + urlencode({"username":data["username"],"exact":"true"}))
        matches = [u for u in users if u.get("username", "").lower() == data["username"].lower()]
        if len(matches) != 1: raise ManagementUnavailable()
        subject = matches[0]["id"]
        try:
            if password:
                self.request("PUT", self.user_path(subject) + "/reset-password", {"type":"password", "value":password,"temporary":True})
            return subject
        except Exception:
            self.delete(subject)
            raise

    def delete(self, subject): self.request("DELETE", self.user_path(subject))
    def enable(self, subject): self.request("PUT", self.user_path(subject), {"enabled":True})

    def applicant_memberships(self, subject):
        """Only unlink the dedicated root applicant group with CAS-only grants."""
        memberships = []
        first = 0
        while True:
            page = self.request("GET", self.user_path(subject) + f"/groups?first={first}&max=100")
            memberships.extend(page)
            if len(page) < 100: break
            first += len(page)
        removable = []
        for group in memberships:
            if group.get("name") != "CAS Applicants" or group.get("path") != "/CAS Applicants": continue
            group_id = quote(group["id"], safe="")
            mappings = self.request("GET", self.api + f"/groups/{group_id}/role-mappings")
            clients = mappings.get("clientMappings", {})
            safe = not mappings.get("realmMappings") and bool(clients)
            for client in clients.values():
                roles = client.get("mappings", [])
                safe = safe and client.get("id") == self.client_id and bool(roles)
                safe = safe and all(role.get("name") in {"CITIZEN", "Citizen"} and not role.get("composite") for role in roles)
            if not safe:
                raise ValidationError({"groups":"CAS Applicants contains additional grants. Remove this membership in Keycloak to avoid changing other access."})
            removable.append(group_id)
        return removable

    def replace_roles(self, subject, names, *, remove_inherited_citizen=False):
        available = {r["name"]:r for r in self.roles()}
        if not set(names).issubset(available): raise ValidationError({"groups":"A selected role is missing in cas-api. Synchronize roles first."})
        if any(available[n].get("composite") for n in names):
            raise ValidationError({"groups":"Assign non-composite CAS roles here; manage composite roles in Chiro Auth."})
        path = self.user_path(subject) + f"/role-mappings/clients/{self.client_id}"
        current = self.request("GET", path)
        effective = self.request("GET", path + "/composite")
        inherited = {r["name"] for r in effective} - {r["name"] for r in current}
        if inherited - set(names) - {"CITIZEN", "Citizen"}: raise ValidationError({"groups":"Remove inherited CAS roles through the user's Keycloak group before changing this assignment."})
        remove_applicant = remove_inherited_citizen and not set(names).intersection({"CITIZEN", "Citizen"})
        memberships = self.applicant_memberships(subject) if remove_applicant and any(r["name"] in {"CITIZEN", "Citizen"} for r in effective) else []
        for group_id in memberships:
            self.request("DELETE", self.user_path(subject) + f"/groups/{group_id}")
        remove = [r for r in current if r["name"] not in names]
        add = [available[n] for n in names if n not in {r["name"] for r in current}]
        if remove: self.request("DELETE", path, remove)
        if add: self.request("POST", path, add)
        effective_names = {r["name"] for r in self.request("GET", path + "/composite")}
        # The effective endpoint deduplicates direct and inherited grants. A
        # default Citizen membership may therefore become visible only after
        # removing the same directly assigned role.
        unexpected = effective_names - set(names) - (set() if remove_inherited_citizen else {"CITIZEN", "Citizen"})
        if unexpected:
            raise ValidationError({"groups":"The user still inherits another CAS role. Remove that assignment through the user's Keycloak group before changing this role."})
        if set(names) - effective_names:
            raise ManagementUnavailable("Keycloak did not retain the selected CAS role. Retry the update or check its role mappings.")
        return sorted(effective_names)
