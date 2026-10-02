"""Checkout refuses a RETIRED SIZE that is still sitting in a cart, and alerts on
low stock against the product's own alert level."""
from decimal import Decimal
from unittest.mock import patch

import pytest

from cart.models import Cart, CartItem
from orders.models import Order
from products.models import Product, ProductVariant, default_variant_for

URL = '/api/orders/'
ADDR = {'shipping_address': '1 Test Rd', 'phone_number': '1234567890', 'payment_method': 'COD'}


def _size(product, weight, stock, price='300.00'):
    return ProductVariant.objects.create(
        product=product, weight=Decimal(weight), unit='g', price=Decimal(price), stock=stock)


def _put(user, product, variant, quantity=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    return CartItem.objects.create(cart=cart, product=product, variant=variant,
                                   item_type='product', quantity=quantity)


@pytest.mark.django_db
class TestRetiredSizeCannotBeOrdered:
    def test_the_order_is_refused_and_nothing_changes(
            self, authenticated_client, test_user, test_product):
        size = _size(test_product, '500', 10)
        _put(test_user, test_product, size, quantity=2)
        ProductVariant.objects.filter(pk=size.pk).update(is_active=False)

        resp = authenticated_client.post(URL, ADDR, format='json')

        assert resp.status_code == 400
        assert 'no longer available' in resp.data['error']
        assert '500' in resp.data['error']            # names the size
        assert not Order.objects.filter(user=test_user).exists()
        assert ProductVariant.objects.get(pk=size.pk).stock == 10
        assert CartItem.objects.filter(cart__user=test_user).count() == 1  # cart kept

    def test_the_same_cart_with_the_size_active_is_accepted(
            self, authenticated_client, test_user, test_product):
        size = _size(test_product, '500', 10)
        _put(test_user, test_product, size, quantity=2)
        resp = authenticated_client.post(URL, ADDR, format='json')
        assert resp.status_code == 201
        assert ProductVariant.objects.get(pk=size.pk).stock == 8

    def test_a_size_retired_after_the_cart_check_is_caught_under_the_lock(
            self, authenticated_client, test_user, test_product):
        """Retired between the first check and the row lock: the locked loop must
        refuse it and roll the whole order back."""
        size = _size(test_product, '500', 10)
        _put(test_user, test_product, size, quantity=2)
        ProductVariant.objects.filter(pk=size.pk).update(is_active=False)

        with patch('orders.views.line_problem', return_value=None):   # skip check one
            resp = authenticated_client.post(URL, ADDR, format='json')

        assert resp.status_code == 400
        assert 'no longer available' in resp.data['error']
        assert not Order.objects.filter(user=test_user).exists()
        assert ProductVariant.objects.get(pk=size.pk).stock == 10

    def test_a_switched_off_product_is_still_refused(
            self, authenticated_client, test_user, test_product):
        _put(test_user, test_product, default_variant_for(test_product.pk))
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        resp = authenticated_client.post(URL, ADDR, format='json')
        assert resp.status_code == 400
        assert 'no longer available' in resp.data['error']

    def test_a_combo_with_a_retired_component_size_is_still_refused(
            self, authenticated_client, test_user, test_combo, test_product2):
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=test_combo, item_type='combo', quantity=1)
        ProductVariant.objects.filter(
            pk=default_variant_for(test_product2.pk).pk).update(is_active=False)
        resp = authenticated_client.post(URL, ADDR, format='json')
        assert resp.status_code == 400
        assert 'no longer available' in resp.data['error']


@pytest.mark.django_db
class TestLowStockAlertUsesTheProductsLevel:
    def test_a_non_default_size_crossing_the_products_level_alerts(
            self, authenticated_client, test_user, test_product,
            django_capture_on_commit_callbacks):
        # The product's alert level is 20; the size's own column stays at 5.
        Product.objects.filter(pk=test_product.pk).update(low_stock_threshold=20)
        size = _size(test_product, '500', 25)
        _put(test_user, test_product, size, quantity=10)     # 25 -> 15: crosses 20

        with patch('orders.views.send_low_stock_alert') as sent:
            with django_capture_on_commit_callbacks(execute=True):
                resp = authenticated_client.post(URL, ADDR, format='json')

        assert resp.status_code == 201
        sent.assert_called_once()
        row = sent.call_args[0][0][0]
        assert '500' in row['name'] and row['threshold'] == 20 and row['stock'] == 15

    def test_no_alert_while_the_size_stays_above_the_level(
            self, authenticated_client, test_user, test_product,
            django_capture_on_commit_callbacks):
        Product.objects.filter(pk=test_product.pk).update(low_stock_threshold=20)
        size = _size(test_product, '500', 50)
        _put(test_user, test_product, size, quantity=10)
        with patch('orders.views.send_low_stock_alert') as sent:
            with django_capture_on_commit_callbacks(execute=True):
                assert authenticated_client.post(URL, ADDR, format='json').status_code == 201
        sent.assert_not_called()
