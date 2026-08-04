"""
Shared pytest fixtures and test utilities for the Django backend test suite.
Provides reusable fixtures for authentication, model creation, and API testing.
"""
import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


# ==================== TEST ISOLATION ====================

@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the cache around every test.

    DRF throttles store request counts in the cache. Without this, counters
    accumulate across tests in a run, so e.g. the 4th registration test trips
    the '3/minute' limit and gets a 429 instead of the status under test. This
    isolates each test (and also clears any cached search corpus / sections)."""
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()


# ==================== CLIENT FIXTURES ====================

@pytest.fixture
def api_client():
    """Returns an unauthenticated API client."""
    return APIClient()


@pytest.fixture
def test_user(db):
    """Creates and returns a regular test user."""
    user = User.objects.create_user(
        username='testuser',
        email='testuser@example.com',
        password='TestPass123!',
        first_name='Test',
        last_name='User',
        phone='1234567890',
        address='123 Test Street',
        city='Test City',
        state='Test State',
        pincode='123456'
    )
    return user


@pytest.fixture
def test_user2(db):
    """Creates and returns a second test user for authorization tests."""
    user = User.objects.create_user(
        username='testuser2',
        email='testuser2@example.com',
        password='TestPass123!',
        first_name='Another',
        last_name='User',
        phone='0987654321'
    )
    return user


@pytest.fixture
def test_admin(db):
    """Creates and returns an admin/superuser."""
    admin = User.objects.create_superuser(
        username='admin',
        email='admin@example.com',
        password='AdminPass123!',
        first_name='Admin',
        last_name='User'
    )
    return admin


@pytest.fixture
def authenticated_client(api_client, test_user):
    """Returns an API client authenticated as a regular user."""
    refresh = RefreshToken.for_user(test_user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return api_client


@pytest.fixture
def authenticated_client_user2(api_client, test_user2):
    """Returns an API client authenticated as second user (for BOLA tests)."""
    client = APIClient()
    refresh = RefreshToken.for_user(test_user2)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return client


@pytest.fixture
def admin_client(api_client, test_admin):
    """Returns an API client authenticated as admin."""
    refresh = RefreshToken.for_user(test_admin)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return api_client


# ==================== PRODUCT FIXTURES ====================

@pytest.fixture
def test_category(db):
    """Creates and returns a test category."""
    from products.models import Category
    category = Category.objects.create(
        name='Test Spices',
        description='Test category for spices',
        is_active=True
    )
    return category


def create_test_image(name='test.jpg'):
    """Creates a mock image file for testing."""
    # 1x1 pixel JPEG image
    image_content = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\'  ,01444\x1f\'9telerik`9444;\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18\r\r\x184;,;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xfb\xd2\x8a(\x00\xff\xd9'
    return SimpleUploadedFile(
        name=name,
        content=image_content,
        content_type='image/jpeg'
    )


@pytest.fixture
def test_product(db, test_category):
    """Creates and returns a test product."""
    from products.models import Product
    product = Product.objects.create(
        name='Test Turmeric Powder',
        category=test_category,
        description='Premium quality turmeric powder',
        price=Decimal('150.00'),
        discount_price=Decimal('120.00'),
        stock=100,
        weight=Decimal('250.00'),
        unit='g',
        spice_form='powder',
        is_active=True,
        is_featured=True,
        image=create_test_image('turmeric.jpg')
    )
    return product


@pytest.fixture
def test_product2(db, test_category):
    """Creates and returns a second test product."""
    from products.models import Product
    product = Product.objects.create(
        name='Test Cumin Seeds',
        category=test_category,
        description='Premium quality cumin seeds',
        price=Decimal('200.00'),
        stock=50,
        weight=Decimal('500.00'),
        unit='g',
        spice_form='whole',
        is_active=True,
        image=create_test_image('cumin.jpg')
    )
    return product


@pytest.fixture
def out_of_stock_product(db, test_category):
    """Creates and returns an out of stock product."""
    from products.models import Product
    product = Product.objects.create(
        name='Out of Stock Spice',
        category=test_category,
        description='This product is out of stock',
        price=Decimal('100.00'),
        stock=0,
        weight=Decimal('100.00'),
        unit='g',
        spice_form='powder',
        is_active=True,
        image=create_test_image('outofstock.jpg')
    )
    return product


@pytest.fixture
def test_combo(db, test_product, test_product2):
    """Creates and returns a test combo with products."""
    from products.models import ProductCombo, ProductComboItem
    combo = ProductCombo.objects.create(
        name='Test Combo Pack',
        description='A combo of test products',
        discount_price=Decimal('250.00'),
        is_active=True,
        is_featured=True
    )
    # Add products to combo. There is no `price` to set: the MRP is DERIVED from
    # these components — 150 + 200 = ₹350 — and the combo sells for 250.
    ProductComboItem.objects.create(combo=combo, product=test_product, quantity=1)
    ProductComboItem.objects.create(combo=combo, product=test_product2, quantity=1)
    return combo


# ==================== CART FIXTURES ====================

@pytest.fixture
def test_cart(db, test_user):
    """Creates and returns a cart for the test user."""
    from cart.models import Cart
    cart, _ = Cart.objects.get_or_create(user=test_user)
    return cart


@pytest.fixture
def cart_with_items(db, test_cart, test_product, test_combo):
    """Creates a cart with both product and combo items."""
    from cart.models import CartItem
    CartItem.objects.create(
        cart=test_cart,
        product=test_product,
        item_type='product',
        quantity=2
    )
    CartItem.objects.create(
        cart=test_cart,
        combo=test_combo,
        item_type='combo',
        quantity=1
    )
    return test_cart


# ==================== ORDER FIXTURES ====================

@pytest.fixture
def test_order(db, test_user, test_product):
    """Creates and returns a test order."""
    from orders.models import Order, OrderItem
    order = Order.objects.create(
        user=test_user,
        shipping_address='123 Test Street, Test City',
        phone_number='1234567890',
        payment_method='COD',
        subtotal=Decimal('240.00'),
        discount_amount=Decimal('0.00'),
        tax=Decimal('24.00'),
        total_amount=Decimal('264.00'),
        status='pending'
    )
    OrderItem.objects.create(
        order=order,
        product=test_product,
        item_type='product',
        product_name=test_product.name,
        product_weight=test_product.weight,
        quantity=2,
        price=test_product.final_price,
        final_price=test_product.final_price * 2
    )
    return order


# ==================== COUPON FIXTURES ====================

@pytest.fixture
def test_coupon(db):
    """Creates and returns a valid test coupon."""
    from admin_panel.models import Coupon
    from django.utils import timezone
    from datetime import timedelta
    
    coupon = Coupon.objects.create(
        code='TESTCOUPON10',
        discount_percent=10,
        is_active=True,
        valid_until=timezone.now() + timedelta(days=30)
    )
    return coupon


@pytest.fixture
def expired_coupon(db):
    """Creates and returns an expired coupon."""
    from admin_panel.models import Coupon
    from django.utils import timezone
    from datetime import timedelta
    
    coupon = Coupon.objects.create(
        code='EXPIREDCOUPON',
        discount_percent=20,
        is_active=True,
        valid_until=timezone.now() - timedelta(days=1)
    )
    return coupon


# ==================== PAYMENT FIXTURES ====================

@pytest.fixture
def test_payment_method(db, test_user):
    """Creates and returns a payment method for test user."""
    from payments.models import PaymentMethod
    payment_method = PaymentMethod.objects.create(
        user=test_user,
        payment_type='UPI',
        upi_id='testuser@upi',
        is_default=True,
        is_active=True
    )
    return payment_method


# ==================== REVIEW FIXTURES ====================

@pytest.fixture
def delivered_order(db, test_user, test_product):
    """Creates a delivered order for verified purchase tests."""
    from orders.models import Order, OrderItem
    order = Order.objects.create(
        user=test_user,
        shipping_address='123 Test Street',
        phone_number='1234567890',
        payment_method='COD',
        subtotal=Decimal('120.00'),
        tax=Decimal('12.00'),
        total_amount=Decimal('132.00'),
        status='delivered'
    )
    OrderItem.objects.create(
        order=order,
        product=test_product,
        item_type='product',
        product_name=test_product.name,
        product_weight=test_product.weight,
        quantity=1,
        price=test_product.final_price,
        final_price=test_product.final_price
    )
    return order


# ==================== MALICIOUS INPUT HELPERS ====================

class MaliciousInputs:
    """Collection of malicious inputs for security testing."""
    
    # SQL Injection attempts
    SQL_INJECTION = [
        "'; DROP TABLE users; --",
        "1' OR '1'='1",
        "1; SELECT * FROM users",
        "admin'--",
        "' UNION SELECT * FROM users--",
    ]
    
    # XSS attempts
    XSS_PAYLOADS = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "javascript:alert('XSS')",
        "<svg onload=alert('XSS')>",
        "'\"><script>alert('XSS')</script>",
    ]
    
    # Oversized payloads
    OVERSIZED_STRING = "A" * 100000
    
    # Special characters
    SPECIAL_CHARS = [
        "!@#$%^&*()_+-=[]{}|;':\",./<>?",
        "\x00\x01\x02\x03",  # Null bytes
        "../../etc/passwd",  # Path traversal
        "\n\r\t",  # Control characters
    ]
    
    # Unicode edge cases
    UNICODE_EDGE_CASES = [
        "مرحبا",  # Arabic
        "こんにちは",  # Japanese
        "🔥🌶️",  # Emojis
        "\u202e\u0041\u0042\u0043",  # Right-to-left override
    ]
    
    # Numeric edge cases
    NUMERIC_EDGE_CASES = {
        'negative': -1,
        'zero': 0,
        'very_large': 999999999999,
        'float_string': '1.5',
        'nan': float('nan'),
    }


@pytest.fixture
def malicious_inputs():
    """Provides access to malicious input test data."""
    return MaliciousInputs()
