"""Tests for the order-flow changes payments introduced: zero-total (full-coupon)
orders, blocked self-cancel of paid orders, and the L3 reconcile command."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from admin_panel.models import Coupon
from orders.models import Order
from payments.models import Payment, PaymentEvent


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
