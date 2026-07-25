"""Coverage for /api/payment-account/ (PaymentAccountView).

Flagged 🔴 / untested in docs/API.md: it hands the payee UPI ID to every logged-in
user, so the field allowlist is the security property. The bank account number,
IFSC and contact details on the same model must never appear in the response.
"""
import pytest

from admin_panel.models import ReceivableAccount

URL = '/api/payment-account/'

# Fields on ReceivableAccount that must never reach a customer.
SENSITIVE_FIELDS = [
    'bank_account_number', 'ifsc_code', 'bank_name',
    'branch_name', 'contact_email', 'contact_phone',
]


@pytest.fixture
def default_account(db):
    return ReceivableAccount.objects.create(
        account_holder_name='Nidhi Masala',
        upi_id='nidhi@upi',
        bank_name='Test Bank',
        bank_account_number='1234567890123456',
        ifsc_code='TEST0001234',
        branch_name='Test Branch',
        contact_email='owner@example.com',
        contact_phone='9876543210',
        is_active=True,
        is_default=True,
    )


@pytest.mark.django_db
class TestPaymentAccountAccess:
    def test_anonymous_denied(self, api_client, default_account):
        assert api_client.get(URL).status_code in (401, 403)

    def test_authenticated_user_allowed(self, authenticated_client, default_account):
        assert authenticated_client.get(URL).status_code == 200


@pytest.mark.django_db
class TestPaymentAccountPayload:
    def test_returns_only_safe_fields(self, authenticated_client, default_account):
        body = authenticated_client.get(URL).json()
        assert set(body.keys()) == {'id', 'account_name', 'upi_id'}
        assert body['upi_id'] == 'nidhi@upi'
        assert body['account_name'] == 'Nidhi Masala'

    def test_bank_details_never_exposed(self, authenticated_client, default_account):
        """The whole point of this endpoint being a hand-built dict."""
        raw = authenticated_client.get(URL).content.decode()
        for field in SENSITIVE_FIELDS:
            assert getattr(default_account, field) not in raw, (
                f'{field} leaked into the payment-account response'
            )


@pytest.mark.django_db
class TestPaymentAccountSelection:
    def test_prefers_the_default_account(self, authenticated_client, default_account):
        ReceivableAccount.objects.create(
            account_holder_name='Other', upi_id='other@upi',
            is_active=True, is_default=False,
        )
        assert authenticated_client.get(URL).json()['upi_id'] == 'nidhi@upi'

    def test_falls_back_to_any_active_account(self, authenticated_client, db):
        ReceivableAccount.objects.create(
            account_holder_name='Fallback', upi_id='fallback@upi',
            is_active=True, is_default=False,
        )
        assert authenticated_client.get(URL).json()['upi_id'] == 'fallback@upi'

    def test_inactive_accounts_ignored(self, authenticated_client, db):
        ReceivableAccount.objects.create(
            account_holder_name='Retired', upi_id='retired@upi',
            is_active=False, is_default=True,
        )
        assert authenticated_client.get(URL).status_code == 503

    def test_no_account_configured_returns_503(self, authenticated_client, db):
        r = authenticated_client.get(URL)
        assert r.status_code == 503
        assert 'error' in r.json()
