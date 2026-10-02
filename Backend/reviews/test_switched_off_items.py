"""Reviews of a switched-off product or combo are not shown to shoppers.

Nothing is deleted or edited: the review is back the moment the item is. Authors
keep seeing their own, and staff see everything.
"""
import pytest

from products.models import Product, ProductCombo
from reviews.models import Review


def _rows(resp):
    data = resp.data
    return data['results'] if isinstance(data, dict) and 'results' in data else data


def _review(user, *, product=None, combo=None, rating=5, **extra):
    return Review.objects.create(
        user=user, rating=rating, comment='lovely', is_verified_purchase=True,
        item_type='combo' if combo else 'product', product=product, combo=combo, **extra)


def _off(product):
    Product.objects.filter(pk=product.pk).update(is_active=False)


def _on(product):
    Product.objects.filter(pk=product.pk).update(is_active=True)


@pytest.mark.django_db
class TestFeaturedStrip:
    def test_a_switched_off_products_review_leaves_the_strip_and_comes_back(
            self, api_client, test_user, test_user2, test_product, test_product2):
        mine = _review(test_user, product=test_product, is_featured=True)
        other = _review(test_user2, product=test_product2, is_featured=True)

        ids = [r['id'] for r in api_client.get('/api/reviews/featured/').data['results']]
        assert set(ids) == {mine.id, other.id}

        _off(test_product)
        ids = [r['id'] for r in api_client.get('/api/reviews/featured/').data['results']]
        assert mine.id not in ids and other.id in ids

        _on(test_product)
        ids = [r['id'] for r in api_client.get('/api/reviews/featured/').data['results']]
        assert mine.id in ids

    def test_the_freed_slot_is_topped_up_so_the_strip_stays_full(
            self, api_client, test_user, test_user2, test_product, test_product2):
        _review(test_user, product=test_product, is_featured=True)
        filler = _review(test_user2, product=test_product2, rating=4)
        _off(test_product)
        data = api_client.get('/api/reviews/featured/').data
        assert [r['id'] for r in data['results']] == [filler.id]
        assert data['count'] == 1

    def test_a_switched_off_combo_too(self, api_client, test_user, test_combo):
        review = _review(test_user, combo=test_combo, is_featured=True)
        ProductCombo.objects.filter(pk=test_combo.pk).update(is_active=False)
        assert review.id not in [r['id'] for r in api_client.get('/api/reviews/featured/').data['results']]

    def test_switching_off_through_the_panel_has_the_same_effect(
            self, api_client, admin_client, test_user, test_product):
        review = _review(test_user, product=test_product, is_featured=True)
        assert admin_client.patch(f'/api/products/{test_product.slug}/',
                                  {'is_active': False}, format='json').status_code == 200
        api_client.credentials()
        assert review.id not in [r['id'] for r in api_client.get('/api/reviews/featured/').data['results']]


@pytest.mark.django_db
class TestPublicList:
    def test_the_public_list_omits_it_and_shows_it_again_when_the_product_is_back(
            self, api_client, test_user, test_product):
        review = _review(test_user, product=test_product)
        url = f'/api/reviews/?product={test_product.id}'
        assert [r['id'] for r in _rows(api_client.get(url))] == [review.id]
        _off(test_product)
        assert _rows(api_client.get(url)) == []
        _on(test_product)
        assert [r['id'] for r in _rows(api_client.get(url))] == [review.id]

    def test_the_author_still_sees_their_own(self, authenticated_client, test_user, test_product):
        review = _review(test_user, product=test_product)
        _off(test_product)
        ids = [r['id'] for r in _rows(authenticated_client.get('/api/reviews/'))]
        assert review.id in ids

    def test_another_customer_does_not(self, authenticated_client_user2, test_user, test_product):
        review = _review(test_user, product=test_product)
        _off(test_product)
        got = authenticated_client_user2.get(f'/api/reviews/?product={test_product.id}')
        assert review.id not in [r['id'] for r in _rows(got)]

    def test_staff_see_everything(self, admin_client, test_user, test_product):
        review = _review(test_user, product=test_product)
        _off(test_product)
        got = admin_client.get('/api/reviews/?all=true')
        assert review.id in [r['id'] for r in _rows(got)]

    def test_nothing_is_deleted_or_edited(self, test_user, test_product):
        review = _review(test_user, product=test_product, is_featured=True)
        _off(test_product)
        _on(test_product)
        review.refresh_from_db()
        assert review.is_featured is True and review.is_hidden is False


@pytest.mark.django_db
class TestFeaturing:
    def test_a_review_of_a_switched_off_product_cannot_be_featured(
            self, admin_client, test_user, test_product):
        review = _review(test_user, product=test_product)
        _off(test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-featured/',
                                 {'featured': True}, format='json')
        assert resp.status_code == 400
        assert 'switched off' in resp.data['error']
        review.refresh_from_db()
        assert review.is_featured is False

    def test_unfeaturing_it_is_still_allowed(self, admin_client, test_user, test_product):
        review = _review(test_user, product=test_product, is_featured=True)
        _off(test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-featured/',
                                 {'featured': False}, format='json')
        assert resp.status_code == 200

    def test_a_live_product_can_still_be_featured(self, admin_client, test_user, test_product):
        review = _review(test_user, product=test_product)
        resp = admin_client.post(f'/api/reviews/{review.id}/set-featured/',
                                 {'featured': True}, format='json')
        assert resp.status_code == 200 and resp.data['is_featured'] is True
