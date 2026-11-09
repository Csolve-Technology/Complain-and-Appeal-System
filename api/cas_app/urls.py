from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .api import *
from .views import *
from .applicant_registration import ApplicantRegistration

router = DefaultRouter()
router.register(r'users', UserViewSet, basename="user")
router.register(r'cases', CaseViewSet, basename='case')
router.register(r'offices', OfficeViewSet, basename='office')
router.register(r'transfers', TransferViewSet, basename='transfer')
router.register(r'assignments', AssignmentViewSet, basename='assignment')
router.register(r"groups", GroupViewSet, basename="group")
router.register(r"role-hierarchy", RoleHierarchyViewSet, basename="role-hierarchy")
router.register(r'reports', ReportsViewSet, basename='reports')
router.register(r'announcements', AnnouncementViewSet, basename='announcement')
router.register(r'feedbacks', CaseFeedbackViewSet, basename='feedback')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('auth/applicant-registration/', ApplicantRegistration.as_view()),
    path("auth/config/", auth_config, name="auth_config"),
    path("", include(router.urls)),
    path('login/', user_login, name='user_login'),
    path('logout/', logout_view, name='logout_view'),
    path('password/forgot/', forget_password, name='forget_password'),
    path('password/reset/', reset_password, name='reset_password'),
    path('password/change/', change_password, name='change_password'),
    path('auth/me/', current_user, name='current_user'),
]
