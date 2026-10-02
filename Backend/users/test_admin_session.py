"""Admin session cookies (WP1): separate admin/customer sessions + admin Google login.

The Panel sends `X-Admin-Panel: 1` and the backend then reads ONLY the
`admin_access_token` cookie (which must carry `scope == 'admin'` and belong to
a staff user). Without the header it reads ONLY the customer cookie.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

User = get_user_model()

ADMIN_HEADER = {'HTTP_X_ADMIN_PANEL': '1'}
ACTIONS_URL = '/api/dashboard/actions/'
PROFILE_URL = '/api/auth/profile/'


def _idinfo(email='admin@example.com', verified=True, **extra):
    info = {
        'email': email,
        'email_verified': verified,
        'name': 'Admin',
        'given_name': 'Admin',
        'family_name': 'User',
    }
    info.update(extra)
    return info


@pytest.fixture
def verify_google(monkeypatch):
    def _set(idinfo=None, side_effect=None):
        target = 'users.views.id_token.verify_oauth2_token'
        if side_effect is not None:
            return patch(target, side_effect=side_effect).start()
        return patch(target, return_value=idinfo).start()
    yield _set
    patch.stopall()


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username='staffer', email='staffer@example.com', password='StaffPass123!',
        is_staff=True,
    )


@pytest.mark.django_db
class TestAdminLogin:
    def test_staff_login_sets_admin_cookies_only(self, api_client, test_admin):
        r = api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        assert r.status_code == 200
        assert 'admin_access_token' in r.cookies
        assert 'admin_refresh_token' in r.cookies
        assert 'access_token' not in r.cookies
        assert 'refresh_token' not in r.cookies

    def test_non_staff_admin_login_401_no_cookie(self, api_client, test_user):
        r = api_client.post('/api/auth/admin/login/', {
            'email': test_user.email, 'password': 'TestPass123!',
        }, format='json')
        assert r.status_code == 401
        assert 'admin_access_token' not in r.cookies
        assert 'admin_refresh_token' not in r.cookies


@pytest.mark.django_db
class TestAdminCookieRouting:
    def _admin_client(self, api_client, test_admin):
        r = api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        assert r.status_code == 200
        return api_client

    def test_header_plus_admin_cookie_ok(self, api_client, test_admin):
        api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        r = api_client.get(ACTIONS_URL, **ADMIN_HEADER)
        assert r.status_code == 200

    def test_header_plus_only_customer_cookie_refused(self, api_client, test_admin):
        # Customer session of a STAFF user must still be refused as an admin session.
        api_client.post('/api/auth/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        r = api_client.get(ACTIONS_URL, **ADMIN_HEADER)
        assert r.status_code in (401, 403)

    def test_no_header_plus_only_admin_cookie_unauthenticated(self, api_client, test_admin):
        api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        # Drop any customer cookies if present; keep only admin cookies.
        if 'access_token' in api_client.cookies:
            del api_client.cookies['access_token']
        if 'refresh_token' in api_client.cookies:
            del api_client.cookies['refresh_token']
        r = api_client.get(PROFILE_URL)
        assert r.status_code == 401

    def test_customer_token_in_admin_cookie_rejected(self, api_client, test_user):
        r = api_client.post('/api/auth/login/', {
            'email': test_user.email, 'password': 'TestPass123!',
        }, format='json')
        assert r.status_code == 200
        customer_access = r.cookies['access_token'].value
        api_client.cookies['admin_access_token'] = customer_access
        r2 = api_client.get(ACTIONS_URL, **ADMIN_HEADER)
        assert r2.status_code == 401


@pytest.mark.django_db
class TestLogoutIsolation:
    def test_logouts_clear_only_their_own_cookies(self, api_client, test_admin):
        api_client.post('/api/auth/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        assert 'access_token' in api_client.cookies
        assert 'admin_access_token' in api_client.cookies

        r = api_client.post('/api/auth/logout/')
        assert r.status_code == 200
        # Customer cookies cleared (deleted → empty value), admin cookies untouched.
        assert r.cookies['access_token'].value == ''
        assert r.cookies['refresh_token'].value == ''
        assert 'admin_access_token' not in r.cookies

        r2 = api_client.post('/api/auth/admin/logout/')
        assert r2.status_code == 200
        assert r2.cookies['admin_access_token'].value == ''
        assert r2.cookies['admin_refresh_token'].value == ''
        assert 'access_token' not in r2.cookies


@pytest.mark.django_db
class TestAdminRefresh:
    def test_refresh_keeps_admin_scope(self, api_client, test_admin):
        api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        r = api_client.post('/api/auth/admin/token/refresh/')
        assert r.status_code == 200
        new_access = r.cookies['admin_access_token'].value
        assert AccessToken(new_access)['scope'] == 'admin'

    def test_refresh_with_customer_token_rejected(self, api_client, test_user):
        r = api_client.post('/api/auth/login/', {
            'email': test_user.email, 'password': 'TestPass123!',
        }, format='json')
        customer_refresh = r.cookies['refresh_token'].value
        api_client.cookies['admin_refresh_token'] = customer_refresh
        r2 = api_client.post('/api/auth/admin/token/refresh/')
        assert r2.status_code == 401

    def test_refresh_after_demoted_401(self, api_client, test_admin):
        api_client.post('/api/auth/admin/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        test_admin.is_staff = False
        test_admin.save()
        r = api_client.post('/api/auth/admin/token/refresh/')
        assert r.status_code == 401


@pytest.mark.django_db
class TestAdminGoogleLogin:
    def test_staff_google_ok(self, api_client, verify_google, test_admin):
        verify_google(_idinfo(email=test_admin.email, verified=True))
        before = User.objects.count()
        r = api_client.post('/api/auth/admin/google/', {'id_token': 'good'}, format='json')
        assert r.status_code == 200
        assert 'admin_access_token' in r.cookies
        assert 'admin_refresh_token' in r.cookies
        assert User.objects.count() == before

    def test_unknown_google_403_no_user_created(self, api_client, verify_google):
        verify_google(_idinfo(email='stranger@example.com', verified=True))
        before = User.objects.count()
        r = api_client.post('/api/auth/admin/google/', {'id_token': 'good'}, format='json')
        assert r.status_code == 403
        assert User.objects.count() == before

    def test_unverified_google_401(self, api_client, verify_google, test_admin):
        verify_google(_idinfo(email=test_admin.email, verified=False))
        r = api_client.post('/api/auth/admin/google/', {'id_token': 'x'}, format='json')
        assert r.status_code == 401


@pytest.mark.django_db
class TestProfileIncludesIsStaff:
    def test_profile_includes_is_staff(self, api_client, test_admin):
        api_client.post('/api/auth/login/', {
            'email': test_admin.email, 'password': 'AdminPass123!',
        }, format='json')
        r = api_client.get(PROFILE_URL)
        assert r.status_code == 200
        assert r.data['is_staff'] is True
