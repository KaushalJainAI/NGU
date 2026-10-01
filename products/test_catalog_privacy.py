"""AP8/S12: exact inventory counts are staff-only in catalog responses."""
import pytest


def _rows(data):
    return data['results'] if isinstance(data, dict) else data


def _row_by_id(data, pk):
    return next(p for p in _rows(data) if p['id'] == pk)


@pytest.mark.django_db
class TestCatalogPrivacy:
    def test_anon_list_hides_counts(self, api_client, test_product):
        r = api_client.get('/api/products/')
        assert r.status_code == 200
        row = _row_by_id(r.data, test_product.id)
        assert 'in_stock' in row
        assert 'stock' not in row
        assert 'low_stock_threshold' not in row
        assert 'sku' not in row
        for v in row['variants']:
            assert 'stock' not in v
            assert 'sku' not in v
            assert 'low_stock_threshold' not in v
            assert 'in_stock' in v

    def test_anon_detail_hides_counts(self, api_client, test_product):
        r = api_client.get(f'/api/products/{test_product.slug}/')
        assert r.status_code == 200
        assert 'in_stock' in r.data
        assert 'stock' not in r.data
        assert 'low_stock_threshold' not in r.data

    def test_anon_combo_hides_threshold(self, api_client, test_combo):
        r = api_client.get('/api/combos/')
        assert r.status_code == 200
        row = _row_by_id(r.data, test_combo.id)
        assert 'low_stock_threshold' not in row
        assert 'available_stock' not in row

    def test_staff_still_sees_counts(self, admin_client, test_product, test_combo):
        r = admin_client.get('/api/products/')
        row = _row_by_id(r.data, test_product.id)
        assert 'stock' in row and 'low_stock_threshold' in row
        assert 'stock' in row['variants'][0] and 'sku' in row['variants'][0]
        d = admin_client.get(f'/api/products/{test_product.slug}/')
        assert 'stock' in d.data and 'low_stock_threshold' in d.data
        c = admin_client.get('/api/combos/')
        assert 'low_stock_threshold' in _row_by_id(c.data, test_combo.id)

    def test_search_in_stock_is_bool(self, api_client, test_product):
        r = api_client.get('/api/search/', {'q': test_product.name})
        assert r.status_code == 200
        assert r.data['products'], 'fixture product should match its own name'
        for p in r.data['products']:
            assert isinstance(p['in_stock'], bool)
            assert 'stock' not in p and 'sku' not in p
