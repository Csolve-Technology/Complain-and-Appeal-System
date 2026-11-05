import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from .chiro_auth import jwks_client
from .models import Case, Office

@override_settings(CAS_REQUIRE_VERIFIED_EMAIL=True, AUTH_MODE="keycloak", ALLOWED_HOSTS=["testserver"], KEYCLOAK_REALM="chirocity", KEYCLOAK_CLIENT_ID="cas-web", KEYCLOAK_AUDIENCE="cas-api")
class ChiroAuthTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key(), as_dict=True)
        public.update(kid="cas-test", use="sig", alg="RS256")
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"keys": [public]}).encode())
            def log_message(self, *args): pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.issuer = cls.url + "/realms/chirocity"
        cls.config = override_settings(KEYCLOAK_URL=cls.url); cls.config.enable()
    @classmethod
    def tearDownClass(cls):
        cls.config.disable(); cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); jwks_client.cache_clear()
        super().tearDownClass()
    @classmethod
    def setUpTestData(cls):
        call_command("bootstrap_admin", verbosity=0)
    def setUp(self): self.client = APIClient()
    def claims(self):
        return dict(sub="verified-subject", iss=self.issuer, aud="cas-api", iat=int(time.time()), exp=int(time.time())+300, typ="Bearer", azp="cas-web", email="citizen@example.com", email_verified=True, given_name="CAS", family_name="User", resource_access={"cas-api": {"roles": ["CITIZEN"]}})
    def token(self, **changes):
        claims = self.claims(); claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "cas-test"})
    def get(self, token=None, path="/api/auth/me/"):
        return self.client.get(path, HTTP_AUTHORIZATION="Bearer " + (token or self.token()))
    def test_verified_identity_gets_local_profile_and_unusable_password(self):
        response = self.get(); self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["user_groups"], ["Citizen"])
        user = get_user_model().objects.get(pk=response.data["id"])
        self.assertFalse(user.has_usable_password()); self.assertEqual(user.keycloak_sub, "verified-subject")
        self.assertFalse(user.is_superuser); self.assertFalse(user.is_staff)
    def test_rejects_wrong_issuer_audience_client_type_and_expiry(self):
        for change in [dict(iss="https://other/realms/chirocity"), dict(aud="hrms-api"), dict(azp="hrms-web"), dict(typ="ID"), dict(exp=int(time.time())-20)]:
            with self.subTest(change=change): self.assertEqual(self.get(self.token(**change)).status_code, 401)
        self.assertFalse(get_user_model().objects.exists())
    def test_rejects_missing_expiration(self):
        claims = self.claims(); claims.pop("exp")
        self.assertEqual(self.get(jwt.encode(claims, self.key, algorithm="RS256", headers={"kid":"cas-test"})).status_code, 401)
    def test_rejects_legacy_hmac_and_unsigned_tokens(self):
        for algorithm, key in [("HS256", "old-local-secret-12345678901234567890"), ("none", None)]:
            self.assertEqual(self.get(jwt.encode(self.claims(), key, algorithm=algorithm)).status_code, 401)
    def test_rejects_other_rsa_signing_key(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.assertEqual(self.get(jwt.encode(self.claims(), other, algorithm="RS256", headers={"kid":"cas-test"})).status_code, 401)
    def test_realm_and_other_client_roles_grant_nothing(self):
        for access in [{}, {"hrms-api":{"roles":["ADMIN"]}}, {"cas-api":{"roles":["UNKNOWN"]}}, {"cas-api":{"roles":"ADMIN"}}]:
            self.assertEqual(self.get(self.token(resource_access=access, realm_access={"roles":["ADMIN"]})).status_code, 403)
        self.assertFalse(get_user_model().objects.exists())
    def test_email_must_be_verified(self):
        self.assertEqual(self.get(self.token(email_verified=False)).status_code, 403)
    def test_existing_email_is_never_automatically_linked(self):
        user = get_user_model().objects.create_user(username="old", email="citizen@example.com")
        self.assertEqual(self.get().status_code, 403); user.refresh_from_db(); self.assertIsNone(user.keycloak_sub)
    def test_linked_id_cases_office_retained_but_old_privileges_removed(self):
        office = Office.objects.create(name="Existing office")
        user = get_user_model().objects.create_user(username="old", email="citizen@example.com", keycloak_sub="verified-subject", keycloak_issuer=self.issuer, is_superuser=True, is_staff=True, office=office)
        user.groups.add(Group.objects.get(name="Admin")); user.user_permissions.add(Permission.objects.first())
        case = Case.objects.create(citizen_id=user, title="Existing case")
        response = self.get(); self.assertEqual(response.status_code, 200, response.data); self.assertEqual(response.data["id"], user.pk)
        user.refresh_from_db(); self.assertEqual(user.office_id, office.pk); self.assertEqual(case.citizen_id_id, user.pk)
        self.assertFalse(user.is_staff); self.assertFalse(user.is_superuser); self.assertFalse(user.user_permissions.exists())
        self.assertEqual(list(user.groups.values_list("name", flat=True)), ["Citizen"])
    def test_disabled_and_deleted_users_remain_denied(self):
        user = get_user_model().objects.create_user(username="disabled", keycloak_sub="verified-subject", keycloak_issuer=self.issuer, is_active=False)
        self.assertEqual(self.get().status_code, 403)
        user.is_active=True; user.is_deleted=True; user.save(); self.assertEqual(self.get().status_code, 403)
        user.is_deleted=False; user.status="deleted"; user.save(); self.assertEqual(self.get().status_code, 403)
    def test_identity_issuer_must_match(self):
        get_user_model().objects.create_user(username="old", keycloak_sub="verified-subject", keycloak_issuer="https://old/realms/chirocity")
        self.assertEqual(self.get().status_code, 403)
    def test_client_roles_map_to_workflow_groups(self):
        for role, group in [("ADMIN","Admin"),("MAYOR_OFFICE","Mayor Office"),("DIRECTOR","Director"),("FOCAL_PERSON","Focal Person"),("CITIZEN","Citizen")]:
            with self.subTest(role=role):
                response=self.get(self.token(resource_access={"cas-api":{"roles":[role]}})); self.assertEqual(response.status_code,200,response.data); self.assertEqual(response.data["user_groups"],[group])
    def test_all_granted_roles_are_retained_with_primary_role_first(self):
        response=self.get(self.token(resource_access={"cas-api":{"roles":["CITIZEN","ADMIN"]}}))
        self.assertEqual(response.data["user_groups"],["Admin", "Citizen"])
    def test_citizens_only_see_own_cases(self):
        user_id = self.get().data["id"]
        other = get_user_model().objects.create_user(username="other")
        own = Case.objects.create(citizen_id_id=user_id,title="Own case")
        Case.objects.create(citizen_id=other,title="Other case")
        response=self.get(path="/api/cases/"); self.assertEqual(response.status_code,200,response.data)
        self.assertEqual([case["id"] for case in response.data],[own.pk])
    def test_local_password_and_admin_endpoints_are_disabled(self):
        for path in ["/api/login/","/api/password/change/","/api/password/forgot/","/api/password/reset/","/admin/login/"]:
            self.assertEqual(self.client.post(path,{}).status_code,403)
    def test_registration_and_local_role_updates_are_disabled(self):
        response=self.client.post("/api/users/",{"username":"bypass","password":"password"}); self.assertEqual(response.status_code,401,response.data)
        user_id=self.get().data["id"]
        response=self.client.patch(f"/api/users/{user_id}/",{"groups":["Admin"]},format="json",HTTP_AUTHORIZATION="Bearer "+self.token()); self.assertEqual(response.status_code,403,response.data)
    def test_removed_roles_deny_even_previously_provisioned_user(self):
        self.assertEqual(self.get().status_code,200)
        self.assertEqual(self.get(self.token(resource_access={})).status_code,403)
    def test_profile_without_token_is_denied(self): self.assertEqual(self.client.get("/api/auth/me/").status_code,401)
    def test_repeated_authentication_does_not_write_to_sqlite(self):
        self.assertEqual(self.get().status_code,200)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as captured: self.assertEqual(self.get().status_code,200)
        writes=[q['sql'] for q in captured if q['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE'))]
        self.assertEqual(writes, [])

    @override_settings(CAS_REQUIRE_VERIFIED_EMAIL=False)
    def test_optional_email_confirmation_still_requires_audience_and_citizen_role(self):
        response=self.get(self.token(email_verified=False))
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['user_groups'],['Citizen'])
        self.assertEqual(self.get(self.token(email_verified=False, aud='account')).status_code,401)
        self.assertEqual(self.get(self.token(email_verified=False,resource_access={})).status_code,403)
        self.assertEqual(self.get(self.token(email_verified=False,email='')).status_code,403)

    @override_settings(CAS_REQUIRE_VERIFIED_EMAIL=False)
    def test_optional_confirmation_never_links_existing_email(self):
        user=get_user_model().objects.create_user(username='existing', email='citizen@example.com')
        self.assertEqual(self.get(self.token(email_verified=False)).status_code,403)
        user.refresh_from_db(); self.assertIsNone(user.keycloak_sub)

    @override_settings(CAS_REQUIRE_VERIFIED_EMAIL=False)
    def test_public_config_reports_confirmation_policy(self):
        response=self.client.get('/api/auth/config/')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.data['requireVerifiedEmail'])

    def test_custom_role_permissions_are_resolved_from_only_cas_client(self):
        group=Group.objects.create(name="Case auditor")
        group.permissions.add(Permission.objects.get(content_type__app_label="cas_app",codename="view_case"))
        token=self.token(resource_access={"cas-api":{"roles":["Case auditor"]}})
        response=self.get(token)
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data["user_groups"],["Case auditor"])
        self.assertIn("cas_app.view_case",response.data["permissions"])
        self.assertEqual(self.get(token,path="/api/cases/").status_code,200)
        self.assertEqual(self.get(token,path="/api/users/").status_code,403)
    def test_applicant_with_default_group_and_staff_role_is_not_forced_to_citizen_scope(self):
        response=self.get(self.token(resource_access={"cas-api":{"roles":["ADMIN","CITIZEN"]}}))
        self.assertEqual(response.status_code,200,response.data)
        other=get_user_model().objects.create_user(username="other")
        case=Case.objects.create(citizen_id=other,title="Staff case")
        response=self.get(self.token(resource_access={"cas-api":{"roles":["ADMIN","CITIZEN"]}}),path="/api/cases/")
        self.assertIn(case.pk,[item["id"] for item in response.data])
    def test_stale_token_cannot_restore_removed_role(self):
        response=self.get();user=get_user_model().objects.get(pk=response.data["id"])
        user.keycloak_roles_valid_after=int(time.time())+1;user.save()
        self.assertEqual(self.get().status_code,401)
    def test_applicant_cannot_read_user_directory_or_change_ownership(self):
        user_id=self.get().data["id"]
        other=get_user_model().objects.create_user(username="someone-else")
        self.assertEqual(self.get(path="/api/users/").status_code,403)
        response=self.client.post("/api/cases/", {"citizen_id":other.pk,"reported_by":other.pk,"title":"Applicant case","status":"closed"}, format="json", HTTP_AUTHORIZATION="Bearer "+self.token())
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data["citizen_id"],user_id);self.assertEqual(response.data["reported_by"],user_id)
        self.assertEqual(response.data["status"],"pending")
