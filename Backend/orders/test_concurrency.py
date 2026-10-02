"""
Concurrency regression tests for G4 and G5 — the real races.

These run two checkouts *simultaneously* on real threads (transaction=True so
each thread commits on its own connection, and select_for_update actually
contends). Before the fix:
  G4 — both orders for the last unit committed (stock clamped to 0) -> oversell.
  G5 — both orders redeemed a max_usage=1 coupon -> usage_count == 2.
After the fix exactly one succeeds.

Postgres is required for true row-level locking (the suite's default test DB).
"""
import threading
from decimal import Decimal

import pytest
from django.db import connection
from rest_framework.test import APIClient

from conftest import create_test_image
from products.models import Product
from cart.models import Cart, CartItem
from orders.models import Order
from admin_panel.models import Coupon

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _make_user(django_user_model, n):
    # AP7b: the COD guard needs verified inboxes — these racers model
    # established buyers, so verify them (the race under test is stock/coupon
    # locking, not verification).
    return django_user_model.objects.create_user(
        username=f"race{n}", email=f"race{n}@example.com", password="x",
        email_verified=True)


def _product(cat, stock, price="600.00"):
    return Product.objects.create(
        name="RaceItem", category=cat, description="x", price=Decimal(price), stock=stock,
        weight=Decimal("250.00"), unit="g", spice_form="powder", is_active=True,
        image=create_test_image("race.jpg"),
    )


def _cart(user, product, qty=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    CartItem.objects.create(cart=cart, product=product, item_type="product", quantity=qty)


def _run_concurrently(users, payload):
    """POST an order as each user at the same time; return list of status codes."""
    results = {}
    barrier = threading.Barrier(len(users))

    def worker(idx, user):
        try:
            client = APIClient()
            client.force_authenticate(user=user)
            barrier.wait()                      # release all threads together
            resp = client.post(URL, payload, format="json")
            results[idx] = resp.status_code
        finally:
            connection.close()                  # don't leak the thread's connection

    threads = [threading.Thread(target=worker, args=(i, u)) for i, u in enumerate(users)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return list(results.values())


@pytest.mark.django_db(transaction=True)
def test_G4_concurrent_checkout_cannot_oversell(django_user_model, test_category):
    """Two buyers race for the last unit — exactly one wins, no oversell."""
    product = _product(test_category, stock=1)
    u1, u2 = _make_user(django_user_model, 1), _make_user(django_user_model, 2)
    _cart(u1, product, qty=1)
    _cart(u2, product, qty=1)

    codes = _run_concurrently([u1, u2], ADDR)

    product.refresh_from_db()
    assert product.stock == 0                         # never negative / oversold
    assert Order.objects.count() == 1                 # exactly one order placed
    assert sorted(codes) == [201, 400]                # one win, one rejected


@pytest.mark.django_db(transaction=True)
def test_G5_single_use_coupon_not_over_redeemed(django_user_model, test_category):
    """Two buyers race to redeem a max_usage=1 coupon — it is used at most once."""
    product = _product(test_category, stock=10)       # plenty of stock; the race is the coupon
    Coupon.objects.create(code="ONERACE", discount_percent=10, is_active=True, max_usage=1)
    u1, u2 = _make_user(django_user_model, 1), _make_user(django_user_model, 2)
    _cart(u1, product, qty=1)
    _cart(u2, product, qty=1)

    codes = _run_concurrently([u1, u2], {**ADDR, "coupon_code": "ONERACE"})

    coupon = Coupon.objects.get(code="ONERACE")
    assert coupon.usage_count == 1                     # never redeemed twice
    assert codes.count(201) == 1                       # exactly one checkout used it
    assert codes.count(400) == 1
