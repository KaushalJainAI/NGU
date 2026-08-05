"""Home page featured reviews, optional titles, and the public reviewer name.

Covers the three behaviours added alongside the moderation fixes:
  * an admin picks at most MAX_FEATURED_REVIEWS reviews for the home page,
  * the review title is genuinely optional (the storefront says it is),
  * `user_name` never falls back to the email-derived username when the
    customer has a real name.
"""
from decimal import Decimal

import pytest
from rest_framework import status

from conftest import create_test_image
from products.models import Product
from reviews.models import MAX_FEATURED_REVIEWS, Review

FEATURED_URL = '/api/reviews/featured/'
BASE_URL = '/api/reviews/'


def _review(user, product, hidden=False, rating=5):
    return Review.objects.create(
        item_type='product', product=product, user=user, rating=rating,
        title='Nice', comment='Good spice', is_verified_purchase=True,
        is_hidden=hidden,
    )


def _product(category, name):
    return Product.objects.create(
        name=name, category=category, description='d', price=Decimal('100'),
        stock=10, weight=Decimal('100'), unit='g', spice_form='powder',
        image=create_test_image(),
    )


def _set_featured(client, review, featured):
    return client.post(f'/api/reviews/{review.id}/set-featured/',
                       {'featured': featured}, format='json')


@pytest.mark.django_db
class TestFeaturedSelection:
    def test_staff_can_feature_and_unfeature(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product)

        resp = _set_featured(admin_client, review, True)
        assert resp.status_code == 200
        assert resp.data['is_featured'] is True
        assert resp.data['featured_count'] == 1
        assert resp.data['max_featured'] == MAX_FEATURED_REVIEWS
        review.refresh_from_db()
        assert review.is_featured is True

        assert _set_featured(admin_client, review, False).status_code == 200
        review.refresh_from_db()
        assert review.is_featured is False

    def test_non_staff_cannot_feature(self, authenticated_client, test_user, test_product):
        review = _review(test_user, test_product)
        assert _set_featured(authenticated_client, review, True).status_code == status.HTTP_403_FORBIDDEN
        review.refresh_from_db()
        assert review.is_featured is False

    def test_anonymous_cannot_feature(self, api_client, test_user, test_product):
        review = _review(test_user, test_product)
        assert _set_featured(api_client, review, True).status_code in (401, 403)
        review.refresh_from_db()
        assert review.is_featured is False

    def test_bad_payload_rejected(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-featured/',
                                 {'featured': 'yes please'}, format='json')
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_cap_is_enforced(self, admin_client, test_user, test_category):
        reviews = [_review(test_user, _product(test_category, f'Cap Spice {i}'))
                   for i in range(MAX_FEATURED_REVIEWS + 1)]

        for r in reviews[:MAX_FEATURED_REVIEWS]:
            assert _set_featured(admin_client, r, True).status_code == 200

        # The extra one is refused, not silently swapped in for an existing pick.
        resp = _set_featured(admin_client, reviews[-1], True)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        reviews[-1].refresh_from_db()
        assert reviews[-1].is_featured is False
        assert Review.objects.filter(is_featured=True).count() == MAX_FEATURED_REVIEWS

        # Freeing a slot admits it.
        assert _set_featured(admin_client, reviews[0], False).status_code == 200
        assert _set_featured(admin_client, reviews[-1], True).status_code == 200

    def test_refeaturing_an_already_featured_review_is_idempotent(self, admin_client, test_user,
                                                                  test_category):
        # Re-sending featured=true must not consume a second slot.
        reviews = [_review(test_user, _product(test_category, f'Idem {i}')) for i in range(3)]
        for r in reviews:
            assert _set_featured(admin_client, r, True).status_code == 200
        resp = _set_featured(admin_client, reviews[0], True)
        assert resp.status_code == 200
        assert Review.objects.filter(is_featured=True).count() == MAX_FEATURED_REVIEWS

    def test_hidden_review_cannot_be_featured(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product, hidden=True)
        assert _set_featured(admin_client, review, True).status_code == status.HTTP_400_BAD_REQUEST
        review.refresh_from_db()
        assert review.is_featured is False

    def test_hiding_a_featured_review_releases_its_slot(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product)
        assert _set_featured(admin_client, review, True).status_code == 200

        resp = admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': True}, format='json')
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.is_featured is False

    def test_is_featured_is_read_only_over_patch(self, authenticated_client, test_user, test_product):
        review = _review(test_user, test_product)
        resp = authenticated_client.patch(f'/api/reviews/{review.id}/',
                                          {'is_featured': True}, format='json')
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.is_featured is False, 'placement must never be self-service'

    def test_staff_can_list_only_the_pinned_ones(self, admin_client, test_user, test_category):
        picked = _review(test_user, _product(test_category, 'Picked'))
        _review(test_user, _product(test_category, 'Unpicked'))
        assert _set_featured(admin_client, picked, True).status_code == 200

        resp = admin_client.get('/api/reviews/?all=true&featured=true')
        assert resp.status_code == 200
        assert [r['id'] for r in resp.data['results']] == [picked.id]


@pytest.mark.django_db
class TestFeaturedStrip:
    def test_is_public(self, api_client, test_user, test_product):
        _review(test_user, test_product)
        assert api_client.get(FEATURED_URL).status_code == 200

    def test_excludes_hidden_reviews(self, api_client, test_user, test_product):
        review = _review(test_user, test_product)
        assert review.id in [r['id'] for r in api_client.get(FEATURED_URL).data['results']]

        review.is_hidden = True
        review.save(update_fields=['is_hidden'])
        assert review.id not in [r['id'] for r in api_client.get(FEATURED_URL).data['results']]

    def test_tops_up_to_three_when_fewer_are_pinned(self, admin_client, api_client,
                                                    test_user, test_category):
        made = [_review(test_user, _product(test_category, f'Fill {i}'), rating=5 if i == 0 else 3)
                for i in range(5)]
        assert _set_featured(admin_client, made[0], True).status_code == 200

        resp = api_client.get(FEATURED_URL)
        assert resp.status_code == 200
        assert resp.data['count'] == MAX_FEATURED_REVIEWS
        ids = [r['id'] for r in resp.data['results']]
        assert ids[0] == made[0].id, 'the pinned review leads the strip'
        assert len(set(ids)) == MAX_FEATURED_REVIEWS, 'a pick must not repeat as a filler'

    def test_never_exceeds_three(self, admin_client, api_client, test_user, test_category):
        for i in range(8):
            _review(test_user, _product(test_category, f'Many {i}'))
        assert api_client.get(FEATURED_URL).data['count'] == MAX_FEATURED_REVIEWS

    def test_returns_what_exists_when_store_has_fewer(self, api_client, test_user, test_product):
        _review(test_user, test_product)
        assert api_client.get(FEATURED_URL).data['count'] == 1

    def test_empty_store_returns_empty_strip(self, api_client):
        resp = api_client.get(FEATURED_URL)
        assert resp.status_code == 200
        assert resp.data['count'] == 0
        assert resp.data['results'] == []


@pytest.mark.django_db
class TestOptionalTitle:
    """The storefront presents the title as optional; the API must agree."""

    def test_missing_title_is_accepted(self, authenticated_client, test_product, delivered_order):
        resp = authenticated_client.post(BASE_URL, {
            'product': test_product.id, 'item_type': 'product',
            'rating': 4, 'comment': 'Good, but I have no headline for it.',
        }, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        assert resp.data['title'] == ''

    def test_blank_title_is_accepted(self, authenticated_client, test_product, delivered_order):
        resp = authenticated_client.post(BASE_URL, {
            'product': test_product.id, 'item_type': 'product',
            'rating': 4, 'title': '', 'comment': 'Blank title.',
        }, format='json')
        assert resp.status_code == status.HTTP_201_CREATED, resp.data

    def test_title_still_stored_when_supplied(self, authenticated_client, test_product, delivered_order):
        resp = authenticated_client.post(BASE_URL, {
            'product': test_product.id, 'item_type': 'product',
            'rating': 4, 'title': 'Excellent', 'comment': 'With a headline.',
        }, format='json')
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data['title'] == 'Excellent'


@pytest.mark.django_db
class TestReviewerDisplayName:
    """`user_name` must not publish the email-derived username."""

    def test_prefers_real_name(self, api_client, test_user, test_product):
        test_user.username = 'kaushaljain7000'
        test_user.first_name = 'Kaushal'
        test_user.last_name = 'Jain'
        if hasattr(test_user, 'name'):
            test_user.name = ''
        test_user.save()
        _review(test_user, test_product)

        resp = api_client.get(f'/api/reviews/?product={test_product.id}')
        assert resp.status_code == 200
        assert resp.data['results'][0]['user_name'] == 'Kaushal Jain'

    def test_falls_back_to_username_when_nameless(self, api_client, test_user, test_product):
        test_user.username = 'anon123'
        test_user.first_name = ''
        test_user.last_name = ''
        if hasattr(test_user, 'name'):
            test_user.name = ''
        test_user.save()
        _review(test_user, test_product)

        resp = api_client.get(f'/api/reviews/?product={test_product.id}')
        assert resp.data['results'][0]['user_name'] == 'anon123'
