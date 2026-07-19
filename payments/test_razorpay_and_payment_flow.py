"""
Tests for the Razorpay integration and order-payment flow:
create-order, verify, webhooks, status endpoint, zero-total orders, cancellation rules,
and reconciliation.
"""
from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from rest_framework import status

from admin_panel.models import Coupon
from orders.models import Order
from payments.models import Payment, PaymentEvent, ProcessedWebhookEvent
from payments import services


# --- From test_razorpay.py ---

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


# --- From test_order_payment_flow.py ---

def _add_to_cart(client, product):
    return client.post('/api/cart/add_item/',
                       {'product_id': product.id, 'quantity': 1}, format='json')


@pytest.mark.django_db
class TestZeroTotalOrder:
    def test_full_coupon_places_paid_order_no_payment_row(
            self, authenticated_client, test_user, test_product):
        _add_to_cart(authenticated_client, test_product)
        Coupon.objects.create(code='FREE100', discount_type='percent',
                              discount_percent=100, is_active=True)
        resp = authenticated_client.post('/api/orders/', {
            'shipping_address': '1 St', 'phone_number': '9999999999',
            'payment_method': 'ONLINE', 'coupon_code': 'FREE100',
        }, format='json')
        assert resp.status_code == 201, resp.data
        order = Order.objects.get(pk=resp.data['order_id'])
        assert order.total_amount == Decimal('0.00')
        assert order.shipping_charge == Decimal('0.00')
        assert order.tax == Decimal('0.00')
        assert order.payment_status == 'paid'
        assert order.status == 'confirmed'
        # No gateway Payment row for a zero-total order.
        assert not Payment.objects.filter(order=order).exists()

    def test_fixed_coupon_covering_subtotal_is_zero_total(
            self, authenticated_client, test_user, test_product):
        _add_to_cart(authenticated_client, test_product)
        # test_product final price is 120; a ₹500 fixed coupon covers it fully.
        Coupon.objects.create(code='BIG500', discount_type='fixed',
                              discount_amount=Decimal('500.00'), is_active=True)
        resp = authenticated_client.post('/api/orders/', {
            'shipping_address': '1 St', 'phone_number': '9999999999',
            'payment_method': 'ONLINE', 'coupon_code': 'BIG500',
        }, format='json')
        assert resp.status_code == 201, resp.data
        order = Order.objects.get(pk=resp.data['order_id'])
        assert order.total_amount == Decimal('0.00')
        assert order.payment_status == 'paid'


@pytest.mark.django_db
class TestAssignedCoupon:
    def test_assigned_coupon_blocks_other_user(
            self, authenticated_client_user2, test_user, test_product):
        # Coupon bound to test_user; user2 tries it.
        Coupon.objects.create(code='MINE', discount_type='percent',
                              discount_percent=10, is_active=True, assigned_user=test_user)
        authenticated_client_user2.post('/api/cart/add_item/',
                                        {'product_id': test_product.id, 'quantity': 1},
                                        format='json')
        resp = authenticated_client_user2.post('/api/orders/validate_coupon/',
                                               {'coupon_code': 'MINE'}, format='json')
        assert resp.status_code == 400
        assert 'not available for your account' in str(resp.data)


@pytest.mark.django_db
class TestCancelPaidOrder:
    def _paid_order_with_payment(self, user):
        order = Order.objects.create(
            user=user, shipping_address='1 St', phone_number='9999999999',
            payment_method='ONLINE', payment_status='paid', status='confirmed',
            subtotal=Decimal('200'), total_amount=Decimal('236'))
        Payment.objects.create(order=order, payment_id='order_PAID',
                               payment_gateway='razorpay', amount=order.total_amount,
                               status='completed')
        return order

    def test_customer_cannot_self_cancel_paid_order(self, authenticated_client, test_user):
        order = self._paid_order_with_payment(test_user)
        resp = authenticated_client.post(f'/api/orders/{order.id}/cancel/')
        assert resp.status_code == 400
        assert 'contact support' in str(resp.data).lower()
        order.refresh_from_db()
        assert order.status == 'confirmed'  # not cancelled


@pytest.mark.django_db
class TestReconcileCommand:
    def _mock_client_with_capture(self, captured):
        client = MagicMock()
        items = [{'id': 'pay_R', 'status': 'captured', 'amount': 23600}] if captured else []
        client.order.payments.return_value = {'items': items}
        return client

    def test_recovers_missed_capture(self, test_user):
        from django.core.management import call_command
        order = Order.objects.create(
            user=test_user, shipping_address='1 St', phone_number='9999999999',
            payment_method='ONLINE', payment_status='pending', status='pending',
            subtotal=Decimal('200'), total_amount=Decimal('236'))
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=2))
        Payment.objects.create(order=order, payment_id='order_MISS',
                               payment_gateway='razorpay', amount=order.total_amount,
                               status='pending')
        with patch('payments.management.commands.reconcile_payments.get_razorpay_client',
                   return_value=self._mock_client_with_capture(True)):
            call_command('reconcile_payments')
        order.refresh_from_db()
        assert order.payment_status == 'paid'
        assert PaymentEvent.objects.filter(event_type='recovered_paid').exists()

    def test_cancels_abandoned_order_and_restores_stock(self, test_user, test_product):
        from django.core.management import call_command
        start_stock = test_product.stock
        order = Order.objects.create(
            user=test_user, shipping_address='1 St', phone_number='9999999999',
            payment_method='ONLINE', payment_status='pending', status='pending',
            subtotal=Decimal('120'), total_amount=Decimal('126'))
        from orders.models import OrderItem
        OrderItem.objects.create(order=order, product=test_product, item_type='product',
                                 product_name=test_product.name, product_weight='250g',
                                 quantity=3, price=Decimal('120'),
                                 discounted_price=Decimal('120'), final_price=Decimal('360'))
        test_product.stock = start_stock - 3
        test_product.save(update_fields=['stock'])
        Order.objects.filter(pk=order.pk).update(
            created_at=timezone.now() - timedelta(hours=2))
        Payment.objects.create(order=order, payment_id='order_ABND',
                               payment_gateway='razorpay', amount=order.total_amount,
                               status='pending')
        with patch('payments.management.commands.reconcile_payments.get_razorpay_client',
                   return_value=self._mock_client_with_capture(False)):
            call_command('reconcile_payments')
        order.refresh_from_db(); test_product.refresh_from_db()
        assert order.status == 'cancelled'
        assert test_product.stock == start_stock  # restored
        assert PaymentEvent.objects.filter(event_type='auto_cancelled').exists()
