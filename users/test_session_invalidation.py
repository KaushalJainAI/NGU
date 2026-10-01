"""AP3/S4: password change and reset revoke ALL sessions (customer + admin).

Access tokens are stateless and live out their remaining minutes; the refresh
path is what dies. Every assertion below is on the refresh endpoints.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from users.models import PasswordResetOTP

NEW_PASSWORD = 'NewStrongPass123!'


def _customer_refresh(api_client, email, password):
    r = api_client.post('/api/auth/login/', {'email': email, 'password': password},
                        format='json')
    assert r.status_code == 200, r.content
    return r.cookies['refresh_token'].value


def _admin_refresh(api_client, email, password):
    r = api_client.post('/api/auth/admin/login/', {'email': email, 'password': password},
                        format='json')
    assert r.status_code == 200, r.content
    return r.cookies['admin_refresh_token'].value


@pytest.mark.django_db
class TestPasswordChangeRevokesSessions:
    def test_old_customer_refresh_dies(self, api_client, test_user):
        old = _customer_refresh(api_client, 'testuser@example.com', 'TestPass123!')
        # Authenticated as the user (Bearer, no CSRF games in tests).
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(test_user)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        r = api_client.post('/api/auth/change-password/',
                            {'old_password': 'TestPass123!', 'new_password': NEW_PASSWORD},
                            format='json')
        assert r.status_code == 200, r.content
        api_client.credentials()  # drop Bearer
        r2 = api_client.post('/api/auth/token/refresh/', {'refresh': old}, format='json')
        assert r2.status_code == 401
        # New password works going forward.
        _customer_refresh(api_client, 'testuser@example.com', NEW_PASSWORD)

    def test_admin_session_of_same_user_dies(self, api_client, test_admin):
        customer_old = _customer_refresh(api_client, 'admin@example.com', 'AdminPass123!')
        admin_old = _admin_refresh(api_client, 'admin@example.com', 'AdminPass123!')
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(test_admin)
        api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {token.access_token}')
        r = api_client.post('/api/auth/change-password/',
                            {'old_password': 'AdminPass123!', 'new_password': NEW_PASSWORD},
                            format='json')
        assert r.status_code == 200, r.content
        api_client.credentials()
        assert api_client.post('/api/auth/token/refresh/',
                               {'refresh': customer_old}, format='json').status_code == 401
        api_client.cookies['admin_refresh_token'] = admin_old
        assert api_client.post('/api/auth/admin/token/refresh/').status_code == 401


@pytest.mark.django_db
class TestPasswordResetRevokesSessions:
    def test_reset_confirm_kills_old_refresh(self, api_client, test_user):
        old = _customer_refresh(api_client, 'testuser@example.com', 'TestPass123!')
        record = PasswordResetOTP(user=test_user,
                                  expires_at=timezone.now() + timedelta(minutes=10))
        record.set_otp('123456')
        record.save()
        rv = api_client.post('/api/auth/password-reset-verify/',
                             {'email': 'testuser@example.com', 'otp_code': '123456'},
                             format='json')
        assert rv.status_code == 200, rv.content
        rc = api_client.post('/api/auth/password-reset-confirm/', {
            'email': 'testuser@example.com',
            'reset_token': rv.data['reset_token'],
            'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        }, format='json')
        assert rc.status_code == 200, rc.content
        assert api_client.post('/api/auth/token/refresh/',
                               {'refresh': old}, format='json').status_code == 401
        _customer_refresh(api_client, 'testuser@example.com', NEW_PASSWORD)


@pytest.mark.django_db
class TestCallerKeepsTheirSession:
    """Revoking every session must not log out the person who asked for it."""

    def _cookie_client(self, email, password):
        from rest_framework.test import APIClient
        client = APIClient()
        r = client.post('/api/auth/login/', {'email': email, 'password': password},
                        format='json')
        assert r.status_code == 200, r.content
        return client, r.cookies['refresh_token'].value

    def test_password_change_reissues_the_callers_cookies(self, test_user):
        client, old = self._cookie_client('testuser@example.com', 'TestPass123!')
        r = client.post('/api/auth/change-password/',
                        {'old_password': 'TestPass123!', 'new_password': NEW_PASSWORD},
                        format='json')
        assert r.status_code == 200, r.content
        assert 'refresh_token' in r.cookies and 'access_token' in r.cookies
        assert r.cookies['refresh_token'].value != old
        # The same browser carries on...
        assert client.post('/api/auth/token/refresh/', {}, format='json').status_code == 200
        assert client.get('/api/auth/profile/').status_code == 200
        # ...while the token it held before is dead (so is any other device's).
        from rest_framework.test import APIClient
        assert APIClient().post('/api/auth/token/refresh/', {'refresh': old},
                                format='json').status_code == 401

    def test_reset_marks_the_email_verified(self, api_client):
        """The reset code proves the inbox; login must work straight after."""
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(
            username='unv', email='unv@example.com', password='Whatever-123!')
        assert user.email_verified is False
        record = PasswordResetOTP(user=user, expires_at=timezone.now() + timedelta(minutes=10))
        record.set_otp('123456')
        record.save()
        rv = api_client.post('/api/auth/password-reset-verify/',
                             {'email': 'unv@example.com', 'otp_code': '123456'}, format='json')
        rc = api_client.post('/api/auth/password-reset-confirm/', {
            'email': 'unv@example.com', 'reset_token': rv.data['reset_token'],
            'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD,
        }, format='json')
        assert rc.status_code == 200, rc.content
        _customer_refresh(api_client, 'unv@example.com', NEW_PASSWORD)
