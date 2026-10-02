"""Low-stock reporting is per SIZE, against the product's alert level.

It used to read `Product.stock`, which only mirrors the DEFAULT size — so a
500 g pack down to 1 unit with a healthy default size was never reported.
"""
from decimal import Decimal

import pytest
from django.core.management import call_command

from products.models import Product, ProductVariant, default_variant_for


def _size(product, weight, stock, *, active=True):
    return ProductVariant.objects.create(
        product=product, weight=Decimal(weight), unit='g', price=Decimal('300.00'),
        stock=stock, is_active=active)


@pytest.fixture
def capture_email(monkeypatch):
    sent = []
    monkeypatch.setattr('orders.emails._send_async', lambda subject, message, recipient: sent.append(
        {'subject': subject, 'message': message, 'recipient': recipient}))
    return sent


@pytest.fixture
def owner_email(settings):
    settings.ADMIN_ALERT_EMAIL = 'owner@shop.test'
    return settings.ADMIN_ALERT_EMAIL


@pytest.fixture
def healthy_default_low_500g(test_product):
    """Default size at 100 (healthy), 500 g at 1 (low)."""
    return _size(test_product, '500', 1)


@pytest.mark.django_db
class TestDashboard:
    def test_a_non_default_size_running_low_is_counted_and_named_with_its_size(
            self, admin_client, test_product, healthy_default_low_500g):
        data = admin_client.get('/api/dashboard/actions/').data
        assert data['low_stock_count'] == 1
        item = data['low_stock_items'][0]
        assert item['id'] == test_product.id
        assert item['variant_id'] == healthy_default_low_500g.id
        assert item['name'] == 'Test Turmeric Powder'
        assert item['size'] == '500g'
        assert item['stock'] == 1

    def test_the_count_is_products_not_sizes(self, admin_client, test_product):
        _size(test_product, '500', 1)
        _size(test_product, '1000', 2)
        data = admin_client.get('/api/dashboard/actions/').data
        assert data['low_stock_count'] == 1            # one product…
        assert len(data['low_stock_items']) == 2       # …two sizes named

    def test_the_products_alert_level_applies_to_every_size(self, admin_client, test_product):
        Product.objects.filter(pk=test_product.pk).update(low_stock_threshold=20)
        _size(test_product, '500', 15)
        assert admin_client.get('/api/dashboard/actions/').data['low_stock_count'] == 1

    def test_a_retired_size_at_zero_is_not_counted(self, admin_client, test_product):
        _size(test_product, '500', 0, active=False)
        assert admin_client.get('/api/dashboard/actions/').data['low_stock_count'] == 0

    def test_a_switched_off_product_is_not_counted(self, admin_client, test_product,
                                                   healthy_default_low_500g):
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        assert admin_client.get('/api/dashboard/actions/').data['low_stock_count'] == 0

    def test_out_of_stock_counts_products_with_a_sold_out_size(
            self, admin_client, test_product, test_product2):
        _size(test_product, '500', 0)
        _size(test_product, '1000', 0)       # same product twice → still one
        data = admin_client.get('/api/dashboard/actions/').data
        assert data['out_of_stock_count'] == 1


@pytest.mark.django_db
class TestEmails:
    def test_daily_digest_names_the_size(self, capture_email, owner_email, test_product,
                                         healthy_default_low_500g):
        call_command('send_daily_digest')
        body = capture_email[0]['message']
        assert 'Test Turmeric Powder (500g) — 1 left' in body
        # the healthy default size is not listed
        assert 'Test Turmeric Powder (250g)' not in body

    def test_weekly_summary_names_the_size(self, capture_email, owner_email, test_product,
                                           healthy_default_low_500g):
        call_command('send_weekly_summary')
        assert 'Test Turmeric Powder (500g) (1 left)' in capture_email[0]['message']


@pytest.mark.django_db
class TestAdminAssistantTool:
    def test_low_stock_rows_carry_the_size(self, test_admin, test_product,
                                           healthy_default_low_500g):
        from assistant.admin_tools import admin_low_stock
        out = admin_low_stock(test_admin, {})
        assert out['count'] == 1
        assert out['products'] == [{'name': 'Test Turmeric Powder', 'size': '500g',
                                    'stock': 1, 'threshold': 5}]

    def test_nothing_low_nothing_reported(self, test_admin, test_product):
        from assistant.admin_tools import admin_low_stock
        assert admin_low_stock(test_admin, {}) == {'products': [], 'count': 0}
