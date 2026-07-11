"""
Homepage-section placement from the admin, plus the section-list endpoint that
powers the product/combo edit multi-select.

The storefront already reads sections at /products/sections/ (rich nested
payload); these tests cover the *write* path — an admin assigning a product or
combo to sections via a JSON PATCH — and the flat /product-sections/ list.
"""
import pytest

from products.models import ProductSection, Product, ProductCombo


@pytest.fixture
def section(db):
    return ProductSection.objects.create(name="Trending Now", section_type="trending")


@pytest.fixture
def section2(db):
    return ProductSection.objects.create(name="Best Sellers", section_type="bestseller")


@pytest.mark.django_db
class TestProductSectionList:
    def test_list_returns_sections(self, admin_client, section, section2):
        resp = admin_client.get("/api/product-sections/")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.data}
        assert {"Trending Now", "Best Sellers"} <= names

    def test_list_is_public_readable(self, api_client, section):
        # Section names aren't sensitive; read is open (write is admin-only).
        resp = api_client.get("/api/product-sections/")
        assert resp.status_code == 200


@pytest.mark.django_db
class TestProductSectionPlacement:
    def test_admin_sets_product_sections(self, admin_client, test_product, section, section2):
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": [section.id, section2.id]},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_product.sections.values_list("id", flat=True)) == {section.id, section2.id}
        assert set(resp.data["sections"]) == {section.id, section2.id}
        assert "Trending Now" in resp.data["section_names"]

    def test_admin_clears_product_sections(self, admin_client, test_product, section):
        test_product.sections.set([section])
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": []},
            format="json",
        )
        assert resp.status_code == 200
        assert test_product.sections.count() == 0

    def test_absent_sections_left_untouched(self, admin_client, test_product, section):
        # A PATCH that doesn't mention sections must not wipe existing placements.
        test_product.sections.set([section])
        resp = admin_client.patch(
            f"/api/products/{test_product.slug}/",
            {"badge": "NEW"},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_product.sections.values_list("id", flat=True)) == {section.id}

    def test_admin_sets_combo_sections(self, admin_client, test_combo, section):
        resp = admin_client.patch(
            f"/api/combos/{test_combo.slug}/",
            {"sections": [section.id]},
            format="json",
        )
        assert resp.status_code == 200
        assert set(test_combo.sections.values_list("id", flat=True)) == {section.id}

    def test_non_admin_cannot_set_sections(self, authenticated_client, test_product, section):
        resp = authenticated_client.patch(
            f"/api/products/{test_product.slug}/",
            {"sections": [section.id]},
            format="json",
        )
        assert resp.status_code in (401, 403)
        assert test_product.sections.count() == 0
