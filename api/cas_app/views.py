from django.shortcuts import render
from django.shortcuts import render, redirect
from .models import *
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from django.contrib.auth import authenticate, login, logout
from .models import *
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.core.mail import send_mail
from django.conf import settings
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode 
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from rest_framework_simplejwt.tokens import RefreshToken
from urllib.parse import urljoin

from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import *  # Ensure correct import path
from rest_framework.views import APIView
# Create your views here.

def home(request):
    return render(request, 'home.html')

@api_view(['POST'])
def user_login(request):
    if request.method != "POST":
        return Response({"detail": "This view only handles POST requests."}, status=status.HTTP_400_BAD_REQUEST)

    identifier = request.data.get('username') or request.data.get('email')
    password = request.data.get('password')
    if not identifier or not password:
        return Response("Email and/or Password are Incorrect", status=status.HTTP_400_BAD_REQUEST)

    # Try authenticating directly as username
    user = authenticate(request, username=identifier, password=password)
    # If that fails, try resolving identifier as email to a username
    if user is None and '@' in identifier:
        try:
            resolved_user = User.objects.get(email=identifier)
            user = authenticate(request, username=resolved_user.username, password=password)
        except User.DoesNotExist:
            user = None
    if user is not None:
        login(request, user)
        # Generate JWT token
        refresh = RefreshToken.for_user(user)   
        # Create a custom response with the token
        response_data = {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user_id': user.id,
            'role': user.groups.first().name if user.groups.exists() else 'Citizen',  # Assuming first group is the role
        }
        return Response(response_data, status=status.HTTP_200_OK)
        # # Here, we use our CustomTokenObtainPairSerializer to handle token creation
        # serializer = CustomTokenObtainPairSerializer(data=request.data)
        
        # # Validate the serializer to trigger our custom token generation logic
        # if serializer.is_valid():
        #     # Serializer is now using the overridden validate method, so it returns our custom response
        #     return Response(serializer.validated_data, status=status.HTTP_200_OK)
        # else:
        #  s   return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    else:
        return Response({"detail": "Invalid login credentials."}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['GET']) # Ensures that this view can only be accessed via a POST request for security
def logout_view(request):
    logout(request)
    return Response({'message': 'logged out successfully.'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    """Return the current authenticated user's information."""
    user = request.user
    serializer = UserSerializer(user, context={'request': request})
    # Add full_name for frontend compatibility
    data = serializer.data
    full_name = f"{user.first_name} {user.last_name}".strip() or user.username
    data['full_name'] = full_name
    # Add user groups for role checking
    from .chiro_auth import ROLE_GROUPS
    order = {name:i for i, (_, name) in enumerate(ROLE_GROUPS)}
    data['user_groups'] = sorted([group.name for group in user.groups.all()], key=lambda n: (order.get(n, 99), n))
    data['permissions'] = sorted(user.get_all_permissions())
    data['office'] = user.office_id
    # Add profile_image_url if available
    if user.profile_image:
        data['profile_image_url'] = request.build_absolute_uri(user.profile_image.url)
    else:
        data['profile_image_url'] = None
    return Response(data, status=status.HTTP_200_OK)


#change password function
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    data = request.data
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    if not old_password or not new_password:
        return Response({'error': 'Both old and new password are required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if the old password is correct
    if not user.check_password(old_password):
        return Response({'error': 'Old password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)
    
    else:
        # Set the new password
        user.set_password(new_password)
        user.save()

        return Response({'message': 'Password changed successfully.'}, status=status.HTTP_200_OK)

#forget password function  
@api_view(['POST'])
def forget_password(request):
    if request.method != "POST":
        return Response({'error': 'Only POST method is allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    email = request.data.get('email')
    if not email:
        return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

    # Find user by email or username (case-insensitive)
    user = (
        User.objects.filter(email__iexact=email).first()
        or User.objects.filter(username__iexact=email).first()
    )

    # Check if user exists, is active, and not deleted
    if not user:
        # Don't reveal if user exists or not for security (same message for both cases)
        return Response(
            {'message': 'If an account exists for that email address, a reset link has been sent.'},
            status=status.HTTP_200_OK,
        )
    
    if not user.is_active:
        return Response(
            {'error': 'Your account is inactive. Please contact support.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    if getattr(user, "is_deleted", False):
        # Don't reveal if user exists or not for security
        return Response(
            {'message': 'If an account exists for that email address, a reset link has been sent.'},
            status=status.HTTP_200_OK,
        )

    # Generate reset token and URL
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    frontend_base = getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3000").rstrip("/")
    password_reset_path = f"/auth/reset-password/{uid}/{token}"
    password_reset_url = urljoin(frontend_base + "/", password_reset_path.lstrip("/"))
    
    # Get email settings from environment
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", getattr(settings, "EMAIL_HOST_USER", "noreply@example.com"))
    
    try:
        send_mail(
            subject='Password Reset Request',
            message=f'Please click on the link to reset your password: {password_reset_url}',
            from_email=from_email,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as e:
        # Log error but don't expose internal details to user
        print(f"Error sending password reset email: {e}")
        return Response(
            {'error': 'Failed to send password reset email. Please try again later.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Always return success message (security best practice - don't reveal if user exists)
    return Response(
        {'message': 'If an account exists for that email address, a reset link has been sent.'},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
def reset_password(request):
    uidb64 = request.data.get("userId")
    token = request.data.get("token")
    new_password = request.data.get("newPassword")

    if not uidb64 or not token or not new_password:
        return Response(
            {'error': 'userId, token, and newPassword are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)

        if default_token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            return Response({'message': 'Password has been reset.'})
        else:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({'error': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([])
def auth_config(request):
    from .chiro_auth import auth_settings
    return Response(auth_settings())
