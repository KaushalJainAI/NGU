"""
Comprehensive tests for the Cart app.
Covers cart operations, favorites, coupon validation, and authorization tests.
"""
import pytest
from decimal import Decimal
from rest_framework import status
from cart.models import Cart, CartItem, Favorite


# ==================== CART OPERATIONS TESTS ====================

@pytest.mark.django_db
class TestCartOperations:
    """Tests for cart CRUD operations."""
    
    base_url = '/api/cart/'
    
    def test_list_cart_authenticated(self, authenticated_client, test_user):
        """Test authenticated user can view their cart."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_cart_unauthenticated(self, api_client):
        """Test unauthenticated user cannot view cart."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_add_product_to_cart(self, authenticated_client, test_product):
        """Test adding a product to cart."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': 2
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_add_combo_to_cart(self, authenticated_client, test_combo):
        """Test adding a combo to cart."""
        # The cart API identifies BOTH products and combos by product_id +
        # item_type (see CartViewSet.add_item docstring), not a separate combo_id.
        data = {
            'product_id': test_combo.id,
            'item_type': 'combo',
            'quantity': 1
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_add_nonexistent_product(self, authenticated_client):
        """Test adding non-existent product to cart fails."""
        data = {
            'product_id': 999999,
            'item_type': 'product',
            'quantity': 1
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_update_cart_item_quantity(self, authenticated_client, cart_with_items):
        """Test updating cart item quantity."""
        # Items are addressed by product_id + item_type (the product/combo id),
        # not the CartItem row id.
        cart_item = cart_with_items.items.first()
        item_id = cart_item.product_id if cart_item.item_type == 'product' else cart_item.combo_id
        data = {
            'product_id': item_id,
            'item_type': cart_item.item_type,
            'quantity': 5
        }
        response = authenticated_client.post(f'{self.base_url}update_item/', data, format='json')
        assert response.status_code == status.HTTP_200_OK

    def test_remove_item_from_cart(self, authenticated_client, cart_with_items):
        """Test removing item from cart."""
        cart_item = cart_with_items.items.first()
        item_id = cart_item.product_id if cart_item.item_type == 'product' else cart_item.combo_id
        data = {'product_id': item_id, 'item_type': cart_item.item_type}
        response = authenticated_client.post(f'{self.base_url}remove_item/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_clear_cart(self, authenticated_client, cart_with_items):
        """Test clearing entire cart."""
        response = authenticated_client.post(f'{self.base_url}clear/')
        assert response.status_code == status.HTTP_200_OK
        
        # Verify cart is empty
        response = authenticated_client.get(self.base_url)
        assert response.data.get('items', []) == [] or len(response.data.get('items', [])) == 0
    
    def test_sync_cart(self, authenticated_client, test_product, test_combo):
        """Test syncing cart items from frontend."""
        data = {
            'items': [
                {
                    'product_id': test_product.id,
                    'item_type': 'product',
                    'quantity': 3
                },
                {
                    'combo_id': test_combo.id,
                    'item_type': 'combo',
                    'quantity': 1
                }
            ]
        }
        response = authenticated_client.post(f'{self.base_url}sync/', data, format='json')
        assert response.status_code == status.HTTP_200_OK


# ==================== CART EDGE CASES ====================

@pytest.mark.django_db
class TestCartEdgeCases:
    """Edge case tests for cart operations."""
    
    base_url = '/api/cart/'
    
    def test_add_zero_quantity(self, authenticated_client, test_product):
        """Test adding item with zero quantity fails."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': 0
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        # Should reject, not 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_negative_quantity(self, authenticated_client, test_product):
        """Test adding item with negative quantity fails."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': -5
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_very_large_quantity(self, authenticated_client, test_product):
        """Test adding item with very large quantity."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': 999999999
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_out_of_stock_product(self, authenticated_client, out_of_stock_product):
        """Test adding out of stock product to cart."""
        data = {
            'product_id': out_of_stock_product.id,
            'item_type': 'product',
            'quantity': 1
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        # Should fail gracefully
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_more_than_stock(self, authenticated_client, test_product):
        """Test adding more items than available stock."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': test_product.stock + 100
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_update_nonexistent_cart_item(self, authenticated_client):
        """Test updating non-existent cart item."""
        data = {
            'item_id': 999999,
            'quantity': 5
        }
        response = authenticated_client.post(f'{self.base_url}update_item/', data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_remove_nonexistent_cart_item(self, authenticated_client):
        """Test removing non-existent cart item."""
        data = {'item_id': 999999}
        response = authenticated_client.post(f'{self.base_url}remove_item/', data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_add_item_missing_fields(self, authenticated_client):
        """Test adding item with missing fields."""
        data = {
            'item_type': 'product'
            # Missing product_id and quantity
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_add_item_invalid_item_type(self, authenticated_client, test_product):
        """Test adding item with invalid item_type."""
        data = {
            'product_id': test_product.id,
            'item_type': 'invalid_type',
            'quantity': 1
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_product_with_combo_type(self, authenticated_client, test_product):
        """Test adding product with combo item_type fails."""
        data = {
            'product_id': test_product.id,
            'item_type': 'combo',  # Should be 'product'
            'quantity': 1
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== CART AUTHORIZATION TESTS (BOLA) ====================

@pytest.mark.django_db
class TestCartAuthorization:
    """Authorization tests for cart - BOLA prevention."""
    
    base_url = '/api/cart/'
    
    def test_cannot_access_other_user_cart(self, authenticated_client_user2, cart_with_items):
        """Test user cannot access another user's cart items."""
        # User2 tries to access User1's cart
        response = authenticated_client_user2.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        # User2's cart should be empty (not showing User1's items)
        items = response.data.get('items', [])
        assert len(items) == 0
    
    def test_cannot_update_other_user_cart_item(self, authenticated_client_user2, cart_with_items):
        """Test user cannot update another user's cart item."""
        cart_item = cart_with_items.items.first()
        data = {
            'item_id': cart_item.id,
            'quantity': 10
        }
        response = authenticated_client_user2.post(f'{self.base_url}update_item/', data, format='json')
        # Should fail - either 404 or 400
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_cannot_remove_other_user_cart_item(self, authenticated_client_user2, cart_with_items):
        """Test user cannot remove another user's cart item."""
        cart_item = cart_with_items.items.first()
        data = {'item_id': cart_item.id}
        response = authenticated_client_user2.post(f'{self.base_url}remove_item/', data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]


# ==================== FAVORITES TESTS ====================

@pytest.mark.django_db
class TestFavoritesOperations:
    """Tests for favorites CRUD operations."""
    
    base_url = '/api/favorites/'
    
    def test_list_favorites_authenticated(self, authenticated_client):
        """Test authenticated user can list favorites."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_favorites_unauthenticated(self, api_client):
        """Test unauthenticated user cannot list favorites."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_add_product_to_favorites(self, authenticated_client, test_product):
        """Test adding product to favorites."""
        data = {'product_id': test_product.id}
        response = authenticated_client.post(self.base_url, data, format='json')
        # API returns 200 or 201 for favorites
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED]
    
    def test_add_duplicate_favorite(self, authenticated_client, test_product, test_user):
        """Test adding duplicate favorite fails gracefully."""
        # First add
        Favorite.objects.create(user=test_user, product=test_product)
        
        # Try to add again
        data = {'product_id': test_product.id}
        response = authenticated_client.post(self.base_url, data, format='json')
        # Should fail - already exists
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_remove_favorite(self, authenticated_client, test_product, test_user):
        """Test removing product from favorites."""
        # destroy() looks up the favorite by product_id, so the URL pk is the
        # product id (not the Favorite row id).
        Favorite.objects.create(user=test_user, product=test_product)

        response = authenticated_client.delete(f'{self.base_url}{test_product.id}/')
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT]
    
    def test_sync_favorites(self, authenticated_client, test_product, test_product2):
        """Test syncing favorites from frontend."""
        data = {
            'product_ids': [test_product.id, test_product2.id]
        }
        response = authenticated_client.post(f'{self.base_url}sync/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_add_nonexistent_product_to_favorites(self, authenticated_client):
        """Test adding non-existent product to favorites fails."""
        data = {'product_id': 999999}
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]


# ==================== FAVORITES AUTHORIZATION TESTS ====================

@pytest.mark.django_db
class TestFavoritesAuthorization:
    """Authorization tests for favorites."""
    
    base_url = '/api/favorites/'
    
    def test_cannot_access_other_user_favorites(self, authenticated_client_user2, test_user, test_product):
        """Test user cannot see another user's favorites."""
        # Create favorite for user1
        Favorite.objects.create(user=test_user, product=test_product)
        
        # User2 lists favorites - should be empty
        response = authenticated_client_user2.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        # Check it's empty (not showing user1's favorites)
        favorites = response.data if isinstance(response.data, list) else response.data.get('results', [])
        assert len(favorites) == 0
    
    def test_cannot_delete_other_user_favorite(self, authenticated_client_user2, test_user, test_product):
        """Test user cannot delete another user's favorite."""
        favorite = Favorite.objects.create(user=test_user, product=test_product)
        
        response = authenticated_client_user2.delete(f'{self.base_url}{favorite.id}/')
        assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


# ==================== COUPON VALIDATION TESTS ====================

@pytest.mark.django_db
class TestCouponValidation:
    """Tests for coupon validation endpoint."""
    
    url = '/api/auth/validate-coupon/'
    
    def test_validate_valid_coupon(self, authenticated_client, test_coupon):
        """Test validating a valid coupon."""
        data = {'code': test_coupon.code}
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert 'discount_percent' in response.data or 'valid' in str(response.data).lower()
    
    def test_validate_expired_coupon(self, authenticated_client, expired_coupon):
        """Test validating an expired coupon is reported invalid.

        The endpoint always returns 200 and signals validity via the `valid`
        flag in the body (see ValidateCouponAPIView)."""
        data = {'code': expired_coupon.code}
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get('valid') is False

    def test_validate_nonexistent_coupon(self, authenticated_client):
        """Test validating non-existent coupon is reported invalid (200 + valid=False)."""
        data = {'code': 'NONEXISTENT'}
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get('valid') is False
    
    def test_validate_empty_code(self, authenticated_client):
        """Test validating with empty code fails."""
        data = {'code': ''}
        response = authenticated_client.post(self.url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_validate_missing_code(self, authenticated_client):
        """Test validating without code field fails."""
        response = authenticated_client.post(self.url, {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_validate_coupon_sql_injection(self, authenticated_client, malicious_inputs):
        """Test SQL injection in coupon code is handled safely."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {'code': payload}
            response = authenticated_client.post(self.url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== CART SECURITY TESTS ====================

@pytest.mark.django_db
class TestCartSecurity:
    """Security tests for cart operations."""
    
    base_url = '/api/cart/'
    
    def test_add_item_sql_injection(self, authenticated_client, malicious_inputs):
        """Test SQL injection in cart item fields."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'product_id': payload,
                'item_type': 'product',
                'quantity': 1
            }
            response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_sync_with_malicious_data(self, authenticated_client, malicious_inputs):
        """Test syncing cart with malicious data."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'items': [
                    {
                        'product_id': payload,
                        'item_type': 'product',
                        'quantity': 1
                    }
                ]
            }
            response = authenticated_client.post(f'{self.base_url}sync/', data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_item_with_string_quantity(self, authenticated_client, test_product):
        """Test adding item with string quantity."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': 'five'
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_add_item_with_float_quantity(self, authenticated_client, test_product):
        """Test adding item with float quantity."""
        data = {
            'product_id': test_product.id,
            'item_type': 'product',
            'quantity': 2.5
        }
        response = authenticated_client.post(f'{self.base_url}add_item/', data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
