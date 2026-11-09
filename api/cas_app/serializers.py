from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework import serializers
from .models import *
from django.contrib.auth.models import Group, Permission

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=6, trim_whitespace=False)
    groups = serializers.SlugRelatedField(
        many=True,
        slug_field="name",
        queryset=Group.objects.all(),
        required=False
    )

    profile_image = serializers.ImageField(required=False, allow_null=True)
    profile_image_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", 
            "email", "phone_number", "national_id", "address", "office",
            "profile_image", "profile_image_url",
            "last_seen", "status",
            "deleted_by", "added_by", "status_changed_by", 
            "created_at", "password", "groups"
        ]
        read_only_fields = [
            "last_seen", "deleted_by", "added_by", 
            "status_changed_by", "created_at", "profile_image_url"
        ]

    def get_profile_image_url(self, obj):
        if obj.profile_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_image.url)
            return obj.profile_image.url
        return None

    def create(self, validated_data):
        groups = validated_data.pop("groups", None)
        user = User.objects.create_user(**validated_data)

        if groups:
            user.groups.set(groups)  # internal user creation with role
        else:
            citizen_group, _ = Group.objects.get_or_create(name="Citizen")
            user.groups.add(citizen_group)  # default external role

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        groups = validated_data.pop("groups", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if groups is not None:
            instance.groups.set(groups)

        return instance

class OfficeSerializer(serializers.ModelSerializer):
    added_by = serializers.StringRelatedField(read_only=True)
    updated_by = serializers.StringRelatedField(read_only=True)
    office_representative = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), allow_null=True, required=False
    )
    representative_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Office
        fields = [
            "id",
            "name",
            "phone_number",
            "email",
            "address",
            "office_representative",
            "representative_name",
            "is_active",
            "created_at",
            "updated_at",
            "added_by",
            "updated_by",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "added_by",
            "updated_by",
            "representative_name",
        ]

    def get_representative_name(self, obj: Office) -> str:
        if obj.office_representative:
            return obj.office_representative.get_full_name() or obj.office_representative.email or obj.office_representative.username or ""
        return ""

class CaseStatusHistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.PrimaryKeyRelatedField(read_only=True)
    class Meta:
        model = CaseStatusHistory
        fields = ["id", "status", "changed_at", "changed_by"]

class CaseFeedbackSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    case_title = serializers.SerializerMethodField()
    case_status = serializers.SerializerMethodField()
    case_id_display = serializers.SerializerMethodField()
    is_appeal = serializers.SerializerMethodField()
    parent_case_id = serializers.SerializerMethodField()

    class Meta:
        model = CaseFeedback
        fields = [
            "id", "case", "case_id_display", "case_title", "case_status",
            "created_by", "created_by_name", "rating", "comment", 
            "created_at", "is_appeal", "parent_case_id"
        ]
        read_only_fields = ["id", "created_by", "created_at", "case"]

    def get_created_by_name(self, obj):
        user = obj.created_by
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.username or user.email or f"User {user.id}"

    def get_case_title(self, obj):
        return obj.case.title or f"Case #{obj.case.id}"

    def get_case_status(self, obj):
        return obj.case.get_status_display() if hasattr(obj.case, 'get_status_display') else obj.case.status

    def get_case_id_display(self, obj):
        return obj.case.id

    def get_is_appeal(self, obj):
        # Check if the case is an appeal (has parent_case or category is appeal)
        return obj.case.parent_case is not None or obj.case.category_id == "appeal"

    def get_parent_case_id(self, obj):
        return obj.case.parent_case.id if obj.case.parent_case else None

    def validate_rating(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value
    
class CaseSerializer(serializers.ModelSerializer):
    # Just declare PK fields without `source=...`
    citizen_id   = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    reported_by  = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    office_id    = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all(), required=False, allow_null=True)
    parent_case  = serializers.PrimaryKeyRelatedField(queryset=Case.objects.all(), required=False, allow_null=True)

    status_history = CaseStatusHistorySerializer(many=True, read_only=True)
    feedbacks      = CaseFeedbackSerializer(many=True, read_only=True)
    attachments = serializers.JSONField(required=False, allow_null=True)

    def validate_attachments(self, value):
        """Custom validation for attachments field."""
        # If value is an empty string, return None (will be handled as null/empty list)
        if isinstance(value, str) and not value.strip():
            return None
        # If value is None, return None
        if value is None:
            return None
        # If value is already a list or dict, return as is
        if isinstance(value, (list, dict)):
            return value
        # For any other invalid type, return None
        return None

    class Meta:
        model = Case
        fields = [
            "id",
            "citizen_id",
            "reported_by",
            "office_id",
            "parent_case",
            "title",
            "description",
            "attachments",
            "category_id",
            "channel",
            "priority",
            "status",
            "created_at",
            "added_by",
            "status_changed_by",
            "deleted_by",
            "last_seen_by",
            "status_history",
            "feedbacks",
        ]
        read_only_fields = [
            "created_at",
            "added_by",
            "status_changed_by",
            "deleted_by",
            "last_seen_by",
        ]


class TransferSerializer(serializers.ModelSerializer):
    # keep *_id naming per your style
    case_id = serializers.PrimaryKeyRelatedField(queryset=Case.objects.filter(deleted_by__isnull=True))
    from_office_id = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())
    to_office_id = serializers.PrimaryKeyRelatedField(queryset=Office.objects.all())

    class Meta:
        model = Transfer
        fields = ["id", "case_id", "from_office_id", "to_office_id", "reason", "timestamp"]
        read_only_fields = ["timestamp"]

    def validate(self, attrs):
        case = attrs["case_id"]
        from_office = attrs["from_office_id"]
        to_office = attrs["to_office_id"]

        if from_office == to_office:
            raise serializers.ValidationError("from_office_id and to_office_id cannot be the same.")

        # sanity: current office should match from_office to avoid race/incorrect transfer
        if case.office_id and case.office_id_id != from_office.id:
            raise serializers.ValidationError("Case current office does not match from_office_id.")
        return attrs


class AssignmentSerializer(serializers.ModelSerializer):
    case_id = serializers.PrimaryKeyRelatedField(queryset=Case.objects.filter(deleted_by__isnull=True))
    from_user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    to_user_id = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    class Meta:
        model = Assignment
        fields = ["id", "case_id", "from_user_id", "to_user_id", "reason", 'countdown_days', 'due_date', "timestamp"]
        read_only_fields = ["timestamp"]

    def validate(self, attrs):
        from_user = attrs.get("from_user_id")
        to_user = attrs["to_user_id"]
        if from_user and from_user == to_user:
            raise serializers.ValidationError("from_user_id and to_user_id cannot be the same.")
        return attrs
    

class RoleHierarchySerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source="role.name", read_only=True)
    can_transfer_to_names = serializers.SerializerMethodField()

    class Meta:
        model = RoleHierarchy
        fields = [
            "id",
            "role",
            "role_name",
            "hierarchy_level",
            "can_transfer_to",
            "can_transfer_to_names",
            "can_assign",
            "can_change_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_can_transfer_to_names(self, obj):
        return [role.name for role in obj.can_transfer_to.all()]
    

class PermissionSerializer(serializers.Serializer):
    """Serializer for permission display."""
    id = serializers.IntegerField()
    codename = serializers.CharField()
    name = serializers.CharField()
    content_type__app_label = serializers.CharField(source="content_type.app_label", read_only=True)
    content_type__model = serializers.CharField(source="content_type.model", read_only=True)


class GroupSerializer(serializers.ModelSerializer):
    # Write by permission IDs; read returns both IDs and codenames
    permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(), required=False
    )
    permission_codenames = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="codename", source="permissions"
    )
    permission_details = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ["id", "name", "permissions", "permission_codenames", "permission_details"]

    def get_permission_details(self, obj):
        """Return detailed permission information."""
        return [
            {
                "id": perm.id,
                "codename": perm.codename,
                "name": perm.name,
                "content_type__app_label": perm.content_type.app_label,
                "content_type__model": perm.content_type.model,
            }
            for perm in obj.permissions.all().select_related("content_type")
        ]

    def validate_name(self, value):
        qs = Group.objects.exclude(pk=self.instance.pk) if self.instance else Group.objects.all()
        if qs.filter(name__iexact=value).exists():
            raise serializers.ValidationError("A group with this name already exists.")
        return value

class AnnouncementSerializer(serializers.ModelSerializer):
    recipients_groups = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Group.objects.all()
    )
    recipients_offices = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Office.objects.all()
    )

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "content", "is_active",
            "recipients_groups", "recipients_offices",
            "created_at", "updated_at", "created_by", "updated_by",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by", "updated_by"]


class NotificationSerializer(serializers.ModelSerializer):
    related_case_id = serializers.PrimaryKeyRelatedField(read_only=True)
    related_case_title = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            "id", "notification_type", "title", "message",
            "is_read", "created_at",
            "related_case_id", "related_case_title",
        ]
        read_only_fields = ["created_at"]

    def get_related_case_title(self, obj):
        if obj.related_case_id:
            return obj.related_case_id.title or f"Case #{obj.related_case_id.id}"
        return None
