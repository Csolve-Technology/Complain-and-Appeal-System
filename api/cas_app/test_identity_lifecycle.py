from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from . import identity_lifecycle as life
from .keycloak_admin import ManagementUnavailable

@override_settings(AUTH_MODE='keycloak', KEYCLOAK_URL='https://identity.invalid', KEYCLOAK_REALM='app')
class LifecycleTests(TestCase):
    def setUp(self):
        stub = patch('cas_app.identity_lifecycle.KeycloakAdmin')
        self.admin = stub.start().return_value
        self.addCleanup(stub.stop)
        self.admin.api = '/admin/realms/app'
    def target(self, subject='subject', issuer='https://identity.invalid/realms/app'):
        link = SimpleNamespace(keycloak_sub=subject, keycloak_issuer=issuer)
        return link
    def test_enabled_user_allowed(self):
        self.admin.request.return_value = {'id':'subject','enabled':True}
        life.assert_active('subject')
    def test_disabled_user_denied_despite_valid_jwt(self):
        self.admin.request.return_value = {'id':'subject','enabled':False}
        with self.assertRaises(PermissionDenied): life.assert_active('subject')
    def test_deleted_user_denied_despite_valid_jwt(self):
        self.admin.request.return_value = None
        with self.assertRaises(AuthenticationFailed): life.assert_active('subject')
    def test_outage_is_not_a_deletion(self):
        self.admin.request.side_effect = ManagementUnavailable()
        with self.assertRaises(ManagementUnavailable): life.assert_active('subject')
    def test_delete_targets_subject_and_accepts_missing(self):
        life.delete_identity(self.target())
        self.admin.request.assert_called_once_with('DELETE','/admin/realms/app/users/subject',missing_ok=True)
    def test_delete_wrong_realm_is_rejected(self):
        with self.assertRaises(ValidationError): life.delete_identity(self.target(issuer='https://other'))
        self.admin.request.assert_not_called()
    def test_failed_delete_propagates(self):
        self.admin.request.side_effect = ManagementUnavailable()
        with self.assertRaises(ManagementUnavailable): life.delete_identity(self.target())
    def test_disable_revokes_sessions(self):
        life.set_enabled(self.target(),False)
        self.assertEqual(self.admin.request.call_args_list[0].args,('PUT','/admin/realms/app/users/subject',{'enabled':False}))
        self.assertEqual(self.admin.request.call_args_list[1].args,('POST','/admin/realms/app/users/subject/logout'))
    def test_unlinked_profile_does_not_delete_remote(self):
        life.delete_identity(self.target(subject=None,issuer=None))
        self.admin.request.assert_not_called()
    def test_list_uses_paginated_central_directory(self):
        self.admin.request.side_effect = [[{'id':str(i)} for i in range(100)],[{'id':'last'}]]
        qs = MagicMock()
        life.visible_users(qs)
        self.assertEqual(self.admin.request.call_count,2)
        qs.filter.assert_called_once()
    def test_malformed_directory_fails_closed(self):
        self.admin.request.return_value = {'error':'unexpected'}
        with self.assertRaises(ManagementUnavailable): life.visible_users(MagicMock())
    def test_authentication_calls_live_check_before_provisioning(self):
        from .chiro_auth import resolve_user
        with patch('cas_app.chiro_auth.assert_active',side_effect=AuthenticationFailed('Deleted')) as check:
            with self.assertRaises(AuthenticationFailed): resolve_user({'sub':'subject'})
            check.assert_called_once_with('subject')

    def test_deleted_link_is_hidden_but_unlinked_profile_is_retained(self):
        User = get_user_model()
        alive = User.objects.create_user(username='alive', email='alive@example.invalid')
        deleted = User.objects.create_user(username='gone', email='gone@example.invalid')
        unlinked = User.objects.create_user(username='legacy', email='legacy@example.invalid')
        User.objects.filter(pk=alive.pk).update(keycloak_sub='alive-sub',keycloak_issuer=life.issuer())
        User.objects.filter(pk=deleted.pk).update(keycloak_sub='gone-sub',keycloak_issuer=life.issuer())
        self.admin.request.return_value = [{'id':'alive-sub'}]
        visible = set(life.visible_users(User.objects.all()).values_list('pk',flat=True))
        self.assertEqual(visible, {alive.pk, unlinked.pk})
        self.assertTrue(User.objects.filter(pk=deleted.pk).exists())

    def test_delete_action_removes_central_identity_and_keeps_history_profile(self):
        from rest_framework.test import APIClient
        User = get_user_model()
        admin = User.objects.create_user(username='admin', email='admin@example.invalid', is_active=True)
        target = User.objects.create_user(username='target', email='target@example.invalid', is_active=True)
        from django.contrib.auth.models import Group, Permission
        role, _ = Group.objects.get_or_create(name='Admin')
        role.permissions.set(Permission.objects.all())
        admin.groups.add(role)
        User.objects.filter(pk=admin.pk).update(keycloak_sub='admin-sub', keycloak_issuer=life.issuer())
        User.objects.filter(pk=target.pk).update(keycloak_sub='target-sub', keycloak_issuer=life.issuer())
        self.admin.request.return_value = [{'id':'admin-sub'}, {'id':'target-sub'}]
        client = APIClient()
        client.force_authenticate(admin)
        response = client.delete('/api/users/' + str(target.pk) + '/')
        self.assertEqual(response.status_code,204,getattr(response,'data',None))
        self.assertTrue(User.objects.filter(pk=target.pk).exists())
        target.refresh_from_db()
        self.assertFalse(target.is_active)
        self.assertTrue(any(call.args[:2] == ('DELETE','/admin/realms/app/users/target-sub') for call in self.admin.request.call_args_list))
