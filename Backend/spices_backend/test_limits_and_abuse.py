"""
Regression tests for the boundedness + abuse-resistance layer.

Every externally-influenced value has an enforced bound; an out-of-bound request
must return a clean 4xx (never a 500), and repeat offenders are trackable/bannable.
Covers: cart quantity / cart size / sync size, order overflow guard, review size,
search bounds, order + cart rate limits, and the abuse flag/ban path.
"""
from decimal import Decimal

import pytest
from django.core.cache import cache

from conftest import create_test_image
from products.models import Product
from cart.models import Cart, CartItem
from orders.models import Order
from spices_backend import abuse, limits

CART_ADD = "/api/cart/add_item/"
CART_UPDATE = "/api/cart/update_item/"
CART_SYNC = "/api/cart/sync/"
ORDER_URL = "/api/orders/"
SEARCH_URL = "/api/search/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _product(cat, name="Item", price="100.00", stock=10000):
    return Product.objects.create(
        name=name, category=cat, description="x", price=Decimal(price), stock=stock,
        weight=Decimal("250.00"), unit="g", spice_form="powder", is_active=True,
        image=create_test_image(f"{name}.jpg"),
    )


# --------------------------------------------------------------------------- #
# Cart bounds
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCartBounds:
    def test_add_quantity_over_max_rejected(self, authenticated_client, test_category):
        p = _product(test_category)
        r = authenticated_client.post(CART_ADD, {"product_id": p.id, "quantity": limits.MAX_ITEM_QUANTITY + 1}, format="json")
        assert r.status_code == 400
        assert str(limits.MAX_ITEM_QUANTITY) in r.json()["error"]

    def test_add_quantity_at_max_ok(self, authenticated_client, test_category):
        p = _product(test_category)
        r = authenticated_client.post(CART_ADD, {"product_id": p.id, "quantity": limits.MAX_ITEM_QUANTITY}, format="json")
        assert r.status_code in (200, 201)

    def test_update_quantity_over_max_rejected(self, authenticated_client, test_category):
        p = _product(test_category)
        authenticated_client.post(CART_ADD, {"product_id": p.id, "quantity": 1}, format="json")
        r = authenticated_client.post(CART_UPDATE, {"product_id": p.id, "quantity": limits.MAX_ITEM_QUANTITY + 5}, format="json")
        assert r.status_code == 400

    def test_cart_item_count_capped(self, authenticated_client, test_category):
        # Fill the cart to the cap, then the next distinct item is rejected.
        for i in range(limits.MAX_CART_ITEMS):
            p = _product(test_category, name=f"P{i}")
            assert authenticated_client.post(CART_ADD, {"product_id": p.id, "quantity": 1}, format="json").status_code in (200, 201)
        over = _product(test_category, name="OverflowLine")
        r = authenticated_client.post(CART_ADD, {"product_id": over.id, "quantity": 1}, format="json")
        assert r.status_code == 400
        assert str(limits.MAX_CART_ITEMS) in r.json()["error"]

    def test_sync_payload_size_capped(self, authenticated_client, test_category):
        p = _product(test_category)
        items = [{"product_id": p.id, "quantity": 1} for _ in range(limits.MAX_SYNC_ITEMS + 1)]
        r = authenticated_client.post(CART_SYNC, {"items": items}, format="json")
        assert r.status_code == 400
        assert str(limits.MAX_SYNC_ITEMS) in r.json()["error"]


# --------------------------------------------------------------------------- #
# Order overflow guard (the V1 crash -> now a clean 400)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestOrderOverflowGuard:
    def test_extreme_quantity_does_not_500(self, authenticated_client, test_user, test_category):
        # Force an oversized line straight into the cart (bypassing the add cap)
        # to prove the order path itself refuses it cleanly rather than 500ing.
        p = _product(test_category, price="99999.99", stock=10_000_000)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, product=p, item_type="product", quantity=5000)
        r = authenticated_client.post(ORDER_URL, ADDR, format="json")
        assert r.status_code == 400            # not 500
        assert not Order.objects.filter(user=test_user).exists()

    def test_order_500_does_not_leak_internal_error(self, authenticated_client, test_user, test_category):
        # Even if something unexpected raises, the body must be generic.
        p = _product(test_category, price="99999.99", stock=10_000_000)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, product=p, item_type="product", quantity=5000)
        r = authenticated_client.post(ORDER_URL, ADDR, format="json")
        body = r.json().get("error", "")
        assert "numeric" not in body.lower() and "precision" not in body.lower()


# --------------------------------------------------------------------------- #
# Review size
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_review_comment_length_capped(authenticated_client, test_category):
    p = _product(test_category)
    huge = "x" * (limits.MAX_REVIEW_COMMENT + 1)
    r = authenticated_client.post("/api/reviews/", {
        "item_type": "product", "product": p.id, "rating": 5, "title": "t", "comment": huge,
    }, format="json")
    assert r.status_code == 400            # rejected by length, never stored/500


# --------------------------------------------------------------------------- #
# Search bounds
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestSearchBounds:
    def test_query_too_long_rejected(self, api_client):
        r = api_client.get(SEARCH_URL, {"q": "a" * (limits.MAX_SEARCH_Q + 1)})
        assert r.status_code == 400

    def test_extreme_top_k_is_clamped_not_500(self, api_client, test_category):
        _product(test_category, name="Turmeric")
        r = api_client.get(SEARCH_URL, {"q": "turmeric", "top_k": 10_000_000, "threshold": -50})
        assert r.status_code == 200        # clamped, handled


# --------------------------------------------------------------------------- #
# Rate limits
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestRateLimits:
    def test_order_rate_limit(self, authenticated_client, test_user, test_category):
        # Place orders until the per-minute order throttle trips (429).
        statuses = []
        for _ in range(15):
            p = _product(test_category, name=f"R{_}")
            cart, _c = Cart.objects.get_or_create(user=test_user)
            CartItem.objects.create(cart=cart, product=p, item_type="product", quantity=1)
            statuses.append(authenticated_client.post(ORDER_URL, ADDR, format="json").status_code)
            if statuses[-1] == 429:
                break
        assert 429 in statuses

    def test_cart_write_rate_limit(self, authenticated_client, test_category):
        p = _product(test_category)
        statuses = []
        for _ in range(80):
            statuses.append(authenticated_client.post(CART_ADD, {"product_id": p.id, "quantity": 1}, format="json").status_code)
            if statuses[-1] == 429:
                break
        assert 429 in statuses


# --------------------------------------------------------------------------- #
# Abuse track + ban
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestAbuseLayer:
    def test_flag_increments_strikes(self, rf):
        cache.clear()
        request = rf.post("/api/cart/add_item/", REMOTE_ADDR="9.9.9.9")
        request.user = type("Anon", (), {"is_authenticated": False})()
        abuse.flag_suspicious(request, reason="test")
        abuse.flag_suspicious(request, reason="test")
        assert cache.get("abuse:strikes:9.9.9.9") == 2

    def test_block_and_unblock(self):
        abuse.block_ip("8.8.8.8")
        assert abuse.is_blocked("8.8.8.8") is True
        abuse.unblock_ip("8.8.8.8")
        assert abuse.is_blocked("8.8.8.8") is False

    def test_banned_ip_gets_403_via_middleware(self, client):
        abuse.block_ip("7.7.7.7")
        try:
            resp = client.get("/api/health/", REMOTE_ADDR="7.7.7.7")
            assert resp.status_code == 403
            # an unbanned IP still works
            ok = client.get("/api/health/", REMOTE_ADDR="1.1.1.1")
            assert ok.status_code == 200
        finally:
            abuse.unblock_ip("7.7.7.7")
