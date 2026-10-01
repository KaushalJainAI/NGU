"""AP5 (S1-full, S9): email verification + uniform registration responses."""
import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from users.models import PasswordResetOTP

User = get_user_model()

REGISTER = '/api/auth/register/'
LOGIN = '/api/auth/login/'
VERIFY = '/api/auth/verify-email/'
RESEND = '/api/auth/verify-email/request/'

GENERIC_REGISTER = {'detail': 'If this email is new, a verification code was sent.'}
LOC_MEM = {'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}


def _reg(api_client, email='new@example.com', username='newuser'):
    return api_client.post(REGISTER, {
        'username': username, 'email': email,
        'password': 'StrongPass123!', 'password2': 'StrongPass123!',
    }, format='json')


def _code_from_outbox():
    assert len(mail.outbox) == 1
    assert 'Verify' in mail.outbox[0].subject
    return re.search(r'\b(\d{6})\b', mail.outbox[0].body).group(1)


@pytest.mark.django_db
class TestRegistrationAndVerify:
    @override_settings(**LOC_MEM)
    def test_register_verify_then_login(self, api_client):
        mail.outbox = []
        assert _reg(api_client) .status_code == 201
        user = User.objects.get(email='new@example.com')
        assert user.email_verified is False
        # Unusable until proven: password is right, inbox is not.
        r = api_client.post(LOGIN, {'email': 'new@example.com',
                                    'password': 'StrongPass123!'}, format='json')
        assert r.status_code == 403
        assert r.data['code'] == 'email_not_verified'
        assert 'access_token' not in r.cookies
        # The REAL emailed code confirms the address.
        code = _code_from_outbox()
        rv = api_client.post(VERIFY, {'email': 'new@example.com', 'otp_code': code},
                             format='json')
        assert rv.status_code == 200
        assert rv.data == {'success': True}
        user.refresh_from_db()
        assert user.email_verified is True
        r2 = api_client.post(LOGIN, {'email': 'new@example.com',
                                     'password': 'StrongPass123!'}, format='json')
        assert r2.status_code == 200
        assert 'access_token' in r2.cookies

    @override_settings(**LOC_MEM)
    def test_register_existing_email_same_response_no_send(self, api_client, test_user):
        mail.outbox = []
        count_before = User.objects.count()
        r = _reg(api_client, email=test_user.email, username='someone-else')
        assert r.status_code == 201
        assert r.data == GENERIC_REGISTER
        assert User.objects.count() == count_before
        assert mail.outbox == []

    def test_google_signin_marks_verified(self, api_client, monkeypatch):
        monkeypatch.setattr(
            'users.views.id_token.verify_oauth2_token',
            lambda *a, **k: {'email': 'guser@example.com', 'email_verified': True,
                             'name': 'G User', 'given_name': 'G', 'family_name': 'User'},
        )
        r = api_client.post('/api/auth/google/', {'access_token': 'good'}, format='json')
        assert r.status_code == 201
        assert 'access_token' in r.cookies
        assert User.objects.get(email='guser@example.com').email_verified is True

    def test_profile_includes_email_verified(self, authenticated_client):
        r = authenticated_client.get('/api/auth/profile/')
        assert r.status_code == 200
        assert r.data['email_verified'] is True


@pytest.mark.django_db
class TestVerifyResend:
    @override_settings(**LOC_MEM)
    def test_resend_issues_code_for_unverified(self, api_client):
        mail.outbox = []
        assert _reg(api_client).status_code == 201
        assert len(mail.outbox) == 1  # registration code
        r = api_client.post(RESEND, {'email': 'new@example.com'}, format='json')
        assert r.status_code == 200
        assert len(mail.outbox) == 2
        code = re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)
        assert api_client.post(VERIFY, {'email': 'new@example.com',
                                        'otp_code': code}, format='json').status_code == 200

    @override_settings(**LOC_MEM)
    def test_resend_is_generic_for_unknown_or_verified(self, api_client, test_user):
        mail.outbox = []
        for email in ('nobody@example.com', test_user.email):
            r = api_client.post(RESEND, {'email': email}, format='json')
            assert r.status_code == 200
        assert mail.outbox == []

    def test_unverified_staff_cannot_admin_login(self, api_client, db):
        staff = User.objects.create_user(username='staffer', email='staff@example.com',
                                         password='StaffPass123!', is_staff=True)
        assert staff.email_verified is False
        r = api_client.post('/api/auth/admin/login/',
                            {'email': 'staff@example.com', 'password': 'StaffPass123!'},
                            format='json')
        assert r.status_code == 403
        assert r.data['code'] == 'email_not_verified'
        assert 'admin_access_token' not in r.cookies


@pytest.mark.django_db
class TestGrandfathering:
    def test_migration_grandfathers_proven_inboxes(self, db, test_product):
        import importlib
        from decimal import Decimal
        from django.apps import apps
        from orders.models import Order
        _migration = importlib.import_module('users.migrations.0010_user_email_verified')
        grandfather_verified = _migration.grandfather_verified

        plain = User.objects.create_user(username='plain', email='plain@x.com', password='x')
        buyer = User.objects.create_user(username='buyer', email='buyer@x.com', password='x')
        Order.objects.create(
            user=buyer, shipping_address='s', phone_number='1', payment_method='COD',
            subtotal=Decimal('120.00'), tax=Decimal('12.00'), total_amount=Decimal('132.00'),
            status='delivered',
        )
        goog = User.objects.create_user(username='goog', email='goog@x.com', password='x')
        goog.set_unusable_password()
        goog.last_login = timezone.now()
        goog.save()

        grandfather_verified(apps, None)

        assert User.objects.get(pk=plain.pk).email_verified is False
        assert User.objects.get(pk=buyer.pk).email_verified is True
        assert User.objects.get(pk=goog.pk).email_verified is True
