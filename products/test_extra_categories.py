"""A product can sit on more than one shelf (audit issue #29).

Chat Masala is canonically a Blended Masala but is also a sprinkler, so it must
appear under both categories without its breadcrumb/canonical category changing.
"""
import pytest

from products.models import Category


@pytest.fixture
def sprinklers(db):
    """A second shelf to list the product on.

    Deliberately NOT named "Sprinklers & Seasonings": that row is already
    seeded by migration 0025, and `name` is a modeltranslation field, so a
    get_or_create on it queries name_en (NULL) while the unique constraint
    fires on the raw column. The behaviour under test is the dual-category
    filter, which doesn't care what the shelf is called.
    """
    return Category.objects.create(
        name="Secondary Shelf (test)",
        description="A second category to list a product under",
        is_active=True,
    )


@pytest.mark.django_db
class TestExtraCategories:
    def test_listed_under_its_canonical_category(self, client, test_product):
        response = client.get(f"/api/products/?category={test_product.category_id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id in ids

    def test_also_listed_under_a_secondary_category(
        self, client, test_product, sprinklers
    ):
        test_product.extra_categories.add(sprinklers)

        response = client.get(f"/api/products/?category={sprinklers.id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id in ids

    def test_secondary_category_does_not_change_the_canonical_one(
        self, test_product, sprinklers
    ):
        original = test_product.category_id
        test_product.extra_categories.add(sprinklers)
        test_product.refresh_from_db()

        # Breadcrumb / schema.org still say Blended Masalas.
        assert test_product.category_id == original

    def test_not_listed_under_an_unrelated_category(
        self, client, test_product, sprinklers
    ):
        other = Category.objects.create(
            name="Totally Unrelated Shelf",
            description="Nothing here",
            is_active=True,
        )

        response = client.get(f"/api/products/?category={other.id}")

        ids = [p["id"] for p in response.json()]
        assert test_product.id not in ids

    def test_appears_once_not_duplicated(self, client, test_product, sprinklers):
        """The OR-join must be distinct()-ed or the product doubles up."""
        test_product.extra_categories.add(sprinklers)

        response = client.get(f"/api/products/?category={sprinklers.id}")

        ids = [p["id"] for p in response.json()]
        assert ids.count(test_product.id) == 1
