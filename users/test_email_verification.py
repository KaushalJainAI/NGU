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


def _last_code():
    return re.search(r'\b(\d{6})\b', mail.outbox[-1].body).group(1)


def _verify(api_client, email, code, password='StrongPass123!'):
    return api_client.post(VERIFY, {'email': email, 'otp_code': code, 'password': password},
                           format='json')


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
        # The code alone is not enough — the password must come with it.
        assert api_client.post(VERIFY, {'email': 'new@example.com', 'otp_code': code},
                               format='json').status_code == 400
        rv = _verify(api_client, 'new@example.com', code)
        assert rv.status_code == 200
        assert rv.data == {'success': True}
        user.refresh_from_db()
        assert user.email_verified is True
        r2 = api_client.post(LOGIN, {'email': 'new@example.com',
                                     'password': 'StrongPass123!'}, format='json')
        assert r2.status_code == 200
        assert 'access_token' in r2.cookies

    @override_settings(**LOC_MEM)
    def test_register_existing_email_same_response_no_code(self, api_client, test_user):
        from django.core.cache import cache
        cache.clear()
        mail.outbox = []
        count_before = User.objects.count()
        old_hash = test_user.password
        r = _reg(api_client, email=test_user.email, username='someone-else')
        assert r.status_code == 201
        assert r.data == GENERIC_REGISTER
        assert User.objects.count() == count_before
        # A verified account is never touched; its owner gets a notice, not a code.
        test_user.refresh_from_db()
        assert test_user.password == old_hash
        assert test_user.username == 'testuser'
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [test_user.email]
        assert 'already have' in mail.outbox[0].subject
        assert not re.search(r'\b\d{6}\b', mail.outbox[0].body)
        # ...and only one notice a day, however often the form is submitted.
        _reg(api_client, email=test_user.email, username='someone-else-2')
        assert len(mail.outbox) == 1

    def test_invalid_form_reads_the_same_for_new_and_existing_email(self, api_client, test_user):
        """S9: a bad payload must not reveal whether the address is taken."""
        def bad(email, username):
            return api_client.post(REGISTER, {
                'username': username, 'email': email,
                'password': 'StrongPass123!', 'password2': 'does-not-match',
            }, format='json')
        new = bad('nobody-yet@example.com', 'u-new')
        taken = bad(test_user.email, 'u-taken')
        assert new.status_code == taken.status_code == 400
        assert new.data == taken.data

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
        assert _verify(api_client, 'new@example.com', _last_code()).status_code == 200

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
        # Google sign-in never stamps last_login, so the rule must not need it.
        goog = User.objects.create_user(username='goog', email='goog@x.com', password='x')
        goog.set_unusable_password()
        goog.save()
        staff = User.objects.create_user(username='staff', email='staff@x.com', password='x',
                                         is_staff=True)

        grandfather_verified(apps, None)

        assert User.objects.get(pk=plain.pk).email_verified is False
        assert User.objects.get(pk=buyer.pk).email_verified is True
        assert User.objects.get(pk=goog.pk).email_verified is True
        # Without this the owner is locked out of the admin panel on deploy.
        assert User.objects.get(pk=staff.pk).email_verified is True


OWNER_PW = 'Owner-Pass-7712!'
SQUAT_PW = 'Squatter-Pass-9931!'


def _register(api_client, email, username, password):
    return api_client.post(REGISTER, {
        'username': username, 'email': email, 'password': password, 'password2': password,
    }, format='json')


def _login(api_client, email, password):
    return api_client.post(LOGIN, {'email': email, 'password': password}, format='json')


@pytest.mark.django_db
class TestPreHijackClosed:
    """S1: registering someone else's address must never yield their account."""

    @override_settings(**LOC_MEM)
    def test_owner_registering_over_a_squatter_replaces_the_squatter(self, api_client):
        mail.outbox = []
        victim = 'victim@example.com'
        assert _register(api_client, victim, 'squatter', SQUAT_PW).status_code == 201
        assert _register(api_client, victim, 'owner', OWNER_PW).status_code == 201
        assert User.objects.filter(email=victim).count() == 1
        assert _verify(api_client, victim, _last_code(), OWNER_PW).status_code == 200
        user = User.objects.get(email=victim)
        assert user.username == 'owner'
        assert _login(api_client, victim, OWNER_PW).status_code == 200
        assert _login(api_client, victim, SQUAT_PW).status_code == 401

    @override_settings(**LOC_MEM)
    def test_owner_typing_a_squatters_code_does_not_verify_the_squatter(self, api_client):
        """The squatter registers; the code lands in the OWNER's inbox. If the
        owner enters it (via resend, or by mistaking it for their own), the
        squatter's password must not become a working login."""
        mail.outbox = []
        victim = 'victim2@example.com'
        _register(api_client, victim, 'squatter', SQUAT_PW)
        api_client.post(RESEND, {'email': victim}, format='json')
        r = _verify(api_client, victim, _last_code(), OWNER_PW)
        assert r.status_code == 400
        assert User.objects.get(email=victim).email_verified is False
        assert _login(api_client, victim, SQUAT_PW).status_code == 403

    @override_settings(**LOC_MEM)
    def test_wrong_password_guesses_lock_the_code(self, api_client):
        mail.outbox = []
        _reg(api_client)
        code = _last_code()
        for _ in range(PasswordResetOTP.MAX_FAILED_ATTEMPTS):
            _verify(api_client, 'new@example.com', code, 'not-the-password')
        assert _verify(api_client, 'new@example.com', code).status_code == 429

    @override_settings(**LOC_MEM)
    def test_account_that_has_logged_in_is_not_overwritten(self, api_client):
        """A legacy unverified customer who has used the shop keeps their
        password when a stranger submits the register form with their email."""
        legacy = User.objects.create_user(username='legacy', email='legacy@example.com',
                                          password=OWNER_PW)
        legacy.last_login = timezone.now()
        legacy.save()
        mail.outbox = []
        assert _register(api_client, 'legacy@example.com', 'stranger', SQUAT_PW).status_code == 201
        legacy.refresh_from_db()
        assert legacy.username == 'legacy'
        assert legacy.check_password(OWNER_PW)
        assert not any(re.search(r'\b\d{6}\b', m.body) for m in mail.outbox)

    @override_settings(**LOC_MEM)
    def test_unverified_staff_row_is_not_overwritten(self, api_client):
        staff = User.objects.create_user(username='staffer', email='staffer@example.com',
                                         password=OWNER_PW, is_staff=True)
        _register(api_client, 'staffer@example.com', 'stranger', SQUAT_PW)
        staff.refresh_from_db()
        assert staff.check_password(OWNER_PW)


@pytest.mark.django_db
class TestCodeQuotasAreSeparate:
    @override_settings(**LOC_MEM)
    def test_reset_requests_do_not_block_or_cancel_verification(self, api_client):
        """A stranger hammering "forgot password" for an address must not stop
        its owner verifying."""
        mail.outbox = []
        _reg(api_client)
        code = _last_code()
        user = User.objects.get(email='new@example.com')
        # Model rows rather than HTTP: the reset endpoint mails from a thread.
        for _ in range(PasswordResetOTP.MAX_CODES_PER_DAY):
            rec = PasswordResetOTP(user=user, purpose=PasswordResetOTP.PURPOSE_RESET,
                                   expires_at=timezone.now() + timedelta(minutes=10))
            rec.set_otp('000000')
            rec.save()
        api_client.post('/api/auth/password-reset-request/', {'email': 'new@example.com'},
                        format='json')
        # The registration code is still live...
        assert _verify(api_client, 'new@example.com', code).status_code == 200
        # ...and a fresh one can still be requested.
        user.email_verified = False
        user.save(update_fields=['email_verified'])
        before = len(mail.outbox)
        api_client.post(RESEND, {'email': 'new@example.com'}, format='json')
        assert len(mail.outbox) == before + 1

    @override_settings(**LOC_MEM)
    def test_verification_codes_are_capped_per_account(self, api_client):
        mail.outbox = []
        _reg(api_client)
        for _ in range(10):
            api_client.post(RESEND, {'email': 'new@example.com'}, format='json')
        assert len(mail.outbox) == PasswordResetOTP.MAX_CODES_PER_DAY

    def test_a_verification_code_cannot_reset_a_password(self, api_client):
        user = User.objects.create_user(username='x', email='x@example.com', password=OWNER_PW)
        rec = PasswordResetOTP(user=user, purpose=PasswordResetOTP.PURPOSE_VERIFY,
                               expires_at=timezone.now() + timedelta(minutes=10))
        rec.set_otp('123456')
        rec.save()
        r = api_client.post('/api/auth/password-reset-verify/',
                            {'email': 'x@example.com', 'otp_code': '123456'}, format='json')
        assert r.status_code == 400


@pytest.mark.django_db
class TestStaffAccounts:
    def test_createsuperuser_account_can_use_the_admin_panel(self, api_client):
        User.objects.create_superuser(username='owner', email='owner@example.com',
                                      password=OWNER_PW)
        r = api_client.post('/api/auth/admin/login/',
                            {'email': 'owner@example.com', 'password': OWNER_PW}, format='json')
        assert r.status_code == 200

    @override_settings(**LOC_MEM)
    def test_unverified_staff_can_verify_then_log_in(self, api_client):
        mail.outbox = []
        User.objects.create_user(username='clerk', email='clerk@example.com',
                                 password=OWNER_PW, is_staff=True)
        creds = {'email': 'clerk@example.com', 'password': OWNER_PW}
        assert api_client.post('/api/auth/admin/login/', creds, format='json').status_code == 403
        api_client.post(RESEND, {'email': 'clerk@example.com'}, format='json')
        assert _verify(api_client, 'clerk@example.com', _last_code(), OWNER_PW).status_code == 200
        assert api_client.post('/api/auth/admin/login/', creds, format='json').status_code == 200
