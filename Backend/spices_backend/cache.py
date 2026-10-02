"""
Compatibility shim — the cache utilities live in products/cache.py.
This module re-exports everything so any stale bytecode or old import
path (spices_backend.cache) still resolves without error.
"""
from products.cache import (  # noqa: F401
    make_cache_key,
    get_cached_or_set,
    invalidate_by_prefix,
    invalidate_product_cache,
    invalidate_category_cache,
    invalidate_combo_cache,
    invalidate_search_cache,
    invalidate_all_caches,
    get_search_corpus_key,
    get_product_list_key,
    get_product_detail_key,
    get_sections_key,
    get_category_list_key,
    get_combo_list_key,
    CACHE_PREFIX_PRODUCTS,
    CACHE_PREFIX_CATEGORIES,
    CACHE_PREFIX_COMBOS,
    CACHE_PREFIX_SECTIONS,
    CACHE_PREFIX_SEARCH,
    TTL_SHORT,
    TTL_MEDIUM,
    TTL_LONG,
)
