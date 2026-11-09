from unittest.mock import patch, Mock
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from .models import Case, Office
from .keycloak_admin import KeycloakAdmin, ManagementUnavailable

@override_settings(AUTH_MODE="keycloak", ALLOWED_HOSTS=["testserver"])
class PermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls): call_command("bootstrap_admin", verbosity=0)
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(username="tester", email="tester@example.com")
        self.group = Group.objects.create(name="Custom reviewer")
        self.user.groups.add(self.group)
        self.client.force_authenticate(self.user)
    def grant(self, *names):
        for name in names:
            app, code = name.split(".")
            self.group.permissions.add(Permission.objects.get(content_type__app_label=app, codename=code))
        for attr in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
            self.user.__dict__.pop(attr, None)
    def test_custom_role_without_grants_cannot_access_directories_or_cases(self):
        for path in ["users", "groups", "offices", "cases", "assignments", "transfers", "feedbacks", "announcements", "reports/summary"]:
            with self.subTest(path=path): self.assertEqual(self.client.get(f"/api/{path}/").status_code, 403)
    def test_granted_directory_access_does_not_require_builtin_role(self):
        self.grant("cas_app.view_user")
        self.assertEqual(self.client.get("/api/users/").status_code, 200)
        self.assertEqual(self.client.post("/api/users/", {}, format="json").status_code, 403)
    def test_custom_read_only_role_cannot_write(self):
        self.grant("cas_app.view_case", "cas_app.view_office")
        case = Case.objects.create(citizen_id=self.user, title="Read only")
        self.assertEqual(self.client.get("/api/cases/").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/cases/{case.pk}/", {"title":"Forbidden"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(f"/api/cases/{case.pk}/change_status/", {"status":"closed"}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/offices/", {"name":"Forbidden"}, format="json").status_code, 403)
    def test_grant_removal_takes_effect_on_next_request(self):
        self.grant("cas_app.view_user")
        self.assertEqual(self.client.get("/api/users/").status_code,200)
        self.group.permissions.clear()
        self.client.force_authenticate(get_user_model().objects.get(pk=self.user.pk))
        self.assertEqual(self.client.get("/api/users/").status_code,403)
    def test_profile_response_exposes_effective_permissions(self):
        self.grant("cas_app.view_user")
        self.assertIn("cas_app.view_user", self.client.get("/api/auth/me/").data["permissions"])
    def test_self_profile_cannot_assign_roles_or_disable_other_users(self):
        self.assertEqual(self.client.patch(f"/api/users/{self.user.pk}/", {"groups":["Admin"]},format="json").status_code,403)
        self.assertEqual(self.client.patch(f"/api/users/{self.user.pk}/", {"status":"active"},format="json").status_code,403)
    def test_custom_user_creator_cannot_grant_admin(self):
        self.grant("cas_app.add_user")
        with patch("cas_app.identity_management.KeycloakAdmin") as manager:
            response=self.client.post("/api/users/", {"username":"new","email":"new@example.com","password":"Strong-example-763!","groups":["Admin"]},format="json")
        self.assertEqual(response.status_code,403); manager.assert_not_called()
    def test_role_manager_cannot_grant_unowned_permissions(self):
        self.grant("auth.add_group", "auth.change_group", "auth.view_group")
        target=Group.objects.create(name="New role")
        admin_permission=Permission.objects.get(content_type__app_label="cas_app",codename="delete_user")
        response=self.client.put(f"/api/groups/{target.pk}/set_permissions/", {"permission_ids":[admin_permission.pk]},format="json")
        self.assertEqual(response.status_code,403)
        self.assertFalse(target.permissions.exists())
    def test_admin_created_identity_has_temp_password_roles_and_unusable_local_password(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        for attr in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]: self.user.__dict__.pop(attr,None)
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            manager=cls.return_value; manager.create.return_value="new-keycloak-subject"; manager.replace_roles.return_value=["CITIZEN"]
            response=self.client.post("/api/users/", {"username":"new","email":"new@example.com","first_name":"New","password":"Strong-example-763!","groups":["Citizen"]},format="json")
            self.assertEqual(response.status_code,201,response.data)
            data, password=manager.create.call_args.args
            self.assertTrue(data["emailVerified"]); self.assertFalse(data["enabled"])
            self.assertEqual(data["requiredActions"],["UPDATE_PASSWORD"])
            manager.replace_roles.assert_called_once_with("new-keycloak-subject",["CITIZEN"])
            manager.enable.assert_called_once_with("new-keycloak-subject")
        user=get_user_model().objects.get(username="new")
        self.assertFalse(user.has_usable_password()); self.assertEqual(user.keycloak_sub,"new-keycloak-subject")
        self.assertNotIn("password",response.data)
    def test_six_character_numeric_password_is_accepted_without_strength_validation(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            manager = cls.return_value
            manager.create.return_value = "six-character-subject"
            manager.replace_roles.return_value = ["CITIZEN"]
            result = self.client.post("/api/users/", {"username":"six-character", "email":"six@example.com", "password":"123456", "groups":["Citizen"]}, format="json")
            self.assertEqual(result.status_code, 201, result.data)
            self.assertEqual(manager.create.call_args.args[1], "123456")
            self.assertFalse(get_user_model().objects.get(username="six-character").has_usable_password())

    def test_fewer_than_six_characters_are_rejected_before_provisioning(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            result = self.client.post("/api/users/", {"username":"too-short", "email":"short@example.com", "password":"12345", "groups":["Citizen"]}, format="json")
            self.assertEqual(result.status_code, 400)
            self.assertIn("password", result.data)
            cls.assert_not_called()

    def test_common_six_character_password_is_accepted(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            manager = cls.return_value
            manager.create.return_value = "common-password-subject"
            manager.replace_roles.return_value = ["CITIZEN"]
            result = self.client.post("/api/users/", {"username":"common-password", "email":"common@example.com", "password":"aaaaaa", "groups":["Citizen"]}, format="json")
            self.assertEqual(result.status_code, 201, result.data)
            self.assertEqual(manager.create.call_args.args[1], "aaaaaa")

    def test_remote_role_failure_cleans_up_disabled_identity(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            manager=cls.return_value;manager.create.return_value="failed-subject"
            manager.replace_roles.side_effect=ManagementUnavailable()
            response=self.client.post("/api/users/", {"username":"failed","email":"failed@example.com","password":"Strong-example-763!","groups":["Citizen"]},format="json")
            self.assertEqual(response.status_code,503)
            manager.delete.assert_called_once_with("failed-subject");manager.enable.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(username="failed").exists())
    def test_role_import_preserves_existing_grants_and_new_roles_are_empty(self):
        self.grant("auth.add_group", "cas_app.view_case")
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            cls.return_value.roles.return_value=[{"name":"Custom reviewer"},{"name":"Audit clerk"}]
            self.assertEqual(self.client.post("/api/groups/sync-roles/").status_code,200)
        self.assertTrue(self.group.permissions.exists());self.assertFalse(Group.objects.get(name="Audit clerk").permissions.exists())
    def test_role_change_sets_stale_token_barrier_and_synchronizes(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        target=get_user_model().objects.create_user(username="target",keycloak_sub="target-sub",keycloak_issuer=settings.KEYCLOAK_URL.rstrip("/")+"/realms/"+settings.KEYCLOAK_REALM)
        target.groups.add(Group.objects.get(name="Director"))
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            cls.return_value.replace_roles.return_value=["CITIZEN"]
            response=self.client.patch(f"/api/users/{target.pk}/", {"groups":["Citizen"]},format="json")
            self.assertEqual(response.status_code,200,response.data)
            cls.return_value.replace_roles.assert_called_once_with("target-sub",["CITIZEN"],remove_inherited_citizen=True)
        target.refresh_from_db();self.assertGreater(target.keycloak_roles_valid_after,0)
        self.assertEqual(list(target.groups.values_list("name",flat=True)),["Citizen"])
    def test_failed_role_update_still_revokes_old_tokens(self):
        self.user.groups.set([Group.objects.get(name="Admin")])
        target=get_user_model().objects.create_user(username="target",keycloak_sub="target-sub",keycloak_issuer=settings.KEYCLOAK_URL.rstrip("/")+"/realms/"+settings.KEYCLOAK_REALM)
        with patch("cas_app.identity_management.KeycloakAdmin") as cls:
            cls.return_value.replace_roles.side_effect=ManagementUnavailable()
            self.assertEqual(self.client.patch(f"/api/users/{target.pk}/", {"groups":["Citizen"]},format="json").status_code,503)
        target.refresh_from_db();self.assertGreater(target.keycloak_roles_valid_after,0)
    def test_missing_provisioner_secret_is_safe_503(self):
        with override_settings(KEYCLOAK_ADMIN_CLIENT_SECRET=""):
            with self.assertRaises(ManagementUnavailable): KeycloakAdmin()
    @override_settings(AUTH_MODE="local")
    def test_anonymous_local_signup_cannot_choose_privileged_role(self):
        self.client.force_authenticate(None)
        response=self.client.post("/api/users/", {"username":"public","email":"public@example.com","password":"Strong-example-763!","groups":["Admin"]},format="json")
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data["groups"],["Citizen"])

    def test_assignable_roles_are_limited_to_owned_permissions(self):
        self.grant("cas_app.add_user")
        response=self.client.get("/api/users/assignable-roles/")
        self.assertEqual(response.status_code,200,response.data)
        self.assertNotIn("Admin",[item["name"] for item in response.data])
    def test_custom_reader_scope_is_own_cases_until_scope_granted(self):
        self.grant("cas_app.view_case")
        other=get_user_model().objects.create_user(username="other")
        own=Case.objects.create(citizen_id=self.user,title="Own")
        foreign=Case.objects.create(citizen_id=other,title="Other")
        self.assertEqual([item["id"] for item in self.client.get("/api/cases/").data],[own.pk])
        self.grant("cas_app.view_all_cases")
        self.assertEqual({item["id"] for item in self.client.get("/api/cases/").data},{own.pk,foreign.pk})
    def test_empty_custom_role_does_not_expand_default_applicant_scope(self):
        self.user.groups.add(Group.objects.get(name="Citizen"))
        other=get_user_model().objects.create_user(username="other")
        Case.objects.create(citizen_id=other,title="Other")
        self.assertEqual(self.client.get("/api/cases/").data,[])
    def test_assignment_grant_cannot_attach_to_foreign_case_without_scope(self):
        self.grant("cas_app.add_assignment")
        other=get_user_model().objects.create_user(username="other")
        other.groups.add(Group.objects.get(name="Director"))
        case=Case.objects.create(citizen_id=other,title="Private")
        response=self.client.post("/api/assignments/", {"case_id":case.pk,"to_user_id":other.pk},format="json")
        self.assertEqual(response.status_code,403,response.data)


    def test_staff_picker_preserves_default_citizen_membership_without_full_profile(self):
        self.grant("cas_app.add_assignment")
        target=get_user_model().objects.create_user(username="staff",email="private@example.com",national_id="private-id")
        target.groups.set([Group.objects.get(name="Citizen"),Group.objects.get(name="Director")])
        response=self.client.get("/api/assignments/assignable-users/")
        self.assertEqual(response.status_code,200,response.data)
        match=next(u for u in response.data if u["id"]==target.pk)
        self.assertNotIn("email",match);self.assertNotIn("national_id",match)


class ManagementRoleTests(TestCase):
    def manager(self):
        manager=KeycloakAdmin.__new__(KeycloakAdmin)
        manager.api="/admin/realms/chirocity";manager.client_id="cas-id"
        manager.roles=Mock(return_value=[{"name":"CITIZEN","id":"citizen"},{"name":"ADMIN","id":"admin"}])
        return manager
    def test_other_client_roles_never_appear_in_assignment_paths(self):
        manager=self.manager();manager.request=Mock(side_effect=[[{"name":"ADMIN","id":"admin"}],[{"name":"ADMIN","id":"admin"}],None,None,[{"name":"CITIZEN","id":"citizen"}]])
        manager.replace_roles("subject",["CITIZEN"])
        self.assertTrue(all("/clients/cas-id" in call.args[1] for call in manager.request.call_args_list))
        self.assertEqual([call.args[0] for call in manager.request.call_args_list],["GET","GET","DELETE","POST","GET"])
    def test_inherited_roles_cannot_be_silently_removed(self):
        manager=self.manager();manager.request=Mock(side_effect=[[],[{"name":"ADMIN"}]])
        with self.assertRaises(ValidationError): manager.replace_roles("subject",["CITIZEN"])
        self.assertEqual(manager.request.call_count,2)

    def test_default_applicant_membership_is_preserved_for_staff_assignments(self):
        manager=self.manager();manager.request=Mock(side_effect=[[],[{"name":"CITIZEN"}],None,[{"name":"ADMIN"},{"name":"CITIZEN"}]])
        self.assertEqual(manager.replace_roles("subject",["ADMIN"]),["ADMIN","CITIZEN"])

    def test_changing_direct_citizen_role_preserves_hidden_default_group_grant(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[
            [{"name":"CITIZEN","id":"citizen"}],
            [{"name":"CITIZEN","id":"citizen"}],
            None, None,
            [{"name":"ADMIN","id":"admin"},{"name":"CITIZEN","id":"citizen"}],
        ])
        self.assertEqual(manager.replace_roles("subject",["ADMIN"]),["ADMIN","CITIZEN"])
        self.assertEqual([call.args[0] for call in manager.request.call_args_list],["GET","GET","DELETE","POST","GET"])

    def test_hidden_inherited_privileged_role_cannot_be_treated_as_removed(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[
            [{"name":"ADMIN","id":"admin"}],
            [{"name":"ADMIN","id":"admin"}],
            None, None,
            [{"name":"ADMIN","id":"admin"},{"name":"CITIZEN","id":"citizen"}],
        ])
        with self.assertRaises(ValidationError): manager.replace_roles("subject",["CITIZEN"])

    def test_missing_selected_role_still_fails_verification(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[[],[],None,[]])
        with self.assertRaises(ManagementUnavailable): manager.replace_roles("subject",["ADMIN"])

    def test_explicit_removal_leaves_dedicated_applicant_group(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[
            [{"name":"ADMIN","id":"admin"}],
            [{"name":"ADMIN","id":"admin"},{"name":"CITIZEN","id":"citizen"}],
            [{"id":"applicants","name":"CAS Applicants","path":"/CAS Applicants"}],
            {"clientMappings":{"cas-api":{"id":"cas-id","mappings":[{"name":"CITIZEN","composite":False}]}}},
            None,
            [{"name":"ADMIN","id":"admin"}],
        ])
        self.assertEqual(manager.replace_roles("subject",["ADMIN"],remove_inherited_citizen=True),["ADMIN"])
        self.assertIn(("DELETE","/admin/realms/chirocity/users/subject/groups/applicants"),[call.args for call in manager.request.call_args_list])

    def test_applicant_group_with_other_app_grants_is_never_removed(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[
            [{"id":"applicants","name":"CAS Applicants","path":"/CAS Applicants"}],
            {"clientMappings":{"hrms-api":{"id":"hrms-id","mappings":[{"name":"ADMIN"}]}}},
        ])
        with self.assertRaises(ValidationError): manager.applicant_memberships("subject")
        self.assertTrue(all(call.args[0]=="GET" for call in manager.request.call_args_list))

    def test_role_from_another_group_cannot_report_successfully_removed(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[[],[{"name":"CITIZEN"}],[],None,[{"name":"ADMIN"},{"name":"CITIZEN"}]])
        with self.assertRaises(ValidationError): manager.replace_roles("subject",["ADMIN"],remove_inherited_citizen=True)

    def test_direct_citizen_can_be_removed_when_not_in_default_group(self):
        manager=self.manager()
        manager.request=Mock(side_effect=[[{"name":"CITIZEN"}],[{"name":"CITIZEN"}],[],None,[]])
        self.assertEqual(manager.replace_roles("subject",[],remove_inherited_citizen=True),[])
