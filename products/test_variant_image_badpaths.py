"""Bad-path coverage for the two 🔴/🟠 product routes flagged in docs/API.md
as having happy-path tests only (or none at all):

  * /api/product-variants/  — variants carry the price and stock customers
    actually buy, so permission and validation failures matter as much as the
    happy path.
  * /api/product-images/    — untested multipart upload to Cloudinary; gained
    size/content-type validation on 2026-07-25.
"""
import random
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from conftest import create_test_image
from products.models import ProductVariant

VARIANTS_URL = '/api/product-variants/'
IMAGES_URL = '/api/product-images/'


@pytest.fixture
def variant(db, test_product):
    return ProductVariant.objects.create(
        product=test_product, weight=Decimal('100.00'), unit='g',
        price=Decimal('150.00'), stock=10, is_default=True,
    )


# ==================== VARIANT PERMISSIONS ====================

@pytest.mark.django_db
class TestVariantPermissions:
    def test_anonymous_cannot_create(self, api_client, test_product):
        r = api_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '99.00', 'stock': 5,
        }, format='json')
        assert r.status_code in (401, 403)
        assert not ProductVariant.objects.filter(price=Decimal('99.00')).exists()

    def test_regular_user_cannot_create(self, authenticated_client, test_product):
        r = authenticated_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '99.00', 'stock': 5,
        }, format='json')
        assert r.status_code == 403
        assert not ProductVariant.objects.filter(price=Decimal('99.00')).exists()

    def test_regular_user_cannot_edit_price(self, authenticated_client, variant):
        r = authenticated_client.patch(
            f'{VARIANTS_URL}{variant.id}/', {'price': '1.00'}, format='json')
        assert r.status_code == 403
        variant.refresh_from_db()
        assert variant.price == Decimal('150.00')

    def test_regular_user_cannot_delete(self, authenticated_client, variant):
        r = authenticated_client.delete(f'{VARIANTS_URL}{variant.id}/')
        assert r.status_code == 403
        assert ProductVariant.objects.filter(id=variant.id).exists()

    def test_anonymous_can_read(self, api_client, variant):
        assert api_client.get(VARIANTS_URL).status_code == 200


# ==================== VARIANT VALIDATION ====================

@pytest.mark.django_db
class TestVariantValidation:
    def test_negative_price_rejected(self, admin_client, test_product):
        r = admin_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '-10.00', 'stock': 5,
        }, format='json')
        assert r.status_code == 400
        assert 'price' in r.json()['details']

    def test_negative_stock_rejected(self, admin_client, test_product):
        r = admin_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '10.00', 'stock': -5,
        }, format='json')
        assert r.status_code == 400
        assert 'stock' in r.json()['details']

    def test_discount_not_below_price_rejected(self, admin_client, test_product):
        r = admin_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '100.00',
            'discount_price': '150.00', 'stock': 5,
        }, format='json')
        assert r.status_code == 400
        assert 'discount_price' in r.json()['details']

    def test_discount_equal_to_price_rejected(self, admin_client, test_product):
        r = admin_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '100.00',
            'discount_price': '100.00', 'stock': 5,
        }, format='json')
        assert r.status_code == 400

    def test_missing_product_rejected(self, admin_client):
        r = admin_client.post(VARIANTS_URL, {'price': '10.00', 'stock': 5}, format='json')
        assert r.status_code == 400

    def test_nonexistent_product_rejected(self, admin_client):
        r = admin_client.post(VARIANTS_URL, {
            'product': 999999, 'price': '10.00', 'stock': 5,
        }, format='json')
        assert r.status_code == 400

    def test_slug_is_read_only(self, admin_client, variant):
        r = admin_client.patch(
            f'{VARIANTS_URL}{variant.id}/', {'slug': 'attacker-chosen'}, format='json')
        assert r.status_code == 200
        variant.refresh_from_db()
        assert variant.slug != 'attacker-chosen'


@pytest.mark.django_db
class TestVariantDefaultHandling:
    def test_new_default_unsets_previous(self, admin_client, test_product, variant):
        assert variant.is_default is True
        r = admin_client.post(VARIANTS_URL, {
            'product': test_product.id, 'price': '250.00', 'stock': 5,
            'weight': '500.00', 'unit': 'g', 'is_default': True,
        }, format='json')
        assert r.status_code == 201

        variant.refresh_from_db()
        assert variant.is_default is False
        assert ProductVariant.objects.filter(
            product=test_product, is_default=True).count() == 1


@pytest.mark.django_db
class TestVariantDelete:
    def test_variant_used_by_order_is_deactivated_not_deleted(
        self, admin_client, variant, test_user
    ):
        """DELETE must never orphan order history — it retires the row instead."""
        from orders.models import Order, OrderItem
        # A sibling so the "last active size" guard isn't what's under test here.
        ProductVariant.objects.create(
            product=variant.product, price=Decimal('99.00'), stock=5,
            weight=Decimal('250.00'), unit='g', is_active=True,
        )
        order = Order.objects.create(
            user=test_user, shipping_address='123 Test St', phone_number='1234567890',
            payment_method='COD', subtotal=Decimal('150.00'), tax=Decimal('15.00'),
            total_amount=Decimal('165.00'), status='delivered',
        )
        OrderItem.objects.create(
            order=order, product=variant.product, variant=variant,
            item_type='product', product_name=variant.product.name,
            product_weight=variant.weight, quantity=1,
            price=variant.price, final_price=variant.price,
        )

        r = admin_client.delete(f'{VARIANTS_URL}{variant.id}/')

        assert r.status_code == 200
        variant.refresh_from_db()
        assert variant.is_active is False
        assert variant.is_default is False

    def test_unreferenced_variant_is_retired_not_deleted(
        self, admin_client, variant, test_product
    ):
        """Even a size nothing points at survives DELETE — no hard delete exists."""
        ProductVariant.objects.create(
            product=test_product, price=Decimal('99.00'), stock=5,
            weight=Decimal('250.00'), unit='g', is_active=True,
        )

        r = admin_client.delete(f'{VARIANTS_URL}{variant.id}/')

        assert r.status_code == 200
        assert ProductVariant.objects.filter(id=variant.id).exists()
        variant.refresh_from_db()
        assert variant.is_active is False
        assert variant.is_default is False

    def test_last_active_size_cannot_be_removed(self, admin_client, variant):
        ProductVariant.objects.filter(product=variant.product).exclude(
            pk=variant.pk).update(is_active=False)

        r = admin_client.delete(f'{VARIANTS_URL}{variant.id}/')
        assert r.status_code == 409
        variant.refresh_from_db()
        assert variant.is_active is True


# ==================== PRODUCT IMAGE UPLOAD ====================

@pytest.mark.django_db
class TestProductImageUpload:
    def test_regular_user_cannot_upload(self, authenticated_client, test_product):
        r = authenticated_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': create_test_image('x.jpg'),
        }, format='multipart')
        assert r.status_code == 403

    def test_anonymous_cannot_upload(self, api_client, test_product):
        r = api_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': create_test_image('x.jpg'),
        }, format='multipart')
        assert r.status_code in (401, 403)

    def test_admin_can_upload_valid_image(self, admin_client, test_product):
        r = admin_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': create_test_image('ok.jpg'),
            'alt_text': 'A jar of turmeric',
        }, format='multipart')
        assert r.status_code == 201

    def test_oversized_image_rejected(self, admin_client, test_product):
        """Over the 5 MB cap — must not reach Cloudinary.

        Built as a genuinely decodable JPEG so the size cap is what rejects it,
        not Pillow's decoder (which would pass the test for the wrong reason).
        """
        from PIL import Image
        from products.serializers import ProductImageSerializer

        buf = BytesIO()
        # Noise resists JPEG compression, so this lands well over the cap.
        noise = Image.frombytes(
            'RGB', (2000, 2000),
            bytes(random.getrandbits(8) for _ in range(2000 * 2000 * 3)),
        )
        noise.save(buf, format='JPEG', quality=100)
        payload = buf.getvalue()
        assert len(payload) > ProductImageSerializer.MAX_IMAGE_BYTES, (
            f'fixture too small ({len(payload)} bytes) to exercise the cap'
        )

        big = SimpleUploadedFile('huge.jpg', payload, content_type='image/jpeg')
        r = admin_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': big,
        }, format='multipart')

        assert r.status_code == 400
        assert 'too large' in str(r.json()['details']['image']).lower()

    def test_disallowed_content_type_rejected(self, admin_client, test_product):
        bad = SimpleUploadedFile(
            'payload.svg', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            content_type='image/svg+xml',
        )
        r = admin_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': bad,
        }, format='multipart')
        assert r.status_code == 400

    def test_non_image_disguised_as_jpeg_rejected(self, admin_client, test_product):
        """Content-type is client-supplied; Pillow validation is the real gate."""
        bad = SimpleUploadedFile(
            'evil.jpg', b'#!/bin/sh\necho pwned\n', content_type='image/jpeg',
        )
        r = admin_client.post(IMAGES_URL, {
            'product': test_product.id, 'image': bad,
        }, format='multipart')
        assert r.status_code == 400
