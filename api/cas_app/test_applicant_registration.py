from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


@override_settings(AUTH_MODE='keycloak')
class ApplicantRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        Group.objects.create(name='Citizen')
        self.client = APIClient()
        self.payload = dict(username='applicant', email='applicant@example.invalid', password='123456', first_name='New', last_name='Applicant', phone_number='0912345678')

    @patch('cas_app.applicant_registration.KeycloakAdmin')
    def test_signup_assigns_only_citizen_and_verified_email(self, management):
        management.return_value.create.return_value = 'new-subject'
        response = self.client.post('/api/auth/applicant-registration/', self.payload)
        self.assertEqual(response.status_code, 201, response.data)
        call = management.return_value.create.call_args
        self.assertTrue(call.args[0]['emailVerified'])
        self.assertFalse(call.kwargs['temporary'])
        management.return_value.replace_roles.assert_called_once_with('new-subject', ['CITIZEN'], remove_inherited_citizen=True)
        user = get_user_model().objects.get(username='applicant')
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Citizen'])
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)

    @patch('cas_app.applicant_registration.KeycloakAdmin')
    def test_public_cannot_assign_privileged_roles(self, management):
        response = self.client.post('/api/auth/applicant-registration/', {**self.payload, 'groups': ['Admin']})
        self.assertEqual(response.status_code, 400)
        management.assert_not_called()

    @patch('cas_app.applicant_registration.KeycloakAdmin')
    def test_duplicate_email_is_not_linked(self, management):
        get_user_model().objects.create(username='existing', email=self.payload['email'])
        response = self.client.post('/api/auth/applicant-registration/', self.payload)
        self.assertEqual(response.status_code, 400)
        management.assert_not_called()

    @patch('cas_app.applicant_registration.KeycloakAdmin')
    def test_failed_activation_rolls_back_and_removes_identity(self, management):
        from cas_app.keycloak_admin import ManagementUnavailable
        management.return_value.create.return_value = 'new-subject'
        management.return_value.enable.side_effect = ManagementUnavailable()
        response = self.client.post('/api/auth/applicant-registration/', self.payload)
        self.assertEqual(response.status_code, 503)
        management.return_value.delete.assert_called_once_with('new-subject')
        self.assertFalse(get_user_model().objects.filter(username='applicant').exists())
