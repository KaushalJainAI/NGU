"""Multi-size behaviour of the bulk editor, the combo write path and the size
(variant) endpoint, plus lookups for ids that name nothing."""
from decimal import Decimal
from io import BytesIO

import pytest

from products.models import (
    ProductCombo, ProductComboItem, ProductVariant, default_variant_for,
)

APPLY = '/api/admin/bulk-products/apply/'


def _size(product, weight, price, **extra):
    return ProductVariant.objects.create(
        product=product, weight=weight, unit='g', price=Decimal(price), **extra)


@pytest.mark.django_db
class TestBulkApplyAcrossSizes:
    def test_several_sizes_of_one_product_in_one_batch(self, admin_client, test_product):
        default = default_variant_for(test_product.pk)
        big = _size(test_product, 500, '280.00', stock=5)
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'variant_id': default.id, 'stock': 11},
            {'id': test_product.id, 'variant_id': big.id, 'price': '300', 'stock': 22},
        ]}, format='json')
        assert resp.status_code == 200
        assert resp.data['applied'] == 2
        default.refresh_from_db()
        big.refresh_from_db()
        assert default.stock == 11
        assert (big.price, big.stock) == (Decimal('300'), 22)

    def test_a_change_without_a_size_lands_on_the_default_size(self, admin_client, test_product):
        """Not on the Product's own columns: those only mirror the default size
        and would be overwritten by the next size save."""
        default = default_variant_for(test_product.pk)
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'price': '180', 'stock': 9},
        ]}, format='json')
        assert resp.status_code == 200
        default.refresh_from_db()
        assert (default.price, default.stock) == (Decimal('180'), 9)

    def test_discount_must_stay_below_the_price_it_ends_up_with(self, admin_client, test_product):
        default = default_variant_for(test_product.pk)   # 150, discounted to 120
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'variant_id': default.id, 'price': '100'},
        ]}, format='json')
        assert resp.status_code == 400
        (error,) = resp.data['errors']
        assert error['variant_id'] == default.id
        assert 'less than the price' in error['error']
        default.refresh_from_db()
        assert default.price == Decimal('150.00')

    def test_raising_price_and_discount_together_is_fine(self, admin_client, test_product):
        default = default_variant_for(test_product.pk)
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'variant_id': default.id,
             'price': '300', 'discount_price': '250'},
        ]}, format='json')
        assert resp.status_code == 200
        default.refresh_from_db()
        assert (default.price, default.discount_price) == (Decimal('300'), Decimal('250'))

    def test_zero_price_rejected(self, admin_client, test_product):
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'price': '0'},
        ]}, format='json')
        assert resp.status_code == 400
        assert 'more than 0' in resp.data['errors'][0]['error']

    def test_zero_discount_clears_it(self, admin_client, test_product):
        default = default_variant_for(test_product.pk)
        resp = admin_client.post(APPLY, {'changes': [
            {'id': test_product.id, 'variant_id': default.id, 'discount_price': '0'},
        ]}, format='json')
        assert resp.status_code == 200
        default.refresh_from_db()
        assert default.discount_price is None

    def test_grid_lists_every_active_size(self, admin_client, test_product):
        _size(test_product, 500, '280.00')
        _size(test_product, 1000, '500.00', is_active=False)
        resp = admin_client.get('/api/admin/bulk-products/')
        row = next(r for r in resp.data if r['id'] == test_product.id)
        assert [v['label'] for v in row['variants']] == ['250g', '500g']
        assert row['is_active'] is True

    def test_import_flags_a_size_listed_twice(self, admin_client, test_product):
        body = f"name,size,price\n{test_product.name},250g,160\n{test_product.name},250g,170\n"
        upload = BytesIO(body.encode())
        upload.name = 'sheet.csv'
        resp = admin_client.post('/api/admin/bulk-products/import/',
                                 {'file': upload}, format='multipart')
        assert resp.status_code == 200
        assert resp.data['ok_count'] == 1
        assert 'already on row 2' in resp.data['rows'][1]['error']


@pytest.mark.django_db
class TestComboWrites:
    def _payload(self, items, **extra):
        return {'items': items, **extra}

    def test_two_sizes_of_the_same_product(self, admin_client, test_product):
        small = default_variant_for(test_product.pk)
        big = _size(test_product, 500, '280.00', stock=10)
        resp = admin_client.post('/api/combos/', {
            'name': 'Turmeric Duo', 'discount_price': '400',
            'items': [{'product': test_product.id, 'variant': small.id, 'quantity': 1},
                      {'product': test_product.id, 'variant': big.id, 'quantity': 1}],
        }, format='json')
        assert resp.status_code == 201, resp.data
        assert Decimal(str(resp.data['price'])) == Decimal('430.00')
        assert [i['variant_label'] for i in resp.data['items']] == ['250g', '500g']

    def test_a_rejected_edit_leaves_the_combo_untouched(self, admin_client, test_combo, test_product):
        """The old lines used to be deleted (and the name already saved) before
        the new ones were validated."""
        before = sorted(ProductComboItem.objects.filter(combo=test_combo)
                        .values_list('variant_id', 'quantity'))
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/', {
            'name': 'Renamed',
            'items': [{'product': test_product.id, 'variant': 999999, 'quantity': 1}],
        }, format='json')
        assert resp.status_code == 400
        test_combo.refresh_from_db()
        assert test_combo.name == 'Test Combo Pack'
        assert sorted(ProductComboItem.objects.filter(combo=test_combo)
                      .values_list('variant_id', 'quantity')) == before

    def test_a_failed_create_leaves_no_empty_combo(self, admin_client, test_product):
        resp = admin_client.post('/api/combos/', {
            'name': 'Ghost', 'items': [{'product': test_product.id, 'variant': 999999}],
        }, format='json')
        assert resp.status_code == 400
        assert not ProductCombo.objects.filter(name='Ghost').exists()

    @pytest.mark.parametrize('items', ['5', '{}', '"x"', '[1, 2]', 'not json'])
    def test_malformed_items_are_a_400(self, admin_client, test_combo, items):
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/',
                                  {'items': items}, format='json')
        assert resp.status_code == 400

    def test_selling_price_is_checked_against_the_new_components(
            self, admin_client, test_combo, test_product):
        """250 was fine against 150+200; it is not against a single 150 size."""
        small = default_variant_for(test_product.pk)
        resp = admin_client.patch(f'/api/combos/{test_combo.slug}/', {
            'items': [{'product': test_product.id, 'variant': small.id, 'quantity': 1}],
        }, format='json')
        assert resp.status_code == 400
        assert ProductComboItem.objects.filter(combo=test_combo).count() == 2

    def test_items_report_a_retired_component(self, admin_client, test_combo, test_product):
        ProductVariant.objects.filter(product=test_product).update(is_active=False)
        resp = admin_client.get(f'/api/combos/{test_combo.slug}/')
        flags = {i['product']: i['variant_is_active'] for i in resp.data['items']}
        assert flags[test_product.id] is False
        assert resp.data['available_stock'] == 0


@pytest.mark.django_db
class TestRetiringASize:
    def test_unticking_active_on_a_combo_component_is_refused(
            self, admin_client, test_combo, test_product):
        _size(test_product, 500, '280.00')          # so it is not the last size
        in_combo = default_variant_for(test_product.pk)
        resp = admin_client.patch(f'/api/product-variants/{in_combo.id}/',
                                  {'is_active': False}, format='json')
        assert resp.status_code == 400
        assert 'Test Combo Pack' in str(resp.data)
        in_combo.refresh_from_db()
        assert in_combo.is_active is True

    def test_unticking_the_last_active_size_is_refused(self, admin_client, test_product):
        only = default_variant_for(test_product.pk)
        resp = admin_client.patch(f'/api/product-variants/{only.id}/',
                                  {'is_active': False}, format='json')
        assert resp.status_code == 400
        only.refresh_from_db()
        assert only.is_active is True

    def test_a_free_size_can_be_switched_off_and_back_on(self, admin_client, test_product):
        default = default_variant_for(test_product.pk)
        spare = _size(test_product, 500, '280.00')
        resp = admin_client.patch(f'/api/product-variants/{spare.id}/',
                                  {'is_active': False}, format='json')
        assert resp.status_code == 200
        resp = admin_client.patch(f'/api/product-variants/{spare.id}/',
                                  {'is_active': True}, format='json')
        assert resp.status_code == 200
        default.refresh_from_db()
        assert default.is_default is True


@pytest.mark.django_db
class TestLookupsThatNameNothing:
    """An id that is not an id is "no such row" — never an exception."""

    @pytest.mark.parametrize('path', [
        '/api/products/99999999999999999999999/',
        '/api/products/²/',
        '/api/combos/99999999999999999999999/',
        '/api/categories/99999999999999999999999/',
        '/api/products/no-such-slug/',
        '/api/combos/0/',
    ])
    def test_detail_is_404(self, api_client, path):
        assert api_client.get(path).status_code == 404

    @pytest.mark.parametrize('path', [
        '/api/product-variants/?product=abc',
        '/api/product-variants/?product=99999999999999999999999',
        '/api/product-images/?product=abc',
        '/api/reviews/?product=abc',
        '/api/reviews/?combo=1;drop',
    ])
    def test_filter_is_an_empty_list(self, api_client, test_product, path):
        resp = api_client.get(path)
        assert resp.status_code == 200
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        assert list(rows) == []
