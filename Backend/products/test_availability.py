"""One place answers "can this be bought?" (products/availability.py), and search,
suggestions, recommendations and the product list all ask it — so a product whose
DEFAULT size is sold out but has another size in stock still shows up."""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cart.models import Cart, CartItem
from products import availability as av
from products.models import (
    Product, ProductCombo, ProductComboItem, ProductVariant, default_variant_for,
)
from products.recommendations import build_suggestions


def _add_size(product, weight, stock, *, active=True, price='300.00'):
    return ProductVariant.objects.create(
        product=product, weight=Decimal(weight), unit='g', price=Decimal(price),
        stock=stock, is_active=active,
    )


def _set_stock(variant, stock):
    variant.stock = stock
    variant.save(update_fields=['stock'])   # also mirrors a default size onto Product


def _line(user, *, product=None, variant=None, combo=None, quantity=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    if combo is not None:
        return CartItem.objects.create(cart=cart, combo=combo, item_type='combo', quantity=quantity)
    return CartItem.objects.create(cart=cart, product=product, variant=variant,
                                   item_type='product', quantity=quantity)


# ---------------------------------------------------------------------------
# Products: "in stock" means ANY active size with stock
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProductStockRule:
    def test_default_sold_out_but_another_size_stocked_counts(self, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 40)
        assert av.product_has_stock(Product.objects.get(pk=test_product.pk)) is True
        assert av.in_stock_products(Product.objects.all()).filter(pk=test_product.pk).exists()

    def test_every_size_sold_out_does_not(self, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 0)
        assert av.product_has_stock(Product.objects.get(pk=test_product.pk)) is False
        assert not av.in_stock_products(Product.objects.all()).filter(pk=test_product.pk).exists()

    def test_a_retired_size_with_stock_does_not_count(self, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 40, active=False)
        assert av.product_has_stock(Product.objects.get(pk=test_product.pk)) is False
        assert not av.in_stock_products(Product.objects.all()).filter(pk=test_product.pk).exists()

    def test_three_stocked_sizes_are_still_one_row(self, test_product):
        _add_size(test_product, '500', 5)
        _add_size(test_product, '1000', 5)
        rows = av.in_stock_products(Product.objects.filter(pk=test_product.pk))
        assert rows.count() == 1

    def test_a_legacy_product_with_no_sizes_falls_back_to_its_own_stock(self, test_product):
        ProductVariant.objects.filter(product=test_product).delete()
        fresh = Product.objects.get(pk=test_product.pk)
        assert fresh.stock > 0
        assert av.product_has_stock(fresh) is True
        assert av.in_stock_products(Product.objects.all()).filter(pk=test_product.pk).exists()
        Product.objects.filter(pk=test_product.pk).update(stock=0)
        assert av.product_has_stock(Product.objects.get(pk=test_product.pk)) is False
        assert not av.in_stock_products(Product.objects.all()).filter(pk=test_product.pk).exists()

    def test_the_model_property_uses_the_same_rule(self, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 40)
        assert Product.objects.get(pk=test_product.pk).in_stock is True


# ---------------------------------------------------------------------------
# Combos
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestComboCanBeBuilt:
    def test_buildable(self, test_combo):
        assert av.combo_can_be_built(test_combo) is True

    def test_quantity_is_checked_against_the_scarcest_component(self, test_combo, test_product2):
        _set_stock(default_variant_for(test_product2.pk), 2)
        combo = ProductCombo.objects.get(pk=test_combo.pk)
        assert av.combo_can_be_built(combo, 2) is True
        assert av.combo_can_be_built(combo, 3) is False

    def test_a_sold_out_component(self, test_combo, test_product2):
        _set_stock(default_variant_for(test_product2.pk), 0)
        assert av.combo_can_be_built(ProductCombo.objects.get(pk=test_combo.pk)) is False

    def test_a_retired_component_size(self, test_combo, test_product2):
        ProductVariant.objects.filter(
            pk=default_variant_for(test_product2.pk).pk).update(is_active=False)
        assert av.combo_can_be_built(ProductCombo.objects.get(pk=test_combo.pk)) is False

    def test_a_switched_off_component_product(self, test_combo, test_product2):
        Product.objects.filter(pk=test_product2.pk).update(is_active=False)  # behind save()
        assert av.combo_can_be_built(ProductCombo.objects.get(pk=test_combo.pk)) is False

    def test_a_combo_that_is_off_sale(self, test_combo):
        ProductCombo.objects.filter(pk=test_combo.pk).update(is_active=False)
        assert av.combo_can_be_built(ProductCombo.objects.get(pk=test_combo.pk)) is False


# ---------------------------------------------------------------------------
# Cart lines: one test per reason code
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLineProblem:
    def test_a_healthy_line(self, test_user, test_product):
        size = default_variant_for(test_product.pk)
        assert av.line_problem(_line(test_user, product=test_product, variant=size)) is None

    def test_product_off(self, test_user, test_product):
        size = default_variant_for(test_product.pk)
        line = _line(test_user, product=test_product, variant=size)
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        line = CartItem.objects.get(pk=line.pk)
        assert av.line_problem(line) == av.PRODUCT_OFF

    def test_size_retired(self, test_user, test_product):
        size = _add_size(test_product, '500', 10)
        line = _line(test_user, product=test_product, variant=size)
        ProductVariant.objects.filter(pk=size.pk).update(is_active=False)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.SIZE_RETIRED

    def test_combo_off(self, test_user, test_combo):
        line = _line(test_user, combo=test_combo)
        ProductCombo.objects.filter(pk=test_combo.pk).update(is_active=False)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.COMBO_OFF

    def test_combo_unavailable(self, test_user, test_combo, test_product2):
        line = _line(test_user, combo=test_combo)
        _set_stock(default_variant_for(test_product2.pk), 0)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.COMBO_UNAVAILABLE

    def test_out_of_stock(self, test_user, test_product):
        size = default_variant_for(test_product.pk)
        line = _line(test_user, product=test_product, variant=size)
        _set_stock(size, 0)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.OUT_OF_STOCK

    def test_insufficient_stock(self, test_user, test_product):
        size = default_variant_for(test_product.pk)
        line = _line(test_user, product=test_product, variant=size, quantity=5)
        _set_stock(size, 3)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.INSUFFICIENT_STOCK

    def test_the_first_matching_code_wins(self, test_user, test_product):
        """A switched-off product with a retired size and no stock is `product_off`."""
        size = default_variant_for(test_product.pk)
        line = _line(test_user, product=test_product, variant=size)
        ProductVariant.objects.filter(pk=size.pk).update(is_active=False, stock=0)
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        assert av.line_problem(CartItem.objects.get(pk=line.pk)) == av.PRODUCT_OFF

    def test_max_quantity_for_a_size_and_for_a_combo(self, test_user, test_product,
                                                      test_combo, test_product2):
        size = default_variant_for(test_product.pk)
        assert av.line_max_quantity(_line(test_user, product=test_product, variant=size)) == size.stock
        _set_stock(default_variant_for(test_product2.pk), 7)
        combo_line = _line(test_user, combo=ProductCombo.objects.get(pk=test_combo.pk))
        assert av.line_max_quantity(combo_line) == 7


# ---------------------------------------------------------------------------
# Low stock: per SIZE, against the product's alert level
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLowStockSizes:
    def test_a_non_default_size_running_low_is_reported_with_the_default_healthy(self, test_product):
        size = _add_size(test_product, '500', 1)
        names = [(v.product_id, v.id) for v in av.low_stock_sizes()]
        assert (test_product.pk, size.pk) in names
        assert (test_product.pk, default_variant_for(test_product.pk).pk) not in names

    def test_the_products_level_applies_to_every_size(self, test_product):
        Product.objects.filter(pk=test_product.pk).update(low_stock_threshold=20)
        size = _add_size(test_product, '500', 15)
        assert size.pk in [v.pk for v in av.low_stock_sizes()]

    def test_a_retired_size_is_not_reported(self, test_product):
        _add_size(test_product, '500', 0, active=False)
        assert av.low_stock_sizes().filter(product=test_product).count() == 0

    def test_a_switched_off_product_is_not_reported(self, test_product):
        _add_size(test_product, '500', 0)
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        assert av.low_stock_sizes().filter(product=test_product).count() == 0

    def test_out_of_stock_sizes(self, test_product):
        size = _add_size(test_product, '500', 0)
        assert size.pk in [v.pk for v in av.out_of_stock_sizes()]


# ---------------------------------------------------------------------------
# Gap 3: search, suggestions, recommendations, product list
# ---------------------------------------------------------------------------

@pytest.fixture
def default_sold_out(test_product):
    """Default size sold out, a 500 g size in stock — the reproduced bug."""
    _set_stock(default_variant_for(test_product.pk), 0)
    _add_size(test_product, '500', 40)
    return test_product


@pytest.mark.django_db
class TestSearchSeesEveryActiveSize:
    def test_suggestions_include_it(self, default_sold_out):
        result = build_suggestions('Test Turmeric', limit=6)
        assert default_sold_out.id in [s['id'] for s in result['suggestions']
                                       if s['type'] == 'product']

    def test_search_includes_it_as_in_stock(self, api_client, default_sold_out):
        resp = api_client.get('/api/search/', {'q': 'Test Turmeric'})
        assert resp.status_code == 200
        row = next(p for p in resp.data['products'] if p['id'] == default_sold_out.id)
        assert row['in_stock'] is True

    def test_product_list_says_in_stock(self, api_client, default_sold_out):
        rows = api_client.get('/api/products/').data
        rows = rows['results'] if isinstance(rows, dict) else rows
        assert next(p for p in rows if p['id'] == default_sold_out.id)['in_stock'] is True

    def test_recommendations_include_it(self, authenticated_client, default_sold_out):
        resp = authenticated_client.get('/api/recommendations/')
        assert resp.status_code == 200
        row = next(p for p in resp.data['products'] if p['id'] == default_sold_out.id)
        assert row['in_stock'] is True

    def test_all_sizes_sold_out_is_absent_from_all_of_them(
            self, api_client, authenticated_client, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 0)
        assert test_product.id not in [s['id'] for s in build_suggestions(
            'Test Turmeric', limit=6)['suggestions']]
        assert test_product.id not in [p['id'] for p in api_client.get(
            '/api/search/', {'q': 'Test Turmeric'}).data['products']]
        assert test_product.id not in [p['id'] for p in authenticated_client.get(
            '/api/recommendations/').data['products']]

    def test_a_retired_size_with_stock_does_not_keep_it_visible(self, api_client, test_product):
        _set_stock(default_variant_for(test_product.pk), 0)
        _add_size(test_product, '500', 40, active=False)
        assert test_product.id not in [p['id'] for p in api_client.get(
            '/api/search/', {'q': 'Test Turmeric'}).data['products']]


@pytest.mark.django_db
class TestNoQueryPerProduct:
    def _count(self, client, url):
        """(number of queries, response data) for one GET."""
        with CaptureQueriesContext(connection) as ctx:
            resp = client.get(url)
            assert resp.status_code == 200
        return len(ctx), resp.data

    def test_product_list_query_count_does_not_grow_with_products(
            self, api_client, test_category):
        from conftest import create_test_image

        def make(i):
            p = Product.objects.create(
                name=f'Bulk Spice {i}', category=test_category, description='x',
                price=Decimal('100.00'), stock=10, weight=Decimal('100'), unit='g',
                spice_form='powder', is_active=True, image=create_test_image(f'b{i}.jpg'))
            _add_size(p, '500', 5)

        for i in range(2):
            make(i)
        api_client.get('/api/products/')      # warm anything cached
        from django.core.cache import cache
        cache.clear()
        few, few_data = self._count(api_client, '/api/products/')
        for i in range(2, 8):
            make(i)
        cache.clear()
        many, many_data = self._count(api_client, '/api/products/')
        rows = lambda d: d['results'] if isinstance(d, dict) else d
        assert len(rows(many_data)) - len(rows(few_data)) == 6   # really more rows
        assert many == few, f'{few} queries for 2 products, {many} for 8'

    def test_public_combo_list_query_count_does_not_grow_with_combos(
            self, api_client, test_product, test_product2):
        from django.core.cache import cache

        def make(i):
            combo = ProductCombo.objects.create(
                name=f'Bundle {i}', description='x', is_active=True)
            ProductComboItem.objects.create(combo=combo, product=test_product, quantity=1)
            ProductComboItem.objects.create(combo=combo, product=test_product2, quantity=1)

        for i in range(2):
            make(i)
        cache.clear()
        few, few_data = self._count(api_client, '/api/combos/')
        for i in range(2, 8):
            make(i)
        cache.clear()
        many, many_data = self._count(api_client, '/api/combos/')
        rows = lambda d: d['results'] if isinstance(d, dict) else d
        assert len(rows(many_data)) - len(rows(few_data)) == 6
        assert all('in_stock' in c for c in rows(many_data))
        assert many == few, f'{few} queries for 2 combos, {many} for 8'

    def test_home_sections_query_count_does_not_grow_with_combos(
            self, api_client, test_product, test_product2):
        from django.core.cache import cache
        from products.models import ProductSection

        section = ProductSection.objects.create(name='Deals', slug='deals', max_products=20)

        def make(i):
            combo = ProductCombo.objects.create(
                name=f'Bundle {i}', description='x', is_active=True)
            ProductComboItem.objects.create(combo=combo, product=test_product, quantity=1)
            ProductComboItem.objects.create(combo=combo, product=test_product2, quantity=1)
            combo.sections.add(section)

        for i in range(2):
            make(i)
        cache.clear()
        few, few_data = self._count(api_client, '/api/products/sections/')
        for i in range(2, 8):
            make(i)
        cache.clear()
        many, many_data = self._count(api_client, '/api/products/sections/')
        combos = lambda d: next(s for s in d if s['slug'] == 'deals')['combos']
        rows = lambda d: d['results'] if isinstance(d, dict) else d
        assert len(combos(rows(many_data))) - len(combos(rows(few_data))) == 6
        assert all('in_stock' in c for c in combos(rows(many_data)))
        assert many == few, f'{few} queries for 2 combos, {many} for 8'
