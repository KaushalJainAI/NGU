"""Review changes must evict the cached catalogue listings.

`GET /api/products/` is cached for CACHE_TTL_MEDIUM and embeds each product's
average_rating / reviews_count. Nothing listened to Review, so an admin could
hide a review, watch it disappear from the moderation table, and still find its
stars on the shop for the next five minutes — indistinguishable from a broken
hide button. These tests pin the invalidation in place.
"""
from decimal import Decimal

import pytest
from django.core.cache import cache

from conftest import create_test_image
from products.models import Product
from reviews.models import Review

PRODUCTS_URL = '/api/products/'


def _rating_of(client, product_id):
    """(average_rating, reviews_count) for a product in the public list."""
    resp = client.get(PRODUCTS_URL)
    assert resp.status_code == 200
    rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
    for row in rows:
        if row['id'] == product_id:
            return row['average_rating'], row['reviews_count']
    raise AssertionError(f'product {product_id} missing from {PRODUCTS_URL}')


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestReviewCacheInvalidation:
    def test_new_review_updates_the_cached_product_list(self, api_client, test_user, test_product):
        # Warm the cache with the unreviewed state.
        assert _rating_of(api_client, test_product.id) == (0, 0)

        Review.objects.create(
            item_type='product', product=test_product, user=test_user, rating=5,
            title='Great', comment='Lovely', is_verified_purchase=True,
        )

        assert _rating_of(api_client, test_product.id) == (5.0, 1), \
            'a new review must not wait for the cache to expire'

    def test_hiding_a_review_updates_the_cached_product_list(self, api_client, admin_client,
                                                             test_user, test_product):
        review = Review.objects.create(
            item_type='product', product=test_product, user=test_user, rating=5,
            title='Great', comment='Lovely', is_verified_purchase=True,
        )
        # Warm the cache while the review is visible.
        assert _rating_of(api_client, test_product.id) == (5.0, 1)

        resp = admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': True}, format='json')
        assert resp.status_code == 200

        assert _rating_of(api_client, test_product.id) == (0, 0), \
            'hiding a review must drop it from the storefront immediately'

    def test_unhiding_restores_the_rating(self, api_client, admin_client, test_user, test_product):
        review = Review.objects.create(
            item_type='product', product=test_product, user=test_user, rating=4,
            title='Good', comment='Nice', is_verified_purchase=True, is_hidden=True,
        )
        assert _rating_of(api_client, test_product.id) == (0, 0)

        assert admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': False}, format='json').status_code == 200
        assert _rating_of(api_client, test_product.id) == (4.0, 1)

    def test_deleting_a_review_updates_the_cached_product_list(self, api_client, test_user,
                                                               test_product):
        review = Review.objects.create(
            item_type='product', product=test_product, user=test_user, rating=5,
            title='Great', comment='Lovely', is_verified_purchase=True,
        )
        assert _rating_of(api_client, test_product.id) == (5.0, 1)

        review.delete()
        assert _rating_of(api_client, test_product.id) == (0, 0)


@pytest.mark.django_db
class TestHiddenReviewsExcludedFromAggregates:
    """The serializer fallback (no viewset annotation) must also skip hidden."""

    def test_detail_endpoint_excludes_hidden(self, api_client, admin_client, test_user, test_product):
        review = Review.objects.create(
            item_type='product', product=test_product, user=test_user, rating=5,
            title='Great', comment='Lovely', is_verified_purchase=True,
        )
        resp = api_client.get(f'/api/products/{test_product.slug}/')
        assert resp.status_code == 200
        assert resp.data['reviews_count'] == 1

        assert admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': True}, format='json').status_code == 200

        resp = api_client.get(f'/api/products/{test_product.slug}/')
        assert resp.data['reviews_count'] == 0
        assert resp.data['average_rating'] == 0

    def test_list_and_detail_agree(self, api_client, test_user, test_user2, test_category):
        """A card and its detail page must never disagree about the rating."""
        product = Product.objects.create(
            name='Agreement Spice', category=test_category, description='d',
            price=Decimal('100'), stock=10, weight=Decimal('100'), unit='g',
            spice_form='powder', image=create_test_image(),
        )
        Review.objects.create(
            item_type='product', product=product, user=test_user, rating=3,
            title='Ok', comment='Fine', is_verified_purchase=True,
        )
        # A different user: one review per person per product.
        Review.objects.create(
            item_type='product', product=product, user=test_user2, rating=5,
            title='Hidden one', comment='Nope', is_verified_purchase=True,
            is_hidden=True,
        )

        list_rating = _rating_of(api_client, product.id)
        detail = api_client.get(f'/api/products/{product.slug}/').data
        assert list_rating == (detail['average_rating'], detail['reviews_count'])
        assert list_rating == (3.0, 1), 'the hidden 5-star must not count anywhere'
