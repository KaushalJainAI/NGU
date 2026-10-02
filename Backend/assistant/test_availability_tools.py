"""The shopping assistant reports combo and product availability from the same rule
as the storefront: a combo is buildable only while every component size is stocked,
and a product is in stock while ANY active size is."""
from decimal import Decimal

import pytest

from assistant import tools as toolkit
from products.models import ProductVariant, default_variant_for


def _sold_out(product):
    size = default_variant_for(product.pk)
    size.stock = 0
    size.save(update_fields=['stock'])


@pytest.mark.django_db
class TestComboAvailability:
    def test_a_buildable_combo_is_in_stock(self, test_combo):
        assert toolkit._combo_public(test_combo)['in_stock'] is True

    def test_a_combo_with_a_sold_out_component_is_not(self, test_combo, test_product2):
        _sold_out(test_product2)
        assert toolkit._combo_public(
            type(test_combo).objects.get(pk=test_combo.pk))['in_stock'] is False

    def test_browse_in_stock_includes_buildable_combos_and_skips_the_rest(
            self, test_user, test_combo, test_product2):
        names = lambda out: [r['name'] for r in out['results']]
        assert 'Test Combo Pack' in names(
            toolkit.tool_browse_products(test_user, {'in_stock': True}))
        _sold_out(test_product2)
        assert 'Test Combo Pack' not in names(
            toolkit.tool_browse_products(test_user, {'in_stock': True}))
        # without the filter it is listed, flagged out of stock
        row = next(r for r in toolkit.tool_browse_products(test_user, {})['results']
                   if r['name'] == 'Test Combo Pack')
        assert row['in_stock'] is False

    def test_a_proposal_for_an_unbuildable_combo_is_refused(
            self, test_user, test_combo, test_product2):
        _sold_out(test_product2)
        action, msg = toolkit.build_add_to_cart(
            test_user, {'item_type': 'combo', 'product_id': test_combo.id, 'quantity': 1})
        assert action is None
        assert 'currently unavailable' in msg

    def test_a_proposal_for_a_buildable_combo_still_works(self, test_user, test_combo):
        action, msg = toolkit.build_add_to_cart(
            test_user, {'item_type': 'combo', 'product_id': test_combo.id, 'quantity': 1})
        assert msg is None and action['item_type'] == 'combo'

    def test_a_cart_proposal_refuses_one_unbuildable_line(
            self, test_user, test_combo, test_product, test_product2):
        _sold_out(test_product2)
        action, msg = toolkit.build_cart_proposal(test_user, {'lines': [
            {'item_type': 'combo', 'product_id': test_combo.id, 'quantity': 1},
            {'item_type': 'product', 'product_id': test_product.id, 'quantity': 1},
        ]})
        assert action is None and 'currently unavailable' in msg


@pytest.mark.django_db
class TestProductAvailability:
    def test_in_stock_when_only_a_non_default_size_has_stock(self, test_user, test_product):
        _sold_out(test_product)
        ProductVariant.objects.create(
            product=test_product, weight=Decimal('500'), unit='g', price=Decimal('300'), stock=9)
        row = toolkit._product_public(type(test_product).objects.get(pk=test_product.pk))
        assert row['in_stock'] is True
        out = toolkit.tool_browse_products(test_user, {'in_stock': True})
        assert test_product.name in [r['name'] for r in out['results']]

    def test_not_in_stock_when_every_size_is_sold_out(self, test_user, test_product):
        _sold_out(test_product)
        row = toolkit._product_public(type(test_product).objects.get(pk=test_product.pk))
        assert row['in_stock'] is False
        out = toolkit.tool_browse_products(test_user, {'in_stock': True})
        assert test_product.name not in [r['name'] for r in out['results']]
