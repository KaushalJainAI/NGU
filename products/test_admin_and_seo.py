"""
Admin catalog tools (bulk apply, CSV import/export, fix_junk_products) and SEO/search edge cases (sitemap.xml, robots.txt, zero results).
"""
from decimal import Decimal
from io import BytesIO, StringIO
from xml.etree import ElementTree

import pytest
from django.core.management import call_command

from conftest import create_test_image
from products.models import Category, Product, ProductVariant, default_variant_for
from products.recommendations import SpiceSearchEngine

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# --- From test_bulk_products.py ---

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
                {'id': test_product2.id, 'price': '-5'},
            ],
        }, format='json')
        assert resp.status_code == 400
        assert resp.data['applied'] == 0
        test_product.refresh_from_db()
        assert test_product.price == original

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
        assert resp.status_code == 400
        assert resp.data['applied'] == 0
        test_product.refresh_from_db()
        assert test_product.price == original

    @pytest.mark.parametrize('bad', ['NaN', 'Infinity'])
    def test_non_finite_stock_rejected(self, admin_client, test_product, bad):
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'stock': bad}],
        }, format='json')
        assert resp.status_code == 400
        assert resp.data['applied'] == 0

    def test_variant_id_edits_that_size_only(self, admin_client, test_product):
        """Editing a non-default size must land on that size and leave the
        legacy Product columns alone.

        This is the regression the whole variant rollout exists for: the bulk
        editor used to write Product.price, which checkout never reads and which
        the mirror signal overwrites on the next variant save — so the edit
        looked applied and then silently vanished.
        """
        default = default_variant_for(test_product.pk)  # auto-created 250g
        variant = ProductVariant.objects.create(
            product=test_product, weight=500, unit='g',
            price=Decimal('100.00'), stock=10,
        )
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'variant_id': variant.id,
                         'price': '175.00', 'stock': 7}],
        }, format='json')
        assert resp.status_code == 200
        variant.refresh_from_db()
        assert variant.price == Decimal('175.00')
        assert variant.stock == 7
        # The 500g edit must not leak onto the product, whose legacy columns
        # mirror the DEFAULT size only.
        test_product.refresh_from_db()
        assert test_product.price == default.price

    def test_variant_id_edit_of_default_updates_mirror(self, admin_client, test_product):
        """Editing the DEFAULT size does propagate to the legacy columns, so
        list cards and variant-less cart fallbacks stay truthful."""
        default = default_variant_for(test_product.pk)
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'variant_id': default.id,
                         'price': '175.00', 'stock': 7}],
        }, format='json')
        assert resp.status_code == 200
        default.refresh_from_db()
        assert default.price == Decimal('175.00')
        test_product.refresh_from_db()
        assert test_product.price == Decimal('175.00')
        assert test_product.stock == 7

    def test_variant_of_another_product_rejected(self, admin_client, test_product, test_product2):
        variant = ProductVariant.objects.create(
            product=test_product2, weight=100, unit='g', price=Decimal('50.00'),
        )
        resp = admin_client.post('/api/admin/bulk-products/apply/', {
            'changes': [{'id': test_product.id, 'variant_id': variant.id, 'price': '9'}],
        }, format='json')
        assert resp.status_code == 400
        assert resp.data['applied'] == 0

    def test_bulk_products_lists_variants(self, admin_client, test_product):
        # The product already owns one auto-created default size; edit it
        # rather than adding a second 250g row beside it.
        default = default_variant_for(test_product.pk)
        default.weight, default.unit = 250, 'g'
        default.price, default.stock = Decimal('80.00'), 3
        default.save()
        resp = admin_client.get('/api/admin/bulk-products/')
        assert resp.status_code == 200
        row = next(r for r in resp.data if r['id'] == test_product.id)
        assert [v['label'] for v in row['variants']] == ['250g']
        assert row['variants'][0]['is_default'] is True


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

    def test_name_matching_stays_case_insensitive(self, admin_client, test_product):
        """The one-query name lookup replaced a per-row `name__iexact`; it must
        still match the way a spreadsheet actually spells things."""
        csv = f"name,price\n{test_product.name.upper()},175\n"
        resp = admin_client.post('/api/admin/bulk-products/import/',
                                 {'file': self._csv(csv)}, format='multipart')
        assert resp.status_code == 200
        assert resp.data['ok_count'] == 1
        assert resp.data['rows'][0]['id'] == test_product.id

    def test_an_oversized_sheet_is_refused(self, admin_client, test_product):
        """5 MB of CSV is ~100k rows, and every row used to cost its own query."""
        from products.bulk_views import MAX_BULK_ROWS
        body = 'name,price\n' + f"{test_product.name},175\n" * (MAX_BULK_ROWS + 1)
        resp = admin_client.post('/api/admin/bulk-products/import/',
                                 {'file': self._csv(body)}, format='multipart')
        assert resp.status_code == 400
        assert 'Too many rows' in resp.data['error']


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


# --- From test_fix_junk_products.py ---

def _junk_category():
    return Category.objects.get_or_create(name="Test Cat", defaults={"description": "d"})[0]


def _junk_product(name, slug=None, **kw):
    cat = kw.pop("category", None) or _junk_category()
    return Product.objects.create(
        name=name, slug=slug, category=cat, description="d",
        spice_form="powder", price="10.00",
        image=create_test_image(f"{name}.jpg"), stock=1, **kw,
    )


@pytest.mark.django_db
class TestFixJunkProducts:
    def test_dry_run_changes_nothing(self):
        p = _junk_product("logo2", slug="logo2-50000")
        out = StringIO()
        call_command("fix_junk_products", stdout=out)
        p.refresh_from_db()
        assert p.is_active is True
        assert "DRY RUN" in out.getvalue()

    def test_default_regex_deactivates_logo_products(self):
        junk = _junk_product("logo2", slug="logo2-50000")
        real = _junk_product("Turmeric Powder", slug="turmeric-powder-100")
        call_command("fix_junk_products", "--apply", stdout=StringIO())
        junk.refresh_from_db()
        real.refresh_from_db()
        assert junk.is_active is False
        assert real.is_active is True

    def test_slug_target_deactivates(self):
        p = _junk_product("Weird Thing", slug="logo2-50000")
        call_command("fix_junk_products", "--slug", "logo2-50000",
                     "--name-regex", "", "--apply", stdout=StringIO())
        p.refresh_from_db()
        assert p.is_active is False

    def test_delete_removes_unordered_product(self):
        p = _junk_product("logo", slug="logo-1")
        pid = p.id
        call_command("fix_junk_products", "--delete", "--apply", stdout=StringIO())
        assert not Product.objects.filter(pk=pid).exists()

    def test_no_match_is_noop(self):
        p = _junk_product("Cumin", slug="cumin-100")
        out = StringIO()
        call_command("fix_junk_products", "--apply", stdout=out)
        p.refresh_from_db()
        assert p.is_active is True
        assert "No matching products" in out.getvalue()


# --- From test_sitemap.py ---

@pytest.mark.django_db
class TestSitemap:
    def test_serves_xml_not_html(self, client):
        response = client.get("/sitemap.xml")

        assert response.status_code == 200
        assert "xml" in response["Content-Type"]
        assert not response.content.lstrip().startswith(b"<!doctype")

    def test_is_wellformed_and_has_urls(self, client, test_product):
        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert len(locs) > 0
        assert "https://nidhimasala.com/" in locs
        assert all(loc.startswith("https://nidhimasala.com") for loc in locs)

    def test_includes_active_products(self, client, test_product):
        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert f"https://nidhimasala.com/products/{test_product.slug}" in locs

    def test_excludes_inactive_products(self, client, test_product):
        test_product.is_active = False
        test_product.save()

        response = client.get("/sitemap.xml")

        root = ElementTree.fromstring(response.content)
        locs = [e.text for e in root.findall(".//sm:loc", NS)]

        assert f"https://nidhimasala.com/products/{test_product.slug}" not in locs

    def test_what_we_cache_is_json_serializable(self, client, test_product):
        import json
        from products.sitemaps import SITEMAP_CACHE_KEY
        from django.core.cache import cache

        cache.delete(SITEMAP_CACHE_KEY)
        client.get("/sitemap.xml")

        cached = cache.get(SITEMAP_CACHE_KEY)
        assert cached is not None, "sitemap was not cached"
        json.dumps(cached)

    def test_second_request_is_served_from_cache(self, client, test_product):
        first = client.get("/sitemap.xml")
        second = client.get("/sitemap.xml")

        assert second.status_code == 200
        assert second.content == first.content


@pytest.mark.django_db
class TestRobots:
    def test_points_at_the_sitemap(self, client):
        response = client.get("/robots.txt")
        body = response.content.decode()

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/plain")
        assert "Sitemap: https://nidhimasala.com/sitemap.xml" in body

    def test_keeps_private_routes_out_of_the_index(self, client):
        body = client.get("/robots.txt").content.decode()

        for private in ("/cart", "/billing", "/profile", "/my-orders"):
            assert f"Disallow: {private}" in body


# --- From test_search_no_results.py ---

@pytest.fixture
def engine():
    return SpiceSearchEngine()


@pytest.mark.django_db
class TestSearchNoResults:
    def test_nonsense_query_returns_no_products(self, engine, test_product):
        result = engine.unified_search("zzzzqqqxyzzy", top_k=20)

        assert result["products"] == []
        assert result["combos"] == []
        assert result["total_results"] == 0

    def test_nonsense_query_still_offers_suggestions(self, engine, test_product):
        result = engine.unified_search("zzzzqqqxyzzy", top_k=20)

        assert "suggestions" in result
        assert result["total_results"] == 0

    def test_real_query_still_matches(self, engine, test_product):
        result = engine.unified_search(test_product.name, top_k=20)

        assert result["total_results"] >= 1
        names = [p["name"] for p in result["products"]]
        assert test_product.name in names

    def test_matching_query_returns_no_suggestions(self, engine, test_product):
        result = engine.unified_search(test_product.name, top_k=20)

        assert result["suggestions"] == []
