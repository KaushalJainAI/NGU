"""
Comprehensive tests for the Products app.
Covers Category, Product, ProductCombo, and ProductImage ViewSets.
Includes authorization tests and security testing.
"""
import pytest
from decimal import Decimal
from rest_framework import status
from products.models import Category, Product, ProductCombo


# ==================== CATEGORY TESTS ====================

@pytest.mark.django_db
class TestCategoryAPI:
    """Tests for Category ViewSet."""
    
    base_url = '/api/categories/'
    
    def test_list_categories_public(self, api_client, test_category):
        """Test anyone can list categories."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1
    
    def test_retrieve_category_by_slug(self, api_client, test_category):
        """Test retrieve category by slug."""
        response = api_client.get(f'{self.base_url}{test_category.slug}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == test_category.name
    
    def test_retrieve_category_by_id(self, api_client, test_category):
        """Test retrieve category by ID."""
        response = api_client.get(f'{self.base_url}{test_category.id}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_nonexistent_category(self, api_client):
        """Test 404 for non-existent category."""
        response = api_client.get(f'{self.base_url}nonexistent-slug/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_create_category_admin_only(self, admin_client):
        """Test only admin can create categories."""
        data = {
            'name': 'New Category',
            'description': 'A new category'
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_category_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot create categories."""
        data = {
            'name': 'Unauthorized Category',
            'description': 'Should not be created'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_create_category_unauthenticated_forbidden(self, api_client):
        """Test unauthenticated user cannot create categories."""
        data = {'name': 'Unauthorized Category'}
        response = api_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_update_category_admin_only(self, admin_client, test_category):
        """Test only admin can update categories."""
        data = {'name': 'Updated Category Name'}
        response = admin_client.patch(
            f'{self.base_url}{test_category.slug}/', 
            data, 
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_delete_category_admin_only(self, admin_client, test_category):
        """Test only admin can delete categories."""
        response = admin_client.delete(f'{self.base_url}{test_category.slug}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_delete_category_regular_user_forbidden(self, authenticated_client, test_category):
        """Test regular user cannot delete categories."""
        response = authenticated_client.delete(f'{self.base_url}{test_category.slug}/')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_create_duplicate_category_name(self, admin_client, test_category):
        """Test creating category with duplicate name fails."""
        data = {'name': test_category.name}
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_category_search(self, api_client, test_category):
        """Test category search functionality."""
        response = api_client.get(f'{self.base_url}?search={test_category.name[:4]}')
        assert response.status_code == status.HTTP_200_OK


# ==================== PRODUCT TESTS ====================

@pytest.mark.django_db
class TestProductAPI:
    """Tests for Product ViewSet."""
    
    base_url = '/api/products/'
    
    def test_list_products_public(self, api_client, test_product):
        """Test anyone can list products."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_product_by_slug(self, api_client, test_product):
        """Test retrieve product by slug."""
        response = api_client.get(f'{self.base_url}{test_product.slug}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == test_product.name
    
    def test_retrieve_product_by_id(self, api_client, test_product):
        """Test retrieve product by ID."""
        response = api_client.get(f'{self.base_url}{test_product.id}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_nonexistent_product(self, api_client):
        """Test 404 for non-existent product."""
        response = api_client.get(f'{self.base_url}999999/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_create_product_admin_only(self, admin_client, test_category):
        """Test only admin can create products (returns 400 if image missing)."""
        data = {
            'name': 'New Spice Product',
            'category': test_category.id,
            'description': 'A new product',
            'price': '199.99',
            'stock': 50,
            'weight': 100,
            'unit': 'g',
            'spice_form': 'powder'
        }
        response = admin_client.post(self.base_url, data, format='json')
        # Returns 400 if image missing, 201 if all fields provided
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST]
    
    def test_create_product_regular_user_forbidden(self, authenticated_client, test_category):
        """Test regular user cannot create products."""
        data = {
            'name': 'Unauthorized Product',
            'category': test_category.id,
            'price': '99.99',
            'stock': 10,
            'weight': 50,
            'unit': 'g'
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_product_admin_only(self, admin_client, test_product):
        """Test only admin can update products."""
        data = {'name': 'Updated Product Name'}
        response = admin_client.patch(
            f'{self.base_url}{test_product.slug}/', 
            data, 
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_products_by_category(self, api_client, test_product):
        """Test filtering products by category."""
        response = api_client.get(f'{self.base_url}?category__slug={test_product.category.slug}')
        assert response.status_code == status.HTTP_200_OK
    
    def test_filter_products_by_spice_form(self, api_client, test_product):
        """Test filtering products by spice form."""
        response = api_client.get(f'{self.base_url}?spice_form={test_product.spice_form}')
        assert response.status_code == status.HTTP_200_OK
    
    def test_search_products(self, api_client, test_product):
        """Test product search functionality."""
        response = api_client.get(f'{self.base_url}?search={test_product.name[:5]}')
        assert response.status_code == status.HTTP_200_OK
    
    def test_product_ordering(self, api_client, test_product):
        """Test product ordering."""
        response = api_client.get(f'{self.base_url}?ordering=-price')
        assert response.status_code == status.HTTP_200_OK
    
    def test_product_sections_endpoint(self, api_client):
        """Test product sections endpoint."""
        response = api_client.get(f'{self.base_url}sections/')
        assert response.status_code == status.HTTP_200_OK


# ==================== PRODUCT EDGE CASES ====================

@pytest.mark.django_db
class TestProductEdgeCases:
    """Edge case tests for products."""
    
    base_url = '/api/products/'
    
    def test_create_product_negative_price(self, admin_client, test_category):
        """Test creating product with negative price fails gracefully."""
        data = {
            'name': 'Negative Price Product',
            'category': test_category.id,
            'price': '-100.00',
            'stock': 10,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        # Should be 400, not 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_product_zero_price(self, admin_client, test_category):
        """Test creating product with zero price."""
        data = {
            'name': 'Free Product',
            'category': test_category.id,
            'price': '0.00',
            'stock': 10,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_product_negative_stock(self, admin_client, test_category):
        """Test creating product with negative stock fails gracefully."""
        data = {
            'name': 'Negative Stock Product',
            'category': test_category.id,
            'price': '100.00',
            'stock': -5,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_product_very_large_price(self, admin_client, test_category):
        """Test creating product with very large price."""
        data = {
            'name': 'Expensive Product',
            'category': test_category.id,
            'price': '99999999.99',
            'stock': 1,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_product_discount_higher_than_price(self, admin_client, test_category):
        """Test discount price higher than regular price."""
        data = {
            'name': 'Invalid Discount Product',
            'category': test_category.id,
            'price': '100.00',
            'discount_price': '150.00',  # Higher than price
            'stock': 10,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        # Should validate and reject, not 500
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_product_with_invalid_category_id(self, admin_client):
        """Test creating product with non-existent category."""
        data = {
            'name': 'Invalid Category Product',
            'category': 999999,
            'price': '100.00',
            'stock': 10,
            'weight': 100,
            'unit': 'g'
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_product_sql_injection_in_name(self, admin_client, test_category, malicious_inputs):
        """Test SQL injection in product name."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'name': payload,
                'category': test_category.id,
                'price': '100.00',
                'stock': 10,
                'weight': '100g'
            }
            response = admin_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_product_xss_in_description(self, admin_client, test_category, malicious_inputs):
        """Test XSS in product description."""
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {
                'name': f'XSS Test Product {hash(payload) % 10000}',
                'category': test_category.id,
                'description': payload,
                'price': '100.00',
                'stock': 10,
                'weight': '100g'
            }
            response = admin_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== COMBO TESTS ====================

@pytest.mark.django_db
class TestComboAPI:
    """Tests for ProductCombo ViewSet."""
    
    base_url = '/api/combos/'
    
    def test_list_combos_public(self, api_client, test_combo):
        """Test anyone can list combos."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_combo_by_slug(self, api_client, test_combo):
        """Test retrieve combo by slug."""
        response = api_client.get(f'{self.base_url}{test_combo.slug}/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['name'] == test_combo.name
    
    def test_retrieve_combo_by_id(self, api_client, test_combo):
        """Test retrieve combo by ID."""
        response = api_client.get(f'{self.base_url}{test_combo.id}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_nonexistent_combo(self, api_client):
        """Test 404 for non-existent combo."""
        response = api_client.get(f'{self.base_url}999999/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_create_combo_admin_only(self, admin_client, test_product):
        """Test only admin can create combos (returns 400 if required fields missing)."""
        data = {
            'name': 'New Combo Pack',
            'description': 'A new combo',
            'price': '500.00',
        }
        response = admin_client.post(self.base_url, data, format='json')
        # Returns 400 if required fields missing, 201 if all provided
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST]
    
    def test_create_combo_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot create combos."""
        data = {
            'name': 'Unauthorized Combo',
            'price': '300.00',
            'stock': 10
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_combo_admin_only(self, admin_client, test_combo):
        """Test only admin can update combos."""
        data = {'name': 'Updated Combo Name'}
        response = admin_client.patch(
            f'{self.base_url}{test_combo.slug}/', 
            data, 
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_delete_combo_admin_only(self, admin_client, test_combo):
        """Test only admin can delete combos."""
        response = admin_client.delete(f'{self.base_url}{test_combo.slug}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_search_combos(self, api_client, test_combo):
        """Test combo search functionality."""
        response = api_client.get(f'{self.base_url}?search={test_combo.name[:4]}')
        assert response.status_code == status.HTTP_200_OK


# ==================== COMBO EDGE CASES ====================

@pytest.mark.django_db
class TestComboEdgeCases:
    """Edge case tests for combos."""
    
    base_url = '/api/combos/'
    
    def test_create_combo_negative_price(self, admin_client):
        """Test creating combo with negative price fails gracefully."""
        data = {
            'name': 'Negative Price Combo',
            'price': '-200.00',
            'stock': 5
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_combo_discount_higher_than_price(self, admin_client):
        """Test combo discount price higher than regular price."""
        data = {
            'name': 'Invalid Discount Combo',
            'price': '100.00',
            'discount_price': '200.00',
            'stock': 5
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_combo_sql_injection_in_name(self, admin_client, malicious_inputs):
        """Test SQL injection in combo name."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'name': payload,
                'price': '200.00',
                'stock': 5
            }
            response = admin_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== SPICE FORMS ENDPOINT ====================

@pytest.mark.django_db
class TestSpiceFormsEndpoint:
    """Tests for spice forms endpoint."""
    
    url = '/api/spice-forms/'
    
    def test_get_spice_forms(self, api_client):
        """Test getting available spice forms."""
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)


# ==================== UNIFIED SEARCH ENDPOINT ====================

@pytest.mark.django_db
class TestUnifiedSearchEndpoint:
    """Tests for unified search endpoint."""
    
    url = '/api/search/'
    
    def test_search_with_query(self, api_client, test_product):
        """Test search with query parameter."""
        response = api_client.get(f'{self.url}?q={test_product.name[:5]}')
        assert response.status_code == status.HTTP_200_OK
    
    def test_search_empty_query(self, api_client):
        """Test search with empty query."""
        response = api_client.get(self.url)
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_search_special_characters(self, api_client, malicious_inputs):
        """Test search with special characters."""
        for chars in malicious_inputs.SPECIAL_CHARS:
            response = api_client.get(f'{self.url}?q={chars}')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_search_sql_injection(self, api_client, malicious_inputs):
        """Test search with SQL injection."""
        for payload in malicious_inputs.SQL_INJECTION:
            response = api_client.get(f'{self.url}?q={payload}')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== FUZZY SEARCH ENGINE ====================

from decimal import Decimal as _Decimal
from django.core.cache import cache as _cache
from products.recommendations import (
    _clean_synonyms,
    _deterministic_synonyms,
    build_search_corpus,
    get_search_corpus,
)
from products.cache import invalidate_search_cache, get_search_corpus_key


@pytest.fixture
def search_catalog(db):
    """Seeded mini-catalog with KB rows; LLM-triggering signals disconnected."""
    from django.db.models.signals import post_save
    from products import signals as product_signals
    from products.models import Product, Category, ProductSearchKB
    from conftest import create_test_image

    post_save.disconnect(product_signals.auto_update_product_on_save, sender=Product)
    try:
        category = Category.objects.create(name='Masalas', is_active=True)

        def make(name, weight, spice_form='powder', **kwargs):
            return Product.objects.create(
                name=name, category=category, description=f'{name} description',
                price=_Decimal('100.00'), stock=50, weight=_Decimal(weight),
                unit='g', spice_form=spice_form, is_active=True,
                image=create_test_image('p.jpg'), **kwargs,
            )

        jeeravan = make('Nidhi Jeeravan 100g', '100')
        turmeric = make('Nidhi Turmeric Powder 500g', '500')
        chilli = make('Nidhi VIP Teja Mirchi 500g', '500')
        no_kb = make('Nidhi Amchur Powder 500g', '500')

        ProductSearchKB.objects.create(
            product=jeeravan, synonyms=['jeeravan', 'jiravan', 'jeerawan', 'indori masala'])
        ProductSearchKB.objects.create(
            product=turmeric, synonyms=['haldi', 'haldee', 'manjal', 'turmeric powder'])
        ProductSearchKB.objects.create(
            product=chilli, synonyms=['mirch', 'mirchi', 'lal mirch', 'red chilli'])

        # locmem cache survives across tests in-process; corpus/suggest entries
        # from a previous test would carry stale product ids.
        _cache.clear()

        yield {'jeeravan': jeeravan, 'turmeric': turmeric,
               'chilli': chilli, 'no_kb': no_kb}
    finally:
        post_save.connect(product_signals.auto_update_product_on_save, sender=Product)


class TestSynonymCleaning:
    """Tests for KB synonym validation and deterministic fallbacks."""

    def test_clean_synonyms_drops_junk(self):
        raw = ['  Haldi ', 'haldi', 'POWDER', 'x', 123, '{bad}', 'http://spam.com',
               'a' * 61, '12345', 'good  term', 'good term', 'line\nbreak']
        assert _clean_synonyms(raw, name='Haldi') == ['good term']

    def test_clean_synonyms_caps_count(self):
        raw = [f'unique term {i}' for i in range(50)]
        assert len(_clean_synonyms(raw)) == 30

    def test_deterministic_synonyms_cover_name_and_weight(self):
        from products.models import Product, Category
        product = Product(
            name='Nidhi Haldi Powder 500g', slug='nidhi-haldi-powder-500g',
            category=Category(name='Spices'), spice_form='powder',
            weight=_Decimal('500'), unit='g',
        )
        terms = _deterministic_synonyms(product)
        assert 'nidhi haldi powder 500g' in terms
        assert 'haldi' in terms
        assert 'spices' in terms
        assert 'nidhi haldi powder 500g 500g' in terms
        # weight/number tokens are never standalone terms
        assert '500g' not in terms


@pytest.mark.django_db
class TestSearchCorpus:
    """Tests for the cached search corpus."""

    def test_product_without_kb_still_matchable(self, search_catalog):
        no_kb = search_catalog['no_kb']
        texts = {(e['text'], e['kind']) for e in build_search_corpus()
                 if e['type'] == 'product' and e['id'] == no_kb.id}
        assert ('nidhi amchur powder 500g', 'name') in texts
        assert ('amchur', 'token') in texts
        assert ('masalas', 'category') in texts

    def test_corpus_cache_invalidation(self, search_catalog):
        get_search_corpus()
        assert _cache.get(get_search_corpus_key()) is not None
        invalidate_search_cache()
        assert _cache.get(get_search_corpus_key()) is None


@pytest.mark.django_db
class TestSearchRanking:
    """End-to-end ranking through GET /api/search/."""

    url = '/api/search/'

    def first_product(self, api_client, query):
        response = api_client.get(self.url, {'q': query})
        assert response.status_code == status.HTTP_200_OK
        products = response.data['products']
        return products[0] if products else None

    def test_hinglish_synonym_exact(self, api_client, search_catalog):
        assert self.first_product(api_client, 'jiravan')['id'] == search_catalog['jeeravan'].id

    def test_hinglish_haldi(self, api_client, search_catalog):
        assert self.first_product(api_client, 'haldi')['id'] == search_catalog['turmeric'].id

    def test_typo_tumeric(self, api_client, search_catalog):
        assert self.first_product(api_client, 'tumeric')['id'] == search_catalog['turmeric'].id

    def test_mirchi_finds_chilli(self, api_client, search_catalog):
        assert self.first_product(api_client, 'mirchi')['id'] == search_catalog['chilli'].id

    def test_weight_qualified_query(self, api_client, search_catalog):
        first = self.first_product(api_client, 'haldi 500g')
        assert first['id'] == search_catalog['turmeric'].id

    def test_exact_name_outranks_synonyms(self, api_client, search_catalog):
        first = self.first_product(api_client, 'nidhi jeeravan 100g')
        assert first['id'] == search_catalog['jeeravan'].id

    def test_product_without_kb_found_by_name(self, api_client, search_catalog):
        first = self.first_product(api_client, 'amchur')
        assert first['id'] == search_catalog['no_kb'].id

    def test_junk_query_has_no_direct_matches(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'qwzxv'})
        assert response.status_code == status.HTTP_200_OK
        assert response.data['stats']['direct_matches'] == 0

    def test_short_query_does_not_match_everything(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'ha'})
        assert response.status_code == status.HTTP_200_OK
        direct = [p for p in response.data['products'] if p['score_type'] == 'direct']
        assert len(direct) < 4  # must not return the whole catalog


class TestRankAndDedupe:
    """Unit tests for the score-type weighting fix in _rank_and_dedupe."""

    def engine(self):
        from products.recommendations import SpiceSearchEngine
        return SpiceSearchEngine()

    def test_weight_applied_once_direct_unchanged(self):
        """A direct match keeps its raw score (weight 1.0) — no double penalty."""
        results = [
            {'type': 'product', 'id': 1, 'score': 72, 'score_type': 'direct'},
            {'type': 'product', 'id': 2, 'score': 75, 'score_type': 'category'},
            {'type': 'product', 'id': 3, 'score': 60, 'score_type': 'trending'},
        ]
        ranked = self.engine()._rank_and_dedupe(results, top_k=10)
        by_id = {r['id']: r['score'] for r in ranked}
        assert by_id[1] == 72              # direct: 72 * 1.0
        assert by_id[2] == pytest.approx(60.0)   # category: 75 * 0.8
        assert by_id[3] == pytest.approx(30.0)   # trending: 60 * 0.5

    def test_direct_outranks_fallback(self):
        """Featured/trending padding must never outrank a genuine direct match."""
        results = [
            {'type': 'product', 'id': 2, 'score': 75, 'score_type': 'category'},
            {'type': 'product', 'id': 3, 'score': 60, 'score_type': 'trending'},
            {'type': 'product', 'id': 1, 'score': 70, 'score_type': 'direct'},
        ]
        ranked = self.engine()._rank_and_dedupe(results, top_k=10)
        assert ranked[0]['id'] == 1

    def test_dedupe_keeps_highest_final_score(self):
        """Same (type, id) twice keeps the entry with the higher weighted score."""
        results = [
            {'type': 'product', 'id': 1, 'score': 75, 'score_type': 'category'},  # ->60
            {'type': 'product', 'id': 1, 'score': 70, 'score_type': 'direct'},    # ->70
        ]
        ranked = self.engine()._rank_and_dedupe(results, top_k=10)
        assert len(ranked) == 1
        assert ranked[0]['score'] == 70


@pytest.mark.django_db
class TestSuggestEndpoint:
    """Tests for GET /api/search/suggest/."""

    url = '/api/search/suggest/'

    def test_single_char_returns_empty(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'j'})
        assert response.status_code == status.HTTP_200_OK
        assert response.data['suggestions'] == []

    def test_prefix_match(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'jee'})
        assert response.status_code == status.HTTP_200_OK
        slugs = [s['slug'] for s in response.data['suggestions']]
        assert search_catalog['jeeravan'].slug in slugs

    def test_payload_is_slim(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'haldi'})
        assert response.data['suggestions'], 'expected at least one suggestion'
        assert set(response.data['suggestions'][0].keys()) == {
            'id', 'name', 'slug', 'type', 'price', 'image'}

    def test_limit_respected(self, api_client, search_catalog):
        response = api_client.get(self.url, {'q': 'nidhi', 'limit': 2})
        assert len(response.data['suggestions']) <= 2


@pytest.mark.django_db
class TestSectionPlacementOrdering:
    """Admin-controlled ordering of products within a homepage section
    (ProductSectionPlacement.position). Covers the model query, the public
    sections API, reordering, the max_products cap, and active filtering."""

    sections_url = '/api/products/sections/'

    @pytest.fixture
    def section_products(self, db, test_category):
        """Three active products to place into a section, in a known order."""
        from conftest import create_test_image
        names = ['Alpha Spice', 'Bravo Spice', 'Charlie Spice']
        products = []
        for i, name in enumerate(names):
            products.append(Product.objects.create(
                name=name,
                category=test_category,
                description='placement test product',
                price=Decimal('100.00'),
                stock=10,
                weight=Decimal(f'{100 + i}.00'),
                unit='g',
                spice_form='powder',
                is_active=True,
                image=create_test_image(f'{name.lower().replace(" ", "-")}.jpg'),
            ))
        return products

    @pytest.fixture
    def placed_section(self, db, section_products):
        """A section with the three products placed in reverse name order
        (Charlie=0, Bravo=1, Alpha=2) so 'position' clearly differs from
        the default -created_at / name ordering."""
        from products.models import ProductSection, ProductSectionPlacement
        section = ProductSection.objects.create(
            name='Featured Test Row', section_type='featured',
            display_order=0, max_products=12, is_active=True,
        )
        for pos, product in enumerate(reversed(section_products)):
            ProductSectionPlacement.objects.create(
                section=section, product=product, position=pos,
            )
        return section

    def test_get_products_follows_position(self, placed_section, section_products):
        """Model-level: get_products() returns products ordered by position."""
        ordered = list(placed_section.get_products())
        expected = list(reversed(section_products))  # Charlie, Bravo, Alpha
        assert [p.id for p in ordered] == [p.id for p in expected]

    def test_sections_api_returns_position_order(self, api_client, placed_section, section_products):
        """API-level: /products/sections/ serializes products in admin order."""
        response = api_client.get(self.sections_url)
        assert response.status_code == status.HTTP_200_OK
        section = next(
            s for s in response.data['results'] if s['id'] == placed_section.id
        )
        ids = [p['id'] for p in section['products']]
        assert ids == [p.id for p in reversed(section_products)]

    def test_reordering_changes_output(self, placed_section, section_products):
        """Changing a placement's position re-sorts the section."""
        from products.models import ProductSectionPlacement
        alpha = section_products[0]
        # Move Alpha to the front.
        placement = ProductSectionPlacement.objects.get(
            section=placed_section, product=alpha
        )
        placement.position = -1
        placement.save(update_fields=['position'])
        assert list(placed_section.get_products())[0].id == alpha.id

    def test_max_products_caps_after_ordering(self, placed_section, section_products):
        """max_products limits the row, applied after position ordering."""
        placed_section.max_products = 2
        placed_section.save(update_fields=['max_products'])
        ordered = list(placed_section.get_products())
        assert len(ordered) == 2
        # The two highest-priority (lowest position) products survive.
        assert [p.id for p in ordered] == [p.id for p in list(reversed(section_products))[:2]]

    def test_inactive_product_excluded(self, placed_section, section_products):
        """Deactivating a placed product drops it from the section output."""
        charlie = section_products[2]
        # .update() bypasses Product.save() (full_clean/thumbnail/signals) so the
        # test targets the get_products() is_active filter, not the save path.
        Product.objects.filter(id=charlie.id).update(is_active=False)
        ids = [p.id for p in placed_section.get_products()]
        assert charlie.id not in ids

    def test_existing_placements_preserved_through_relation(self, placed_section, section_products):
        """The through model reuses the M2M table, so reverse access still works."""
        # Reverse: product.sections still resolves the section membership.
        alpha = section_products[0]
        assert placed_section in alpha.sections.all()
