import logging

from rest_framework import generics, status
from rest_framework.response import Response
from django.db import IntegrityError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from .authentication import ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE, ADMIN_SCOPE
from .serializers import (
    UserRegistrationSerializer,
    UserSerializer,
    CustomTokenObtainPairSerializer,
)


logger = logging.getLogger(__name__)


# ==================== AUTH COOKIE HELPERS ====================

def _cookie_max_age(key, default_seconds):
    """Cookie lifetime in seconds, taken from SIMPLE_JWT so the cookie can never
    outlive (or expire before) the token it carries."""
    lifetime = getattr(settings, 'SIMPLE_JWT', {}).get(key)
    return int(lifetime.total_seconds()) if lifetime else default_seconds


def set_access_cookie(response, access_token, key='access_token'):
    response.set_cookie(
        key=key,
        value=str(access_token),
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=_cookie_max_age('ACCESS_TOKEN_LIFETIME', 3600),
    )


def set_refresh_cookie(response, refresh_token, key='refresh_token'):
    response.set_cookie(
        key=key,
        value=str(refresh_token),
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=_cookie_max_age('REFRESH_TOKEN_LIFETIME', 3600 * 24 * 7),
    )


def clear_auth_cookies(response, access_key, refresh_key):
    for key in (access_key, refresh_key):
        response.delete_cookie(key, samesite=settings.AUTH_COOKIE_SAMESITE)


def _blacklist_quietly(raw_refresh):
    """Invalidate a refresh token; never raise (logout must always succeed)."""
    if not raw_refresh:
        return
    try:
        RefreshToken(raw_refresh).blacklist()
    except Exception:  # noqa: BLE001
        pass


def _blacklist_all_for(user):
    """Invalidate every outstanding refresh token for a user (AP3/S4).

    Covers BOTH customer and admin cookies because OutstandingToken covers all
    scopes. Never raises — callers (password change/reset) must not fail after
    the password was already written. Access tokens are stateless and live out
    their remaining minutes; the refresh path (and both session cookies after
    rotation) is what dies here.
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:  # pragma: no cover - blacklist app always installed
        return
    from django.utils import timezone
    for token in OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True):
        try:
            if token.expires_at > timezone.now():
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:  # noqa: BLE001
            continue


def admin_tokens_for(user):
    refresh = CustomTokenObtainPairSerializer.get_token(user)
    refresh['scope'] = ADMIN_SCOPE          # set BEFORE reading .access_token
    return refresh, refresh.access_token


# ==================== CUSTOM THROTTLES ====================

class LoginRateThrottle(AnonRateThrottle):
    """Throttle for login attempts - prevents brute force attacks"""
    scope = 'login'


class RegisterRateThrottle(AnonRateThrottle):
    """Throttle for registration - prevents mass account creation"""
    scope = 'register'


# ========== User Authentication Views ==========

class UserRegistrationView(generics.CreateAPIView):
    """
    Register a new user
    Rate limited: 3 attempts per minute
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'user': UserSerializer(user).data,
            'message': 'User registered successfully. Please login to continue.'
        }, status=status.HTTP_201_CREATED)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Get and update user profile
    """
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user
    
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        if not old_password or not new_password:
            return Response({'detail': 'Both passwords required'}, status=status.HTTP_400_BAD_REQUEST)
        if not user.check_password(old_password):
            return Response({'detail': 'Old password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Enforce strong password validation
        try:
            validate_password(new_password, user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages}, status=status.HTTP_400_BAD_REQUEST)
        
        user.set_password(new_password)
        user.save()
        # AP3/S4: a password change evicts every other session (customer AND
        # admin). The caller's own cookies are left alone — they just proved
        # they know the password, and the next refresh re-authenticates.
        _blacklist_all_for(user)
        return Response({'detail': 'Password updated successfully'}, status=status.HTTP_200_OK)



class CustomTokenObtainPairView(TokenObtainPairView):
    """
    Custom JWT token view with additional user data
    Rate limited: 5 attempts per minute to prevent brute force
    """
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            access_token = response.data['access']
            refresh_token = response.data['refresh']
            
            # Set both tokens in secure HttpOnly cookies
            set_access_cookie(response, access_token)
            set_refresh_cookie(response, refresh_token)
            # The tokens now live ONLY in the HttpOnly cookies above — don't also
            # return them in the JSON body, where page JavaScript (and thus any
            # XSS) could read them. The SPA relies on the cookie, not the body.
            response.data = {'success': True}
        return response


class CustomTokenRefreshView(TokenRefreshView):
    """
    Custom Token Refresh View to update cookies
    """
    def post(self, request, *args, **kwargs):
        # Allow refresh from cookie if not in body
        refresh_from_cookie = request.COOKIES.get('refresh_token')
        if not request.data.get('refresh') and refresh_from_cookie:
            request.data['refresh'] = refresh_from_cookie
            
        response = super().post(request, *args, **kwargs)
        if response.status_code == 200:
            set_access_cookie(response, response.data['access'])
            # If rotation is on, we'll get a new refresh token
            if 'refresh' in response.data:
                set_refresh_cookie(response, response.data['refresh'])
            # Deliver the refreshed token via the HttpOnly cookie only, never the
            # JSON body (see CustomTokenObtainPairView).
            response.data = {'success': True}
        return response


# ==================== PASSWORD RESET VIEWS ====================
import random
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from .serializers import PasswordResetRequestSerializer, OTPVerifySerializer, PasswordResetConfirmSerializer
from .models import PasswordResetOTP

User = get_user_model()


class PasswordResetRateThrottle(AnonRateThrottle):
    """Throttle for password reset - 10 attempts per day per IP."""
    scope = 'password_reset'


class PasswordResetRequestView(APIView):
    """
    Send an OTP to the user's email for password reset verification.
    Rate limited: 10 attempts per day.
    """
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        try:
            user = User.objects.get(email=email)
            
            # Generate 6-digit OTP
            otp_code = f"{random.randint(100000, 999999)}"
            
            # Invalidate previous unexpired OTPs for this user
            PasswordResetOTP.objects.filter(user=user, is_used=False).update(is_used=True)
            
            # Clean up expired OTPs older than 24 hours (opportunistic cleanup)
            PasswordResetOTP.objects.filter(
                user=user,
                expires_at__lt=timezone.now() - timedelta(hours=24)
            ).delete()
            
            # Create new OTP record (expires in 10 minutes)
            expires_at = timezone.now() + timedelta(minutes=10)
            otp_record = PasswordResetOTP(
                user=user,
                expires_at=expires_at
            )
            otp_record.set_otp(otp_code)
            otp_record.save()
            
            # Send Email asynchronously to prevent blocking and timing attacks
            def send_otp_email(email_kwargs):
                import logging
                logger = logging.getLogger(__name__)
                try:
                    send_mail(**email_kwargs)
                except Exception as e:
                    logger.error(f"Failed to send OTP email to {email_kwargs['recipient_list']}: {str(e)}")
                    # Also print to console for immediate visibility in dev
                    print(f"\n❌ EMAIL ERROR: {str(e)}\n")

            import threading
            email_kwargs = {
                'subject': 'Password Reset OTP - NGU Spices',
                'message': f'Your OTP for password reset is: {otp_code}\n\nThis code will expire in 10 minutes.',
                'from_email': settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else settings.EMAIL_HOST_USER,
                'recipient_list': [user.email],
                'fail_silently': False,
            }
            threading.Thread(target=send_otp_email, args=(email_kwargs,)).start()
            
        except User.DoesNotExist:
            # Prevent email enumeration via timing attack
            User().set_password('dummy_password')
            
        return Response(
            {'detail': 'If an account exists with this email, an OTP has been sent.'}, 
            status=status.HTTP_200_OK
        )

class PasswordResetVerifyView(APIView):
    """
    Verify the OTP code sent to the email (without resetting password yet).
    Rate limited: 10 attempts per day.
    """
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        otp_code = serializer.validated_data['otp_code']
        
        try:
            user = User.objects.get(email=email)
            # Get the latest unused OTP for this user (regardless of the code submitted)
            otp_record = PasswordResetOTP.objects.filter(
                user=user,
                is_used=False
            ).latest('created_at')
            
            if otp_record.is_expired:
                return Response({'detail': 'OTP has expired. Please request a new one.'}, status=status.HTTP_400_BAD_REQUEST)
            
            if otp_record.is_locked:
                return Response({'detail': 'Too many failed attempts. Please request a new OTP.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            # Check if the submitted OTP code matches
            if not otp_record.check_otp(otp_code):
                otp_record.failed_attempts += 1
                otp_record.save(update_fields=['failed_attempts'])
                remaining = PasswordResetOTP.MAX_FAILED_ATTEMPTS - otp_record.failed_attempts
                if remaining > 0:
                    return Response({'detail': f'Invalid OTP. {remaining} attempt(s) remaining.'}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response({'detail': 'Too many failed attempts. Please request a new OTP.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
                
            import uuid
            otp_record.is_used = True
            otp_record.reset_token = str(uuid.uuid4())
            otp_record.save(update_fields=['is_used', 'reset_token'])

            return Response({
                'detail': 'OTP verified successfully. You may proceed to reset password.',
                'reset_token': otp_record.reset_token
            }, status=status.HTTP_200_OK)
            
        except (User.DoesNotExist, PasswordResetOTP.DoesNotExist):
            return Response({'detail': 'Invalid OTP or email.'}, status=status.HTTP_400_BAD_REQUEST)

class PasswordResetConfirmView(APIView):
    """
    Confirm OTP and reset the password.
    Rate limited: 10 attempts per day.
    """
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        reset_token = serializer.validated_data['reset_token']
        new_password = serializer.validated_data['new_password']
        
        try:
            user = User.objects.get(email=email)
            # Find the OTP record by reset_token
            otp_record = PasswordResetOTP.objects.get(
                user=user,
                reset_token=reset_token,
                is_used=True
            )
            
            if otp_record.is_expired:
                return Response({'detail': 'Password reset session has expired. Please request a new OTP.'}, status=status.HTTP_400_BAD_REQUEST)
                
            # Valid OTP, update password
            user.set_password(new_password)
            user.save()

            # AP3/S4: a reset evicts every session before the reset token is
            # cleared, so whoever was in before no longer is.
            _blacklist_all_for(user)

            # Clear reset token
            otp_record.reset_token = None
            otp_record.save()
            
            return Response({'detail': 'Password has been reset successfully. You can now login.'}, status=status.HTTP_200_OK)
            
        except (User.DoesNotExist, PasswordResetOTP.DoesNotExist):
            return Response({'detail': 'Invalid OTP or email.'}, status=status.HTTP_400_BAD_REQUEST)

# ==================== GOOGLE SOCIAL AUTH VIEWS ====================
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


def verify_google_id_token(token):
    client_id = settings.SOCIALACCOUNT_PROVIDERS['google']['APP']['client_id']
    idinfo = id_token.verify_oauth2_token(token, google_requests.Request(), client_id)
    email = (idinfo.get('email') or '').strip().lower()
    if not email:
        raise ValueError('Email not provided by Google')
    if idinfo.get('email_verified') not in (True, 'true'):
        raise ValueError('Google account email is not verified')
    return email, idinfo


def _unique_username_from_email(email):
    """Derive a username from the local part, de-duplicated.

    The bare local part collides across domains (a@x.com vs a@y.com), which used
    to surface as an IntegrityError/500 on the second signup.
    """
    base = email.split('@')[0][:140] or 'user'
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f'{base}{suffix}'
    return username


class GoogleLogin(APIView):
    """
    Google Social Login View (Manual id_token Verification)
    Receives frontend's Google credential, verifies it locally,
    and returns JWT tokens for the session.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        # Frontend sends the credential as `access_token` due to authAPI setup
        token = request.data.get('access_token') or request.data.get('id_token')

        if not token:
            return Response({'detail': 'Google token is missing'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            email, idinfo = verify_google_id_token(token)

            # 2. Extract user info
            name = idinfo.get('name', '')
            first_name = idinfo.get('given_name', '')
            last_name = idinfo.get('family_name', '')

            # 3. Get or create user (match email case-insensitively so a Google
            # sign-in never forks a second account from a case variant).
            user = User.objects.filter(email__iexact=email).first()
            created = user is None
            if created:
                user = User.objects.create(
                    email=email,
                    username=_unique_username_from_email(email),
                    name=name,
                    first_name=first_name,
                    last_name=last_name,
                )

            if created:
                user.set_unusable_password()
                user.save()
            elif not user.name and name:
                # Update name if previously empty
                user.name = name
                user.save(update_fields=['name'])
                
            # 4. Generate identical JWT tokens as CustomTokenObtainPairView
            refresh = CustomTokenObtainPairSerializer.get_token(user)
            access = refresh.access_token
            
            # Tokens are delivered via the HttpOnly cookies set below only — not
            # in the JSON body, where JS/XSS could read them. Return just the
            # (non-secret) user profile; the SPA authenticates via the cookie.
            response = Response({
                'success': True,
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)
            
            # 5. Set HttpOnly secure cookies
            set_access_cookie(response, access)
            set_refresh_cookie(response, refresh)

            return response

        except ValueError as e:
            # verify_google_id_token raises ValueError for a bad signature as
            # well as for a missing/unverified email — preserve the old
            # per-case statuses so existing clients/tests keep passing.
            msg = str(e)
            if msg == 'Email not provided by Google':
                return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
            if msg == 'Google account email is not verified':
                return Response({'detail': msg}, status=status.HTTP_401_UNAUTHORIZED)
            # google-auth raises ValueError for a bad signature/aud/issuer/expiry.
            return Response({'detail': 'Invalid Google token', 'error': msg}, status=status.HTTP_401_UNAUTHORIZED)
        except (KeyError, IntegrityError) as e:
            # Misconfigured SOCIALACCOUNT_PROVIDERS, or a racing signup on the
            # same email. Neither is the caller's fault — don't leak a 500.
            logger.exception('Google login failed: %s', e)
            return Response(
                {'detail': 'Google sign-in is temporarily unavailable.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


# ==================== LOGOUT + ADMIN SESSION ====================

class LogoutView(APIView):
    """Customer logout: blacklist the customer refresh cookie, clear both.

    Must NOT touch the admin cookies — the two sessions are independent.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _blacklist_quietly(request.COOKIES.get('refresh_token'))
        response = Response({'success': True})
        clear_auth_cookies(response, 'access_token', 'refresh_token')
        return response


class AdminLoginView(APIView):
    """Staff-only login that issues the admin session cookies."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = CustomTokenObtainPairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        if not user.is_staff:
            return Response(
                {'detail': 'Invalid credentials or not an admin account.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        refresh, access = admin_tokens_for(user)
        response = Response({'success': True, 'user': UserSerializer(user).data})
        set_access_cookie(response, access, key=ADMIN_ACCESS_COOKIE)
        set_refresh_cookie(response, refresh, key=ADMIN_REFRESH_COOKIE)
        return response


class AdminGoogleLoginView(APIView):
    """Google sign-in for EXISTING staff accounts only. Never creates a user."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        token = request.data.get('id_token') or request.data.get('access_token')
        if not token:
            return Response({'detail': 'Google token is missing'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            email, _idinfo = verify_google_id_token(token)
        except ValueError:
            return Response({'detail': 'Invalid Google token'}, status=status.HTTP_401_UNAUTHORIZED)
        except (KeyError, IntegrityError):
            logger.exception('Admin Google login failed')
            return Response(
                {'detail': 'Google sign-in is temporarily unavailable.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        user = User.objects.filter(email__iexact=email, is_staff=True, is_active=True).first()
        if user is None:
            return Response(
                {'detail': 'This Google account is not an admin of this store.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        refresh, access = admin_tokens_for(user)
        response = Response({'success': True, 'user': UserSerializer(user).data})
        set_access_cookie(response, access, key=ADMIN_ACCESS_COOKIE)
        set_refresh_cookie(response, refresh, key=ADMIN_REFRESH_COOKIE)
        return response


class AdminTokenRefreshView(APIView):
    """Refresh the admin session from the admin refresh cookie."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.COOKIES.get(ADMIN_REFRESH_COOKIE)
        if not raw:
            return Response({'detail': 'Admin refresh token is missing.'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            token = RefreshToken(raw)
        except TokenError:
            return Response({'detail': 'Invalid admin refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)
        if token.get('scope') != ADMIN_SCOPE:
            return Response({'detail': 'Invalid admin refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)
        user_id = token.get('user_id')
        user = User.objects.filter(pk=user_id, is_staff=True, is_active=True).first()
        if user is None:
            response = Response({'detail': 'Admin session required.'}, status=status.HTTP_401_UNAUTHORIZED)
            clear_auth_cookies(response, ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE)
            return response
        serializer = TokenRefreshSerializer(data={'refresh': raw})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response({'detail': 'Invalid admin refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)
        response = Response({'success': True})
        set_access_cookie(response, serializer.validated_data['access'], key=ADMIN_ACCESS_COOKIE)
        if 'refresh' in serializer.validated_data:
            set_refresh_cookie(response, serializer.validated_data['refresh'], key=ADMIN_REFRESH_COOKIE)
        return response


class AdminLogoutView(APIView):
    """Admin logout: blacklist the admin refresh cookie, clear both.

    Must NOT touch the customer cookies.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _blacklist_quietly(request.COOKIES.get(ADMIN_REFRESH_COOKIE))
        response = Response({'success': True})
        clear_auth_cookies(response, ADMIN_ACCESS_COOKIE, ADMIN_REFRESH_COOKIE)
        return response

