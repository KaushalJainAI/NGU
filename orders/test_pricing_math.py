"""
Order pricing math — the most safety-critical numbers in the system.

The existing orders/tests.py confirms an order *can* be created; these tests
assert the *exact* money: subtotal, percentage-coupon discount + rounding,
proportional per-item discount, the ₹500 free-shipping boundary, 5% tax on the
discounted amount, the grand total, coupon usage accounting, and stock
decrement — including the industry edge case where stock drops between
add-to-cart and checkout.

Pricing rules (orders/views.py):
  discount        = subtotal * percent/100          (quantized to 0.01)
  discounted_sub  = subtotal - discount
  shipping        = 0 if discounted_sub >= FREE_SHIPPING_THRESHOLD (500) else SHIPPING_CHARGE (69)
  tax             = discounted_sub * 0.05            (quantized to 0.01)
  total           = discounted_sub + shipping + tax
"""
from decimal import Decimal

import pytest
from django.utils import timezone
from datetime import timedelta

from conftest import create_test_image
from products.models import Product
from cart.models import Cart, CartItem
from orders.models import Order
from admin_panel.models import Coupon

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Test Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _product(category, price, stock=100, discount=None, name="Item"):
    return Product.objects.create(
        name=name, category=category, description="x",
        price=Decimal(price), discount_price=(Decimal(discount) if discount else None),
        stock=stock, weight=Decimal("250.00"), unit="g", spice_form="powder",
        is_active=True, image=create_test_image(f"{name}.jpg"),
    )


def _cart_line(user, product, qty):
    cart, _ = Cart.objects.get_or_create(user=user)
    CartItem.objects.create(cart=cart, product=product, item_type="product", quantity=qty)
    return cart


def _place(client, **extra):
    return client.post(URL, {**ADDR, **extra}, format="json")


@pytest.mark.django_db
class TestTotalsWithoutCoupon:
    def test_subtotal_under_threshold_charges_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "200.00"), 2)  # subtotal 400
        r = _place(authenticated_client)
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.subtotal == Decimal("400.00")
        assert o.discount_amount == Decimal("0")
        assert o.shipping_charge == Decimal("50")      # 400 < 500
        assert o.tax == Decimal("20.00")               # 400 * 0.05
        assert o.total_amount == Decimal("470.00")     # 400 + 50 + 20

    def test_subtotal_exactly_500_is_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "250.00"), 2)  # subtotal 500
        r = _place(authenticated_client)
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")       # boundary: >= 500
        assert o.tax == Decimal("25.00")
        assert o.total_amount == Decimal("525.00")

    def test_subtotal_above_threshold_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "300.00"), 2)  # 600
        o_resp = _place(authenticated_client)
        assert o_resp.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")
        assert o.total_amount == Decimal("630.00")     # 600 + 0 + 30


@pytest.mark.django_db
class TestTotalsWithCoupon:
    def _coupon(self, percent, **kw):
        return Coupon.objects.create(
            code=kw.pop("code", "SAVE"), discount_percent=percent, is_active=True,
            valid_until=timezone.now() + timedelta(days=10), **kw,
        )

    def test_ten_percent_off_above_threshold(self, authenticated_client, test_user, test_category):
        c = self._coupon(10, code="SAVE10")
        _cart_line(test_user, _product(test_category, "300.00"), 2)  # 600
        r = _place(authenticated_client, coupon_code="SAVE10")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.discount_amount == Decimal("60.00")   # 600 * 10%
        # discounted 540 -> free shipping, tax 27.00
        assert o.shipping_charge == Decimal("0")
        assert o.tax == Decimal("27.00")
        assert o.total_amount == Decimal("567.00")
        c.refresh_from_db()
        assert c.usage_count == 1                       # usage accounted exactly once

    def test_coupon_code_is_case_insensitive(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="SAVE10")
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        r = _place(authenticated_client, coupon_code="save10")   # lower-case
        assert r.status_code == 201
        assert Order.objects.get(user=test_user).discount_amount == Decimal("60.00")

    def test_full_discount_still_charges_shipping(self, authenticated_client, test_user, test_category):
        # 100% coupon -> items free, but a sub-₹500 order still pays shipping and
        # tax is 0. Guards against a "free order" total of 0.
        self._coupon(100, code="FREE100")
        _cart_line(test_user, _product(test_category, "200.00"), 2)  # 400
        r = _place(authenticated_client, coupon_code="FREE100")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.discount_amount == Decimal("400.00")
        assert o.tax == Decimal("0.00")
        assert o.shipping_charge == Decimal("50")
        assert o.total_amount == Decimal("50.00")

    def test_coupon_below_minimum_is_rejected(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="BIGSPEND", minimum_order_amount=Decimal("1000.00"))
        _cart_line(test_user, _product(test_category, "200.00"), 1)  # 200 < 1000
        r = _place(authenticated_client, coupon_code="BIGSPEND")
        assert r.status_code == 400
        assert not Order.objects.filter(user=test_user).exists()

    # ---- the error message must state the ACTUAL reason ------------------- #
    def test_message_for_below_minimum_states_shortfall(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="MIN1000", minimum_order_amount=Decimal("1000.00"))
        _cart_line(test_user, _product(test_category, "200.00"), 1)  # subtotal 200, short by 800
        msg = _place(authenticated_client, coupon_code="MIN1000").json()["error"]
        assert "800" in msg and "1000" in msg          # not a vague catch-all

    def test_message_for_expired_says_expired(self, authenticated_client, test_user, test_category):
        Coupon.objects.create(code="OLD", discount_percent=10, is_active=True,
                              valid_until=timezone.now() - timedelta(days=1))
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        msg = _place(authenticated_client, coupon_code="OLD").json()["error"]
        assert "expired" in msg.lower()

    def test_message_for_unknown_code_says_invalid_code(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        msg = _place(authenticated_client, coupon_code="NOPE404").json()["error"]
        assert "valid coupon code" in msg.lower()

    def test_exhausted_coupon_is_rejected(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="ONEUSE", max_usage=1)
        Coupon.objects.filter(code="ONEUSE").update(usage_count=1)  # already used up
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        r = _place(authenticated_client, coupon_code="ONEUSE")
        assert r.status_code == 400
        assert "usage limit" in r.json()["error"].lower()


@pytest.mark.django_db
class TestProportionalItemDiscount:
    def test_discount_split_across_lines(self, authenticated_client, test_user, test_category):
        # Two lines, 10% off. Each line's discount is proportional to its share.
        cart, _ = Cart.objects.get_or_create(user=test_user)
        a = _product(test_category, "400.00", name="A")   # line total 400
        b = _product(test_category, "100.00", name="B")   # line total 200 (qty 2)
        CartItem.objects.create(cart=cart, product=a, item_type="product", quantity=1)
        CartItem.objects.create(cart=cart, product=b, item_type="product", quantity=2)
        Coupon.objects.create(code="SPLIT", discount_percent=10, is_active=True,
                              valid_until=timezone.now() + timedelta(days=10))
        r = _place(authenticated_client, coupon_code="SPLIT")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        # subtotal 600, total discount 60. The sum of per-item discounts must
        # equal the order-level discount (no money created or lost in rounding).
        per_item = sum((i.discount_amount for i in o.items.all()), Decimal("0"))
        assert per_item == o.discount_amount == Decimal("60.00")


@pytest.mark.django_db
class TestStockOnCheckout:
    def test_stock_decremented_exactly(self, authenticated_client, test_user, test_category):
        p = _product(test_category, "100.00", stock=10)
        _cart_line(test_user, p, 3)
        assert _place(authenticated_client).status_code == 201
        p.refresh_from_db()
        assert p.stock == 7

    def test_stock_dropped_after_add_to_cart_blocks_checkout(self, authenticated_client, test_user, test_category):
        # Classic race: item added to cart, then stock falls below the cart qty
        # (e.g. another buyer). Checkout must refuse, not oversell.
        p = _product(test_category, "100.00", stock=10)
        _cart_line(test_user, p, 5)
        Product.objects.filter(pk=p.pk).update(stock=2)   # stock dropped to 2
        r = _place(authenticated_client)
        assert r.status_code == 400
        assert "stock" in r.json().get("error", "").lower()
        p.refresh_from_db()
        assert p.stock == 2                                # unchanged, not oversold
        assert not Order.objects.filter(user=test_user).exists()
