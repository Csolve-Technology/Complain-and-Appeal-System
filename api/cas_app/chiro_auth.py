from .identity_lifecycle import assert_active
"""Chiro Auth access-token verification and explicit local identity linkage."""
from functools import lru_cache
from urllib.parse import urlparse
import uuid
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

# Highest role wins: CAS workflows and citizen scoping expect one primary group.
ROLE_GROUPS = (
    (("ADMIN", "Admin"), "Admin"),
    (("MAYOR_OFFICE", "Mayor Office"), "Mayor Office"),
    (("DIRECTOR", "Director"), "Director"),
    (("FOCAL_PERSON", "Focal Person"), "Focal Person"),
    (("CITIZEN", "Citizen"), "Citizen"),
)

def auth_settings():
    mode = settings.AUTH_MODE
    url = settings.KEYCLOAK_URL.rstrip("/")
    realm = settings.KEYCLOAK_REALM
    return {"mode": mode, "url": url, "realm": realm, "clientId": settings.KEYCLOAK_CLIENT_ID, "requireVerifiedEmail": settings.CAS_REQUIRE_VERIFIED_EMAIL}

@lru_cache(maxsize=8)
def jwks_client(issuer):
    return jwt.PyJWKClient(issuer + "/protocol/openid-connect/certs", cache_jwk_set=True, lifespan=300, timeout=5)

def verify_token(token):
    issuer = settings.KEYCLOAK_URL.rstrip("/") + "/realms/" + settings.KEYCLOAK_REALM
    try:
        if jwt.get_unverified_header(token).get("alg") != "RS256":
            raise AuthenticationFailed("Invalid Chiro Auth access token.")
        key = jwks_client(issuer).get_signing_key_from_jwt(token)
        payload = jwt.decode(token, key.key, algorithms=["RS256"], issuer=issuer,
                             audience=settings.KEYCLOAK_AUDIENCE,
                             options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except jwt.PyJWTError as error:
        raise AuthenticationFailed("Invalid or expired Chiro Auth access token.") from error
    if payload.get("typ") != "Bearer" or payload.get("azp") != settings.KEYCLOAK_CLIENT_ID:
        raise AuthenticationFailed("Invalid Chiro Auth access token type or client.")
    return payload

def resolve_user(payload):
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise AuthenticationFailed("Invalid Chiro Auth identity.")
    assert_active(subject)
    resources = payload.get("resource_access", {})
    client = resources.get(settings.KEYCLOAK_AUDIENCE, {}) if isinstance(resources, dict) else {}
    roles = client.get("roles", []) if isinstance(client, dict) else []
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise PermissionDenied("Your account has not been granted access to CAS.")
    known = [name for aliases, name in ROLE_GROUPS if any(role in roles for role in aliases)]
    aliases = {alias for names, _ in ROLE_GROUPS for alias in names}
    custom = list(Group.objects.filter(name__in=[r for r in roles if r not in aliases]).values_list("name", flat=True))
    group_names = known + sorted(custom)
    if not group_names:
        raise PermissionDenied("Your account has not been granted access to CAS.")
    group_name = group_names[0]
    email = payload.get("email")
    if not isinstance(email, str) or not email or len(email) > 254:
        raise PermissionDenied("Your Chiro Auth account must include an email address.")
    if settings.CAS_REQUIRE_VERIFIED_EMAIL and payload.get("email_verified") is not True:
        raise PermissionDenied("Verify your email address in Chiro Auth before accessing CAS.")
    issuer = settings.KEYCLOAK_URL.rstrip("/") + "/realms/" + settings.KEYCLOAK_REALM
    User = get_user_model()
    try:
        with transaction.atomic():
            groups = list(Group.objects.filter(name__in=group_names))
            if len(groups) != len(group_names):
                raise PermissionDenied("CAS role permissions are not configured. Contact your administrator.")
            user = User.objects.select_for_update().filter(keycloak_sub=subject).first()
            if user:
                if payload.get("iat", 0) < user.keycloak_roles_valid_after:
                    raise AuthenticationFailed("Your CAS roles changed. Sign out and sign in again.")
                if not user.is_active or user.is_deleted or user.status != "active":
                    raise PermissionDenied("This CAS account is disabled.")
                if user.keycloak_issuer != issuer:
                    raise PermissionDenied("This CAS account is linked to another identity provider.")
            else:
                if User.objects.filter(email__iexact=email).exists():
                    raise PermissionDenied("A CAS account already uses this email. Ask your administrator to link it to Chiro Auth.")
                user = User(username="chiro_" + uuid.uuid4().hex, email=email.lower(), keycloak_sub=subject, keycloak_issuer=issuer)
                user.set_unusable_password()
            # Do not retain old local superuser status or direct permission grants.
            changes = []
            for field, value in (("is_staff", group_name == "Admin"), ("is_superuser", False)):
                if getattr(user, field) != value:
                    setattr(user, field, value); changes.append(field)
            for field in ("first_name", "last_name"):
                claim = payload.get("given_name" if field == "first_name" else "family_name")
                if isinstance(claim, str) and getattr(user, field) != claim[:150]:
                    setattr(user, field, claim[:150]); changes.append(field)
            if user.pk is None: user.save()
            elif changes: user.save(update_fields=changes)
            if set(user.groups.values_list("pk", flat=True)) != {g.pk for g in groups}: user.groups.set(groups)
            if user.user_permissions.exists(): user.user_permissions.clear()
            return user
    except IntegrityError as error:
        raise PermissionDenied("This identity conflicts with an existing CAS account. Contact your administrator.") from error

class ChiroAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if settings.AUTH_MODE != "keycloak":
            return JWTAuthentication().authenticate(request)
        parts = get_authorization_header(request).split()
        if not parts: return None
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            raise AuthenticationFailed("Use a Chiro Auth bearer token.")
        try: token = parts[1].decode("ascii")
        except UnicodeDecodeError as error: raise AuthenticationFailed("Invalid bearer token.") from error
        payload = verify_token(token)
        return resolve_user(payload), payload
    def authenticate_header(self, request): return "Bearer"

class CentralIdentityMiddleware:
    """Legacy password/session endpoints cannot bypass centralized authentication."""
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        if settings.AUTH_MODE == "keycloak" and (
            request.path.startswith("/admin/") or
            request.path in ("/api/login/", "/api/password/forgot/", "/api/password/reset/", "/api/password/change/")
        ):
            return JsonResponse({"detail": "Manage sign-in and passwords in Chiro Auth."}, status=403)
        return self.get_response(request)
