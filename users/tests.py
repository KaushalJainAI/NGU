"""
Comprehensive tests for the Users app.
Covers authentication, registration, profile management, email normalization,
password resets, and security testing.
"""
from datetime import timedelta
import pytest
from django.urls import reverse
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone

from users.models import PasswordResetOTP

User = get_user_model()


# ==================== REGISTRATION TESTS ====================

@pytest.mark.django_db
class TestUserRegistration:
    """Tests for user registration endpoint."""
    
    url = '/api/auth/register/'
    
    def test_register_valid_user(self, api_client):
        """Test successful user registration with valid data."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'first_name': 'New',
            'last_name': 'User',
            'phone': '9876543210'
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        # AP5/S9: generic response — no user object, no existence signal.
        assert response.data == {'detail': 'If this email is new, a verification code was sent.'}
        user = User.objects.get(email='newuser@example.com')
        assert user.email_verified is False  # unusable until OTP confirmed

    def test_register_duplicate_email(self, api_client, test_user):
        """Test registration with a duplicate email is indistinguishable (S9)."""
        count_before = User.objects.count()
        data = {
            'username': 'anotheruser',
            'email': test_user.email,  # Duplicate
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data == {'detail': 'If this email is new, a verification code was sent.'}
        assert User.objects.count() == count_before
    
    def test_register_duplicate_username(self, api_client, test_user):
        """Test registration fails with duplicate username."""
        data = {
            'username': test_user.username,  # Duplicate
            'email': 'unique@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_register_password_mismatch(self, api_client):
        """Test registration fails when passwords don't match."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'StrongPass123!',
            'password2': 'DifferentPass123!',
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'password' in str(response.data).lower()
    
    def test_register_weak_password(self, api_client):
        """Test registration fails with weak password."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': '123',  # Too weak
            'password2': '123',
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_register_missing_required_fields(self, api_client):
        """Test registration fails with missing required fields."""
        data = {
            'username': 'newuser',
            # Missing email, password, password2
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_register_invalid_email(self, api_client):
        """Test registration fails with invalid email format."""
        data = {
            'username': 'newuser',
            'email': 'not-an-email',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_register_sql_injection_in_username(self, api_client, malicious_inputs):
        """Test SQL injection attempts are handled safely."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'username': payload,
                'email': 'test@example.com',
                'password': 'StrongPass123!',
                'password2': 'StrongPass123!',
            }
            response = api_client.post(self.url, data, format='json')
            # Should return 400 (invalid) or 201 (sanitized), never 500
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_register_xss_in_name_fields(self, api_client, malicious_inputs):
        """Test XSS payloads are handled safely."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {
                'username': 'testuser123',
                'email': 'xsstest@example.com',
                'password': 'StrongPass123!',
                'password2': 'StrongPass123!',
                'first_name': payload,
                'last_name': payload,
            }
            response = api_client.post(self.url, data, format='json')
            # Should not cause 500 error
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_register_oversized_payload(self, api_client, malicious_inputs):
        """Test oversized payloads are handled gracefully."""
        data = {
            'username': malicious_inputs.OVERSIZED_STRING[:150],  # Truncate for username
            'email': 'test@example.com',
            'password': 'StrongPass123!',
            'password2': 'StrongPass123!',
            'address': malicious_inputs.OVERSIZED_STRING,
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_register_unicode_characters(self, api_client, malicious_inputs):
        """Test Unicode characters are handled properly."""
        for payload in malicious_inputs.UNICODE_EDGE_CASES:
            data = {
                'username': f'user_{abs(hash(payload)) % 10000}',
                'email': f'unicode{abs(hash(payload)) % 10000}@example.com',
                'password': 'StrongPass123!',
                'password2': 'StrongPass123!',
                'first_name': payload,
            }
            response = api_client.post(self.url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== LOGIN TESTS ====================

@pytest.mark.django_db
class TestUserLogin:
    """Tests for user login endpoint."""
    
    url = '/api/auth/login/'
    
    def test_login_valid_credentials(self, api_client, test_user):
        """Test successful login with valid credentials."""
        data = {
            'email': test_user.email,
            'password': 'TestPass123!'
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        # Tokens are delivered as HttpOnly cookies, NOT in the JSON body (so page
        # JS / any XSS can't read them). The body carries no secret token.
        assert 'access_token' in response.cookies
        assert 'refresh_token' in response.cookies
        assert 'access' not in response.data
        assert 'refresh' not in response.data

    def test_login_invalid_password(self, api_client, test_user):
        """Test login fails with wrong password."""
        data = {
            'email': test_user.email,
            'password': 'WrongPassword123!'
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_nonexistent_user(self, api_client):
        """Test login fails for non-existent user."""
        data = {
            'email': 'nonexistent@example.com',
            'password': 'SomePassword123!'
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_missing_fields(self, api_client):
        """Test login fails with missing fields."""
        response = api_client.post(self.url, {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_login_empty_password(self, api_client, test_user):
        """Test login fails with empty password."""
        data = {
            'email': test_user.email,
            'password': ''
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_login_sql_injection(self, api_client, malicious_inputs):
        """Test SQL injection in login is handled safely."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'email': payload,
                'password': payload
            }
            response = api_client.post(self.url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== PROFILE TESTS ====================

@pytest.mark.django_db
class TestUserProfile:
    """Tests for user profile endpoint."""
    
    url = '/api/auth/profile/'
    
    def test_get_profile_authenticated(self, authenticated_client, test_user):
        """Test getting profile when authenticated."""
        response = authenticated_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == test_user.email
        assert response.data['username'] == test_user.username
    
    def test_get_profile_unauthenticated(self, api_client):
        """Test getting profile without authentication fails."""
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_update_profile(self, authenticated_client, test_user):
        """Test updating profile fields."""
        data = {
            'first_name': 'Updated',
            'last_name': 'Name',
            'phone': '1111111111'
        }
        response = authenticated_client.patch(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['first_name'] == 'Updated'
        
        # Verify in database
        test_user.refresh_from_db()
        assert test_user.first_name == 'Updated'
    
    def test_update_profile_readonly_fields(self, authenticated_client, test_user):
        """Test that read-only fields cannot be modified."""
        original_id = test_user.id
        data = {
            'id': 999999,  # Should be read-only
        }
        response = authenticated_client.patch(self.url, data, format='json')
        # Should succeed but ignore read-only field
        test_user.refresh_from_db()
        assert test_user.id == original_id
    
    def test_update_profile_xss_payload(self, authenticated_client, malicious_inputs):
        """Test XSS payloads in profile update."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {'first_name': payload}
            response = authenticated_client.patch(self.url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_profile_with_invalid_token(self, api_client):
        """Test profile access with invalid token."""
        api_client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token_here')
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== PASSWORD CHANGE TESTS ====================

@pytest.mark.django_db
class TestPasswordChange:
    """Tests for password change endpoint."""
    
    url = '/api/auth/change-password/'
    
    def test_change_password_valid(self, authenticated_client, test_user):
        """Test successful password change."""
        data = {
            'old_password': 'TestPass123!',
            'new_password': 'NewStrongPass456!'
        }
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        
        # Verify new password works
        test_user.refresh_from_db()
        assert test_user.check_password('NewStrongPass456!')
    
    def test_change_password_wrong_old_password(self, authenticated_client):
        """Test password change fails with wrong old password."""
        data = {
            'old_password': 'WrongOldPassword!',
            'new_password': 'NewStrongPass456!'
        }
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_change_password_missing_fields(self, authenticated_client):
        """Test password change fails with missing fields."""
        data = {
            'old_password': 'TestPass123!'
            # Missing new_password
        }
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_change_password_unauthenticated(self, api_client):
        """Test password change without authentication fails."""
        data = {
            'old_password': 'TestPass123!',
            'new_password': 'NewStrongPass456!'
        }
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_change_password_empty_new_password(self, authenticated_client):
        """Test password change fails with empty new password."""
        data = {
            'old_password': 'TestPass123!',
            'new_password': ''
        }
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ==================== TOKEN REFRESH TESTS ====================

@pytest.mark.django_db
class TestTokenRefresh:
    """Tests for token refresh endpoint."""
    
    url = '/api/auth/token/refresh/'
    
    def test_refresh_valid_token(self, api_client, test_user):
        """Test token refresh with valid refresh token."""
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(test_user)
        
        data = {'refresh': str(refresh)}
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        # Refreshed access token is delivered via the HttpOnly cookie, not the body.
        assert 'access_token' in response.cookies
        assert 'access' not in response.data
    
    def test_refresh_invalid_token(self, api_client):
        """Test token refresh with invalid token fails."""
        data = {'refresh': 'invalid_refresh_token'}
        response = api_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_refresh_missing_token(self, api_client):
        """Test token refresh without token fails."""
        response = api_client.post(self.url, {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ==================== EDGE CASES ====================

@pytest.mark.django_db
class TestUserEdgeCases:
    """Edge case tests for user-related endpoints."""
    
    def test_register_empty_request_body(self, api_client):
        """Test registration with empty request body."""
        response = api_client.post('/api/auth/register/', {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_register_null_values(self, api_client):
        """Test registration with null values."""
        data = {
            'username': None,
            'email': None,
            'password': None,
            'password2': None,
        }
        response = api_client.post('/api/auth/register/', data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_login_empty_request_body(self, api_client):
        """Test login with empty request body."""
        response = api_client.post('/api/auth/login/', {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_profile_put_vs_patch(self, authenticated_client):
        """Test PUT request to profile endpoint."""
        data = {
            'first_name': 'Updated'
        }
        response = authenticated_client.put('/api/auth/profile/', data, format='json')
        # PUT might require all fields - should not cause 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_special_characters_in_address(self, authenticated_client):
        """Test special characters in address field."""
        data = {
            'address': '123 Main St. #Apt-5, (Near Park), City & State'
        }
        response = authenticated_client.patch('/api/auth/profile/', data, format='json')
        assert response.status_code == status.HTTP_200_OK


# --- From test_email_normalization.py ---

REGISTER_URL = "/api/auth/register/"
LOGIN_URL = "/api/auth/login/"


def _reg_payload(username, email):
    return {
        "username": username, "email": email, "name": "X",
        "first_name": "X", "last_name": "Y", "phone": "9999999999",
        "password": "TestPass123!", "password2": "TestPass123!",
    }


@pytest.mark.django_db
class TestEmailNormalization:
    def test_email_stored_lowercase(self, db):
        u = User.objects.create_user(username="up", email="Mixed.Case@Example.COM", password="x")
        u.refresh_from_db()
        assert u.email == "mixed.case@example.com"

    def test_register_lowercases_email(self, api_client):
        r = api_client.post(REGISTER_URL, _reg_payload("u1", "New.User@Example.com"), format="json")
        assert r.status_code in (200, 201)
        assert User.objects.filter(email="new.user@example.com").exists()

    def test_case_variant_registration_rejected(self, api_client):
        first = api_client.post(REGISTER_URL, _reg_payload("u1", "dup@example.com"), format="json")
        assert first.status_code in (200, 201)
        # AP5/S9: same generic 201 as a fresh address — existence stays hidden.
        second = api_client.post(REGISTER_URL, _reg_payload("u2", "DUP@example.com"), format="json")
        assert second.status_code == 201
        assert User.objects.filter(email__iexact="dup@example.com").count() == 1

    def test_login_is_case_insensitive(self, api_client):
        from datetime import timedelta
        from django.utils import timezone
        from users.models import PasswordResetOTP
        api_client.post(REGISTER_URL, _reg_payload("u1", "case@example.com"), format="json")
        # AP5: confirm the OTP first (known code via a model row), then log in.
        # Consume the registration-issued code first so exactly one live OTP
        # exists — latest() can never be ambiguous.
        user = User.objects.get(email="case@example.com")
        PasswordResetOTP.objects.filter(user=user, is_used=False).update(is_used=True)
        record = PasswordResetOTP(user=user, expires_at=timezone.now() + timedelta(minutes=10))
        record.set_otp("123456")
        record.save()
        confirm = api_client.post("/api/auth/verify-email/",
                                  {"email": "case@example.com", "otp_code": "123456"},
                                  format="json")
        assert confirm.status_code == 200
        for typed in ("case@example.com", "CASE@example.com", "Case@Example.Com"):
            r = api_client.post(LOGIN_URL, {"email": typed, "password": "TestPass123!"}, format="json")
            assert r.status_code == 200, f"login failed for {typed!r}"


@pytest.mark.django_db
class TestProfileEmailUpdate:
    """G8 — the profile update path must apply the same email rules, not 500."""

    def test_case_variant_of_other_user_rejected_cleanly(self, authenticated_client, test_user):
        # another account owns victim@example.com
        User.objects.create_user(username="victim", email="victim@example.com", password="x")
        r = authenticated_client.patch("/api/auth/profile/", {"email": "VICTIM@example.com"}, format="json")
        assert r.status_code == 400            # clean validation error, NOT a 500
        test_user.refresh_from_db()
        assert test_user.email != "victim@example.com"

    def test_profile_email_is_normalized(self, authenticated_client, test_user):
        r = authenticated_client.patch("/api/auth/profile/", {"email": "New.Me@Example.COM"}, format="json")
        assert r.status_code == 200
        test_user.refresh_from_db()
        assert test_user.email == "new.me@example.com"

    def test_can_keep_own_email_unchanged(self, authenticated_client, test_user):
        # PATCHing the same email (any case) must not trip the uniqueness check on self.
        r = authenticated_client.patch(
            "/api/auth/profile/", {"email": test_user.email.upper(), "city": "Pune"}, format="json")
        assert r.status_code == 200
        test_user.refresh_from_db()
        assert test_user.city == "Pune"


# --- From test_password_reset.py ---

REQ_URL = "/api/auth/password-reset-request/"
VERIFY_URL = "/api/auth/password-reset-verify/"
CONFIRM_URL = "/api/auth/password-reset-confirm/"


def _seed_otp(user, raw="654321", minutes=10):
    otp = PasswordResetOTP(user=user, expires_at=timezone.now() + timedelta(minutes=minutes))
    otp.set_otp(raw)
    otp.save()
    return otp


@pytest.mark.django_db
class TestOTPModel:
    def test_otp_is_hashed_at_rest(self, test_user):
        otp = _seed_otp(test_user, "123456")
        assert otp.otp_code != "123456"          # never stored in clear
        assert "$" in otp.otp_code               # Django password-hash format

    def test_check_otp_accepts_correct_rejects_wrong(self, test_user):
        otp = _seed_otp(test_user, "123456")
        assert otp.check_otp("123456") is True
        assert otp.check_otp("000000") is False

    def test_is_expired_boundary(self, test_user):
        past = PasswordResetOTP(user=test_user, expires_at=timezone.now() - timedelta(seconds=1))
        future = PasswordResetOTP(user=test_user, expires_at=timezone.now() + timedelta(seconds=60))
        assert past.is_expired is True
        assert future.is_expired is False

    def test_is_locked_at_max_attempts(self, test_user):
        otp = PasswordResetOTP(user=test_user, expires_at=timezone.now() + timedelta(minutes=5))
        otp.failed_attempts = PasswordResetOTP.MAX_FAILED_ATTEMPTS - 1
        assert otp.is_locked is False
        otp.failed_attempts = PasswordResetOTP.MAX_FAILED_ATTEMPTS
        assert otp.is_locked is True


@pytest.mark.django_db
class TestResetRequest:
    def test_unknown_email_returns_generic_200(self, api_client):
        r = api_client.post(REQ_URL, {"email": "nobody-here@example.com"}, format="json")
        assert r.status_code == 200
        assert not PasswordResetOTP.objects.exists()   # no record created

    def test_known_email_creates_otp_and_invalidates_prior(self, api_client, test_user):
        old = _seed_otp(test_user, "111111")
        r = api_client.post(REQ_URL, {"email": test_user.email}, format="json")
        assert r.status_code == 200
        old.refresh_from_db()
        assert old.is_used is True                      # previous unused OTP retired
        # a fresh, unused OTP now exists
        assert PasswordResetOTP.objects.filter(user=test_user, is_used=False).exists()


@pytest.mark.django_db
class TestResetVerify:
    def test_wrong_code_increments_then_locks(self, api_client, test_user):
        _seed_otp(test_user, "654321")
        last = None
        for _ in range(PasswordResetOTP.MAX_FAILED_ATTEMPTS):
            last = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "000000"}, format="json")
        # 5th wrong attempt exhausts the allowance
        assert last.status_code == 429
        # a further attempt is locked out even if the code were correct
        again = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"}, format="json")
        assert again.status_code == 429

    def test_expired_otp_rejected(self, api_client, test_user):
        _seed_otp(test_user, "654321", minutes=-1)      # already expired
        r = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"}, format="json")
        assert r.status_code == 400

    def test_correct_code_is_single_use(self, api_client, test_user):
        _seed_otp(test_user, "654321")
        ok = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"}, format="json")
        assert ok.status_code == 200 and ok.json().get("reset_token")
        # verifying again finds no unused OTP -> rejected
        again = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"}, format="json")
        assert again.status_code == 400


@pytest.mark.django_db
class TestResetConfirm:
    def test_full_flow_resets_password(self, api_client, test_user):
        _seed_otp(test_user, "654321")
        token = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"},
                                format="json").json()["reset_token"]
        new_pw = "BrandNewP@ss99"
        r = api_client.post(CONFIRM_URL, {
            "email": test_user.email, "reset_token": token,
            "new_password": new_pw, "confirm_password": new_pw,
        }, format="json")
        assert r.status_code == 200
        # new password works, old one no longer does
        assert api_client.post(LOGIN_URL, {"email": test_user.email, "password": new_pw},
                               format="json").status_code == 200
        assert api_client.post(LOGIN_URL, {"email": test_user.email, "password": "TestPass123!"},
                               format="json").status_code in (400, 401)

    def test_confirm_with_bad_token_rejected(self, api_client, test_user):
        _seed_otp(test_user, "654321")
        r = api_client.post(CONFIRM_URL, {
            "email": test_user.email, "reset_token": "not-a-real-token",
            "new_password": "Whatever123!", "confirm_password": "Whatever123!",
        }, format="json")
        assert r.status_code == 400

    def test_confirm_password_mismatch_rejected(self, api_client, test_user):
        _seed_otp(test_user, "654321")
        token = api_client.post(VERIFY_URL, {"email": test_user.email, "otp_code": "654321"},
                                format="json").json()["reset_token"]
        r = api_client.post(CONFIRM_URL, {
            "email": test_user.email, "reset_token": token,
            "new_password": "Mismatch123!", "confirm_password": "Different123!",
        }, format="json")
        assert r.status_code == 400
