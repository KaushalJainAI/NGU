"""Tests for homepage-section admin CRUD + product ordering, promoted from the
old read-only viewset so the admin panel can manage sections without the Django
admin."""
import pytest

from products.models import ProductSection, ProductSectionPlacement


@pytest.mark.django_db
class TestSectionCrud:
    def test_staff_can_create_section(self, admin_client):
        resp = admin_client.post('/api/product-sections/', {
            'name': 'Festival Picks', 'section_type': 'custom', 'max_products': 8,
        }, format='json')
        assert resp.status_code == 201
        assert ProductSection.objects.filter(name='Festival Picks').exists()

    def test_customer_cannot_create_section(self, authenticated_client):
        resp = authenticated_client.post('/api/product-sections/', {
            'name': 'Hax', 'section_type': 'custom',
        }, format='json')
        assert resp.status_code == 403

    def test_delete_soft_hides(self, admin_client):
        section = ProductSection.objects.create(name='Temp', section_type='custom')
        resp = admin_client.delete(f'/api/product-sections/{section.id}/')
        assert resp.status_code == 204
        section.refresh_from_db()
        assert section.is_active is False  # hidden, not destroyed

    def test_set_and_reorder_products(self, admin_client, test_product, test_product2):
        section = ProductSection.objects.create(name='Row', section_type='custom')
        # Place both products, product2 first.
        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [test_product2.id, test_product.id]}, format='json')
        assert resp.status_code == 200
        positions = {p['id']: p['position'] for p in resp.data}
        assert positions[test_product2.id] == 0
        assert positions[test_product.id] == 1
        assert ProductSectionPlacement.objects.filter(section=section).count() == 2

        # Reorder: product first now.
        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [test_product.id, test_product2.id]}, format='json')
        positions = {p['id']: p['position'] for p in resp.data}
        assert positions[test_product.id] == 0

    def test_unknown_product_id_rejected(self, admin_client):
        section = ProductSection.objects.create(name='Row2', section_type='custom')
        resp = admin_client.put(
            f'/api/product-sections/{section.id}/products/',
            {'product_ids': [999999]}, format='json')
        assert resp.status_code == 400

    def test_get_products_is_public(self, api_client, test_product):
        section = ProductSection.objects.create(name='Pub', section_type='custom')
        ProductSectionPlacement.objects.create(section=section, product=test_product, position=0)
        resp = api_client.get(f'/api/product-sections/{section.id}/products/')
        assert resp.status_code == 200
        assert resp.data[0]['id'] == test_product.id
