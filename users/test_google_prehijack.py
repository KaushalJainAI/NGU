"""AP4/S1-interim: Google sign-in into a password account kills the password.

Anyone can register with someone else's email (no ownership proof until AP5).
When the real owner signs in with Google (verified inbox), the attacker's
password must stop working and the attacker's sessions must die.
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


@pytest.mark.django_db
class TestGooglePrehijackInterim:
    def test_google_signin_disables_existing_password(self, api_client, verify, test_user):
        """The S1 probe from the audit, asserting the fix: register with a
        password, then the owner signs in with Google for the same address."""
        verify(_idinfo(test_user.email, verified=True))
        r = api_client.post(URL, {'access_token': 'owner-google-credential'}, format='json')
        assert r.status_code == 200
        test_user.refresh_from_db()
        assert not test_user.has_usable_password()

    def test_attacker_password_login_fails_after_owner_google_signin(
            self, api_client, verify, test_user):
        old_password = 'TestPass123!'
        # Attacker session first (proves they were in).
        r = api_client.post('/api/auth/login/',
                            {'email': test_user.email, 'password': old_password},
                            format='json')
        assert r.status_code == 200
        attacker_refresh = r.cookies['refresh_token'].value
        # Owner proves the inbox via Google.
        verify(_idinfo(test_user.email, verified=True))
        assert api_client.post(URL, {'access_token': 'owner'}, format='json').status_code == 200
        # Attacker's password no longer works and their session is dead.
        assert api_client.post(
            '/api/auth/login/', {'email': test_user.email, 'password': old_password},
            format='json').status_code in (400, 401)
        assert api_client.post('/api/auth/token/refresh/',
                               {'refresh': attacker_refresh},
                               format='json').status_code == 401

    def test_google_first_account_unaffected(self, api_client, verify):
        """A brand-new Google sign-in still creates a working session (201)."""
        verify(_idinfo('fresh-owner@example.com', verified=True))
        r = api_client.post(URL, {'access_token': 'good'}, format='json')
        assert r.status_code == 201
        assert User.objects.get(email='fresh-owner@example.com').has_usable_password() is False
