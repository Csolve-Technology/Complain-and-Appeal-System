"""Realm-scoped live account checks; no positive status cache or event plugin."""
from urllib.parse import quote
from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from .keycloak_admin import KeycloakAdmin, ManagementUnavailable

def issuer():
    return settings.KEYCLOAK_URL.rstrip('/') + '/realms/' + settings.KEYCLOAK_REALM

def close(admin):
    if hasattr(admin, 'close'): admin.close()
    else: admin.opener.close()

def assert_active(subject):
    admin = KeycloakAdmin()
    try:
        user = admin.request('GET', admin.api + '/users/' + quote(subject, safe=''), missing_ok=True)
        if user is None: raise AuthenticationFailed('This Chiro Auth account was deleted.')
        if not isinstance(user, dict) or user.get('id') != subject or not isinstance(user.get('enabled'), bool):
            raise ManagementUnavailable('Invalid Chiro Auth account response.')
        if not user['enabled']: raise PermissionDenied('This Chiro Auth account is disabled.')
    finally:
        close(admin)

def identity(user):
    link = user
    subject, provider = getattr(link, 'keycloak_sub', None), getattr(link, 'keycloak_issuer', None)
    if subject and provider != issuer(): raise ValidationError('This account belongs to another realm. Review its identity link.')
    return subject

def set_enabled(user, enabled):
    subject = identity(user)
    if not subject: return
    admin = KeycloakAdmin()
    try:
        path = admin.api + '/users/' + quote(subject, safe='')
        admin.request('PUT', path, {'enabled': enabled}, missing_ok=not enabled)
        if not enabled: admin.request('POST', path + '/logout', missing_ok=True)
    finally:
        close(admin)

def delete_identity(user):
    subject = identity(user)
    if not subject: return
    admin = KeycloakAdmin()
    try:
        admin.request('DELETE', admin.api + '/users/' + quote(subject, safe=''), missing_ok=True)
    finally:
        close(admin)

def visible_users(queryset):
    if settings.AUTH_MODE != 'keycloak': return queryset
    admin = KeycloakAdmin()
    ids = []
    try:
        first = 0
        while True:
            batch = admin.request('GET', admin.api + '/users?first=' + str(first) + '&max=100&briefRepresentation=true')
            if not isinstance(batch, list) or any(not isinstance(u, dict) or not isinstance(u.get('id'), str) for u in batch):
                raise ManagementUnavailable('Invalid Chiro Auth user directory response.')
            ids.extend(u['id'] for u in batch)
            if len(batch) < 100: break
            first += 100
    finally:
        close(admin)
    return queryset.filter(Q(keycloak_sub__isnull=True) | Q(keycloak_issuer=issuer(), keycloak_sub__in=ids))
