"""Search must be able to say "no results" (audit issue #17).

A nonsense query used to come back with a product anyway: with zero direct
matches, unified_search padded the list with `_other_recommendations`, so the
UI could never render an empty state.
"""
import pytest

from products.recommendations import SpiceSearchEngine


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
        """Merchandising fallback survives — but not disguised as a match."""
        result = engine.unified_search("zzzzqqqxyzzy", top_k=20)

        assert "suggestions" in result
        # Whatever we suggest must not be reported as a search hit.
        assert result["total_results"] == 0

    def test_real_query_still_matches(self, engine, test_product):
        result = engine.unified_search(test_product.name, top_k=20)

        assert result["total_results"] >= 1
        names = [p["name"] for p in result["products"]]
        assert test_product.name in names

    def test_matching_query_returns_no_suggestions(self, engine, test_product):
        """Suggestions only appear in the empty state."""
        result = engine.unified_search(test_product.name, top_k=20)

        assert result["suggestions"] == []
