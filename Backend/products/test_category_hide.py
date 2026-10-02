"""Hiding a category must not leave its products on sale with no shelf.

Default rule (owner decision D1): a category that still holds ACTIVE products
cannot be hidden — the admin is told which, and moves or switches them off first.
Categories that are already hidden are kept consistent everywhere shoppers look.
"""
import pytest

from products.models import Category, Product
from products.recommendations import SpiceSearchEngine, build_search_corpus


def _other_category(name='Other Shelf'):
    return Category.objects.create(name=name, is_active=True)


@pytest.mark.django_db
class TestHidingIsRefusedWhileProductsAreOnSale:
    def test_delete_is_refused_and_names_the_products(
            self, admin_client, test_category, test_product, test_product2):
        resp = admin_client.delete(f'/api/categories/{test_category.slug}/')
        assert resp.status_code == 409
        assert resp.data['count'] == 2
        assert set(resp.data['products']) == {test_product.name, test_product2.name}
        assert 'Move them to another category or switch them off first' in resp.data['detail']
        assert test_product.name in resp.data['detail']
        assert Category.objects.get(pk=test_category.pk).is_active is True

    def test_the_panels_show_hide_switch_is_refused_too(
            self, admin_client, test_category, test_product):
        resp = admin_client.patch(f'/api/categories/{test_category.slug}/',
                                  {'is_active': False}, format='json')
        assert resp.status_code == 400
        assert test_product.name in str(resp.data)
        assert Category.objects.get(pk=test_category.pk).is_active is True

    def test_a_long_list_is_capped_at_ten_names(self, admin_client, test_category):
        from conftest import create_test_image
        from decimal import Decimal
        for i in range(12):
            Product.objects.create(
                name=f'Spice {i:02d}', category=test_category, description='x',
                price=Decimal('10'), stock=5, weight=Decimal('100'), unit='g',
                spice_form='powder', is_active=True, image=create_test_image(f's{i}.jpg'))
        resp = admin_client.delete(f'/api/categories/{test_category.slug}/')
        assert resp.status_code == 409
        assert resp.data['count'] == 12 and len(resp.data['products']) == 10
        assert '…' in resp.data['detail']

    def test_after_moving_the_products_it_can_be_hidden(
            self, admin_client, test_category, test_product, test_product2):
        elsewhere = _other_category()
        Product.objects.filter(category=test_category).update(category=elsewhere)
        assert admin_client.delete(f'/api/categories/{test_category.slug}/').status_code == 204
        assert Category.objects.get(pk=test_category.pk).is_active is False

    def test_after_switching_them_off_it_can_be_hidden_by_patch(
            self, admin_client, test_category, test_product, test_product2):
        Product.objects.filter(category=test_category).update(is_active=False)
        resp = admin_client.patch(f'/api/categories/{test_category.slug}/',
                                  {'is_active': False}, format='json')
        assert resp.status_code == 200
        assert Category.objects.get(pk=test_category.pk).is_active is False

    def test_a_secondary_shelf_does_not_block_hiding(self, admin_client, test_category,
                                                     test_product):
        elsewhere = _other_category()
        Product.objects.filter(pk=test_product.pk).update(category=elsewhere)
        test_product.extra_categories.add(test_category)    # only a secondary shelf here
        assert admin_client.delete(f'/api/categories/{test_category.slug}/').status_code == 204

    def test_showing_it_again_and_other_edits_are_unaffected(
            self, admin_client, test_category, test_product):
        resp = admin_client.patch(f'/api/categories/{test_category.slug}/',
                                  {'description': 'new words'}, format='json')
        assert resp.status_code == 200
        Category.objects.filter(pk=test_category.pk).update(is_active=False)
        Product.objects.filter(pk=test_product.pk).update(is_active=False)
        resp = admin_client.patch(f'/api/categories/{test_category.slug}/',
                                  {'is_active': True}, format='json')
        assert resp.status_code == 200


@pytest.mark.django_db
class TestAnAlreadyHiddenCategoryIsConsistent:
    """Rows that exist today, or were changed outside the panel."""

    @pytest.fixture
    def hidden(self, test_category, test_product):
        Category.objects.filter(pk=test_category.pk).update(is_active=False)
        return test_category

    @staticmethod
    def _ids(resp):
        data = resp.data
        rows = data['results'] if isinstance(data, dict) and 'results' in data else data
        return [p['id'] for p in rows]

    def test_the_public_category_filter_lists_nothing(self, api_client, hidden, test_product):
        assert self._ids(api_client.get(f'/api/products/?category={hidden.id}')) == []
        assert self._ids(api_client.get(f'/api/products/?category={hidden.slug}')) == []

    def test_staff_still_see_it(self, admin_client, hidden, test_product):
        assert test_product.id in self._ids(admin_client.get(f'/api/products/?category={hidden.id}'))

    def test_a_visible_category_still_lists_its_products(self, api_client, test_category,
                                                         test_product):
        assert test_product.id in self._ids(
            api_client.get(f'/api/products/?category={test_category.id}'))

    def test_a_visible_secondary_shelf_still_lists_the_product(self, api_client, test_product):
        shelf = _other_category('Gift Shelf')
        test_product.extra_categories.add(shelf)
        assert test_product.id in self._ids(api_client.get(f'/api/products/?category={shelf.id}'))

    def test_the_search_corpus_drops_the_hidden_category_name(self, hidden, test_product):
        kinds = {(e['text'], e['kind']) for e in build_search_corpus() if e['type'] == 'product'}
        assert (hidden.name.lower(), 'category') not in kinds
        # the product itself is still searchable by its own name
        assert ('test turmeric powder', 'name') in kinds

    def test_a_visible_category_name_is_still_a_search_term(self, test_category, test_product):
        kinds = {(e['text'], e['kind']) for e in build_search_corpus()}
        assert (test_category.name.lower(), 'category') in kinds

    def test_the_category_fallback_ignores_a_hidden_category(self, hidden, test_product):
        rows = SpiceSearchEngine()._other_recommendations('test spices', 8)
        assert not [r for r in rows if r['score_type'] == 'category']

    def test_the_category_fallback_uses_a_visible_one(self, test_category, test_product):
        rows = SpiceSearchEngine()._other_recommendations('test spices', 8)
        assert [r for r in rows if r['score_type'] == 'category']
