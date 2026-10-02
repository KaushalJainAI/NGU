"""
Catalog, search, autocomplete, and search input bounds.
"""
import pytest

MAX_SEARCH_Q = 200


# --- From test_health_and_catalog.py ---

@pytest.mark.smoke
def test_health(session, api):
    r = session.get(f"{api}/health/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "healthy"
    assert body.get("service") == "ngu-backend"


@pytest.mark.smoke
@pytest.mark.catalog
def test_categories_list(session, api):
    r = session.get(f"{api}/categories/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert isinstance(items, list)


@pytest.mark.smoke
@pytest.mark.catalog
def test_products_list_and_detail(session, api):
    r = session.get(f"{api}/products/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert isinstance(items, list)
    if not items:
        pytest.skip("catalog is empty on this target")

    first = items[0]
    slug = first.get("slug")
    assert slug, f"product missing slug: {first}"
    detail = session.get(f"{api}/products/{slug}/")
    assert detail.status_code == 200
    assert detail.json().get("slug") == slug


@pytest.mark.catalog
def test_combos_list(session, api):
    r = session.get(f"{api}/combos/")
    assert r.status_code == 200


@pytest.mark.catalog
def test_spice_forms(session, api):
    r = session.get(f"{api}/spice-forms/")
    assert r.status_code == 200


@pytest.mark.catalog
def test_products_pagination_is_bounded(session, api):
    """A naive `page_size` should not let a client exfiltrate the whole table."""
    r = session.get(f"{api}/products/", params={"page_size": 100000})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict) and "results" in data:
            assert len(data["results"]) <= 1000


# --- From test_search.py ---

@pytest.mark.smoke
@pytest.mark.catalog
def test_search_basic(session, api):
    r = session.get(f"{api}/search/", params={"q": "masala"})
    assert r.status_code == 200
    assert r.headers.get("Content-Type", "").startswith("application/json")


@pytest.mark.catalog
def test_search_empty_query(session, api):
    r = session.get(f"{api}/search/", params={"q": ""})
    assert r.status_code in (200, 400)


@pytest.mark.catalog
def test_search_suggest(session, api):
    r = session.get(f"{api}/search/suggest/", params={"q": "tur"})
    assert r.status_code == 200


@pytest.mark.catalog
def test_search_unicode_and_long_query(session, api):
    r = session.get(f"{api}/search/", params={"q": "हल्दी " + "a" * 5000})
    assert r.status_code in (200, 400, 413)


# --- From test_input_bounds.py (search bounds) ---

@pytest.mark.catalog
def test_search_query_too_long_rejected(session, api):
    r = session.get(f"{api}/search/", params={"q": "a" * (MAX_SEARCH_Q + 1)})
    assert r.status_code == 400


@pytest.mark.catalog
def test_search_extreme_top_k_is_clamped_not_500(session, api):
    r = session.get(f"{api}/search/", params={"q": "masala", "top_k": 10_000_000, "threshold": -50})
    assert r.status_code == 200
