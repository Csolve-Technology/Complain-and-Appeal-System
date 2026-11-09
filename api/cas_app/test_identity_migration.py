import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings


@override_settings(KEYCLOAK_URL='https://auth.chirocity.gov.et', KEYCLOAK_REALM='chiro-public')
class IdentityMigrationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='existing-admin', email='cas@example.com', keycloak_sub='old-subject', keycloak_issuer='https://auth.chirocity.gov.et/realms/chirocity')
        self.environment = patch.dict(os.environ, LINK_EMAIL=self.user.email, KEYCLOAK_SUB='new-subject')
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_explicit_migration_preserves_local_account(self):
        call_command('link_chiro_user', previous_subject='old-subject', previous_issuer=self.user.keycloak_issuer)
        self.user.refresh_from_db()
        self.assertEqual(self.user.keycloak_sub, 'new-subject')
        self.assertEqual(self.user.keycloak_issuer, 'https://auth.chirocity.gov.et/realms/chiro-public')
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(self.user.username, 'existing-admin')

    def test_rejects_unconfirmed_or_stale_migration(self):
        for options in ({}, {'previous_subject': 'wrong', 'previous_issuer': self.user.keycloak_issuer}):
            with self.assertRaises(CommandError):
                call_command('link_chiro_user', **options)
        self.user.refresh_from_db()
        self.assertEqual(self.user.keycloak_sub, 'old-subject')
