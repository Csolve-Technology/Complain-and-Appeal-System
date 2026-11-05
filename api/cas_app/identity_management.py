"""Provision identities first, then activate only after the CAS profile is saved."""
import math
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from .keycloak_admin import KeycloakAdmin
from .chiro_auth import ROLE_GROUPS

ROLE_NAMES = {name: aliases[0] for aliases, name in ROLE_GROUPS}
def remote_name(group): return ROLE_NAMES.get(group.name, group.name)
def local_groups(role_names):
    aliases = {alias:name for names,name in ROLE_GROUPS for alias in names}
    names = {aliases.get(role, role) for role in role_names}
    groups = list(Group.objects.filter(name__in=names))
    if len(groups) != len(names): raise ValidationError({"groups":"Synchronize roles before assigning them."})
    return groups

def issuer(): return settings.KEYCLOAK_URL.rstrip("/") + "/realms/" + settings.KEYCLOAK_REALM

def ensure_group(name): KeycloakAdmin().ensure_role(ROLE_NAMES.get(name, name))

def sync_groups():
    aliases = {alias:name for names,name in ROLE_GROUPS for alias in names}
    names = []
    for role in KeycloakAdmin().roles():
        name = aliases.get(role["name"], role["name"])
        Group.objects.get_or_create(name=name)  # Imported roles begin with no permissions.
        names.append(name)
    return names

def create_user(actor, serializer):
    values = serializer.validated_data
    email = values.get("email", "").strip()
    if not email: raise ValidationError({"email":"Email is required for Chiro Auth accounts."})
    password = values.pop("password", None)
    if not password: raise ValidationError({"password":"Enter an initial temporary password for this Chiro Auth account."})
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    try: validate_password(password)
    except DjangoValidationError as error: raise ValidationError({"password":error.messages}) from error
    manager = KeycloakAdmin()
    subject = manager.create({"username":values["username"],"email":email,"emailVerified":True,"enabled":False,"firstName":values.get("first_name", ""),"lastName":values.get("last_name", ""),"requiredActions":["UPDATE_PASSWORD"]}, password)
    try:
        effective = manager.replace_roles(subject, [remote_name(g) for g in values["groups"]])
        values["groups"] = local_groups(effective)
        with transaction.atomic():
            user = serializer.save(added_by=actor, keycloak_sub=subject, keycloak_issuer=issuer())
            user.set_unusable_password(); user.save(update_fields=["password"])
            manager.enable(subject)
    except Exception:
        manager.delete(subject)
        raise

def update_user(actor, serializer):
    values, user = serializer.validated_data, serializer.instance
    if {"password", "username", "email"}.intersection(values):
        raise PermissionDenied("Manage usernames, emails and passwords in Chiro Auth.")
    if "groups" not in values:
        serializer.save(status_changed_by=actor); return
    if not user.keycloak_sub or user.keycloak_issuer != issuer():
        raise ValidationError({"groups":"This CAS profile must first be explicitly linked to its Chiro Auth identity."})
    # Commit revocation barrier before remote changes, even if the remote call fails.
    # Old tokens can never undo role removal during the synchronization window.
    user.keycloak_roles_valid_after = math.ceil(timezone.now().timestamp())
    user.save(update_fields=["keycloak_roles_valid_after"])
    effective = KeycloakAdmin().replace_roles(user.keycloak_sub, [remote_name(g) for g in values["groups"]])
    values["groups"] = local_groups(effective)
    serializer.save(status_changed_by=actor)
