"""Old product URLs must keep resolving after a re-slug (audit issue #3)."""
import pytest

from products.models import ProductSlugAlias


@pytest.fixture
def product(test_product):
    """Reuse the shared product fixture from conftest."""
    return test_product


@pytest.mark.django_db
class TestSlugAlias:
    def test_renaming_records_the_old_slug(self, product):
        original = product.slug

        product.slug = "kitchen-king-masala-new"
        product.save()

        assert ProductSlugAlias.objects.filter(
            slug=original, product=product
        ).exists()

    def test_old_slug_still_resolves_to_the_product(self, client, product):
        original = product.slug
        product.slug = "kitchen-king-masala-new"
        product.save()

        response = client.get(f"/api/products/{original}/")

        assert response.status_code == 200
        assert response.json()["slug"] == "kitchen-king-masala-new"

    def test_canonical_slug_still_resolves(self, client, product):
        response = client.get(f"/api/products/{product.slug}/")

        assert response.status_code == 200

    def test_unknown_slug_still_404s(self, client, product):
        response = client.get("/api/products/no-such-product/")

        assert response.status_code == 404

    def test_reusing_a_retired_slug_clears_the_alias(self, product):
        """A slug can be canonical or an alias, never both."""
        original = product.slug
        product.slug = "temporary-slug"
        product.save()
        assert ProductSlugAlias.objects.filter(slug=original).exists()

        product.slug = original  # renamed back
        product.save()

        assert not ProductSlugAlias.objects.filter(slug=original).exists()
        assert ProductSlugAlias.objects.filter(slug="temporary-slug").exists()

    def test_multiple_renames_all_keep_resolving(self, client, product):
        first = product.slug
        product.slug = "second-slug"
        product.save()
        product.slug = "third-slug"
        product.save()

        for old in (first, "second-slug"):
            assert client.get(f"/api/products/{old}/").status_code == 200
