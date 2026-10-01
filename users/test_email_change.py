"""AP6/S3: the login email changes ONLY via change-email/ (password + OTP)."""
import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

CHANGE_URL = '/api/auth/change-email/'
PROFILE_URL = '/api/auth/profile/'
LOC_MEM = {'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}


@pytest.fixture
def bearer(api_client, test_user):
    """APIClient carrying a Bearer token for test_user (no CSRF games)."""
    token = RefreshToken.for_user(test_user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
    return api_client


@pytest.mark.django_db
class TestProfileEmailLocked:
    def test_patch_email_rejected_with_pointer(self, bearer, test_user):
        r = bearer.patch(PROFILE_URL, {'email': 'brand@new.com'}, format='json')
        assert r.status_code == 400
        assert 'change-email' in str(r.data)
        test_user.refresh_from_db()
        assert test_user.email == 'testuser@example.com'


@pytest.mark.django_db
class TestChangeEmail:
    def test_requires_current_password(self, bearer):
        assert bearer.post(CHANGE_URL, {'new_email': 'a@b.com'}, format='json').status_code == 400
        r = bearer.post(CHANGE_URL, {'new_email': 'a@b.com', 'current_password': 'Wrong!'},
                        format='json')
        # 400, not 401: a 401 reads as "session expired" and logs the user out.
        assert r.status_code == 400
        r2 = bearer.post(CHANGE_URL, {'new_email': 'a@b.com', 'current_password': 'Wrong!',
                                      'otp_code': '000000'}, format='json')
        assert r2.status_code == 400

    def test_taken_address_rejected(self, bearer, test_user2):
        r = bearer.post(CHANGE_URL, {'new_email': test_user2.email,
                                     'current_password': 'TestPass123!'}, format='json')
        assert r.status_code == 400

    @override_settings(**LOC_MEM)
    def test_full_two_step(self, api_client, test_user):
        mail.outbox = []
        old_refresh = api_client.post(
            '/api/auth/login/',
            {'email': 'testuser@example.com', 'password': 'TestPass123!'},
            format='json').cookies['refresh_token'].value
        token = RefreshToken.for_user(test_user)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')

        r1 = api_client.post(CHANGE_URL, {'new_email': 'moved@example.com',
                                          'current_password': 'TestPass123!'}, format='json')
        assert r1.status_code == 200
        assert r1.data == {'detail': 'Code sent.'}
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['moved@example.com']
        code = re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)

        test_user.refresh_from_db()
        assert test_user.email == 'testuser@example.com'  # unchanged until call 2

        r2 = api_client.post(CHANGE_URL, {'new_email': 'moved@example.com',
                                          'current_password': 'TestPass123!',
                                          'otp_code': code}, format='json')
        assert r2.status_code == 200
        test_user.refresh_from_db()
        assert test_user.email == 'moved@example.com'
        assert test_user.email_verified is True

        # Every OTHER session died; the old address was notified.
        api_client.credentials()
        assert api_client.post('/api/auth/token/refresh/',
                               {'refresh': old_refresh}, format='json').status_code == 401
        assert [m.to for m in mail.outbox] == [['moved@example.com'], ['testuser@example.com']]
        # New address logs in going forward.
        assert api_client.post(
            '/api/auth/login/',
            {'email': 'moved@example.com', 'password': 'TestPass123!'},
            format='json').status_code == 200

    def test_wrong_code_rejected(self, bearer, test_user):
        bearer.post(CHANGE_URL, {'new_email': 'moved@example.com',
                                 'current_password': 'TestPass123!'}, format='json')
        r = bearer.post(CHANGE_URL, {'new_email': 'moved@example.com',
                                     'current_password': 'TestPass123!',
                                     'otp_code': '000000'}, format='json')
        assert r.status_code == 400
        test_user.refresh_from_db()
        assert test_user.email == 'testuser@example.com'


@pytest.mark.django_db
class TestAccessLifetime:
    def test_access_token_lifetime_is_15_minutes(self, api_client, test_user):
        """AP6: stolen access cookies are useful for minutes, not an hour."""
        from rest_framework_simplejwt.tokens import AccessToken
        r = api_client.post('/api/auth/login/',
                            {'email': test_user.email, 'password': 'TestPass123!'},
                            format='json')
        assert r.status_code == 200
        claims = AccessToken(r.cookies['access_token'].value)
        assert claims['exp'] - claims['iat'] == 900
