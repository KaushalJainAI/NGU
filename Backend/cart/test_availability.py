"""The cart tells the truth about a line that cannot be bought.

A switched-off product, a retired size, a sold-out line or an unbuildable combo is
reported as such (`available`, `unavailable_reason`, `in_stock`), is left out of the
summary the Billing page quotes, and can still be removed. Combos are limited by
their components' stock, not a hard-coded 999.
"""
from decimal import Decimal

import pytest

from cart.models import Cart, CartItem
from products.models import (
    Product, ProductCombo, ProductVariant, default_variant_for,
)

CART = '/api/cart/'


def _size(product, weight, stock, price='300.00'):
    return ProductVariant.objects.create(
        product=product, weight=Decimal(weight), unit='g', price=Decimal(price), stock=stock)


def _put(user, *, product=None, variant=None, combo=None, quantity=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    if combo is not None:
        return CartItem.objects.create(cart=cart, combo=combo, item_type='combo', quantity=quantity)
    return CartItem.objects.create(cart=cart, product=product, variant=variant,
                                   item_type='product', quantity=quantity)


def _read(client):
    data = client.get(CART).data
    return data['items'], data['summary']


def _remove(client, line):
    if line.item_type == 'combo':
        body = {'product_id': line.combo_id, 'item_type': 'combo'}
    else:
        body = {'product_id': line.product_id, 'item_type': 'product',
                'variant_id': line.variant_id}
    return client.post(f'{CART}remove_item/', body, format='json')


def _break(case, test_user, test_product, test_product2, test_combo):
    """Put one line in the cart and break it in the named way. Returns (line, code)."""
    size = default_variant_for(test_product.pk)
    if case == 'product_off':
        line = _put(test_user, product=test_product, variant=size)
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        return line, 'product_off'
    if case == 'size_retired':
        extra = _size(test_product, '500', 10)
        line = _put(test_user, product=test_product, variant=extra)
        ProductVariant.objects.filter(pk=extra.pk).update(is_active=False)
        return line, 'size_retired'
    if case == 'combo_off':
        line = _put(test_user, combo=test_combo)
        ProductCombo.objects.filter(pk=test_combo.pk).update(is_active=False)
        return line, 'combo_off'
    if case == 'combo_unavailable':
        line = _put(test_user, combo=test_combo)
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 0
        size2.save(update_fields=['stock'])
        return line, 'combo_unavailable'
    if case == 'out_of_stock':
        line = _put(test_user, product=test_product, variant=size)
        size.stock = 0
        size.save(update_fields=['stock'])
        return line, 'out_of_stock'
    raise AssertionError(case)


CASES = ['product_off', 'size_retired', 'combo_off', 'combo_unavailable', 'out_of_stock']


@pytest.mark.django_db
class TestCartFlagsUnbuyableLines:
    @pytest.mark.parametrize('case', CASES)
    def test_the_line_is_flagged(self, case, authenticated_client, test_user, test_product,
                                 test_product2, test_combo):
        line, code = _break(case, test_user, test_product, test_product2, test_combo)
        items, summary = _read(authenticated_client)
        row = items[0]
        assert row['available'] is False
        assert row['unavailable_reason'] == code
        assert row['in_stock'] is False          # the storefront greys it out on this
        assert summary['unavailable_count'] == 1

    @pytest.mark.parametrize('case', CASES)
    def test_it_is_left_out_of_the_summary(self, case, authenticated_client, test_user,
                                           test_product, test_product2, test_combo):
        # A second, healthy line (a size of product2 nothing above touches).
        healthy_size = _size(test_product2, '100', 50, price='80.00')
        _put(test_user, product=test_product2, variant=healthy_size, quantity=2)
        _break(case, test_user, test_product, test_product2, test_combo)
        items, summary = _read(authenticated_client)
        assert len(items) == 2
        assert summary['subtotal'] == 160.0
        assert summary['unavailable_count'] == 1
        # delivery and GST are worked out from the 160 only
        assert summary['shipping'] == 59.0
        assert summary['total'] == round(160 + 59 + summary['shipping_tax'], 2)

    @pytest.mark.parametrize('case', CASES)
    def test_it_can_still_be_removed(self, case, authenticated_client, test_user, test_product,
                                     test_product2, test_combo):
        line, _ = _break(case, test_user, test_product, test_product2, test_combo)
        resp = _remove(authenticated_client, line)
        assert resp.status_code == 200
        assert not CartItem.objects.filter(pk=line.pk).exists()
        assert resp.data['summary']['unavailable_count'] == 0

    def test_a_healthy_cart_is_unchanged(self, authenticated_client, test_user, test_product):
        size = default_variant_for(test_product.pk)
        _put(test_user, product=test_product, variant=size, quantity=2)
        items, summary = _read(authenticated_client)
        assert items[0]['available'] is True
        assert items[0]['unavailable_reason'] is None
        assert items[0]['in_stock'] is True
        assert summary['unavailable_count'] == 0
        assert summary['subtotal'] == float(size.final_price * 2)

    def test_a_line_that_is_only_short_stays_in_stock_so_it_can_be_lowered(
            self, authenticated_client, test_user, test_product):
        size = default_variant_for(test_product.pk)
        _put(test_user, product=test_product, variant=size, quantity=5)
        size.stock = 3
        size.save(update_fields=['stock'])
        items, summary = _read(authenticated_client)
        row = items[0]
        assert row['in_stock'] is True
        assert row['available'] is False
        assert row['unavailable_reason'] == 'insufficient_stock'
        assert row['stock'] == 3
        # still priced (the customer lowers the quantity), but Billing is told
        assert summary['subtotal'] == float(size.final_price * 5)
        assert summary['unavailable_count'] == 1

    def test_a_combos_stock_is_what_can_be_built_not_999(
            self, authenticated_client, test_user, test_combo, test_product2):
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 4
        size2.save(update_fields=['stock'])
        _put(test_user, combo=test_combo)
        items, _ = _read(authenticated_client)
        assert items[0]['stock'] == 4

    def test_query_count_does_not_grow_with_the_number_of_lines(
            self, authenticated_client, test_user, test_product, test_product2, test_combo):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        _put(test_user, product=test_product,
             variant=default_variant_for(test_product.pk))
        with CaptureQueriesContext(connection) as few:
            authenticated_client.get(CART)
        _put(test_user, product=test_product2,
             variant=default_variant_for(test_product2.pk))
        _put(test_user, combo=test_combo)
        extra = _size(test_product, '500', 10)
        _put(test_user, product=test_product, variant=extra)
        with CaptureQueriesContext(connection) as many:
            authenticated_client.get(CART)
        # More lines may cost the per-line GST allocation, but the availability
        # check itself must add no query per line: allow a small fixed margin.
        assert len(many) <= len(few) + 8, f'{len(few)} -> {len(many)}'


@pytest.mark.django_db
class TestCombosAreLimitedByTheirComponents:
    def _soldout(self, test_product2):
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 0
        size2.save(update_fields=['stock'])

    def test_add_refuses_an_unbuildable_combo(self, authenticated_client, test_combo,
                                              test_product2):
        self._soldout(test_product2)
        resp = authenticated_client.post(f'{CART}add_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 1}, format='json')
        assert resp.status_code == 400
        assert resp.data['error'] == 'This combo is currently unavailable'
        assert not CartItem.objects.filter(combo=test_combo).exists()

    def test_add_refuses_more_than_can_be_built(self, authenticated_client, test_combo,
                                                test_product2):
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 2
        size2.save(update_fields=['stock'])
        resp = authenticated_client.post(f'{CART}add_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 3}, format='json')
        assert resp.status_code == 400
        assert resp.data['error'] == 'Only 2 units available'
        ok = authenticated_client.post(f'{CART}add_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 2}, format='json')
        assert ok.status_code == 200

    def test_add_again_cannot_exceed_it_either(self, authenticated_client, test_combo,
                                               test_product2):
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 2
        size2.save(update_fields=['stock'])
        for _ in range(2):
            authenticated_client.post(f'{CART}add_item/', {
                'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 1}, format='json')
        third = authenticated_client.post(f'{CART}add_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 1}, format='json')
        assert third.status_code == 400
        assert CartItem.objects.get(combo=test_combo).quantity == 2

    def test_update_refuses_an_unbuildable_combo_but_removal_still_works(
            self, authenticated_client, test_user, test_combo, test_product2):
        _put(test_user, combo=test_combo)
        self._soldout(test_product2)
        resp = authenticated_client.post(f'{CART}update_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 2}, format='json')
        assert resp.status_code == 400
        assert resp.data['error'] == 'This combo is currently unavailable'
        gone = authenticated_client.post(f'{CART}update_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 0}, format='json')
        assert gone.status_code == 200
        assert not CartItem.objects.filter(combo=test_combo).exists()

    def test_sync_skips_an_unbuildable_combo(self, authenticated_client, test_combo,
                                             test_product2):
        self._soldout(test_product2)
        resp = authenticated_client.post(f'{CART}sync/', {'items': [
            {'id': test_combo.id, 'item_type': 'combo', 'quantity': 1}]}, format='json')
        assert resp.status_code == 200
        assert resp.data['items'] == []
        assert resp.data['skipped'][0]['reason'] == 'currently unavailable'

    def test_a_combo_with_a_retired_component_size_is_refused(
            self, authenticated_client, test_combo, test_product2):
        ProductVariant.objects.filter(
            pk=default_variant_for(test_product2.pk).pk).update(is_active=False)
        resp = authenticated_client.post(f'{CART}add_item/', {
            'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 1}, format='json')
        assert resp.status_code == 400


@pytest.mark.django_db
class TestPublicComboAvailability:
    def _row(self, client, combo):
        data = client.get('/api/combos/').data
        rows = data['results'] if isinstance(data, dict) else data
        return next((c for c in rows if c['id'] == combo.id), None)

    def test_in_stock_when_buildable(self, api_client, test_combo):
        assert self._row(api_client, test_combo)['in_stock'] is True

    def test_false_for_a_sold_out_component(self, api_client, test_combo, test_product2):
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 0
        size2.save(update_fields=['stock'])
        assert self._row(api_client, test_combo)['in_stock'] is False

    def test_false_for_a_retired_component_size(self, api_client, test_combo, test_product2):
        ProductVariant.objects.filter(
            pk=default_variant_for(test_product2.pk).pk).update(is_active=False)
        assert self._row(api_client, test_combo)['in_stock'] is False

    def test_false_for_a_switched_off_component_product(
            self, api_client, test_combo, test_product2):
        Product.objects.filter(pk=test_product2.pk).update(is_active=False)  # behind save()
        assert self._row(api_client, test_combo)['in_stock'] is False

    def test_the_public_never_gets_a_count(self, api_client, test_combo):
        row = self._row(api_client, test_combo)
        assert 'available_stock' not in row
        assert 'low_stock_threshold' not in row

    def test_staff_still_get_the_count(self, admin_client, test_combo):
        row = self._row(admin_client, test_combo)
        assert row['available_stock'] == 50 and row['in_stock'] is True

    def test_search_and_home_sections_carry_the_flag(
            self, api_client, test_combo, test_product2):
        from products.models import ProductSection
        size2 = default_variant_for(test_product2.pk)
        size2.stock = 0
        size2.save(update_fields=['stock'])
        section = ProductSection.objects.create(name='Deals', slug='deals', max_products=10)
        test_combo.sections.add(section)

        hits = api_client.get('/api/search/', {'q': 'Test Combo Pack'}).data
        combo_hit = next(c for c in hits['combos'] if c['id'] == test_combo.id)
        assert combo_hit['in_stock'] is False

        data = api_client.get('/api/products/sections/').data
        rows = data['results'] if isinstance(data, dict) else data
        sec = next(s for s in rows if s['slug'] == 'deals')
        assert sec['combos'][0]['in_stock'] is False
