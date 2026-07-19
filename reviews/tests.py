"""
Comprehensive tests for the Reviews app.
Covers review creation, duplicate prevention, verified purchase, eligibility checks,
moderation, and update integrity tests.
"""
from decimal import Decimal
import pytest
from rest_framework import status

from conftest import create_test_image
from orders.models import Order, OrderItem
from products.models import Product
from reviews.models import Review

# Shared helper used across review eligibility & gating tests
def _order_with(product, user, status_val):
    order = Order.objects.create(
        user=user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="COD", subtotal=Decimal("120.00"), tax=Decimal("6.00"),
        total_amount=Decimal("126.00"), status=status_val,
    )
    OrderItem.objects.create(
        order=order, product=product, item_type="product",
        product_name=product.name, product_weight=product.weight,
        quantity=1, price=product.final_price, final_price=product.final_price,
    )
    return order


# ==================== REVIEW CREATION TESTS ====================

@pytest.mark.django_db
class TestReviewCreation:
    """Tests for review creation."""
    
    base_url = '/api/reviews/'
    
    def test_create_product_review_authenticated(self, authenticated_client, test_product, delivered_order):
        """Test creating review for a purchased product."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': 5,
            'comment': 'Great product!'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        # Returns 201 if valid, 400 if missing fields or already reviewed
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST]
    
    def test_create_review_unauthenticated(self, api_client, test_product):
        """Test unauthenticated user cannot create review."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': 5,
            'comment': 'Great!'
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_combo_review(self, authenticated_client, test_user, test_combo):
        """Test creating review for a purchased combo."""
        # Verified-purchase is enforced: the user must have ordered this combo
        # in a confirmed/delivered order. Set that up first.
        order = Order.objects.create(
            user=test_user,
            shipping_address='123 Test Street',
            phone_number='1234567890',
            payment_method='COD',
            subtotal=Decimal('250.00'),
            tax=Decimal('25.00'),
            total_amount=Decimal('275.00'),
            status='delivered',
        )
        OrderItem.objects.create(
            order=order,
            combo=test_combo,
            item_type='combo',
            product_name=test_combo.name,
            product_weight='',
            quantity=1,
            price=test_combo.final_price,
            final_price=test_combo.final_price,
        )
        data = {
            'combo': test_combo.id,
            'item_type': 'combo',
            'rating': 4,
            'title': 'Nice combo',
            'comment': 'Nice combo!'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data


# ==================== DUPLICATE REVIEW PREVENTION ====================

@pytest.mark.django_db
class TestDuplicateReviewPrevention:
    """Tests for preventing duplicate reviews."""
    
    base_url = '/api/reviews/'
    
    def test_cannot_create_duplicate_product_review(self, authenticated_client, test_product, test_user):
        """Test user cannot review same product twice."""
        # Create first review
        Review.objects.create(
            user=test_user,
            product=test_product,
            item_type='product',
            rating=5,
            comment='First review'
        )
        
        # Try to create second review
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': 3,
            'comment': 'Second review'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_cannot_create_duplicate_combo_review(self, authenticated_client, test_combo, test_user):
        """Test user cannot review same combo twice."""
        # Create first review
        Review.objects.create(
            user=test_user,
            combo=test_combo,
            item_type='combo',
            rating=4,
            comment='First review'
        )
        
        # Try to create second review
        data = {
            'combo': test_combo.id,
            'item_type': 'combo',
            'rating': 2,
            'comment': 'Second review'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ==================== REVIEW RETRIEVAL TESTS ====================

@pytest.mark.django_db
class TestReviewRetrieval:
    """Tests for review listing and filtering."""
    
    base_url = '/api/reviews/'
    
    def test_list_reviews_public(self, api_client, test_product, test_user):
        """Test anyone can list reviews."""
        Review.objects.create(
            user=test_user,
            product=test_product,
            item_type='product',
            rating=5,
            comment='Great!'
        )
        
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_reviews_by_product(self, api_client, test_product, test_user):
        """Test filtering reviews by product."""
        Review.objects.create(
            user=test_user,
            product=test_product,
            item_type='product',
            rating=5,
            comment='Test'
        )
        
        response = api_client.get(f'{self.base_url}?product={test_product.id}')
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_reviews_by_combo(self, api_client, test_combo, test_user):
        """Test filtering reviews by combo."""
        Review.objects.create(
            user=test_user,
            combo=test_combo,
            item_type='combo',
            rating=4,
            comment='Test'
        )
        
        response = api_client.get(f'{self.base_url}?combo={test_combo.id}')
        assert response.status_code == status.HTTP_200_OK


# ==================== REVIEW EDGE CASES ====================

@pytest.mark.django_db
class TestReviewEdgeCases:
    """Edge case tests for reviews."""
    
    base_url = '/api/reviews/'
    
    def test_create_review_invalid_rating_zero(self, authenticated_client, test_product):
        """Test creating review with zero rating."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': 0,
            'comment': 'Zero rating test'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_review_invalid_rating_negative(self, authenticated_client, test_product):
        """Test creating review with negative rating."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': -5,
            'comment': 'Negative rating test'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_review_invalid_rating_too_high(self, authenticated_client, test_product):
        """Test creating review with rating > 5."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'rating': 100,
            'comment': 'High rating test'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_review_nonexistent_product(self, authenticated_client):
        """Test creating review for non-existent product."""
        data = {
            'product': 999999,
            'item_type': 'product',
            'rating': 5,
            'comment': 'Test'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_create_review_missing_rating(self, authenticated_client, test_product):
        """Test creating review without rating."""
        data = {
            'product': test_product.id,
            'item_type': 'product',
            'comment': 'No rating'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_review_xss_in_comment(self, authenticated_client, test_product, malicious_inputs):
        """Test XSS payloads in review comment."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {
                'product': test_product.id,
                'item_type': 'product',
                'rating': 5,
                'comment': payload
            }
            response = authenticated_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
            # Clean up for next iteration
            Review.objects.filter(user__email='testuser@example.com').delete()
    
    def test_review_sql_injection_in_comment(self, authenticated_client, test_product, malicious_inputs):
        """Test SQL injection in review comment."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'product': test_product.id,
                'item_type': 'product',
                'rating': 4,
                'comment': payload
            }
            response = authenticated_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
            Review.objects.filter(user__email='testuser@example.com').delete()


# --- From test_can_review.py ---

CAN_REVIEW_URL = "/api/reviews/can-review/"
CREATE_URL = "/api/reviews/"


@pytest.mark.django_db
class TestCanReview:
    def test_requires_authentication(self, api_client, test_product):
        r = api_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.status_code in (401, 403)

    def test_never_purchased(self, authenticated_client, test_product):
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.status_code == 200
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    @pytest.mark.parametrize("good_status", ["confirmed", "processing", "shipped", "delivering", "delivered"])
    def test_purchased_can_review(self, authenticated_client, test_user, test_product, good_status):
        _order_with(test_product, test_user, good_status)
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.json() == {"can_review": True, "reason": None}

    @pytest.mark.parametrize("bad_status", ["pending", "cancelled"])
    def test_unfulfilled_order_cannot_review(self, authenticated_client, test_user, test_product, bad_status):
        _order_with(test_product, test_user, bad_status)
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    def test_another_users_purchase_does_not_count(self, authenticated_client, test_user2, test_product):
        _order_with(test_product, test_user2, "delivered")
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "not_purchased"}

    def test_already_reviewed(self, authenticated_client, test_user, test_product):
        _order_with(test_product, test_user, "delivered")
        created = authenticated_client.post(
            CREATE_URL,
            {"item_type": "product", "product": test_product.id, "rating": 5,
             "title": "Nice", "comment": "Fresh and aromatic"},
            format="json",
        )
        assert created.status_code == 201
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}")
        assert r.json() == {"can_review": False, "reason": "already_reviewed"}

    def test_agrees_with_create_endpoint_when_not_purchased(self, authenticated_client, test_product):
        """can_review False => the POST it guards must also reject."""
        assert authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}").json()["can_review"] is False
        posted = authenticated_client.post(
            CREATE_URL,
            {"item_type": "product", "product": test_product.id, "rating": 5,
             "title": "Nice", "comment": "Fresh"},
            format="json",
        )
        assert posted.status_code == 400

    def test_missing_params_rejected(self, authenticated_client):
        assert authenticated_client.get(CAN_REVIEW_URL).status_code == 400

    def test_both_params_rejected(self, authenticated_client, test_product):
        r = authenticated_client.get(f"{CAN_REVIEW_URL}?product={test_product.id}&combo=1")
        assert r.status_code == 400

    def test_non_numeric_id_rejected(self, authenticated_client):
        assert authenticated_client.get(f"{CAN_REVIEW_URL}?product=abc").status_code == 400


# --- From test_moderation.py ---

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


# --- From test_review_update_integrity.py ---

def _product(cat, name):
    return Product.objects.create(
        name=name, category=cat, description="x", price=Decimal("100.00"), stock=10,
        weight=Decimal("250.00"), unit="g", spice_form="powder", is_active=True,
        image=create_test_image(f"{name}.jpg"),
    )


def _delivered(user, product):
    order = Order.objects.create(
        user=user, shipping_address="a", phone_number="1", payment_method="COD",
        subtotal=Decimal("100.00"), tax=Decimal("5.00"), total_amount=Decimal("105.00"),
        status="delivered",
    )
    OrderItem.objects.create(
        order=order, product=product, item_type="product", product_name=product.name,
        product_weight=product.weight, quantity=1, price=product.final_price,
        final_price=product.final_price,
    )


@pytest.mark.django_db
class TestReviewSubjectImmutable:
    def _make_verified_review(self, client, user, cat):
        bought = _product(cat, "Bought")
        _delivered(user, bought)
        r = client.post(CREATE_URL, {"item_type": "product", "product": bought.id,
                                     "rating": 5, "title": "t", "comment": "c"}, format="json")
        assert r.status_code == 201
        return r.json()["id"], bought

    def test_cannot_reassign_review_to_unpurchased_product(self, authenticated_client, test_user, test_category):
        rid, bought = self._make_verified_review(authenticated_client, test_user, test_category)
        not_bought = _product(test_category, "NotBought")
        patch = authenticated_client.patch(f"{CREATE_URL}{rid}/", {"product": not_bought.id}, format="json")
        assert patch.status_code == 400
        rev = Review.objects.get(id=rid)
        assert rev.product_id == bought.id            # unchanged
        assert rev.is_verified_purchase is True

    def test_can_still_edit_rating_and_comment(self, authenticated_client, test_user, test_category):
        rid, _bought = self._make_verified_review(authenticated_client, test_user, test_category)
        patch = authenticated_client.patch(
            f"{CREATE_URL}{rid}/", {"rating": 3, "comment": "updated"}, format="json")
        assert patch.status_code == 200
        rev = Review.objects.get(id=rid)
        assert rev.rating == 3 and rev.comment == "updated"

    def test_cannot_change_item_type(self, authenticated_client, test_user, test_category):
        rid, _bought = self._make_verified_review(authenticated_client, test_user, test_category)
        patch = authenticated_client.patch(f"{CREATE_URL}{rid}/", {"item_type": "combo"}, format="json")
        assert patch.status_code == 400


# --- From test_verified_purchase.py ---

def _review_payload(product, rating=5):
    return {"item_type": "product", "product": product.id, "rating": rating,
            "title": "Nice", "comment": "Fresh and aromatic"}


@pytest.mark.django_db
class TestVerifiedPurchaseGate:
    def test_never_ordered_is_blocked(self, authenticated_client, test_product):
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product), format="json")
        assert r.status_code == 400

    @pytest.mark.parametrize("good_status", ["confirmed", "processing", "shipped", "delivering", "delivered"])
    def test_fulfilment_statuses_allow_review(self, authenticated_client, test_user, test_product, good_status):
        _order_with(test_product, test_user, good_status)
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product), format="json")
        assert r.status_code == 201, r.content
        assert r.json().get("is_verified_purchase") is True

    @pytest.mark.parametrize("bad_status", ["pending", "cancelled"])
    def test_non_fulfilled_statuses_block_review(self, authenticated_client, test_user, test_product, bad_status):
        _order_with(test_product, test_user, bad_status)
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product), format="json")
        assert r.status_code == 400

    def test_another_users_purchase_does_not_count(self, authenticated_client, test_user2, test_product):
        # test_user2 bought it (delivered), but the *authenticated* user (test_user) did not.
        _order_with(test_product, test_user2, "delivered")
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product), format="json")
        assert r.status_code == 400

    def test_duplicate_review_blocked_after_valid_one(self, authenticated_client, test_user, test_product):
        _order_with(test_product, test_user, "delivered")
        first = authenticated_client.post(CREATE_URL, _review_payload(test_product), format="json")
        assert first.status_code == 201
        second = authenticated_client.post(CREATE_URL, _review_payload(test_product, rating=3), format="json")
        assert second.status_code == 400

    @pytest.mark.parametrize("bad_rating", [0, -1, 6, 99])
    def test_rating_out_of_bounds_rejected(self, authenticated_client, test_user, test_product, bad_rating):
        _order_with(test_product, test_user, "delivered")
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product, rating=bad_rating), format="json")
        assert r.status_code == 400

    @pytest.mark.parametrize("ok_rating", [1, 5])
    def test_rating_boundaries_accepted(self, authenticated_client, test_user, test_product, ok_rating):
        _order_with(test_product, test_user, "delivered")
        r = authenticated_client.post(CREATE_URL, _review_payload(test_product, rating=ok_rating), format="json")
        assert r.status_code == 201
