"""Tests for /api/auth/google/ (GoogleLogin).

This endpoint had no coverage at all until 2026-07-25, despite issuing session
cookies. The critical case is `test_unverified_email_rejected`: a validly-signed
id_token can still carry an unverified email, and since accounts are matched by
email, trusting one would be account takeover.

Google's servers are never contacted — `id_token.verify_oauth2_token` is patched,
which is exactly the trust boundary under test.
"""
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

URL = '/api/auth/google/'


def _idinfo(email='someone@example.com', verified=True, **extra):
    info = {
        'email': email,
        'email_verified': verified,
        'name': 'Some One',
        'given_name': 'Some',
        'family_name': 'One',
    }
    info.update(extra)
    return info


@pytest.fixture
def verify(monkeypatch):
    """Patches Google token verification; yields a setter for the payload."""
    def _set(idinfo=None, side_effect=None):
        target = 'users.views.id_token.verify_oauth2_token'
        if side_effect is not None:
            return patch(target, side_effect=side_effect).start()
        return patch(target, return_value=idinfo).start()
    yield _set
    patch.stopall()


@pytest.mark.django_db
class TestGoogleLoginSecurity:
    def test_unverified_email_rejected(self, api_client, verify, test_user):
        """A signed token with email_verified=False must NOT log anyone in.

        This is the account-takeover case: the email matches an existing local
        account, so a pre-fix build would hand back that user's session cookies.
        """
        verify(_idinfo(email=test_user.email, verified=False))
        r = api_client.post(URL, {'access_token': 'signed-but-unverified'}, format='json')

        assert r.status_code == 401
        assert 'access_token' not in r.cookies
        assert 'refresh_token' not in r.cookies

    def test_unverified_email_does_not_create_account(self, api_client, verify):
        verify(_idinfo(email='brand-new@example.com', verified=False))
        r = api_client.post(URL, {'access_token': 'signed-but-unverified'}, format='json')

        assert r.status_code == 401
        assert not User.objects.filter(email='brand-new@example.com').exists()

    def test_missing_email_verified_claim_rejected(self, api_client, verify):
        """Absent claim is treated as unverified, not as permission."""
        info = _idinfo()
        del info['email_verified']
        verify(info)
        assert api_client.post(URL, {'access_token': 'x'}, format='json').status_code == 401

    def test_invalid_token_rejected(self, api_client, verify):
        verify(side_effect=ValueError('Wrong issuer.'))
        r = api_client.post(URL, {'access_token': 'forged'}, format='json')
        assert r.status_code == 401
        assert 'access_token' not in r.cookies

    def test_missing_token_rejected(self, api_client):
        assert api_client.post(URL, {}, format='json').status_code == 400

    def test_no_email_in_token_rejected(self, api_client, verify):
        verify(_idinfo(email=None))
        assert api_client.post(URL, {'access_token': 'x'}, format='json').status_code == 400


@pytest.mark.django_db
class TestGoogleLoginHappyPath:
    def test_verified_new_user_created_and_logged_in(self, api_client, verify):
        verify(_idinfo(email='fresh@example.com', verified=True))
        r = api_client.post(URL, {'access_token': 'good'}, format='json')

        assert r.status_code == 201
        user = User.objects.get(email='fresh@example.com')
        assert not user.has_usable_password()
        # Tokens are delivered by HttpOnly cookie only, never the JSON body.
        assert r.cookies['access_token']['httponly']
        assert r.cookies['refresh_token']['httponly']
        assert 'access' not in r.json()
        assert 'refresh' not in r.json()

    def test_verified_string_true_accepted(self, api_client, verify):
        """Google sends "true" as a string in some flows."""
        verify(_idinfo(email='stringy@example.com', verified='true'))
        assert api_client.post(URL, {'access_token': 'good'}, format='json').status_code == 201

    def test_existing_user_matched_case_insensitively(self, api_client, verify, test_user):
        verify(_idinfo(email=test_user.email.upper(), verified=True))
        r = api_client.post(URL, {'access_token': 'good'}, format='json')

        assert r.status_code == 200
        # Matched the existing account rather than forking a second one.
        assert User.objects.filter(email__iexact=test_user.email).count() == 1

    def test_username_collision_across_domains(self, api_client, verify):
        """Same local part, different domains, must not 500."""
        verify(_idinfo(email='collide@first.com', verified=True))
        assert api_client.post(URL, {'access_token': 'g'}, format='json').status_code == 201

        patch.stopall()
        verify(_idinfo(email='collide@second.com', verified=True))
        r = api_client.post(URL, {'access_token': 'g'}, format='json')

        assert r.status_code == 201
        assert User.objects.filter(email='collide@second.com').exists()
        usernames = set(User.objects.filter(
            email__in=['collide@first.com', 'collide@second.com']
        ).values_list('username', flat=True))
        assert len(usernames) == 2
