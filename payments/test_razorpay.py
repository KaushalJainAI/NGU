"""Tests for the Razorpay integration: endpoints, the idempotent capture core,
the resilience guarantees, and the zero-total / cancel interactions.

Razorpay's SDK is mocked throughout — no network, no real keys needed. The
signature checks are patched to accept/reject deterministically so we exercise
OUR logic (idempotency, lock ordering, out-of-order safety), not razorpay's HMAC.
"""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status

from orders.models import Order
from payments.models import Payment, PaymentEvent, ProcessedWebhookEvent
from payments import services


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _make_order(user, total='236.00', payment_status='pending', order_status='pending'):
    return Order.objects.create(
        user=user,
        shipping_address='1 Test St, Test City',
        phone_number='9999999999',
        payment_method='ONLINE',
        payment_status=payment_status,
        status=order_status,
        subtotal=Decimal('200.00'),
        tax=Decimal('10.00'),
        shipping_charge=Decimal('26.00'),
        total_amount=Decimal(total),
    )


@pytest.fixture
def order(test_user):
    return _make_order(test_user)


@pytest.fixture
def pending_payment(order):
    return Payment.objects.create(
        order=order, payment_id='order_RZP123', payment_gateway='razorpay',
        amount=order.total_amount, status='pending',
    )


def _mock_client(valid_signature=True):
    client = MagicMock()
    if valid_signature:
        client.utility.verify_payment_signature.return_value = True
        client.utility.verify_webhook_signature.return_value = True
    else:
        client.utility.verify_payment_signature.side_effect = Exception("bad sig")
        client.utility.verify_webhook_signature.side_effect = Exception("bad sig")
    client.order.create.return_value = {'id': 'order_RZPNEW', 'amount': 23600}
    return client


# --------------------------------------------------------------------------- #
# create-order
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestCreateOrder:
    url = '/api/payments/create-order/'

    def test_amount_is_server_side(self, authenticated_client, order):
        """Client cannot influence the amount — it comes from Order.total_amount."""
        with patch('payments.views.get_razorpay_client', return_value=_mock_client()):
            resp = authenticated_client.post(
                self.url, {'order_id': order.id, 'amount': 1}, format='json')
        assert resp.status_code == 200
        assert resp.data['amount'] == 23600  # 236.00 * 100, not the injected 1
        assert resp.data['currency'] == 'INR'
        assert resp.data['razorpay_order_id'] == 'order_RZPNEW'

    def test_creates_payment_row(self, authenticated_client, order):
        with patch('payments.views.get_razorpay_client', return_value=_mock_client()):
            authenticated_client.post(self.url, {'order_id': order.id}, format='json')
        payment = Payment.objects.get(order=order)
        assert payment.payment_gateway == 'razorpay'
        assert payment.payment_id == 'order_RZPNEW'
        assert payment.status == 'pending'
        assert PaymentEvent.objects.filter(payment=payment, event_type='order_created').exists()

    def test_idempotent_returns_existing(self, authenticated_client, order, pending_payment):
        """A second create-order for the same Order returns the existing Razorpay
        order — never mints a second live one (§7.7)."""
        client = _mock_client()
        with patch('payments.views.get_razorpay_client', return_value=client):
            resp = authenticated_client.post(self.url, {'order_id': order.id}, format='json')
        assert resp.status_code == 200
        assert resp.data['razorpay_order_id'] == 'order_RZP123'
        client.order.create.assert_not_called()

    def test_amount_drift_supersedes_not_reuse(self, authenticated_client, order, pending_payment):
        """If the order total changed since the pending Razorpay order was minted,
        create-order must mint a fresh one (not reuse the stale-amount one)."""
        Order.objects.filter(pk=order.pk).update(total_amount=Decimal('300.00'))
        client = _mock_client()
        with patch('payments.views.get_razorpay_client', return_value=client):
            resp = authenticated_client.post(self.url, {'order_id': order.id}, format='json')
        assert resp.status_code == 200
        assert resp.data['razorpay_order_id'] == 'order_RZPNEW'  # not the stale order_RZP123
        client.order.create.assert_called_once()
        pending_payment.refresh_from_db()
        assert pending_payment.payment_id == 'order_RZPNEW'
        assert 'order_RZP123' in pending_payment.transaction_details['superseded_order_ids']

    def test_rejects_other_users_order(self, authenticated_client_user2, order):
        with patch('payments.views.get_razorpay_client', return_value=_mock_client()):
            resp = authenticated_client_user2.post(self.url, {'order_id': order.id}, format='json')
        assert resp.status_code == 404

    def test_rejects_paid_order(self, authenticated_client, test_user):
        paid = _make_order(test_user, payment_status='paid', order_status='confirmed')
        with patch('payments.views.get_razorpay_client', return_value=_mock_client()):
            resp = authenticated_client.post(self.url, {'order_id': paid.id}, format='json')
        assert resp.status_code == 400

    def test_requires_auth(self, api_client, order):
        resp = api_client.post(self.url, {'order_id': order.id}, format='json')
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# --------------------------------------------------------------------------- #
# verify (L1)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestVerify:
    url = '/api/payments/verify/'

    def _payload(self):
        return {'razorpay_order_id': 'order_RZP123',
                'razorpay_payment_id': 'pay_ABC', 'razorpay_signature': 'sig'}

    def test_valid_signature_marks_paid(self, authenticated_client, order, pending_payment):
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = authenticated_client.post(self.url, self._payload(), format='json')
        assert resp.status_code == 200 and resp.data['success'] is True
        order.refresh_from_db(); pending_payment.refresh_from_db()
        assert order.payment_status == 'paid' and order.status == 'confirmed'
        assert pending_payment.status == 'completed'
        assert pending_payment.razorpay_payment_id == 'pay_ABC'

    def test_invalid_signature_rejected(self, authenticated_client, order, pending_payment):
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(False)):
            resp = authenticated_client.post(self.url, self._payload(), format='json')
        assert resp.status_code == 400
        pending_payment.refresh_from_db()
        assert pending_payment.status == 'pending'
        assert PaymentEvent.objects.filter(event_type='verify_signature_failed',
                                           is_exception=True).exists()

    def test_rejects_other_users_payment(self, authenticated_client_user2, order, pending_payment):
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = authenticated_client_user2.post(self.url, self._payload(), format='json')
        assert resp.status_code == 404

    def test_capture_after_cancel_returns_honest_not_success(
            self, authenticated_client, test_user):
        """If the order was cancelled before verify lands, don't tell the browser
        'success' — the money is routed to refund, the order stays cancelled."""
        cancelled = _make_order(test_user, order_status='cancelled')
        Payment.objects.create(order=cancelled, payment_id='order_RZP123',
                               payment_gateway='razorpay', amount=cancelled.total_amount,
                               status='pending')
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = authenticated_client.post(self.url, self._payload(), format='json')
        assert resp.status_code == 200
        assert resp.data['success'] is False
        assert resp.data['status'] == 'cancelled'
        cancelled.refresh_from_db()
        assert cancelled.status == 'cancelled'


# --------------------------------------------------------------------------- #
# Idempotent capture core + resilience
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestCaptureCore:
    def test_double_capture_is_noop(self, order, pending_payment):
        services.mark_payment_captured('order_RZP123', 'pay_ABC', event_id='ev1', source='webhook')
        services.mark_payment_captured('order_RZP123', 'pay_ABC', event_id='ev1', source='webhook')
        order.refresh_from_db()
        assert order.payment_status == 'paid'
        # Exactly one 'captured' event despite two calls.
        assert PaymentEvent.objects.filter(payment=pending_payment, event_type='captured').count() == 1

    def test_l1_l2_race_single_confirmation(self, order, pending_payment):
        """verify (client) then webhook → paid once, second is duplicate_ignored."""
        services.mark_payment_captured('order_RZP123', 'pay_ABC', source='client')
        services.mark_payment_captured('order_RZP123', 'pay_ABC', event_id='ev2', source='webhook')
        assert PaymentEvent.objects.filter(payment=pending_payment, event_type='captured').count() == 1
        assert PaymentEvent.objects.filter(event_type='duplicate_ignored').count() == 1

    def test_failed_after_captured_does_not_unpay(self, order, pending_payment):
        services.mark_payment_captured('order_RZP123', 'pay_ABC', source='webhook')
        services.mark_payment_failed('order_RZP123', event_id='evf', source='webhook',
                                     error_description='late failure')
        order.refresh_from_db(); pending_payment.refresh_from_db()
        assert order.payment_status == 'paid'
        assert pending_payment.status == 'completed'
        assert PaymentEvent.objects.filter(event_type='out_of_order_ignored').exists()

    def test_amount_mismatch_flagged_not_fulfilled(self, order, pending_payment):
        # Webhook claims 999 paise; expected 23600 → mismatch, do not confirm.
        services.mark_payment_captured('order_RZP123', 'pay_ABC', event_id='evm',
                                       source='webhook', amount=999)
        order.refresh_from_db(); pending_payment.refresh_from_db()
        assert order.payment_status == 'pending'
        assert pending_payment.status == 'pending'
        assert PaymentEvent.objects.filter(event_type='amount_mismatch', is_exception=True).exists()

    def test_capture_after_cancel_records_but_keeps_cancelled(self, test_user):
        cancelled = _make_order(test_user, order_status='cancelled')
        pay = Payment.objects.create(order=cancelled, payment_id='order_CANC',
                                     payment_gateway='razorpay', amount=cancelled.total_amount,
                                     status='pending')
        services.mark_payment_captured('order_CANC', 'pay_X', event_id='evc', source='webhook')
        cancelled.refresh_from_db(); pay.refresh_from_db()
        assert cancelled.status == 'cancelled'           # never resurrected
        assert pay.status == 'completed'                 # money recorded truthfully
        assert PaymentEvent.objects.filter(event_type='captured_after_cancel',
                                           is_exception=True).exists()

    def test_processed_event_ledger_dedup(self, order, pending_payment):
        services._record_processed_event('dup', 'payment.captured')
        services._record_processed_event('dup', 'payment.captured')  # no IntegrityError bubbles
        assert ProcessedWebhookEvent.objects.filter(event_id='dup').count() == 1

    def test_refund_resolved_by_payment_id_when_order_id_missing(self, order, pending_payment):
        """Refund entities don't reliably carry the Razorpay order id; resolving by
        the captured payment id must still find and refund the local Payment."""
        services.mark_payment_captured('order_RZP123', 'pay_ABC', source='webhook')
        services.mark_payment_refunded(razorpay_order_id=None,
                                       razorpay_payment_id='pay_ABC', source='webhook')
        order.refresh_from_db(); pending_payment.refresh_from_db()
        assert pending_payment.status == 'refunded'
        assert order.payment_status == 'refunded'
        assert PaymentEvent.objects.filter(event_type='refunded').exists()


# --------------------------------------------------------------------------- #
# webhook (L2)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestWebhook:
    url = '/api/payments/webhook/'

    def _captured_body(self, order_id='order_RZP123', amount=23600):
        return json.dumps({
            'event': 'payment.captured',
            'payload': {'payment': {'entity': {
                'id': 'pay_WH', 'order_id': order_id, 'amount': amount, 'status': 'captured'}}},
        })

    def test_valid_webhook_marks_paid(self, settings, api_client, order, pending_payment):
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = api_client.post(self.url, self._captured_body(),
                                   content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE='s', HTTP_X_RAZORPAY_EVENT_ID='wh1')
        assert resp.status_code == 200
        order.refresh_from_db()
        assert order.payment_status == 'paid'

    def test_bad_signature_rejected(self, settings, api_client, order, pending_payment):
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(False)):
            resp = api_client.post(self.url, self._captured_body(),
                                   content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE='bad', HTTP_X_RAZORPAY_EVENT_ID='wh2')
        assert resp.status_code == 400
        order.refresh_from_db()
        assert order.payment_status == 'pending'

    def test_duplicate_event_id_noop(self, settings, api_client, order, pending_payment):
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            for _ in range(2):
                api_client.post(self.url, self._captured_body(),
                                content_type='application/json',
                                HTTP_X_RAZORPAY_SIGNATURE='s', HTTP_X_RAZORPAY_EVENT_ID='whdup')
        assert PaymentEvent.objects.filter(payment=pending_payment, event_type='captured').count() == 1

    def test_missing_secret_rejected(self, settings, api_client, order, pending_payment):
        settings.RAZORPAY_WEBHOOK_SECRET = ''
        resp = api_client.post(self.url, self._captured_body(),
                               content_type='application/json',
                               HTTP_X_RAZORPAY_SIGNATURE='s')
        assert resp.status_code == 400

    def test_unknown_event_acked(self, settings, api_client):
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        body = json.dumps({'event': 'subscription.charged', 'payload': {}})
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = api_client.post(self.url, body, content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE='s', HTTP_X_RAZORPAY_EVENT_ID='whk')
        assert resp.status_code == 200

    def test_orphan_payment_flagged_but_acked(self, settings, api_client):
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = api_client.post(self.url, self._captured_body(order_id='order_UNKNOWN'),
                                   content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE='s', HTTP_X_RAZORPAY_EVENT_ID='who')
        assert resp.status_code == 200
        assert PaymentEvent.objects.filter(event_type='orphan_payment', is_exception=True).exists()

    def test_refund_webhook_without_order_id_still_refunds(
            self, settings, api_client, order, pending_payment):
        """A refund.processed payload carrying only payment_id (no order_id) must
        still mark the local Payment refunded, not fall through to an orphan."""
        settings.RAZORPAY_WEBHOOK_SECRET = 'whsec'
        services.mark_payment_captured('order_RZP123', 'pay_WH', source='webhook')
        body = json.dumps({
            'event': 'refund.processed',
            'payload': {'refund': {'entity': {'id': 'rfnd_1', 'payment_id': 'pay_WH'}}},
        })
        with patch('payments.views.get_razorpay_client', return_value=_mock_client(True)):
            resp = api_client.post(self.url, body, content_type='application/json',
                                   HTTP_X_RAZORPAY_SIGNATURE='s', HTTP_X_RAZORPAY_EVENT_ID='whr')
        assert resp.status_code == 200
        order.refresh_from_db(); pending_payment.refresh_from_db()
        assert pending_payment.status == 'refunded'
        assert order.payment_status == 'refunded'
        assert not PaymentEvent.objects.filter(event_type='orphan_payment').exists()


# --------------------------------------------------------------------------- #
# status endpoint
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestStatus:
    def test_processing_label_not_failure(self, authenticated_client, test_user):
        o = _make_order(test_user, payment_status='processing')
        resp = authenticated_client.get(f'/api/payments/status/?order_id={o.id}')
        assert resp.status_code == 200
        assert resp.data['label'] == 'Confirming your payment…'

    def test_paid_label(self, authenticated_client, order, pending_payment):
        services.mark_payment_captured('order_RZP123', 'pay_ABC', source='client')
        resp = authenticated_client.get(f'/api/payments/status/?order_id={order.id}')
        assert resp.data['payment_status'] == 'paid'
        assert resp.data['razorpay_payment_id'] == 'pay_ABC'
