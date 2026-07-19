"""Tests for the admin bulk product tools: the editable grid apply endpoint,
the validated CSV import preview, and the products CSV export."""
from decimal import Decimal
from io import BytesIO

import pytest

from products.models import Product


@pytest.mark.django_db
class TestBulkApply:
    def test_apply_updates_price_and_stock(self, admin_client, test_product):
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'price': '199.50', 'stock': 42}],
        }, format='json')
        assert resp.status_code == 200
        assert resp.data['applied'] == 1
        test_product.refresh_from_db()
        assert test_product.price == Decimal('199.50')
        assert test_product.stock == 42

    def test_clearing_discount_price(self, admin_client, test_product):
        assert test_product.discount_price is not None
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'discount_price': ''}],
        }, format='json')
        assert resp.status_code == 200
        test_product.refresh_from_db()
        assert test_product.discount_price is None

    def test_invalid_row_is_all_or_nothing(self, admin_client, test_product, test_product2):
        original = test_product.price
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [
                {'id': test_product.id, 'price': '50'},
                {'id': test_product2.id, 'price': '-5'},  # invalid → whole batch rejected
            ],
        }, format='json')
        assert resp.status_code == 400
        assert resp.data['applied'] == 0
        test_product.refresh_from_db()
        assert test_product.price == original  # nothing saved

    def test_requires_staff(self, authenticated_client, test_product):
        resp = authenticated_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'price': '5'}],
        }, format='json')
        assert resp.status_code == 403

    @pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-Infinity'])
    def test_non_finite_numbers_rejected(self, admin_client, test_product, bad):
        original = test_product.price
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'price': bad}],
        }, format='json')
        assert resp.status_code == 400          # rejected, not a 500
        assert resp.data['applied'] == 0
        test_product.refresh_from_db()
        assert test_product.price == original    # nothing corrupted

    @pytest.mark.parametrize('bad', ['NaN', 'Infinity'])
    def test_non_finite_stock_rejected(self, admin_client, test_product, bad):
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'stock': bad}],
        }, format='json')
        assert resp.status_code == 400
        assert resp.data['applied'] == 0


@pytest.mark.django_db
class TestBulkImportPreview:
    def _csv(self, text):
        f = BytesIO(text.encode('utf-8'))
        f.name = 'update.csv'
        return f

    def test_preview_matches_by_name_and_flags_unknown(self, admin_client, test_product):
        csv = (
            "name,price,stock\n"
            f"{test_product.name},175,20\n"
            "No Such Product,100,5\n"
        )
        resp = admin_client.post('/api/admin/bulk-products/import/',
                                 {'file': self._csv(csv)}, format='multipart')
        assert resp.status_code == 200
        assert resp.data['ok_count'] == 1
        assert resp.data['error_count'] == 1
        ok_row = next(r for r in resp.data['rows'] if r['id'] == test_product.id)
        assert ok_row['changes']['price'] == '175'
        bad_row = next(r for r in resp.data['rows'] if r['id'] is None)
        assert 'No Such Product' in bad_row['name']
        # Import is preview-only — the product is NOT changed yet.
        test_product.refresh_from_db()
        assert test_product.price != Decimal('175')

    def test_missing_name_column_rejected(self, admin_client):
        resp = admin_client.post('/api/admin/bulk-products/import/',
                                 {'file': self._csv('price,stock\n10,5\n')}, format='multipart')
        assert resp.status_code == 400

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.post('/api/admin/bulk-products/import/',
                                         {'file': self._csv('name,price\nx,1\n')}, format='multipart')
        assert resp.status_code == 403


@pytest.mark.django_db
class TestProductsExport:
    def test_export_csv(self, admin_client, test_product):
        resp = admin_client.get('/api/admin/products-export/')
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('text/csv')
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        assert 'low_stock_threshold' in body
        assert test_product.name in body

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.get('/api/admin/products-export/')
        assert resp.status_code == 403
