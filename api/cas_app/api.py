from .identity_lifecycle import visible_users, delete_identity
from django.conf import settings
from rest_framework.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .serializers import *
from .models import *
from django.db import transaction
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from datetime import datetime
from django.db.models import Count, Q
from django.utils.dateparse import parse_date

from .access import PermissionMixin, ActionPermission, can, check_grants

User = get_user_model()

class IsSelfOrStaff(permissions.BasePermission):
    """Allow users to see/update themselves; staff can access anyone."""
    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_authenticated and request.user.is_staff:
            return True
        return request.user.is_authenticated and obj.pk == request.user.pk


class IsDirectorOrAdmin(permissions.BasePermission):
    """Allow users with hierarchy level >= Director level or Admin users to access."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Admin users (staff/superuser)
        if request.user.is_staff or request.user.is_superuser:
            return True
        # Check hierarchy level dynamically (Director level is 3, Mayor Office is 4)
        user_hierarchy = get_user_role_hierarchy(request.user)
        if user_hierarchy and user_hierarchy.hierarchy_level >= 3:
            return True
        return False


class UserViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.user"
    queryset = User.objects.all().order_by("-id")
    serializer_class = UserSerializer
    # default; we'll override per-action in get_permissions()
    permission_classes = [permissions.IsAuthenticated]

    def get_permissions(self):
        if self.action == "create" and settings.AUTH_MODE == "local" and not self.request.user.is_authenticated:
            return [permissions.AllowAny()]
        return [ActionPermission()]

    @action(detail=False, methods=["get"], url_path="assignable-roles")
    def assignable_roles(self, request):
        from .access import group_permissions
        own = request.user.get_all_permissions()
        groups = [g for g in Group.objects.prefetch_related("permissions__content_type").all() if group_permissions([g]).issubset(own)]
        return Response([{"id":g.pk, "name":g.name} for g in groups])

    def get_serializer_context(self):
        """Add request to serializer context for absolute URLs."""
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        qs = visible_users(super().get_queryset().filter(is_deleted=False).exclude(status="deleted"))
        if can(self.request.user, "cas_app.view_user") or can(self.request.user, "cas_app.change_user"):
            if self.request.user.groups.filter(name="Focal Person").exists():
                return qs.filter(office=self.request.user.office) if self.request.user.office_id else qs.filter(pk=self.request.user.pk)
            return qs
        return qs.filter(pk=self.request.user.pk)

    def perform_create(self, serializer):
        from .identity_management import create_user
        groups = serializer.validated_data.get("groups") or [Group.objects.get(name="Citizen")]
        if not self.request.user.is_authenticated:
            groups = [Group.objects.get(name="Citizen")]
            serializer.validated_data["status"] = "active"
        else:
            check_grants(self.request.user, groups)
        serializer.validated_data["groups"] = groups
        if settings.AUTH_MODE == "keycloak":
            create_user(self.request.user, serializer)
        else:
            serializer.save(added_by=self.request.user if self.request.user.is_authenticated else None)

    def perform_update(self, serializer):
        from .identity_management import update_user
        actor, target = self.request.user, serializer.instance
        sensitive = {"groups", "status", "office", "username", "email", "password"}
        if not can(actor, "cas_app.change_user") and sensitive.intersection(serializer.validated_data):
            raise PermissionDenied("You may update only your own profile details.")
        if "groups" in serializer.validated_data:
            check_grants(actor, serializer.validated_data["groups"], target.groups.all())
        if settings.AUTH_MODE == "keycloak":
            update_user(actor, serializer)
        else:
            serializer.save(status_changed_by=actor)

    def destroy(self, request, *args, **kwargs):
        # Only admins can destroy (permission enforced in get_permissions)
        instance = self.get_object()
        if instance.pk == request.user.pk:
            raise PermissionDenied('You cannot delete yourself.')
        check_grants(request.user, [], instance.groups.all())
        if instance.groups.filter(name='Admin').exists() and not User.objects.filter(groups__name='Admin', is_active=True, status='active', is_deleted=False).exclude(pk=instance.pk).exists():
            raise PermissionDenied('Keep at least one active administrator.')
        if settings.AUTH_MODE == 'keycloak': delete_identity(instance)
        instance.is_active = False
        instance.is_deleted = True
        instance.deleted_by = request.user
        instance.status = "deleted"
        instance.save(update_fields=["deleted_by", "status", "is_active", "is_deleted"])
        return Response({"message": "User marked as deleted successfully."}, status=status.HTTP_204_NO_CONTENT)


def is_citizen(user):
    return user.is_authenticated and not can(user, "cas_app.view_all_cases")


def get_user_hierarchy_level(user):
    """Get the hierarchy level of a user's primary role. Returns None if no hierarchy configured."""
    if not user or not user.is_authenticated:
        return None
    user_groups = user.groups.all()
    if not user_groups.exists():
        return None
    
    # Get hierarchy for the first group (assuming single primary role)
    try:
        hierarchy = RoleHierarchy.objects.filter(role__in=user_groups).order_by("-hierarchy_level").first()
        return hierarchy.hierarchy_level if hierarchy else None
    except RoleHierarchy.DoesNotExist:
        return None


def get_user_role_hierarchy(user):
    """Get the RoleHierarchy object for a user's primary role."""
    if not user or not user.is_authenticated:
        return None
    user_groups = user.groups.all()
    if not user_groups.exists():
        return None
    
    try:
        return RoleHierarchy.objects.filter(role__in=user_groups).order_by("-hierarchy_level").first()
    except RoleHierarchy.DoesNotExist:
        return None


def can_transfer_between_roles(from_user, to_office_representative):
    """
    Check if a transfer is allowed based on hierarchy.
    Transfers can only go upward (to higher hierarchy levels).
    """
    from_hierarchy = get_user_role_hierarchy(from_user)
    if not from_hierarchy:
        return False, "Your role does not have transfer permissions configured."
    
    if not to_office_representative:
        return False, "Target office has no representative assigned."
    
    to_hierarchy = get_user_role_hierarchy(to_office_representative)
    if not to_hierarchy:
        return False, "Target office representative's role does not have hierarchy configured."
    
    # Check if transfer is explicitly allowed
    if from_hierarchy.can_transfer_to.filter(id=to_hierarchy.role.id).exists():
        return True, None
    
    # Fallback: check hierarchy level (upward only)
    if to_hierarchy.hierarchy_level > from_hierarchy.hierarchy_level:
        return True, None
    
    return False, f"Transfers can only go upward in hierarchy. Your level ({from_hierarchy.hierarchy_level}) cannot transfer to level ({to_hierarchy.hierarchy_level})."


class CaseAccessPermission(BasePermission):
    """
    - Citizens: can list/retrieve ONLY their cases; can create only for themselves;
                can update/partial_update their own cases;
                can submit_feedback / submit_appeal / mark_seen on their own cases;
                cannot destroy/change_status.
    - Staff/Admins (non-citizen or superuser): full access.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if is_citizen(user):
            allowed_actions = {
                "list", "retrieve", "create",
                "update", "partial_update",
                "submit_feedback", "submit_appeal", "mark_seen",
            }
            action = getattr(view, "action", None)
            if action in allowed_actions:
                return True
            if request.method in SAFE_METHODS:
                return True
            return False

        # staff/admins
        return True

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # staff/admins get full object access
        if not is_citizen(user) or user.is_superuser:
            return True

        # citizens: object must be theirs
        is_owner = (obj.citizen_id_id == user.id)

        if request.method in SAFE_METHODS and is_owner:
            return True

        action = getattr(view, "action", None)

        # allow retrieve / update / partial_update on own case
        if action in {"retrieve", "update", "partial_update"} and is_owner:
            return True

        # allow mark_seen / submit_feedback / submit_appeal on own case
        if action in {"mark_seen", "submit_feedback", "submit_appeal"} and is_owner:
            return True

        if action == "create":
            return True

        return False


class CaseViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.case"
    """
    CRUD for Case with:
    - citizen scoping (citizens only see their cases)
    - soft delete
    - status change tracking (history)
    - mark seen
    - feedback & appeal (citizen-owned only)
    """
    queryset = (
        Case.objects
        .filter(deleted_by__isnull=True)
        .select_related("citizen_id", "reported_by", "office_id", "added_by", "status_changed_by", "last_seen_by", "parent_case")
    )
    serializer_class = CaseSerializer
    permission_classes = [permissions.IsAuthenticated, CaseAccessPermission]

    def get_permissions(self):
        return [ActionPermission(), CaseAccessPermission()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # Citizens only see their own cases
        if is_citizen(user):
            return qs.filter(citizen_id=user)

        # Staff/admins see all (already filtered by deleted_by__isnull)
        return qs

    def create(self, request, *args, **kwargs):
        # Handle file attachments if present in request.FILES
        attachments_data = []
        has_files = hasattr(request, 'FILES') and 'attachments' in request.FILES
        
        if has_files:
            files = request.FILES.getlist('attachments')
            import base64
            for file in files:
                # Read file content and encode as base64
                file_content = file.read()
                base64_content = base64.b64encode(file_content).decode('utf-8')
                attachments_data.append({
                    'name': file.name,
                    'type': file.content_type or 'application/octet-stream',
                    'size': file.size,
                    'data': f"data:{file.content_type or 'application/octet-stream'};base64,{base64_content}"
                })
        
        # If attachments are in request.data as JSON, use those instead (only if no files)
        if not attachments_data and 'attachments' in request.data:
            att_value = request.data['attachments']
            # Handle JSON string from FormData
            if isinstance(att_value, str):
                import json
                try:
                    att_value = json.loads(att_value)
                except (json.JSONDecodeError, ValueError):
                    pass  # Keep as string if not valid JSON
            if isinstance(att_value, list):
                attachments_data = att_value
        
        # Create a mutable dict from request.data
        # Convert QueryDict to regular dict to ensure proper deletion
        if hasattr(request.data, 'dict'):
            data = request.data.dict()
        elif hasattr(request.data, 'copy'):
            data = dict(request.data.copy())
        else:
            data = dict(request.data)
        
        # Remove 'attachments' from data if files are present in FILES to avoid serializer validation error
        # Django REST Framework's multipart parser might add it as empty string or invalid value
        if has_files and 'attachments' in data:
            data.pop('attachments', None)
        
        # Set attachments_data (either from files or from request.data JSON)
        if attachments_data:
            data['attachments'] = attachments_data
        elif not has_files and 'attachments' not in data:
            # If no files and no attachments_data, ensure attachments is not in data
            # (let serializer use default or None)
            pass
        
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        instance = self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        # If the creator is a citizen, force the case owner to be themselves
        if is_citizen(self.request.user):
            case = serializer.save(added_by=self.request.user, citizen_id=self.request.user, reported_by=self.request.user, status="pending", parent_case=None)
        else:
            # Staff/internal can create for any citizen; if citizen_id missing, default to current user
            if not can(self.request.user, "cas_app.view_user"):
                serializer.validated_data["reported_by"] = self.request.user
            citizen = serializer.validated_data.get("citizen_id") or self.request.user
            case = serializer.save(added_by=self.request.user, citizen_id=citizen)

        CaseStatusHistory.objects.create(
            case=case,
            status=case.status,
            changed_by=self.request.user
        )
        return case

    def update(self, request, *args, **kwargs):
        """
        Allow citizens to edit ONLY specific fields on their own cases;
        staff can edit everything. Still track status history on real status changes.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()  # object-level permission already checked
        previous_status = instance.status

        data = request.data.copy()

        # If editor is a citizen, restrict editable fields
        if is_citizen(request.user):
            # choose the fields you want citizens to be able to change:
            allowed = {"title", "description", "attachments", "channel"}
            # Option A: silently drop forbidden fields
            for key in list(data.keys()):
                if key not in allowed:
                    data.pop(key, None)

        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        instance.refresh_from_db()
        if instance.status != previous_status:
            instance.status_changed_by = request.user
            instance.save(update_fields=["status_changed_by"])
            CaseStatusHistory.objects.create(
                case=instance,
                status=instance.status,
                changed_by=request.user
            )

        return Response(self.get_serializer(instance).data)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()  # object permission checked
        # Citizens are blocked by permission class; staff proceed:
        instance.deleted_by = request.user
        instance.save(update_fields=["deleted_by"])
        return Response({"message": "Case marked as deleted."}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def change_status(self, request, pk=None):
        """POST { 'status': 'resolved' } -> updates status + records history (staff only)."""
        if is_citizen(request.user):
            return Response({"detail": "Not permitted."}, status=403)

        instance = self.get_object()
        new_status = request.data.get("status")
        valid = dict(Case.STATUS_CHOICES).keys()
        if new_status not in valid:
            return Response({"detail": f"Invalid status. Allowed: {', '.join(valid)}"}, status=400)

        if instance.status != new_status:
            instance.status = new_status
            instance.status_changed_by = request.user
            instance.save(update_fields=["status", "status_changed_by"])
            CaseStatusHistory.objects.create(case=instance, status=new_status, changed_by=request.user)

        return Response(self.get_serializer(instance).data, status=200)

    @action(detail=True, methods=["post"])
    def mark_seen(self, request, pk=None):
        instance = self.get_object()  # object permission checked
        instance.last_seen_by = request.user
        instance.save(update_fields=["last_seen_by"])
        return Response({"message": "Marked as seen."}, status=200)

    @action(detail=True, methods=["post"])
    def submit_feedback(self, request, pk=None):
        case = self.get_object()  # object permission checked
        if case.citizen_id_id != request.user.id:
            return Response({"detail": "Only the case owner can submit feedback."}, status=403)
        if case.status != "closed":
            return Response({"detail": "Feedback can only be submitted after the case is Closed."}, status=400)

        ser = CaseFeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        from django.db import IntegrityError
        try:
            feedback = CaseFeedback.objects.create(
                case=case,
                created_by=request.user,
                rating=ser.validated_data["rating"],
                comment=ser.validated_data.get("comment", "")
            )
        except IntegrityError:
            return Response({"detail": "Feedback already submitted for this case by this user."}, status=400)

        CaseStatusHistory.objects.create(case=case, status=case.status, changed_by=request.user)
        return Response(CaseFeedbackSerializer(feedback).data, status=201)

    @transaction.atomic
    @action(detail=True, methods=["post"])
    def submit_appeal(self, request, pk=None):
        base_case = self.get_object()  # object permission checked
        if base_case.citizen_id_id != request.user.id:
            return Response({"detail": "Only the case owner can submit an appeal."}, status=403)
        if base_case.status != "closed":
            return Response({"detail": "Appeal can only be submitted after the case is Closed."}, status=400)

        to_office_id = request.data.get("to_office_id")
        reason = request.data.get("reason", "")

        target_office = base_case.office_id
        if to_office_id:
            try:
                target_office = Office.objects.get(pk=to_office_id)
            except Office.DoesNotExist:
                return Response({"detail": "to_office_id not found."}, status=400)

        appeal_case = Case.objects.create(
            parent_case=base_case,
            citizen_id=base_case.citizen_id,
            office_id=target_office,
            category_id="appeal",
            channel="web",
            priority=base_case.priority,
            status="pending",
            added_by=request.user,
        )
        CaseStatusHistory.objects.create(case=appeal_case, status="pending", changed_by=request.user)

        if reason:
            CaseFeedback.objects.create(case=appeal_case, created_by=request.user, rating=5, comment=f"[Appeal Reason] {reason}")

        return Response(self.get_serializer(appeal_case).data, status=201)


class OfficeViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.office"
    queryset = Office.objects.all().order_by("name")
    serializer_class = OfficeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        # auto-attach who created the office
        serializer.save(added_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        # update tracking
        serializer.save(updated_by=self.request.user)
        
class TransferViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.transfer"
    """
    Creates a transfer and, on success, updates the case.office_id to the destination office.
    Enforces upward hierarchy only - transfers can only go to higher level roles.
    """
    queryset = Transfer.objects.select_related("case_id", "from_office_id", "to_office_id")
    serializer_class = TransferSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if is_citizen(self.request.user): return qs.filter(case_id__citizen_id=self.request.user)
        return qs

    def create(self, request, *args, **kwargs):
        # Validate hierarchy before creating transfer
        to_office_id = request.data.get("to_office_id")
        if not to_office_id:
            return Response(
                {"detail": "to_office_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            to_office = Office.objects.get(pk=to_office_id)
        except Office.DoesNotExist:
            return Response(
                {"detail": "Target office not found."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if transfer is allowed based on hierarchy
        can_transfer, error_msg = can_transfer_between_roles(
            request.user,
            to_office.office_representative
        )
        
        if not can_transfer:
            return Response(
                {"detail": error_msg or "Transfer not allowed."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().create(request, *args, **kwargs)

    def validate_case_scope(self, case):
        if case.deleted_by_id or (is_citizen(self.request.user) and case.citizen_id_id != self.request.user.pk):
            raise PermissionDenied("You cannot manage activity for this case.")

    def perform_update(self, serializer):
        self.validate_case_scope(serializer.validated_data.get("case_id", serializer.instance.case_id))
        office = serializer.validated_data.get("to_office_id", serializer.instance.to_office_id)
        allowed, reason = can_transfer_between_roles(self.request.user, office.office_representative)
        if not allowed: raise PermissionDenied(reason or "Transfer not allowed.")
        serializer.save()

    @transaction.atomic
    def perform_create(self, serializer):
        self.validate_case_scope(serializer.validated_data["case_id"])
        transfer = serializer.save()
        # reflect the office move on the case
        case = transfer.case_id
        case.office_id = transfer.to_office_id
        case.status_changed_by = self.request.user  # optional: who performed the transfer
        case.save(update_fields=["office_id", "status_changed_by"])
        
        # Create notification for the target office representative
        to_office = transfer.to_office_id
        if to_office and to_office.office_representative:
            Notification.objects.create(
                user=to_office.office_representative,
                notification_type="case_transferred",
                title=f"Case Transferred to {to_office.name}",
                message=f"Case '{case.title or f'#{case.id}'}' has been transferred to your office.",
                related_case_id=case,
                related_transfer_id=transfer,
            )

    # Optional quick endpoint to fetch transfers of a case
    @action(detail=False, methods=["get"], url_path="by-case/(?P<case_pk>[^/.]+)")
    def by_case(self, request, case_pk=None):
        qs = self.get_queryset().filter(case_id_id=case_pk)
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)


class AssignmentViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.assignment"
    """
    Records a handover between users for a case.
    If from_user_id not supplied, default to request.user for convenience.
    
    Assignment rules:
    - Director/Mayor Office: Can assign to any office or users in any office (except Citizen)
    - Focal Person: Can only assign to users within their own office (except Citizen)
    """
    queryset = Assignment.objects.select_related("case_id", "from_user_id", "to_user_id")
    serializer_class = AssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if is_citizen(self.request.user): return qs.filter(case_id__citizen_id=self.request.user)
        return qs

    def create(self, request, *args, **kwargs):
        """Validate assignment permissions before creating."""
        to_user_id = request.data.get("to_user_id")
        if not to_user_id:
            return Response(
                {"detail": "to_user_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            to_user = User.objects.get(pk=to_user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "Target user not found."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if target user is Citizen (not allowed)
        if is_citizen(to_user):
            return Response(
                {"detail": "Cannot assign cases to Citizen role users."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get current user's role groups
        current_user_groups = [g.name for g in request.user.groups.all()]
        is_director = "Director" in current_user_groups
        is_mayor_office = "Mayor Office" in current_user_groups
        is_focal_person = "Focal Person" in current_user_groups
        
        # Director and Mayor Office can assign to any office/users
        if is_director or is_mayor_office:
            # Allowed - proceed
            pass
        elif is_focal_person:
            # Focal Person can only assign to users in their own office
            if not request.user.office:
                return Response(
                    {"detail": "You must be assigned to an office to assign cases."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            if to_user.office_id != request.user.office_id:
                return Response(
                    {"detail": "Focal Person can only assign cases to users within their own office."},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            # Other roles (Admin, etc.) - allow for now, or add specific rules
            pass
        
        return super().create(request, *args, **kwargs)

    def validate_case_scope(self, case):
        if case.deleted_by_id or (is_citizen(self.request.user) and case.citizen_id_id != self.request.user.pk):
            raise PermissionDenied("You cannot manage activity for this case.")

    def validate_assignment(self, serializer):
        self.validate_case_scope(serializer.validated_data.get("case_id", serializer.instance.case_id if serializer.instance else None))
        target = serializer.validated_data.get("to_user_id", serializer.instance.to_user_id if serializer.instance else None)
        if target is None or is_citizen(target): raise PermissionDenied("Assignments require an active staff recipient.")
        if not target.is_active or target.is_deleted or target.status != "active": raise PermissionDenied("The recipient is disabled.")
        if self.request.user.groups.filter(name="Focal Person").exists() and not self.request.user.groups.filter(name__in=["Admin", "Director", "Mayor Office"]).exists():
            if not self.request.user.office_id or self.request.user.office_id != target.office_id:
                raise PermissionDenied("You can assign only within your office.")

    def perform_update(self, serializer):
        self.validate_assignment(serializer)
        serializer.save()

    def perform_create(self, serializer):
        self.validate_assignment(serializer)
        from_user = serializer.validated_data.get("from_user_id")
        if not from_user:
            # Assume the current actor is handing over the case
            serializer.validated_data["from_user_id"] = self.request.user
        assignment = serializer.save()
        
        # Create notification for the assigned user
        to_user = assignment.to_user_id
        case = assignment.case_id
        if to_user:
            Notification.objects.create(
                user=to_user,
                notification_type="case_assigned",
                title=f"New Case Assignment",
                message=f"Case '{case.title or f'#{case.id}'}' has been assigned to you.",
                related_case_id=case,
                related_assignment_id=assignment,
            )

    # Optional quick endpoint to fetch assignments of a case
    @action(detail=False, methods=["get"], url_path="by-case/(?P<case_pk>[^/.]+)")
    def by_case(self, request, case_pk=None):
        qs = self.get_queryset().filter(case_id_id=case_pk)
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data)

    @action(detail=False, methods=["get"], url_path="assignable-users")
    def assignable_users(self, request):
        """
        Get list of users that the current user can assign cases to.
        - Director/Mayor Office: All users in any office (except Citizen)
        - Focal Person: Only users in their own office (except Citizen)
        """
        # Get current user's role groups
        current_user_groups = [g.name for g in request.user.groups.all()]
        is_director = "Director" in current_user_groups
        is_mayor_office = "Mayor Office" in current_user_groups
        is_focal_person = "Focal Person" in current_user_groups
        
        # Explicit staff scope keeps default Citizen + staff memberships assignable.
        qs = User.objects.filter(is_active=True, is_deleted=False, status="active", groups__permissions__content_type__app_label="cas_app", groups__permissions__codename="view_all_cases").distinct()

        # Filter based on role
        if can(request.user, "cas_app.add_assignment") and not is_focal_person:
            # Permission grants assignment access
            pass  # No additional filtering
        elif is_focal_person:
            # Can only assign to users in their own office
            if request.user.office:
                qs = qs.filter(office=request.user.office)
            else:
                # If focal person has no office, they can't assign to anyone
                qs = User.objects.none()
        else:
            # Other roles - default to empty or add specific rules
            qs = User.objects.none()
        
        # A picker needs names and IDs, not the protected full user profile.
        return Response([{"id":u.pk,"first_name":u.first_name,"last_name":u.last_name,"username":u.username,"office":u.office_id} for u in qs])
    

class RoleHierarchyViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.rolehierarchy"
    """
    Manage role hierarchy configuration.
    Only staff/superusers can modify hierarchy.
    """
    queryset = RoleHierarchy.objects.select_related("role").prefetch_related("can_transfer_to")
    serializer_class = RoleHierarchySerializer
    permission_classes = [permissions.IsAuthenticated]


    @action(detail=False, methods=["get"], url_path="current-user")
    def current_user_hierarchy(self, request):
        """Get the current user's role hierarchy information."""
        user_hierarchy = get_user_role_hierarchy(request.user)
        if not user_hierarchy:
            return Response(
                {"detail": "Your role does not have hierarchy configured."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(user_hierarchy)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="transfer-targets")
    def transfer_targets(self, request):
        """Get offices that the current user can transfer cases to (based on hierarchy)."""
        user_hierarchy = get_user_role_hierarchy(request.user)
        if not user_hierarchy:
            return Response(
                {"detail": "Your role does not have transfer permissions."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get roles that can receive transfers from current user
        allowed_roles = user_hierarchy.can_transfer_to.all()
        if not allowed_roles.exists():
            # Fallback: get roles with higher hierarchy level
            allowed_roles = Group.objects.filter(
                hierarchy__hierarchy_level__gt=user_hierarchy.hierarchy_level
            )
        
        # Get offices with representatives in allowed roles
        offices = Office.objects.filter(
            office_representative__groups__in=allowed_roles,
            is_active=True
        ).distinct().select_related("office_representative")
        
        from .serializers import OfficeSerializer
        serializer = OfficeSerializer(offices, many=True)
        return Response(serializer.data)


class IsAdminGroup(BasePermission):
    """Only users with Admin group can manage roles."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Check if user is in Admin group
        user_groups = [g.name for g in request.user.groups.all()]
        return "Admin" in user_groups or request.user.is_superuser


class GroupViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "auth.group"
    """
    /groups/                      GET, POST
    /groups/{id}/                 GET, PUT, PATCH, DELETE

    Custom:
    /groups/{id}/users/           GET
    /groups/{id}/add_users/       POST { "user_ids": [1,2] }
    /groups/{id}/remove_users/    POST { "user_ids": [1,2] }
    /groups/{id}/set_users/       PUT  { "user_ids": [1,2] }

    /groups/{id}/permissions/     GET
    /groups/{id}/add_permissions/ POST { "permission_ids": [10,11] }
    /groups/{id}/remove_permissions/ POST { "permission_ids": [10,11] }
    /groups/{id}/set_permissions/ PUT  { "permission_ids": [10,11] }
    """
    queryset = Group.objects.all().prefetch_related("permissions", "user_set")
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def perform_create(self, serializer):
        from .identity_management import ensure_group
        self.check_permission_grants(serializer.validated_data.get("permissions", []))
        if settings.AUTH_MODE == "keycloak": ensure_group(serializer.validated_data["name"])
        serializer.save()

    def perform_update(self, serializer):
        check_grants(self.request.user, [], [serializer.instance])
        self.check_permission_grants(serializer.validated_data.get("permissions", []))
        if settings.AUTH_MODE == "keycloak" and serializer.validated_data.get("name", serializer.instance.name) != serializer.instance.name:
            raise PermissionDenied("Synchronized role names cannot be renamed here.")
        serializer.save()

    def perform_destroy(self, instance):
        if settings.AUTH_MODE == "keycloak":
            raise PermissionDenied("Delete synchronized roles in Chiro Auth after removing their assignments.")
        check_grants(self.request.user, [], [instance])
        instance.delete()

    def check_permission_grants(self, permissions):
        names = {f"{p.content_type.app_label}.{p.codename}" for p in permissions}
        if not self.request.user.is_superuser and not names.issubset(self.request.user.get_all_permissions()):
            raise PermissionDenied("You cannot grant permissions beyond your own access.")

    @action(detail=False, methods=["post"], url_path="sync-roles")
    def sync_roles(self, request):
        from .identity_management import sync_groups
        return Response({"roles": sync_groups()})

    # optional: filters/search (works out of the box if django-filter installed)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = {
        "permissions": ["exact"],
        "permissions__codename": ["exact", "in"],
        "name": ["exact", "icontains"],
    }
    search_fields = ["name", "permissions__codename", "permissions__name", "user_set__username", "user_set__email"]
    ordering_fields = ["name", "id"]
    ordering = ["name"]

    # ---------- Users in a group ----------
    @action(detail=True, methods=["get"], url_path="users")
    def users(self, request, pk=None):
        g = self.get_object()
        data = list(g.user_set.order_by("username").values("id", "username", "email", "is_active"))
        return Response(data)

    @action(detail=True, methods=["post"], url_path="add_users")
    def add_users(self, request, pk=None):
        g = self.get_object()
        if settings.AUTH_MODE == "keycloak":
            raise PermissionDenied("Assign roles through the Users form so Chiro Auth stays synchronized.")
        check_grants(request.user, [], [g])
        ids = request.data.get("user_ids", [])
        users = User.objects.filter(id__in=ids)
        for u in users:
            u.groups.add(g)
        return Response({"added": list(users.values_list("id", flat=True))}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remove_users")
    def remove_users(self, request, pk=None):
        g = self.get_object()
        if settings.AUTH_MODE == "keycloak":
            raise PermissionDenied("Assign roles through the Users form so Chiro Auth stays synchronized.")
        check_grants(request.user, [], [g])
        ids = request.data.get("user_ids", [])
        users = User.objects.filter(id__in=ids)
        for u in users:
            u.groups.remove(g)
        return Response({"removed": list(users.values_list("id", flat=True))}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["put"], url_path="set_users")
    def set_users(self, request, pk=None):
        g = self.get_object()
        if settings.AUTH_MODE == "keycloak":
            raise PermissionDenied("Assign roles through the Users form so Chiro Auth stays synchronized.")
        check_grants(request.user, [], [g])
        new_ids = set(request.data.get("user_ids", []))
        current_ids = set(g.user_set.values_list("id", flat=True))

        # remove missing
        for uid in current_ids - new_ids:
            user = User.objects.filter(id=uid).first()
            if user:
                user.groups.remove(g)
        # add new
        for uid in new_ids - current_ids:
            user = User.objects.filter(id=uid).first()
            if user:
                user.groups.add(g)

        return Response({"users": sorted(list(new_ids))}, status=status.HTTP_200_OK)

    # ---------- Permissions in a group ----------
    @action(detail=True, methods=["get"], url_path="permissions")
    def list_permissions(self, request, pk=None):
        g = self.get_object()
        data = list(g.permissions.order_by("codename").values("id", "codename", "name"))
        return Response(data)

    @action(detail=True, methods=["post"], url_path="add_permissions")
    def add_permissions(self, request, pk=None):
        g = self.get_object()
        check_grants(request.user, [], [g])
        ids = request.data.get("permission_ids", [])
        perms = Permission.objects.filter(id__in=ids)
        self.check_permission_grants(perms)
        g.permissions.add(*perms)
        return Response({"added": list(perms.values_list("id", flat=True))}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remove_permissions")
    def remove_permissions(self, request, pk=None):
        g = self.get_object()
        check_grants(request.user, [], [g])
        ids = request.data.get("permission_ids", [])
        perms = Permission.objects.filter(id__in=ids)
        self.check_permission_grants(perms)
        g.permissions.remove(*perms)
        return Response({"removed": list(perms.values_list("id", flat=True))}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["put"], url_path="set_permissions")
    def set_permissions(self, request, pk=None):
        g = self.get_object()
        check_grants(request.user, [], [g])
        ids = request.data.get("permission_ids", [])
        perms = Permission.objects.filter(id__in=ids)
        self.check_permission_grants(perms)
        g.permissions.set(perms)
        return Response({"permissions": list(perms.values_list("id", flat=True))}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="all-permissions")
    def all_permissions(self, request):
        """Get all available permissions in the system."""
        perms = Permission.objects.all().order_by("content_type__app_label", "content_type__model", "codename")
        data = list(perms.values("id", "codename", "name", "content_type__app_label", "content_type__model"))
        return Response(data)

class ReportsPermission(permissions.BasePermission):
    """
    Citizens can see only reports of their own cases.
    Officials (non-citizens) and superusers can see everything.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class ReportsViewSet(PermissionMixin, viewsets.ViewSet):
    permission_model = "cas_app.case"
    permission_classes = [permissions.IsAuthenticated, ReportsPermission]

    # ---- helpers ----
    def _filtered_cases(self, request):
        qs = Case.objects.filter(deleted_by__isnull=True)

        # citizen scoping
        if is_citizen(request.user):
            qs = qs.filter(citizen_id=request.user)

        # optional filters
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        office = request.query_params.get("office")
        category = request.query_params.get("category")
        status = request.query_params.get("status")

        if start:
            d = parse_date(start)
            if d:
                qs = qs.filter(created_at__date__gte=d)
        if end:
            d = parse_date(end)
            if d:
                qs = qs.filter(created_at__date__lte=d)
        if office:
            qs = qs.filter(office_id_id=office)
        if category:
            qs = qs.filter(category_id=category)
        if status:
            qs = qs.filter(status=status)

        return qs.select_related("office_id", "citizen_id")

    # ---- /reports/summary/ ----
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        qs = self._filtered_cases(request)

        # total counts by status
        status_counts = qs.values("status").annotate(total=Count("id"))
        by_status = {row["status"]: row["total"] for row in status_counts}

        total = qs.count()
        data = {
            "total_cases": total,
            "pending": by_status.get("pending", 0),
            "investigation": by_status.get("investigation", 0),
            "resolved": by_status.get("resolved", 0),
            "rejected": by_status.get("rejected", 0),
            "closed": by_status.get("closed", 0),
            # A simple "open" definition (not closed or resolved or rejected)
            "open": total - (by_status.get("resolved", 0) + by_status.get("rejected", 0) + by_status.get("closed", 0)),
        }
        return Response(data)

    # ---- /reports/cases_by_status/ ----
    @action(detail=False, methods=["get"], url_path="cases_by_status")
    def cases_by_status(self, request):
        qs = self._filtered_cases(request)
        agg = qs.values("status").annotate(total=Count("id")).order_by("status")
        # -> [{status, total}]
        out = [{"status": r["status"], "total": r["total"]} for r in agg]
        return Response(out)

    # ---- /reports/cases_by_office/ ----
    @action(detail=False, methods=["get"], url_path="cases_by_office")
    def cases_by_office(self, request):
        qs = self._filtered_cases(request)
        agg = qs.values("office_id__id", "office_id__name").annotate(total=Count("id")).order_by("office_id__name")
        out = [
            {
                "office_id": r["office_id__id"],
                "office_name": r["office_id__name"] or "Unassigned",
                "total": r["total"],
            }
            for r in agg
        ]
        return Response(out)

    # ---- /reports/cases_by_category/ ----
    @action(detail=False, methods=["get"], url_path="cases_by_category")
    def cases_by_category(self, request):
        qs = self._filtered_cases(request)
        agg = qs.values("category_id").annotate(total=Count("id")).order_by("category_id")
        out = [{"category": r["category_id"], "total": r["total"]} for r in agg]
        return Response(out)

    # ---- /reports/top_assignees/ ----
    @action(detail=False, methods=["get"], url_path="top_assignees")
    def top_assignees(self, request):
        """
        Rank users by how many assignments they received (to_user_id).
        For citizens: only counts assignments on their own cases.
        Optional filters apply via _filtered_cases.
        """
        case_ids = list(self._filtered_cases(request).values_list("id", flat=True))
        q = Assignment.objects.filter(case_id_id__in=case_ids)

        agg = (
            q.values("to_user_id")
             .annotate(total=Count("id"))
             .order_by("-total")[:10]
        )

        # Fetch user basics in one go
        user_map = {
            u.id: u for u in User.objects.filter(id__in=[row["to_user_id"] for row in agg])
        }
        out = []
        for row in agg:
            u = user_map.get(row["to_user_id"])
            out.append({
                "user_id": row["to_user_id"],
                "username": getattr(u, "username", None),
                "first_name": getattr(u, "first_name", ""),
                "last_name": getattr(u, "last_name", ""),
                "total": row["total"],
            })
        return Response(out)
    

DIRECTOR_AND_ABOVE = {"Director", "President Office", "President"}

def is_citizen(user):
    return user.is_authenticated and not can(user, "cas_app.view_all_cases")

def is_director_or_above(user):
    return user.is_authenticated and user.groups.filter(name__in=DIRECTOR_AND_ABOVE).exists()

class AnnouncementPermission(BasePermission):
    """
    - Anyone authenticated can READ (list/retrieve).
    - Only Director & above (or superuser) can CREATE/UPDATE/DELETE.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        # non-safe methods
        return user.is_superuser or is_director_or_above(user)

    def has_object_permission(self, request, view, obj):
        # same rules object-level
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_superuser or is_director_or_above(request.user)
    
class CaseFeedbackViewSet(PermissionMixin, viewsets.ReadOnlyModelViewSet):
    permission_model = "cas_app.casefeedback"
    """
    ViewSet for viewing feedback and appeals.
    - Admin, Director, and Focal Person can see all feedback/appeals
    - Filtered by office for Focal Person
    """
    serializer_class = CaseFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = CaseFeedback.objects.select_related(
            "case", "created_by", "case__citizen_id", 
            "case__office_id", "case__parent_case"
        ).order_by("-created_at")

        # Filter by case type if requested
        feedback_type = self.request.query_params.get("type", None)
        if feedback_type == "appeal":
            # Appeals are cases with parent_case or category="appeal"
            qs = qs.filter(
                Q(case__parent_case__isnull=False) | 
                Q(case__category_id="appeal")
            )
        elif feedback_type == "feedback":
            # Regular feedback (not appeals)
            qs = qs.filter(
                case__parent_case__isnull=True
            ).exclude(case__category_id="appeal")

        # Citizens only see their own feedback
        if is_citizen(user):
            qs = qs.filter(case__citizen_id=user)
        # Focal Person sees feedback for cases in their office
        elif hasattr(user, 'office') and user.office:
            qs = qs.filter(case__office_id=user.office)
        # Admin and Director see all

        return qs


class AnnouncementViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.announcement"
    queryset = Announcement.objects.all()
    serializer_class = AnnouncementSerializer
    permission_classes = [permissions.IsAuthenticated, AnnouncementPermission]

    def get_queryset(self):
        """
        Everyone sees active announcements by default.
        Optionally filter for the current user's audience.
        Query params:
          - all=1            -> include inactive too (director & above only)
          - for_me=1         -> only those targeted to my roles/offices (or public)
          - office=<id>      -> narrow by office id
        """
        qs = Announcement.objects.all()

        # Unless privileged, show only active
        user = self.request.user
        if not can(user, "cas_app.change_announcement"):
            qs = qs.filter(is_active=True)

        # filter by office
        office_id = self.request.query_params.get("office")
        if office_id:
            qs = qs.filter(recipients_offices=office_id) | qs.filter(recipients_offices__isnull=True)

        # include inactive if explicitly requested and user is privileged
        if self.request.query_params.get("all") != "1":
            qs = qs.filter(is_active=True)

        # for_me: returns announcements targeted to user's roles/offices, or public (no recipients set)
        if self.request.query_params.get("for_me") == "1":
            # user roles
            user_group_ids = list(user.groups.values_list("id", flat=True))
            # note: if you later add user.office relation, use it here.
            qs = qs.filter(
                models.Q(recipients_groups__isnull=True, recipients_offices__isnull=True) |
                models.Q(recipients_groups__in=user_group_ids) |
                models.Q(recipients_offices__isnull=True)  # still public by office
            ).distinct()

        return qs.distinct().order_by("-created_at")

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        
        # Create notifications for announcement recipients (optimized with bulk_create)
        # Get target users based on recipients_groups and recipients_offices
        target_users = User.objects.none()
        
        # Users in recipient groups
        if instance.recipients_groups.exists():
            group_ids = instance.recipients_groups.values_list('id', flat=True)
            target_users = User.objects.filter(groups__id__in=group_ids, is_active=True, is_deleted=False).distinct()
        else:
            # If no groups specified, it's public - notify all active users
            target_users = User.objects.filter(is_active=True, is_deleted=False)
        
        # Filter by offices if specified
        if instance.recipients_offices.exists():
            office_ids = instance.recipients_offices.values_list('id', flat=True)
            office_users = User.objects.filter(office_id__in=office_ids, is_active=True, is_deleted=False).distinct()
            if instance.recipients_groups.exists():
                target_users = target_users.filter(id__in=office_users.values_list('id', flat=True))
            else:
                target_users = office_users
        
        # Limit to prevent too many notifications (safety limit)
        target_users = target_users[:500]  # Max 500 users per announcement
        
        # Create notifications in bulk (more efficient)
        if target_users.exists():
            message_preview = instance.content[:200] + ("..." if len(instance.content) > 200 else "")
            notifications = [
                Notification(
                    user=user,
                    notification_type="announcement",
                    title=f"New Announcement: {instance.title}",
                    message=message_preview,
                    related_announcement_id=instance,
                )
                for user in target_users
            ]
            # Bulk create in chunks of 100 for better performance
            chunk_size = 100
            for i in range(0, len(notifications), chunk_size):
                Notification.objects.bulk_create(notifications[i:i + chunk_size], ignore_conflicts=True)
        
        return instance

    def perform_update(self, serializer):
        instance = serializer.save(updated_by=self.request.user)

    # Optional: quick publish/unpublish toggle (Director+)
    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):
        ann = self.get_object()
        ann.is_active = not ann.is_active
        ann.updated_by = request.user
        ann.save(update_fields=["is_active", "updated_by", "updated_at"])
        return Response({"id": ann.id, "is_active": ann.is_active})


class NotificationViewSet(PermissionMixin, viewsets.ModelViewSet):
    permission_model = "cas_app.notification"
    """
    ViewSet for user notifications.
    Users can only see their own notifications.
    Optimized with pagination and efficient queries.
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # We'll handle pagination manually for better control

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user).select_related(
            "related_case_id"
        ).only(
            "id", "notification_type", "title", "message", "is_read", "created_at",
            "related_case_id", "related_case_id__title", "related_case_id__id"
        )
        
        # Support "since" parameter to fetch only new notifications
        since = self.request.query_params.get("since")
        if since:
            try:
                from django.utils.dateparse import parse_datetime
                since_dt = parse_datetime(since)
                if since_dt:
                    qs = qs.filter(created_at__gt=since_dt)
            except (ValueError, TypeError):
                pass  # Ignore invalid since parameter
        
        # Limit to last 30 notifications for performance
        limit = int(self.request.query_params.get("limit", 30))
        return qs[:limit]

    def list(self, request, *args, **kwargs):
        """List notifications with optimized pagination."""
        queryset = self.get_queryset()
        
        # Get only unread count if requested
        if request.query_params.get("count_only") == "true":
            count = Notification.objects.filter(user=request.user, is_read=False).count()
            return Response({"count": count})
        
        serializer = self.get_serializer(queryset, many=True)
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        
        return Response({
            "results": serializer.data,
            "unread_count": unread_count,
            "has_more": queryset.count() >= int(request.query_params.get("limit", 30))
        })

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Mark a notification as read."""
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response({"detail": "Notification marked as read."})

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Mark all notifications as read for the current user."""
        updated = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({"detail": f"{updated} notifications marked as read."})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        """Get the count of unread notifications - optimized with caching headers."""
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        response = Response({"count": count})
        # Add cache headers to reduce server load
        response["Cache-Control"] = "private, max-age=10"  # Cache for 10 seconds
        return response