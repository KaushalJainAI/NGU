"""Tests for admin review moderation: the staff-only hide/show switch and the
public exclusion of hidden reviews (while the author still sees their own)."""
import pytest

from reviews.models import Review


def _review(user, product, hidden=False, rating=5):
    return Review.objects.create(
        item_type='product', product=product, user=user, rating=rating,
        title='Nice', comment='Good spice', is_verified_purchase=True,
        is_hidden=hidden,
    )


@pytest.mark.django_db
class TestReviewModeration:
    def test_staff_can_hide_and_show(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': True}, format='json')
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.is_hidden is True

        resp = admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': False}, format='json')
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.is_hidden is False

    def test_customer_cannot_moderate(self, authenticated_client, test_user, test_product):
        review = _review(test_user, test_product)
        resp = authenticated_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                         {'hidden': True}, format='json')
        assert resp.status_code == 403

    def test_bad_payload_rejected(self, admin_client, test_user, test_product):
        review = _review(test_user, test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-hidden/',
                                 {'hidden': 'yes'}, format='json')
        assert resp.status_code == 400

    def test_hidden_review_excluded_from_public_product_listing(
            self, api_client, test_user, test_product):
        _review(test_user, test_product, hidden=True)
        resp = api_client.get('/api/reviews/', {'product': test_product.id})
        assert resp.status_code == 200
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        assert results == []

    def test_hidden_review_visible_to_its_author(
            self, authenticated_client, test_user, test_product):
        _review(test_user, test_product, hidden=True)
        resp = authenticated_client.get('/api/reviews/', {'product': test_product.id})
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        assert len(results) == 1

    def test_admin_all_view_lists_hidden(self, admin_client, test_user, test_product):
        _review(test_user, test_product, hidden=True)
        resp = admin_client.get('/api/reviews/', {'all': 'true'})
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        assert len(results) == 1
        assert results[0]['is_hidden'] is True

    def test_hidden_reviews_excluded_from_product_rating(
            self, api_client, test_user, test_user2, test_product):
        # One visible 5-star, one hidden 1-star: the average must ignore the hidden.
        _review(test_user, test_product, hidden=False, rating=5)
        _review(test_user2, test_product, hidden=True, rating=1)
        resp = api_client.get(f'/api/products/{test_product.slug}/')
        assert resp.status_code == 200
        assert resp.data['average_rating'] == 5
        assert resp.data['reviews_count'] == 1
