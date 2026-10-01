"""S1: Google sign-in into an UNVERIFIED password account kills the password.

A password on a row whose inbox was never proven may be a squatter's. When the
real owner signs in with Google (verified inbox), that password must stop
working and any session must die. A verified account's password is the
owner's own and is left alone.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

URL = '/api/auth/google/'


def _idinfo(email, verified=True):
    return {
        'email': email,
        'email_verified': verified,
        'name': 'Victim Owner',
        'given_name': 'Victim',
        'family_name': 'Owner',
    }


@pytest.fixture
def verify(monkeypatch):
    def _set(idinfo):
        monkeypatch.setattr('users.views.id_token.verify_oauth2_token',
                            lambda *a, **k: idinfo)
    return _set


@pytest.fixture
def squatted(db):
    """A password account whose inbox was never proven (what a squatter makes)."""
    return User.objects.create_user(username='squatted', email='squatted@example.com',
                                    password='TestPass123!')


@pytest.mark.django_db
class TestGooglePrehijack:
    def test_google_signin_disables_an_unproven_password(self, api_client, verify, squatted):
        """The S1 probe from the audit, asserting the fix: register with a
        password, then the owner signs in with Google for the same address."""
        verify(_idinfo(squatted.email, verified=True))
        r = api_client.post(URL, {'access_token': 'owner-google-credential'}, format='json')
        assert r.status_code == 200
        squatted.refresh_from_db()
        assert not squatted.has_usable_password()
        assert squatted.email_verified is True
        assert api_client.post(
            '/api/auth/login/', {'email': squatted.email, 'password': 'TestPass123!'},
            format='json').status_code in (400, 401)

    def test_sessions_of_an_unproven_account_die_on_google_signin(
            self, api_client, verify, squatted):
        from rest_framework_simplejwt.tokens import RefreshToken
        # A session that predates verification (legacy rows could hold one).
        stale = str(RefreshToken.for_user(squatted))
        verify(_idinfo(squatted.email, verified=True))
        assert api_client.post(URL, {'access_token': 'owner'}, format='json').status_code == 200
        assert api_client.post('/api/auth/token/refresh/',
                               {'refresh': stale}, format='json').status_code == 401

    def test_verified_account_keeps_its_password(self, api_client, verify, test_user):
        """The owner of a verified account chose that password. Using Google
        once must not silently take password login away."""
        verify(_idinfo(test_user.email, verified=True))
        assert api_client.post(URL, {'access_token': 'owner'}, format='json').status_code == 200
        r = api_client.post('/api/auth/login/',
                            {'email': test_user.email, 'password': 'TestPass123!'},
                            format='json')
        assert r.status_code == 200

    def test_staff_keep_admin_password_login_after_storefront_google_signin(
            self, api_client, verify, test_admin):
        verify(_idinfo(test_admin.email, verified=True))
        assert api_client.post(URL, {'access_token': 'owner'}, format='json').status_code == 200
        r = api_client.post('/api/auth/admin/login/',
                            {'email': test_admin.email, 'password': 'AdminPass123!'},
                            format='json')
        assert r.status_code == 200

    def test_disabled_account_cannot_sign_in_with_google(self, api_client, verify, test_user):
        test_user.is_active = False
        test_user.save(update_fields=['is_active'])
        verify(_idinfo(test_user.email, verified=True))
        r = api_client.post(URL, {'access_token': 'owner'}, format='json')
        assert r.status_code == 403
        assert 'access_token' not in r.cookies

    def test_google_first_account_unaffected(self, api_client, verify):
        """A brand-new Google sign-in still creates a working session (201)."""
        verify(_idinfo('fresh-owner@example.com', verified=True))
        r = api_client.post(URL, {'access_token': 'good'}, format='json')
        assert r.status_code == 201
        assert User.objects.get(email='fresh-owner@example.com').has_usable_password() is False
