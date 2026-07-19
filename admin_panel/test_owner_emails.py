"""Tests for the store-owner emails (new-order alert, daily digest, weekly
summary). The real send is a background thread, so we monkeypatch the shared
`_send_async` helper to capture (subject, body, recipient) synchronously and
assert on the composed content."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from orders.models import Order, OrderItem


@pytest.fixture
def capture_email(monkeypatch):
    """Capture every _send_async(...) call across the order-email module."""
    sent = []

    def fake_send(subject, message, recipient):
        sent.append({'subject': subject, 'message': message, 'recipient': recipient})

    monkeypatch.setattr('orders.emails._send_async', fake_send)
    return sent


@pytest.fixture
def owner_email(settings):
    """Configure the store-owner alert address (pytest-django settings fixture
    restores it automatically after the test)."""
    settings.ADMIN_ALERT_EMAIL = 'owner@shop.test'
    return settings.ADMIN_ALERT_EMAIL


def _order(user, product, **kw):
    order = Order.objects.create(
        user=user, shipping_address='1 Test Rd, City', phone_number='9990001112',
        payment_method=kw.get('payment_method', 'COD'),
        subtotal=Decimal('240'), tax=Decimal('24'), total_amount=Decimal('264'),
        status=kw.get('status', 'pending'),
    )
    OrderItem.objects.create(
        order=order, product=product, item_type='product',
        product_name=product.name, product_weight=str(product.weight),
        quantity=2, price=product.final_price, final_price=product.final_price * 2,
    )
    return order


@pytest.mark.django_db
class TestNewOrderAlert:
    def test_alert_composed_for_owner(self, capture_email, owner_email, test_user, test_product):
        from orders.emails import send_new_order_admin_alert
        order = _order(test_user, test_product)
        send_new_order_admin_alert(order)
        assert len(capture_email) == 1
        mail = capture_email[0]
        assert mail['recipient'] == 'owner@shop.test'
        assert f'ORD-{order.id:06d}' in mail['message']
        assert 'Cash on Delivery' in mail['message']

    def test_no_alert_without_configured_email(self, capture_email, settings,
                                               test_user, test_product):
        from orders.emails import send_new_order_admin_alert
        settings.ADMIN_ALERT_EMAIL = ''
        send_new_order_admin_alert(_order(test_user, test_product))
        assert capture_email == []


@pytest.mark.django_db
class TestDailyDigest:
    def test_digest_lists_low_stock_and_waiting_orders(
            self, capture_email, owner_email, test_user, test_product):
        _order(test_user, test_product, status='pending')  # waiting to confirm
        test_product.stock = 2  # below default threshold 5
        test_product.save(update_fields=['stock'])

        call_command('send_daily_digest')

        assert len(capture_email) == 1
        body = capture_email[0]['message']
        assert 'waiting to be confirmed' in body
        assert test_product.name in body  # low-stock line

    def test_skipped_when_email_unset(self, capture_email, settings):
        settings.ADMIN_ALERT_EMAIL = ''
        call_command('send_daily_digest')
        assert capture_email == []


@pytest.mark.django_db
class TestWeeklySummary:
    def test_summary_reports_sales_and_best_sellers(
            self, capture_email, owner_email, test_user, test_product):
        from analytics.models import DailySalesRollup

        yesterday = timezone.now().date() - timedelta(days=1)
        DailySalesRollup.objects.create(
            date=yesterday, orders=3, units=6, revenue=Decimal('900'))
        # An order in the window feeds the best-seller list.
        o = _order(test_user, test_product, status='delivered')
        Order.objects.filter(pk=o.pk).update(
            created_at=timezone.now() - timedelta(days=1))

        call_command('send_weekly_summary')

        assert len(capture_email) == 1
        body = capture_email[0]['message']
        assert 'Rs. 900' in body
        assert test_product.name in body  # best seller

    def test_skipped_when_email_unset(self, capture_email, settings):
        settings.ADMIN_ALERT_EMAIL = ''
        call_command('send_weekly_summary')
        assert capture_email == []


@pytest.mark.django_db
class TestSendReportEndpoint:
    def test_staff_can_trigger_weekly(self, admin_client, capture_email, owner_email):
        resp = admin_client.post('/api/dashboard/send-report/', {'type': 'weekly'}, format='json')
        assert resp.status_code == 200
        assert resp.data['sent'] is True
        assert len(capture_email) == 1

    def test_invalid_type_rejected(self, admin_client):
        resp = admin_client.post('/api/dashboard/send-report/', {'type': 'monthly'}, format='json')
        assert resp.status_code == 400

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.post('/api/dashboard/send-report/', {'type': 'weekly'}, format='json')
        assert resp.status_code == 403
