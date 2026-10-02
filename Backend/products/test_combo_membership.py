"""A switched-off product is taken out of every combo, and comes back with it."""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from cart.models import Cart, CartItem
from products.models import (
    DetachedComboLine, Product, ProductCombo, ProductComboItem, ProductVariant,
    default_variant_for,
)

ADDR = {"shipping_address": "1 Test Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _lines(combo):
    return sorted(ProductComboItem.objects.filter(combo=combo)
                  .values_list('product__name', 'quantity'))


def _switch(client, product, on):
    return client.patch(f'/api/products/{product.slug}/', {'is_active': on}, format='json')


@pytest.mark.django_db
class TestSwitchingAProductOff:
    def test_it_leaves_every_combo_and_the_combo_goes_off_sale(
            self, admin_client, test_combo, test_product):
        resp = _switch(admin_client, test_product, False)
        assert resp.status_code == 200
        assert resp.data['combo_changes'] == {
            'removed_from': ['Test Combo Pack'], 'switched_off': ['Test Combo Pack']}

        assert _lines(test_combo) == [('Test Cumin Seeds', 1)]
        test_combo.refresh_from_db()
        # Off, but NOT stamped as deleted — the Recycle Bin purge must never
        # age out a combo the system switched off by itself.
        assert test_combo.is_active is False
        assert test_combo.deactivated_at is None

    def test_delete_does_the_same(self, admin_client, test_combo, test_product):
        assert admin_client.delete(f'/api/products/{test_product.slug}/').status_code == 204
        assert _lines(test_combo) == [('Test Cumin Seeds', 1)]
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False

    def test_a_save_that_does_not_touch_is_active_changes_nothing(
            self, admin_client, test_combo, test_product):
        resp = admin_client.patch(f'/api/products/{test_product.slug}/',
                                  {'badge': 'New'}, format='json')
        assert resp.status_code == 200
        assert 'combo_changes' not in resp.data
        assert len(_lines(test_combo)) == 2

    def test_a_combo_priced_above_its_reduced_mrp_does_not_block_the_switch_off(
            self, admin_client, test_combo, test_product2):
        """250 against 150+200 is fine; with the 200 line gone the MRP is 150
        and ProductCombo.clean() would refuse to save. The product must still
        be switchable off."""
        assert _switch(admin_client, test_product2, False).status_code == 200
        assert _lines(test_combo) == [('Test Turmeric Powder', 1)]

    def test_public_combo_list_no_longer_offers_it(
            self, admin_client, api_client, test_combo, test_product):
        _switch(admin_client, test_product, False)
        api_client.credentials()
        names = [c['name'] for c in api_client.get('/api/combos/').data]
        assert 'Test Combo Pack' not in names

    def test_staff_see_what_the_combo_is_missing(self, admin_client, test_combo, test_product):
        _switch(admin_client, test_product, False)
        data = admin_client.get(f'/api/combos/{test_combo.slug}/').data
        assert data['missing_products'] == ['Test Turmeric Powder']


@pytest.mark.django_db
class TestSwitchingItBackOn:
    def test_lines_and_combo_come_back(self, admin_client, test_combo, test_product):
        before = _lines(test_combo)
        _switch(admin_client, test_product, False)
        resp = _switch(admin_client, test_product, True)
        assert resp.data['combo_changes'] == {
            'restored_to': ['Test Combo Pack'], 'switched_on': ['Test Combo Pack']}
        assert _lines(test_combo) == before
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is True
        assert not DetachedComboLine.objects.exists()

    def test_quantity_and_size_are_restored_exactly(self, admin_client, test_product, test_product2):
        big = ProductVariant.objects.create(product=test_product, weight=500, unit='g',
                                            price=Decimal('280'), stock=10)
        combo = ProductCombo.objects.create(name='Big Pack')
        ProductComboItem.objects.create(combo=combo, product=test_product, variant=big, quantity=3)
        ProductComboItem.objects.create(combo=combo, product=test_product2, quantity=1)

        _switch(admin_client, test_product, False)
        _switch(admin_client, test_product, True)
        line = ProductComboItem.objects.get(combo=combo, product=test_product)
        assert (line.variant_id, line.quantity) == (big.id, 3)

    def test_a_combo_that_was_already_off_stays_off(self, admin_client, test_combo, test_product):
        ProductCombo.objects.filter(pk=test_combo.pk).update(is_active=False)
        _switch(admin_client, test_product, False)
        resp = _switch(admin_client, test_product, True)
        assert resp.data['combo_changes'] == {'restored_to': ['Test Combo Pack'], 'switched_on': []}
        assert len(_lines(test_combo)) == 2
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False

    def test_combo_waits_until_every_missing_product_is_back(
            self, admin_client, test_combo, test_product, test_product2):
        _switch(admin_client, test_product, False)
        _switch(admin_client, test_product2, False)
        assert _lines(test_combo) == []

        _switch(admin_client, test_product, True)
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False   # still short
        _switch(admin_client, test_product2, True)
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is True
        assert len(_lines(test_combo)) == 2

    def test_a_combo_the_admin_re_defined_is_left_alone(
            self, admin_client, test_combo, test_product, test_product2):
        """Editing the combo while the product is off is the owner saying
        "this is the bundle now" — the old line must not be pushed back in."""
        _switch(admin_client, test_product, False)
        cumin = default_variant_for(test_product2.pk)
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/', {
            'discount_price': '180', 'is_active': True,
            'items': [{'product': test_product2.id, 'variant': cumin.id, 'quantity': 1}],
        }, format='json')
        assert resp.status_code == 200, resp.data

        resp = _switch(admin_client, test_product, True)
        assert 'combo_changes' not in resp.data
        assert _lines(test_combo) == [('Test Cumin Seeds', 1)]

    def test_a_combo_sent_to_the_bin_meanwhile_is_not_switched_back_on(
            self, admin_client, test_combo, test_product):
        _switch(admin_client, test_product, False)
        # Binning must work even though 250 is now above the reduced MRP (200).
        assert admin_client.delete(f'/api/combos/{test_combo.slug}/').status_code == 204
        _switch(admin_client, test_product, True)
        assert len(_lines(test_combo)) == 2                             # whole again…
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False   # …but still binned


@pytest.mark.django_db
class TestAReducedComboCannotQuietlyGoBackOnSale:
    def test_switching_it_on_above_its_new_mrp_is_refused(
            self, admin_client, test_combo, test_product2):
        """Cumin (200) leaves; the combo still says 250 against an MRP of 150."""
        _switch(admin_client, test_product2, False)
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/',
                                  {'is_active': True}, format='json')
        assert resp.status_code == 400
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False

    def test_it_can_be_repriced_while_off_and_then_switched_on(
            self, admin_client, test_combo, test_product2):
        _switch(admin_client, test_product2, False)
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/',
                                  {'discount_price': '140', 'is_active': True}, format='json')
        assert resp.status_code == 200, resp.data
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is True


@pytest.mark.django_db
class TestBehindSavesBack:
    """Rows changed with .update()/SQL never pass through Product.save()."""

    def test_checkout_refuses_a_combo_holding_a_switched_off_product(
            self, authenticated_client, test_user, test_combo, test_product):
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=test_combo, item_type='combo', quantity=1)
        resp = authenticated_client.post('/api/orders/', ADDR, format='json')
        assert resp.status_code == 400
        assert 'no longer available' in resp.data['error']

    def test_such_a_combo_counts_as_unbuildable(self, test_combo, test_product):
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        assert ProductCombo.objects.get(pk=test_combo.pk).available_stock == 0

    def test_the_cleanup_command(self, test_combo, test_product):
        Product.objects.filter(pk=test_product.pk).update(is_active=False)

        out = StringIO()
        call_command('detach_inactive_products_from_combos', '--dry-run', stdout=out)
        assert 'would be removed from Test Combo Pack' in out.getvalue()
        assert len(_lines(test_combo)) == 2                      # dry run changed nothing

        call_command('detach_inactive_products_from_combos', stdout=StringIO())
        assert _lines(test_combo) == [('Test Cumin Seeds', 1)]
        assert ProductCombo.objects.get(pk=test_combo.pk).is_active is False
        assert DetachedComboLine.objects.count() == 1
