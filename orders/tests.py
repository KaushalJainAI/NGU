"""
Comprehensive tests for the Orders app.
Covers order creation, cancellation, stock management, and authorization tests.
"""
import pytest
from decimal import Decimal
from rest_framework import status
from orders.models import Order, OrderItem
from products.models import Product


# ==================== ORDER CREATION TESTS ====================

@pytest.mark.django_db
class TestOrderCreation:
    """Tests for order creation endpoint."""
    
    base_url = '/api/orders/'
    
    def test_create_order_with_valid_cart(self, authenticated_client, cart_with_items, test_user):
        """Test creating order from cart with items."""
        data = {
            'shipping_address': '123 Test Street, Test City, Test State 123456',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify order was created
        assert Order.objects.filter(user=test_user).exists()
    
    def test_create_order_with_empty_cart(self, authenticated_client, test_cart):
        """Test creating order with empty cart fails."""
        # Ensure cart is empty
        test_cart.items.all().delete()
        
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_order_unauthenticated(self, api_client):
        """Test unauthenticated user cannot create order."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_order_with_coupon(self, authenticated_client, cart_with_items, test_coupon):
        """Test creating order with valid coupon."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD',
            'coupon_code': test_coupon.code
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_order_with_expired_coupon(self, authenticated_client, cart_with_items, expired_coupon):
        """Test creating order with expired coupon fails or ignores coupon."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD',
            'coupon_code': expired_coupon.code
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        # Should either reject or create order without coupon, not 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_order_with_invalid_coupon(self, authenticated_client, cart_with_items):
        """Test creating order with invalid coupon code."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD',
            'coupon_code': 'INVALIDCODE123'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_order_online_payment(self, authenticated_client, cart_with_items):
        """Test creating order with online payment."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'ONLINE'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED


# ==================== ORDER VALIDATION TESTS ====================

@pytest.mark.django_db
class TestOrderValidation:
    """Tests for order field validation."""
    
    base_url = '/api/orders/'
    
    def test_create_order_missing_shipping_address(self, authenticated_client, cart_with_items):
        """Test order fails without shipping address."""
        data = {
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_order_missing_phone(self, authenticated_client, cart_with_items):
        """Test order fails without phone number."""
        data = {
            'shipping_address': '123 Test Street',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_order_missing_payment_method(self, authenticated_client, cart_with_items):
        """Test order fails without payment method."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_order_invalid_payment_method(self, authenticated_client, cart_with_items):
        """Test order fails with invalid payment method."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'BITCOIN'  # Invalid
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_order_empty_body(self, authenticated_client, cart_with_items):
        """Test order fails with empty request body."""
        response = authenticated_client.post(self.base_url, {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ==================== ORDER LIST AND RETRIEVE TESTS ====================

@pytest.mark.django_db
class TestOrderListRetrieve:
    """Tests for order listing and retrieval."""
    
    base_url = '/api/orders/'
    
    def test_list_orders_authenticated(self, authenticated_client, test_order):
        """Test authenticated user can list their orders."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_orders_unauthenticated(self, api_client):
        """Test unauthenticated user cannot list orders."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_retrieve_order_detail(self, authenticated_client, test_order):
        """Test retrieving specific order details."""
        response = authenticated_client.get(f'{self.base_url}{test_order.id}/')
        assert response.status_code == status.HTTP_200_OK
        assert 'items' in response.data
    
    def test_retrieve_nonexistent_order(self, authenticated_client):
        """Test retrieving non-existent order returns 404."""
        response = authenticated_client.get(f'{self.base_url}999999/')
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============ LIST SCOPE: CUSTOMER SURFACE vs ADMIN SURFACE ============

@pytest.mark.django_db
class TestOrderListScope:
    """The order list serves two surfaces with different powers, chosen by the
    REQUEST (`?scope=all`) and not by the caller's is_staff flag.

    Regression: a staff account browsing the storefront used to be served the
    paginated all-customers admin table on /my-orders. The storefront expects a
    bare array, so it rendered "no orders" and the owner could not see an order
    they had just paid for — while the same response carried every customer's PII.
    """

    base_url = '/api/orders/'

    def test_staff_storefront_list_is_bare_array_of_own_orders_only(
        self, admin_client, test_admin, test_order, test_product,
    ):
        """A staff user with no admin params gets the CUSTOMER view: a bare array
        holding only their own orders. `test_order` belongs to `test_user`, so it
        must NOT appear."""
        from orders.models import Order
        own = Order.objects.create(
            user=test_admin, shipping_address='1 Admin Way', phone_number='555',
            payment_method='COD', subtotal=Decimal('10.00'),
            discount_amount=Decimal('0.00'), tax=Decimal('0.00'),
            total_amount=Decimal('10.00'), status='pending',
        )

        response = admin_client.get(self.base_url)

        assert response.status_code == status.HTTP_200_OK
        # Bare array — NOT a {count, results} envelope the storefront can't read.
        assert isinstance(response.data, list)
        assert [o['id'] for o in response.data] == [own.id]

    def test_admin_scope_returns_all_orders_paginated(
        self, admin_client, test_order,
    ):
        """`?scope=all` keeps the admin table exactly as the panel expects:
        every customer's orders, in a DRF pagination envelope."""
        response = admin_client.get(self.base_url, {'scope': 'all', 'page': 1})

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data) >= {'count', 'next', 'previous', 'results'}
        # test_order belongs to another user and must be visible to the admin.
        assert test_order.id in [o['id'] for o in response.data['results']]

    def test_customer_cannot_request_admin_scope(
        self, authenticated_client_user2, test_order,
    ):
        """A non-staff caller asking for the admin table is refused outright,
        rather than silently downgraded to an empty-looking customer list."""
        response = authenticated_client_user2.get(self.base_url, {'scope': 'all'})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_customer_with_stray_admin_param_still_gets_own_orders(
        self, authenticated_client, test_order,
    ):
        """The compat shim is staff-only: a customer sending `?page=1` gets their
        own orders, not a 403 and never someone else's."""
        response = authenticated_client.get(self.base_url, {'page': 1})
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert [o['id'] for o in response.data] == [test_order.id]

    def test_customer_list_unaffected_by_scope_change(
        self, authenticated_client, test_order,
    ):
        """The ordinary customer path still returns a bare array of own orders."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert [o['id'] for o in response.data] == [test_order.id]

    def test_legacy_admin_params_still_serve_admin_view(
        self, admin_client, test_order,
    ):
        """Compat shim: an admin build predating `scope=all` is recognised by its
        filter params, so the panel keeps working across the deploy gap."""
        response = admin_client.get(self.base_url, {'page': 1})
        assert response.status_code == status.HTTP_200_OK
        assert 'results' in response.data
        assert test_order.id in [o['id'] for o in response.data['results']]


# ==================== ORDER AUTHORIZATION TESTS (BOLA) ====================

@pytest.mark.django_db
class TestOrderAuthorization:
    """Authorization tests for orders - BOLA prevention."""
    
    base_url = '/api/orders/'
    
    def test_cannot_view_other_user_orders(self, authenticated_client_user2, test_order):
        """Test user cannot view another user's order list."""
        response = authenticated_client_user2.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        # Should be empty - not showing other user's orders
        orders = response.data if isinstance(response.data, list) else response.data.get('results', [])
        assert len(orders) == 0
    
    def test_cannot_retrieve_other_user_order(self, authenticated_client_user2, test_order):
        """Test user cannot retrieve another user's order details."""
        response = authenticated_client_user2.get(f'{self.base_url}{test_order.id}/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_cannot_cancel_other_user_order(self, authenticated_client_user2, test_order):
        """Test user cannot cancel another user's order."""
        response = authenticated_client_user2.post(f'{self.base_url}{test_order.id}/cancel/')
        assert response.status_code in [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND]


# ==================== ORDER CANCELLATION TESTS ====================

@pytest.mark.django_db
class TestOrderCancellation:
    """Tests for order cancellation functionality."""
    
    base_url = '/api/orders/'
    
    def test_cancel_pending_order(self, authenticated_client, test_order):
        """Test cancelling a pending order."""
        response = authenticated_client.post(f'{self.base_url}{test_order.id}/cancel/')
        assert response.status_code == status.HTTP_200_OK
        
        # Verify status changed
        test_order.refresh_from_db()
        assert test_order.status == 'cancelled'
    
    def test_cancel_already_cancelled_order(self, authenticated_client, test_order):
        """Test cancelling already cancelled order."""
        test_order.status = 'cancelled'
        test_order.save()
        
        response = authenticated_client.post(f'{self.base_url}{test_order.id}/cancel/')
        # Should fail gracefully
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_cancel_delivered_order(self, authenticated_client, test_order):
        """Test cancelling delivered order fails."""
        test_order.status = 'delivered'
        test_order.save()
        
        response = authenticated_client.post(f'{self.base_url}{test_order.id}/cancel/')
        # Should reject - can't cancel delivered order
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_cancel_nonexistent_order(self, authenticated_client):
        """Test cancelling non-existent order fails."""
        response = authenticated_client.post(f'{self.base_url}999999/cancel/')
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ==================== STOCK MANAGEMENT TESTS ====================

@pytest.mark.django_db
class TestStockManagement:
    """Tests for stock management during order lifecycle."""
    
    base_url = '/api/orders/'
    
    def test_stock_reduced_on_order_creation(self, authenticated_client, test_cart, test_product):
        """Test product stock is reduced when order is created."""
        from cart.models import CartItem
        
        initial_stock = test_product.stock
        quantity = 2
        
        # Add product to cart
        CartItem.objects.create(
            cart=test_cart,
            product=test_product,
            item_type='product',
            quantity=quantity
        )
        
        # Create order
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        
        # Verify stock reduced
        test_product.refresh_from_db()
        assert test_product.stock == initial_stock - quantity
    
    def test_stock_restored_on_order_cancellation(self, authenticated_client, test_order, test_product):
        """Test product stock is restored when order is cancelled."""
        initial_stock = test_product.stock
        order_item = test_order.items.first()
        ordered_quantity = order_item.quantity
        
        # Cancel order
        response = authenticated_client.post(f'{self.base_url}{test_order.id}/cancel/')
        assert response.status_code == status.HTTP_200_OK
        
        # Verify stock restored
        test_product.refresh_from_db()
        assert test_product.stock == initial_stock + ordered_quantity


# ==================== ORDER EDGE CASES ====================

@pytest.mark.django_db
class TestOrderEdgeCases:
    """Edge case tests for orders."""
    
    base_url = '/api/orders/'
    
    def test_order_with_oversized_address(self, authenticated_client, cart_with_items, malicious_inputs):
        """Test order with oversized shipping address."""
        data = {
            'shipping_address': malicious_inputs.OVERSIZED_STRING[:500],  # Truncate
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_with_special_chars_in_address(self, authenticated_client, cart_with_items):
        """Test order with special characters in address."""
        data = {
            'shipping_address': '123 Main St. #Apt-5, (Near Park), City & State <test>',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_with_unicode_address(self, authenticated_client, cart_with_items):
        """Test order with Unicode characters in address."""
        data = {
            'shipping_address': '123 मुख्य मार्ग, テスト市',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_with_invalid_phone_format(self, authenticated_client, cart_with_items):
        """Test order with invalid phone format."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': 'not-a-phone',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        # Should either reject or sanitize, not 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_with_very_long_phone(self, authenticated_client, cart_with_items):
        """Test order with very long phone number."""
        data = {
            'shipping_address': '123 Test Street',
            'phone_number': '1' * 100,
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== ORDER SECURITY TESTS ====================

@pytest.mark.django_db
class TestOrderSecurity:
    """Security tests for order operations."""
    
    base_url = '/api/orders/'
    
    def test_order_sql_injection_in_address(self, authenticated_client, cart_with_items, malicious_inputs):
        """Test SQL injection in shipping address."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'shipping_address': payload,
                'phone_number': '1234567890',
                'payment_method': 'COD'
            }
            response = authenticated_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_xss_in_address(self, authenticated_client, cart_with_items, malicious_inputs):
        """Test XSS payloads in shipping address."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {
                'shipping_address': payload,
                'phone_number': '1234567890',
                'payment_method': 'COD'
            }
            response = authenticated_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_order_path_traversal_in_address(self, authenticated_client, cart_with_items):
        """Test path traversal attempt in address."""
        data = {
            'shipping_address': '../../etc/passwd',
            'phone_number': '1234567890',
            'payment_method': 'COD'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== COUPON VALIDATION IN ORDER ====================

@pytest.mark.django_db
class TestOrderCouponValidation:
    """Tests for coupon validation during order creation."""
    
    base_url = '/api/orders/'
    validate_url = '/api/orders/validate_coupon/'
    
    def test_validate_coupon_endpoint(self, authenticated_client, test_coupon):
        """Test validate coupon endpoint."""
        data = {'coupon_code': test_coupon.code}
        response = authenticated_client.post(self.validate_url, data, format='json')
        # Returns 200 if valid, 400/404 if not found or invalid
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_validate_invalid_coupon(self, authenticated_client):
        """Test validate invalid coupon."""
        data = {'coupon_code': 'INVALID123'}
        response = authenticated_client.post(self.validate_url, data, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    
    def test_validate_coupon_sql_injection(self, authenticated_client, malicious_inputs):
        """Test SQL injection in coupon validation."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {'coupon_code': payload}
            response = authenticated_client.post(self.validate_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
