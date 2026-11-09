from io import BytesIO
from urllib.request import Request
from urllib.error import HTTPError
from unittest.mock import Mock
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError
from .keycloak_admin import KeycloakAdmin, ManagementUnavailable, ManagementConnection
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def response(body=b'{}', status=200, headers=None):
    result = BytesIO(body)
    result.status, result.headers = status, headers or {}
    return result


class ManagementTransportTests(SimpleTestCase):
    def manager(self):
        manager = KeycloakAdmin.__new__(KeycloakAdmin)
        manager.base = 'https://identity.example.invalid'
        manager.token = 'test-only'
        manager.api = '/admin/realms/test'
        manager.opener = Mock()
        return manager

    def test_retries_a_dropped_read(self):
        manager = self.manager()
        manager.opener.open.side_effect = [TimeoutError(), response()]
        self.assertEqual(manager.request('GET', '/roles'), {})
        self.assertEqual(manager.opener.open.call_count, 2)

    def test_account_creation_is_not_replayed(self):
        manager = self.manager()
        manager.opener.open.side_effect = TimeoutError()
        with self.assertRaisesMessage(ManagementUnavailable, 'could not connect'):
            manager.request('POST', '/users', {'username': 'test-only'})
        self.assertEqual(manager.opener.open.call_count, 1)

    def test_token_request_can_retry_without_creating_an_account(self):
        manager = self.manager()
        manager.opener.open.side_effect = [TimeoutError(), response(b'{"access_token":"test-only"}')]
        self.assertEqual(manager.request('POST', '/token', form={'grant_type': 'client_credentials'})['access_token'], 'test-only')
        self.assertEqual(manager.opener.open.call_count, 2)

    def test_creation_location_avoids_an_additional_identity_search(self):
        manager = self.manager()
        manager.request = Mock(side_effect=[{'_location': 'https://identity.example.invalid/users/new-subject'}, None])
        self.assertEqual(manager.create({'username': 'new-user'}, 'test-only-password'), 'new-subject')
        self.assertEqual([call.args[0] for call in manager.request.call_args_list], ['POST', 'PUT'])

    def test_missing_selected_role_is_created_without_assigning_or_regranting_permissions(self):
        manager = self.manager()
        manager.client_id = 'cas-client'
        manager.roles = Mock(side_effect=[[{'name': 'ADMIN'}], [{'name': 'ADMIN'}, {'name': 'DIRECTOR', 'id': 'director'}]])
        manager.request = Mock()
        available = manager.ensure_roles(['DIRECTOR'])
        self.assertEqual(available['DIRECTOR']['id'], 'director')
        manager.request.assert_called_once_with('POST', '/admin/realms/test/clients/cas-client/roles', {'name': 'DIRECTOR'})

    def test_existing_role_is_not_recreated(self):
        manager = self.manager()
        manager.client_id = 'cas-client'
        manager.roles = Mock(return_value=[{'name': 'CITIZEN', 'id': 'citizen'}])
        manager.request = Mock()
        self.assertEqual(manager.ensure_roles(['CITIZEN'])['CITIZEN']['id'], 'citizen')
        manager.request.assert_not_called()

    def test_password_policy_rejection_is_validation_not_an_outage(self):
        manager = self.manager()
        manager.opener.open.side_effect = HTTPError(manager.base, 400, 'policy', {}, BytesIO())
        with self.assertRaises(ValidationError) as caught:
            manager.request('PUT', '/users/test/reset-password', {})
        self.assertIn('password', caught.exception.detail)

    def test_credentials_and_permissions_have_distinct_errors(self):
        for code, message in [(401, 'credentials'), (403, 'management permissions')]:
            manager = self.manager()
            manager.opener.open.side_effect = HTTPError(manager.base, code, 'test-only', {}, BytesIO())
            with self.assertRaisesMessage(ManagementUnavailable, message):
                manager.request('GET', '/roles')
            self.assertEqual(manager.opener.open.call_count, 1)

    def test_reuses_connection_and_does_not_follow_redirects(self):
        ports = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                ports.append(self.client_address[1])
                redirect = self.path == '/redirect'
                self.send_response(302 if redirect else 200)
                if redirect:
                    self.send_header('Location', '/not-followed')
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        transport = ManagementConnection(base)
        try:
            for path in ['/one', '/two']:
                with transport.open(Request(base + path)) as result:
                    self.assertEqual(result.read(), b'{}')
            self.assertEqual(ports[0], ports[1])
            with self.assertRaises(HTTPError) as caught:
                transport.open(Request(base + '/redirect'))
            self.assertEqual(caught.exception.code, 302)
            self.assertEqual(len(ports), 3)
            with self.assertRaises(ValueError):
                transport.open(Request('https://another.example.invalid/users'))
        finally:
            transport.close()
            server.shutdown()
            server.server_close()
            thread.join()
