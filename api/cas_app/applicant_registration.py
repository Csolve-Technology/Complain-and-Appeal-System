from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from .keycloak_admin import KeycloakAdmin


class ApplicantThrottle(AnonRateThrottle):
    rate = '5/hour'


class ApplicantSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=6, write_only=True, trim_whitespace=False)
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(max_length=15)
    national_id = serializers.CharField(required=False, allow_blank=True, max_length=20)
    address = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Roles and permissions are assigned by the server.')
        User = get_user_model()
        for field in ('username', 'email'):
            if User.objects.filter(**{field + '__iexact': attrs[field]}).exists():
                raise serializers.ValidationError({field: 'An account already exists. Sign in or contact support.'})
        for field in ('phone_number', 'national_id'):
            if attrs.get(field) and User.objects.filter(**{field: attrs[field]}).exists():
                raise serializers.ValidationError({field: 'This value is already registered.'})
        if not attrs.get('national_id'):
            attrs.pop('national_id', None)
        return attrs

    def create(self, data):
        group = Group.objects.filter(name='Citizen').first()
        if not group:
            raise serializers.ValidationError('Applicant access is not configured.')
        password = data.pop('password')
        manager = KeycloakAdmin()
        subject = None
        try:
            manager.ensure_role('CITIZEN')
            subject = manager.create({
                'username': data['username'], 'email': data['email'],
                'firstName': data['first_name'], 'lastName': data['last_name'],
                'emailVerified': True, 'enabled': False, 'requiredActions': [],
            }, password, temporary=False)
            manager.replace_roles(subject, ['CITIZEN'], remove_inherited_citizen=True)
            with transaction.atomic():
                user = get_user_model()(**data, keycloak_sub=subject,
                    keycloak_issuer=settings.KEYCLOAK_URL.rstrip('/') + '/realms/' + settings.KEYCLOAK_REALM,
                    is_staff=False, is_superuser=False)
                user.set_unusable_password()
                user.save()
                user.groups.set([group])
                manager.enable(subject)
            return user
        except Exception:
            if subject:
                manager.delete(subject)
            raise
        finally:
            manager.opener.close()


class ApplicantRegistration(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ApplicantThrottle]

    def post(self, request):
        if settings.AUTH_MODE != 'keycloak':
            return Response({'detail': 'Central registration is not enabled.'}, status=403)
        serializer = ApplicantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Applicant account created. Sign in with Chiro Auth.'}, status=201)
