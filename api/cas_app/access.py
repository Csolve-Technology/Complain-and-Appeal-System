"""Shared action permissions; ownership and office restrictions remain additional checks."""
from rest_framework.permissions import BasePermission

ACTION_VERBS = {"list": "view", "retrieve": "view", "create": "add", "update": "change", "partial_update": "change", "destroy": "delete"}
EXTRA = {
    "toggle_active": ("cas_app.change_announcement",),
    "change_status": ("cas_app.change_case",), "mark_seen": ("cas_app.view_case",),
    "submit_feedback": ("cas_app.view_case", "cas_app.add_casefeedback"),
    "submit_appeal": ("cas_app.view_case", "cas_app.add_case"),
    "by_case": None, "assignable_users": ("cas_app.add_assignment",),
    "current_user_hierarchy": (), "transfer_targets": ("cas_app.add_transfer",),
    "users": ("auth.view_group", "cas_app.view_user"),
    "add_users": ("auth.change_group", "cas_app.change_user"),
    "remove_users": ("auth.change_group", "cas_app.change_user"),
    "set_users": ("auth.change_group", "cas_app.change_user"),
    "list_permissions": ("auth.view_group",), "all_permissions": ("auth.view_group",),
    "add_permissions": ("auth.change_group",), "remove_permissions": ("auth.change_group",),
    "set_permissions": ("auth.change_group",), "sync_roles": ("auth.add_group",),
    "mark_read": (), "mark_all_read": (), "unread_count": (),
}

def can(user, permission):
    return bool(user and user.is_authenticated and user.has_perm(permission))

def group_permissions(groups):
    return {f"{p.content_type.app_label}.{p.codename}" for g in groups for p in g.permissions.select_related("content_type").all()}

def check_grants(actor, groups, existing=()):
    from rest_framework.exceptions import PermissionDenied
    # Delegation cannot manufacture permissions the actor does not hold.
    if not actor.is_superuser and not (group_permissions(groups) | group_permissions(existing)).issubset(actor.get_all_permissions()):
        raise PermissionDenied("You cannot manage roles with permissions beyond your own access.")

class ActionPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated: return False
        action = getattr(view, "action", "")
        model = getattr(view, "permission_model", None)
        if not model: return False
        # Notifications are a personal inbox, not a role-managed directory.
        if model == "cas_app.notification":
            return action in {"list", "retrieve", "destroy", "mark_read", "mark_all_read", "unread_count"}
        if model == "cas_app.user" and action in {"retrieve", "update", "partial_update"}:
            if str(view.kwargs.get("pk")) == str(user.pk): return True
        if model == "cas_app.user" and action == "assignable_roles":
            return can(user, "cas_app.add_user") or can(user, "cas_app.change_user")
        required = EXTRA.get(action)
        if action in ACTION_VERBS:
            app, name = model.split(".")
            required = (f"{app}.{ACTION_VERBS[action]}_{name}",)
        elif action == "by_case":
            app, name = model.split(".")
            required = (f"{app}.view_{name}",)
        elif model == "cas_app.case" and action not in EXTRA:
            required = ("cas_app.view_case",)
        elif getattr(view, "basename", "") == "reports":
            required = ("cas_app.view_case",)
        return required is not None and all(can(user, p) for p in required)

class PermissionMixin:
    def get_permissions(self):
        return [ActionPermission()]
