"""
Personalized recommendation engine (heuristic, collaborative-filtering ready).

This is the per-user counterpart to the fuzzy ``SpiceSearchEngine`` in
recommendations.py. It ranks in-stock products for a logged-in user from the
behavioral signals we collect (orders, favorites, cart, and UserEvent views/
clicks).

The final score is a simple weighted sum of independent signal terms. A
``cf_score`` term is included but currently returns 0 — it is the slot where a
collaborative-filtering model output gets blended in later (the "hybrid, phased"
plan), at which point only its weight needs to change.
"""
from collections import defaultdict
from datetime import timedelta
import logging

from django.db.models import Count
from django.utils import timezone
from django.utils.translation import get_language

from .models import Product
from .serializers import SearchProductSerializer
from .cache import make_cache_key, TTL_SHORT, TTL_MEDIUM
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Signal weights. Tuned by intent, not data, for the first iteration:
# a past purchase says more about taste than a fleeting product view.
W_CATEGORY = 3.0       # affinity for the product's category
W_COPURCHASE = 2.5     # bought by others alongside what this user bought
W_RECENT_VIEW = 1.5    # user recently viewed/clicked this exact product
W_POPULARITY = 1.0     # global order popularity (mild, breaks ties)
W_FEATURED = 0.5       # merchandising boost
W_CF = 0.0             # collaborative-filtering slot — disabled until phase 2
# TODO(geo): regional-popularity slot. analytics.UserGeo now captures each
# consenting user's coarse city/state/pincode_prefix. Once enough data
# accumulates, blend a region-filtered popularity term here (mirror _popularity
# but scope the OrderItem aggregation to the user's state) and bump W_GEO > 0.
W_GEO = 0.0            # regional-popularity slot — capture live, ranking deferred

# Per-signal contribution to category affinity.
CAT_PURCHASE = 3.0
CAT_FAVORITE = 2.0
CAT_CART = 1.5
CAT_VIEW = 1.0

RECENT_DAYS = 30
CACHE_PREFIX_RECS = 'recs'


class RecommendationEngine:
    def __init__(self, user):
        self.user = user

    # ----- signal gathering -----

    def _category_affinity(self):
        """Map of category_id -> affinity score from this user's behavior."""
        scores = defaultdict(float)

        from orders.models import OrderItem
        from cart.models import Favorite, CartItem
        from analytics.models import UserEvent

        for cat_id in OrderItem.objects.filter(
            order__user=self.user, product__isnull=False
        ).values_list('product__category_id', flat=True):
            if cat_id:
                scores[cat_id] += CAT_PURCHASE

        for cat_id in Favorite.objects.filter(
            user=self.user
        ).values_list('product__category_id', flat=True):
            if cat_id:
                scores[cat_id] += CAT_FAVORITE

        for cat_id in CartItem.objects.filter(
            cart__user=self.user, product__isnull=False
        ).values_list('product__category_id', flat=True):
            if cat_id:
                scores[cat_id] += CAT_CART

        since = timezone.now() - timedelta(days=RECENT_DAYS)
        events = UserEvent.objects.filter(
            user=self.user,
            event_type__in=['view', 'click'],
            created_at__gte=since,
        ).values_list('category_id', 'product__category_id')
        for cat_id, prod_cat_id in events:
            resolved = cat_id or prod_cat_id
            if resolved:
                scores[resolved] += CAT_VIEW

        return scores

    def _purchased_product_ids(self):
        from orders.models import OrderItem
        return set(OrderItem.objects.filter(
            order__user=self.user, product__isnull=False
        ).values_list('product_id', flat=True))

    def _copurchase_counts(self, purchased_ids):
        """
        Products frequently appearing in the same orders as the user's
        purchases (a lightweight item-item co-occurrence signal).
        """
        if not purchased_ids:
            return {}
        from orders.models import OrderItem
        related_order_ids = OrderItem.objects.filter(
            product_id__in=purchased_ids
        ).values_list('order_id', flat=True)
        rows = OrderItem.objects.filter(
            order_id__in=related_order_ids, product__isnull=False,
        ).exclude(
            product_id__in=purchased_ids
        ).values('product_id').annotate(c=Count('id'))
        return {r['product_id']: r['c'] for r in rows}

    def _recent_viewed_ids(self):
        from analytics.models import UserEvent
        since = timezone.now() - timedelta(days=RECENT_DAYS)
        return set(UserEvent.objects.filter(
            user=self.user,
            event_type__in=['view', 'click'],
            product__isnull=False,
            created_at__gte=since,
        ).values_list('product_id', flat=True))

    def _popularity(self):
        # Global order popularity is identical for every user, so compute it
        # once and share it rather than re-aggregating the whole OrderItem
        # table on each user's (cold-cache) recommendation request.
        return _global_popularity()

    def _cf_score(self, product_id):
        """Collaborative-filtering term — phase-2 hybrid slot (no-op for now)."""
        return 0.0

    # ----- ranking -----

    def recommend(self, limit=12):
        affinity = self._category_affinity()
        purchased_ids = self._purchased_product_ids()
        copurchase = self._copurchase_counts(purchased_ids)
        recent_viewed = self._recent_viewed_ids()

        if not affinity and not copurchase and not recent_viewed:
            return self._fallback(limit)

        popularity = self._popularity()
        max_pop = max(popularity.values()) if popularity else 1
        max_copurchase = max(copurchase.values()) if copurchase else 1

        candidates = list(
            Product.objects.filter(is_active=True, stock__gt=0).select_related('category')
        )

        scored = []
        for product in candidates:
            score = 0.0
            score += W_CATEGORY * affinity.get(product.category_id, 0.0)
            if copurchase:
                score += W_COPURCHASE * (copurchase.get(product.id, 0) / max_copurchase)
            if product.id in recent_viewed:
                score += W_RECENT_VIEW
            if popularity:
                score += W_POPULARITY * (popularity.get(product.id, 0) / max_pop)
            if product.is_featured:
                score += W_FEATURED
            score += W_CF * self._cf_score(product.id)

            if score > 0:
                scored.append((score, product))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        # Cold-signal users may not fill the row — pad with popular fallback.
        if len(top) < limit:
            chosen_ids = {p.id for _, p in top}
            for product in self._fallback_queryset(limit * 2):
                if product.id not in chosen_ids:
                    top.append((0.0, product))
                    chosen_ids.add(product.id)
                if len(top) >= limit:
                    break

        return self._serialize([p for _, p in top[:limit]], [s for s, _ in top[:limit]])

    def _fallback_queryset(self, limit):
        """Featured-first, then any active in-stock product."""
        featured = list(Product.objects.filter(
            is_active=True, stock__gt=0, is_featured=True
        ).select_related('category')[:limit])
        if len(featured) >= limit:
            return featured
        seen = {p.id for p in featured}
        extra = Product.objects.filter(
            is_active=True, stock__gt=0
        ).exclude(id__in=seen).select_related('category')[:limit - len(featured)]
        return featured + list(extra)

    def _fallback(self, limit):
        products = self._fallback_queryset(limit)
        return self._serialize(products, [0.0] * len(products), score_type='popular')

    def _serialize(self, products, scores, score_type='personalized'):
        data = SearchProductSerializer(products, many=True).data
        for item, score in zip(data, scores):
            item['score'] = round(float(score), 3)
            item['score_type'] = score_type
        return data


def _compute_popularity():
    from orders.models import OrderItem
    rows = OrderItem.objects.filter(
        product__isnull=False
    ).values('product_id').annotate(c=Count('id'))
    return {r['product_id']: r['c'] for r in rows}


def _global_popularity():
    """Order popularity per product, cached across all users (not user-scoped)."""
    key = make_cache_key(CACHE_PREFIX_RECS, 'popularity', 'v1')
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _compute_popularity()
    cache.set(key, data, TTL_MEDIUM)
    return data


def _cache_key(user_id, context, limit):
    # Include language so a user who switches language gets recommendations with
    # translated product names rather than the cached English ones.
    return make_cache_key(CACHE_PREFIX_RECS, user_id, context, limit, get_language())


def get_recommendations(user, limit=12, context='home'):
    """Cached entry point used by the API view."""
    key = _cache_key(user.id, context, limit)
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = RecommendationEngine(user).recommend(limit=limit)
    cache.set(key, data, TTL_SHORT)
    return data


def invalidate_user_recommendations(user_id):
    """Drop a user's cached recommendations (e.g. after a purchase).

    Redis clears every (context, limit) variant by pattern. Pattern matching is
    a no-op on the locmem backend (dev/tests), so we also delete the default
    key directly there — same belt-and-suspenders approach as the search cache.
    """
    try:
        if hasattr(cache, 'delete_pattern'):
            # Raw pattern only — django-redis prepends KEY_PREFIX + version.
            cache.delete_pattern(f'{CACHE_PREFIX_RECS}:{user_id}:*')
        else:
            cache.delete(_cache_key(user_id, 'home', 12))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(f"recs cache invalidation skipped for user {user_id}: {exc}")
