"""
Cache utilities for the products app.
Provides helper functions for caching product-related data and automatic cache invalidation.
Works with both Redis (production) and local memory cache (development).
"""
from django.core.cache import cache
from django.conf import settings
import hashlib
import logging

logger = logging.getLogger(__name__)

# Cache key prefixes
CACHE_PREFIX_PRODUCTS = 'products'
CACHE_PREFIX_CATEGORIES = 'categories'
CACHE_PREFIX_COMBOS = 'combos'
CACHE_PREFIX_SECTIONS = 'sections'
CACHE_PREFIX_SEARCH = 'search'

# Default TTLs (use from settings if available)
TTL_SHORT = getattr(settings, 'CACHE_TTL_SHORT', 60)
TTL_MEDIUM = getattr(settings, 'CACHE_TTL_MEDIUM', 300)
TTL_LONG = getattr(settings, 'CACHE_TTL_LONG', 900)


def make_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Generate a consistent cache key from prefix and arguments.
    
    Args:
        prefix: Cache key prefix (e.g., 'products', 'categories')
        *args: Positional arguments to include in key
        **kwargs: Keyword arguments to include in key
    
    Returns:
        A consistent, unique cache key string
    """
    key_parts = [prefix] + [str(a) for a in args]
    if kwargs:
        sorted_kwargs = sorted(kwargs.items())
        key_parts.extend([f"{k}:{v}" for k, v in sorted_kwargs])
    key = ":".join(key_parts)
    
    # Hash if key is too long (Redis max key length is 512MB, but shorter is better)
    if len(key) > 200:
        key = f"{prefix}:{hashlib.md5(key.encode()).hexdigest()}"
    return key


def get_cached_or_set(cache_key: str, callback, timeout: int = None):
    """
    Get data from cache or compute and store it.
    
    Args:
        cache_key: The cache key to use
        callback: A callable that returns the data if cache miss
        timeout: Cache timeout in seconds (uses default if None)
    
    Returns:
        The cached or computed data
    """
    data = cache.get(cache_key)
    if data is not None:
        logger.debug(f"Cache HIT: {cache_key}")
        return data
    
    # Cache miss - compute the data
    data = callback()
    timeout = timeout or TTL_MEDIUM
    cache.set(cache_key, data, timeout)
    logger.debug(f"Cache SET: {cache_key} (TTL: {timeout}s)")
    return data


def invalidate_by_prefix(prefix: str):
    """
    Invalidate all cache keys with a given prefix.
    Works with both Redis (pattern matching) and local memory cache.
    
    Args:
        prefix: The cache prefix to invalidate
    """
    try:
        # For django-redis, use delete_pattern. Pass the RAW key pattern only —
        # django-redis prepends KEY_PREFIX and the cache version itself (e.g.
        # 'ngu:1:'), so hard-coding 'ngu:' here would double the prefix
        # ('ngu:1:ngu:categories:*') and match nothing.
        if hasattr(cache, 'delete_pattern'):
            pattern = f'{prefix}:*'
            deleted = cache.delete_pattern(pattern)
            logger.info(f"Cache invalidated: {pattern} ({deleted} keys)")
        else:
            # For local memory cache, we can't do pattern matching
            # Clear specific known keys instead
            logger.debug(f"Pattern-based cache invalidation not available for prefix: {prefix}")
    except Exception as e:
        logger.error(f"Cache invalidation failed for prefix {prefix}: {e}")


def invalidate_product_cache():
    """Invalidate all product-related caches."""
    invalidate_by_prefix(CACHE_PREFIX_PRODUCTS)
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)


def invalidate_category_cache():
    """Invalidate all category caches."""
    invalidate_by_prefix(CACHE_PREFIX_CATEGORIES)


def invalidate_combo_cache():
    """Invalidate all combo caches."""
    invalidate_by_prefix(CACHE_PREFIX_COMBOS)
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)


def get_search_corpus_key() -> str:
    """Cache key for the assembled fuzzy-search corpus."""
    return make_cache_key(CACHE_PREFIX_SEARCH, 'corpus', 'v1')


def invalidate_search_cache():
    """Invalidate the search corpus and suggest-response caches."""
    invalidate_by_prefix(CACHE_PREFIX_SEARCH)
    # Pattern invalidation is a no-op on the locmem backend (dev/tests);
    # delete the corpus key directly so it is never stale there.
    cache.delete(get_search_corpus_key())


def invalidate_all_caches():
    """Invalidate all product, combo, category and section caches."""
    invalidate_by_prefix(CACHE_PREFIX_PRODUCTS)
    invalidate_by_prefix(CACHE_PREFIX_CATEGORIES)
    invalidate_by_prefix(CACHE_PREFIX_COMBOS)
    invalidate_by_prefix(CACHE_PREFIX_SECTIONS)
    invalidate_by_prefix(CACHE_PREFIX_SEARCH)


# Cache key generators for specific use cases
def get_product_list_key(query_params: dict = None) -> str:
    """Generate cache key for product list endpoint."""
    if query_params:
        return make_cache_key(CACHE_PREFIX_PRODUCTS, 'list', **query_params)
    return make_cache_key(CACHE_PREFIX_PRODUCTS, 'list')


def get_product_detail_key(slug_or_id: str) -> str:
    """Generate cache key for product detail endpoint."""
    return make_cache_key(CACHE_PREFIX_PRODUCTS, 'detail', slug_or_id)


def get_sections_key() -> str:
    """Generate cache key for sections endpoint."""
    return make_cache_key(CACHE_PREFIX_SECTIONS, 'all')


def get_category_list_key() -> str:
    """Generate cache key for category list endpoint."""
    return make_cache_key(CACHE_PREFIX_CATEGORIES, 'list')


def get_combo_list_key(query_params: dict = None) -> str:
    """Generate cache key for combo list endpoint."""
    if query_params:
        return make_cache_key(CACHE_PREFIX_COMBOS, 'list', **query_params)
    return make_cache_key(CACHE_PREFIX_COMBOS, 'list')
