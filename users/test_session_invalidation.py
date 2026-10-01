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
