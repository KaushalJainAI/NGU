"""
Checkout invariants, PDF invoices, delivery bills, date filtering, CSV export, packing slips, and recycle bin.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from admin_panel.models import Coupon
from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.invoice import (
    _money,
    _order_number,
    _customer_name,
    _two,
    _three,
    _num_words,
    _amount_in_words,
    generate_invoice_pdf,
)
from orders.models import Order, OrderItem
from orders.views import OrderViewSet
from payments import services
from payments.models import Payment
from products.models import (
    Product, ProductCombo, ProductComboItem, default_variant_for,
)

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


# --- From test_pricing_math.py ---

@pytest.mark.django_db
class TestTotalsWithoutCoupon:
    def test_subtotal_under_threshold_charges_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "200.00"), 2)
        r = _place(authenticated_client)
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.subtotal == Decimal("400.00")
        assert o.discount_amount == Decimal("0")
        assert o.shipping_charge == Decimal("59")
        # Prices are GST-inclusive: the 5% is carved OUT of the ₹400 subtotal
        # (400 * 5/105), not added to it.
        assert o.tax == Decimal("19.05")
        assert o.tax_inclusive is True
        # Delivery uses the OPPOSITE convention — quoted net and taxed at 18% on
        # top (SAC 9968) — so its GST really is an addend:
        #   400 (incl. 19.05 GST) + 59 + 10.62 = 469.62
        assert o.shipping_tax == Decimal("10.62")
        assert o.total_tax == Decimal("29.67")
        assert o.total_amount == Decimal("469.62")

    def test_subtotal_exactly_500_is_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "250.00"), 2)
        r = _place(authenticated_client)
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")
        assert o.tax == Decimal("23.81")          # 500 * 5/105, contained in subtotal
        assert o.total_amount == Decimal("500.00")

    def test_subtotal_above_threshold_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        o_resp = _place(authenticated_client)
        assert o_resp.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")
        assert o.total_amount == Decimal("600.00")


@pytest.mark.django_db
class TestTotalsWithCoupon:
    def _coupon(self, percent, **kw):
        return Coupon.objects.create(
            code=kw.pop("code", "SAVE"), discount_percent=percent, is_active=True,
            valid_until=timezone.now() + timedelta(days=10), **kw,
        )

    def test_ten_percent_off_above_threshold(self, authenticated_client, test_user, test_category):
        c = self._coupon(10, code="TENOFF")
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        r = _place(authenticated_client, coupon_code="TENOFF")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.discount_amount == Decimal("60.00")
        assert o.shipping_charge == Decimal("0")
        # GST extracted from the DISCOUNTED line total: 540 * 5/105.
        assert o.tax == Decimal("25.71")
        assert o.total_amount == Decimal("540.00")
        c.refresh_from_db()
        assert c.usage_count == 1

    def test_coupon_code_is_case_insensitive(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="TENOFF")
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        r = _place(authenticated_client, coupon_code="tenoff")
        assert r.status_code == 201
        assert Order.objects.get(user=test_user).discount_amount == Decimal("60.00")

    def test_full_discount_is_zero_total_order(self, authenticated_client, test_user, test_category):
        self._coupon(100, code="FREE100")
        _cart_line(test_user, _product(test_category, "200.00"), 2)
        r = _place(authenticated_client, coupon_code="FREE100")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.discount_amount == Decimal("400.00")
        assert o.tax == Decimal("0.00")
        assert o.shipping_charge == Decimal("0.00")
        assert o.total_amount == Decimal("0.00")
        assert o.payment_status == "paid"
        assert o.status == "confirmed"

    def test_coupon_below_minimum_is_rejected(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="BIGSPEND", minimum_order_amount=Decimal("1000.00"))
        _cart_line(test_user, _product(test_category, "200.00"), 1)
        r = _place(authenticated_client, coupon_code="BIGSPEND")
        assert r.status_code == 400
        assert not Order.objects.filter(user=test_user).exists()

    def test_message_for_below_minimum_states_shortfall(self, authenticated_client, test_user, test_category):
        self._coupon(10, code="MIN1000", minimum_order_amount=Decimal("1000.00"))
        _cart_line(test_user, _product(test_category, "200.00"), 1)
        msg = _place(authenticated_client, coupon_code="MIN1000").json()["error"]
        assert "800" in msg and "1000" in msg

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
        Coupon.objects.filter(code="ONEUSE").update(usage_count=1)
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        r = _place(authenticated_client, coupon_code="ONEUSE")
        assert r.status_code == 400
        assert "usage limit" in r.json()["error"].lower()


@pytest.mark.django_db
class TestProportionalItemDiscount:
    def test_discount_split_across_lines(self, authenticated_client, test_user, test_category):
        cart, _ = Cart.objects.get_or_create(user=test_user)
        a = _product(test_category, "400.00", name="A")
        b = _product(test_category, "100.00", name="B")
        CartItem.objects.create(cart=cart, product=a, item_type="product", quantity=1)
        CartItem.objects.create(cart=cart, product=b, item_type="product", quantity=2)
        Coupon.objects.create(code="SPLIT", discount_percent=10, is_active=True,
                              valid_until=timezone.now() + timedelta(days=10))
        r = _place(authenticated_client, coupon_code="SPLIT")
        assert r.status_code == 201
        o = Order.objects.get(user=test_user)
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
        p = _product(test_category, "100.00", stock=10)
        _cart_line(test_user, p, 5)
        Product.objects.filter(pk=p.pk).update(stock=2)
        r = _place(authenticated_client)
        assert r.status_code == 400
        assert "stock" in r.json().get("error", "").lower()
        p.refresh_from_db()
        assert p.stock == 2
        assert not Order.objects.filter(user=test_user).exists()


@pytest.mark.django_db
class TestLowStockAlertOnCheckout:
    """Store-owner threshold alerts fired from the checkout transaction. The
    senders are patched (they run on transaction.on_commit → a background thread
    in prod); the assertions verify the CROSSING logic and the payload, not SMTP.
    django_capture_on_commit_callbacks(execute=True) runs the on_commit hooks
    that the default rolled-back test transaction would otherwise skip."""

    def test_alert_fires_once_when_order_crosses_threshold(
            self, authenticated_client, test_user, test_category, django_capture_on_commit_callbacks):
        # threshold default is 5; stock 6 → order 2 → 4 (crosses 6>5, 4<=5).
        p = _product(test_category, "100.00", stock=6)
        _cart_line(test_user, p, 2)
        with patch("orders.views.send_low_stock_alert") as mock_send:
            with django_capture_on_commit_callbacks(execute=True):
                assert _place(authenticated_client).status_code == 201
        mock_send.assert_called_once()
        items = mock_send.call_args.args[0]
        assert items == [{"name": p.name, "stock": 4, "threshold": 5}]

    def test_no_alert_when_already_below_threshold(
            self, authenticated_client, test_user, test_category, django_capture_on_commit_callbacks):
        # stock 4 already <= threshold 5; ordering 1 does NOT cross (before !> 5).
        p = _product(test_category, "100.00", stock=4)
        _cart_line(test_user, p, 1)
        with patch("orders.views.send_low_stock_alert") as mock_send:
            with django_capture_on_commit_callbacks(execute=True):
                assert _place(authenticated_client).status_code == 201
        mock_send.assert_not_called()

    def test_no_alert_when_staying_above_threshold(
            self, authenticated_client, test_user, test_category, django_capture_on_commit_callbacks):
        p = _product(test_category, "100.00", stock=100)
        _cart_line(test_user, p, 2)  # 100 → 98, well above 5
        with patch("orders.views.send_low_stock_alert") as mock_send:
            with django_capture_on_commit_callbacks(execute=True):
                assert _place(authenticated_client).status_code == 201
        mock_send.assert_not_called()

    def test_combo_alert_on_buildable_count_crossing(
            self, authenticated_client, test_user, test_category, django_capture_on_commit_callbacks):
        # Scarcest component (A) drives the buildable count. A uses 3 units per
        # combo; stock 20 stays well above A's OWN product threshold (5) after
        # the order, so ONLY the combo-level alert should fire — proving the two
        # signals are independent and the per-combo-qty math (units/line_qty=3).
        a = _product(test_category, "50.00", stock=20, name="CompA")
        b = _product(test_category, "50.00", stock=100, name="CompB")
        combo = ProductCombo.objects.create(
            name="Spice Box", is_active=True, low_stock_threshold=5,
        )
        ProductComboItem.objects.create(combo=combo, product=a, quantity=3)
        ProductComboItem.objects.create(combo=combo, product=b, quantity=1)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=2)
        with patch("orders.views.send_low_stock_alert") as mock_send:
            with django_capture_on_commit_callbacks(execute=True):
                assert _place(authenticated_client).status_code == 201
        mock_send.assert_called_once()
        items = mock_send.call_args.args[0]
        # buildable before = min(20//3, 100) = 6, after = min(14//3, 98) = 4;
        # crosses combo threshold 5. Components A(14) & B(98) stay above 5.
        assert items == [{"name": "Spice Box (combo)", "stock": 4, "threshold": 5}]

    def test_subject_names_the_single_low_product(self, settings):
        settings.ADMIN_ALERT_EMAIL = "owner@test.com"
        from orders.emails import send_low_stock_alert
        with patch("orders.emails._send_async") as m:
            send_low_stock_alert([{"name": "Turmeric 100g", "stock": 2, "threshold": 5}])
        subject = m.call_args.kwargs["subject"]
        assert "Turmeric 100g" in subject and "running low" in subject
        assert "Turmeric 100g" in m.call_args.kwargs["message"]

    def test_subject_names_first_product_and_counts_rest(self, settings):
        settings.ADMIN_ALERT_EMAIL = "owner@test.com"
        from orders.emails import send_low_stock_alert
        with patch("orders.emails._send_async") as m:
            send_low_stock_alert([
                {"name": "Chili 200g", "stock": 0, "threshold": 5},
                {"name": "Cumin 100g", "stock": 3, "threshold": 5},
            ])
        subject = m.call_args.kwargs["subject"]
        assert "Chili 200g" in subject and "out of stock" in subject
        assert "1 other product" in subject  # the remaining low item

    def test_coupon_usage_alert_on_crossing_limit(
            self, authenticated_client, test_user, test_category, django_capture_on_commit_callbacks):
        p = _product(test_category, "300.00", stock=100)
        _cart_line(test_user, p, 1)
        # max_usage 2, 90% → alert_level ceil(1.8)=2; pre-seed usage 1 so this
        # redemption (→2) crosses both the warn level and exhaustion.
        Coupon.objects.create(
            code="SAVE", discount_type="percent", discount_percent=10,
            is_active=True, max_usage=2, usage_count=1,
        )
        with patch("orders.views.send_coupon_usage_alert") as mock_send:
            with django_capture_on_commit_callbacks(execute=True):
                assert _place(authenticated_client, coupon_code="SAVE").status_code == 201
        mock_send.assert_called_once()
        coupon_arg = mock_send.call_args.args[0]
        assert coupon_arg.usage_count == 2


# --- From test_resilience.py ---

def _resilience_product(cat, name, price="100.00", stock=5):
    return Product.objects.create(
        name=name, category=cat, description="x", price=Decimal(price), stock=stock,
        weight=Decimal("250.00"), unit="g", spice_form="powder", is_active=True,
        image=create_test_image(f"{name}.jpg"),
    )


def _combo(name, *components):
    """A combo over `(product, qty)` pairs. No price is passed: the MRP is
    DERIVED from the components attached below."""
    combo = ProductCombo.objects.create(name=name, is_active=True)
    for product, qty in components:
        ProductComboItem.objects.create(combo=combo, product=product, quantity=qty)
    return combo


@pytest.mark.django_db
class TestInactiveNotOrderable:
    def test_inactive_product_blocked(self, authenticated_client, test_user, test_category):
        p = _resilience_product(test_category, "Delisted", stock=5)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, product=p, item_type="product", quantity=1)
        Product.objects.filter(pk=p.pk).update(is_active=False)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 400
        assert "no longer available" in r.json().get("error", "").lower()
        assert not Order.objects.filter(user=test_user).exists()

    def test_inactive_combo_blocked(self, authenticated_client, test_user, test_category):
        a = _resilience_product(test_category, "CompA", stock=5)
        combo = _combo("Delisted Combo", (a, 1))
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=1)
        ProductCombo.objects.filter(pk=combo.pk).update(is_active=False)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 400


@pytest.mark.django_db
class TestComboComponentStock:
    def test_combo_blocked_when_component_out_of_stock(self, authenticated_client, test_user, test_category):
        a = _resilience_product(test_category, "CompA", stock=0)
        b = _resilience_product(test_category, "CompB", stock=5)
        combo = _combo("OOS Combo", (a, 1), (b, 1))
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=1)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 400
        assert "CompA" in r.json().get("error", "")
        assert not Order.objects.filter(user=test_user).exists()

    def test_combo_decrements_component_stock(self, authenticated_client, test_user, test_category):
        a = _resilience_product(test_category, "CompA", stock=10)
        b = _resilience_product(test_category, "CompB", stock=10)
        combo = _combo("Box", (a, 2), (b, 1))
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=3)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 201
        a.refresh_from_db(); b.refresh_from_db()
        assert a.stock == 10 - (2 * 3)
        assert b.stock == 10 - (1 * 3)

    def test_combo_exceeding_component_stock_blocked(self, authenticated_client, test_user, test_category):
        a = _resilience_product(test_category, "CompA", stock=5)
        combo = _combo("Box2", (a, 2))
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=3)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 400
        a.refresh_from_db()
        assert a.stock == 5

    def test_cancel_restores_component_stock(self, authenticated_client, test_user, test_category):
        a = _resilience_product(test_category, "CompA", stock=10)
        combo = _combo("Box3", (a, 2))
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=2)
        create = authenticated_client.post(URL, ADDR, format="json")
        assert create.status_code == 201
        a.refresh_from_db()
        assert a.stock == 6
        order = Order.objects.get(user=test_user)
        cancel = authenticated_client.post(f"{URL}{order.id}/cancel/")
        assert cancel.status_code == 200
        a.refresh_from_db()
        assert a.stock == 10


# --- From test_cart_retention.py ---

def _add_to_cart(client, product, qty=2):
    r = client.post('/api/cart/add_item/',
                    {'product_id': product.id, 'quantity': qty}, format='json')
    assert r.status_code == 200, r.data
    return r


def _place_retention(client, method='ONLINE', coupon=None):
    data = {'shipping_address': '1 St', 'phone_number': '9999999999',
            'payment_method': method}
    if coupon:
        data['coupon_code'] = coupon
    return client.post('/api/orders/', data, format='json')


@pytest.mark.django_db
class TestCartRetention:
    def test_online_order_keeps_cart(self, authenticated_client, test_user, test_product):
        start_stock = test_product.stock
        _add_to_cart(authenticated_client, test_product, qty=2)

        resp = _place_retention(authenticated_client, 'ONLINE')
        assert resp.status_code == 201, resp.data

        order = Order.objects.get(pk=resp.data['order_id'])
        assert order.payment_status == 'pending' and order.status == 'pending'
        assert CartItem.objects.filter(cart__user=test_user).count() == 1
        test_product.refresh_from_db()
        assert test_product.stock == start_stock - 2

    def test_second_online_checkout_supersedes_first(
            self, authenticated_client, test_user, test_product):
        start_stock = test_product.stock
        _add_to_cart(authenticated_client, test_product, qty=2)

        first = Order.objects.get(pk=_place_retention(authenticated_client, 'ONLINE').data['order_id'])
        assert CartItem.objects.filter(cart__user=test_user).exists()

        second = Order.objects.get(pk=_place_retention(authenticated_client, 'ONLINE').data['order_id'])

        first.refresh_from_db()
        assert first.status == 'cancelled'
        assert first.payment_status == 'rejected'
        assert first.cancelled_at is not None
        assert Order.objects.filter(user=test_user, status='pending',
                                    payment_status='pending').count() == 1
        assert second.status == 'pending'
        test_product.refresh_from_db()
        assert test_product.stock == start_stock - 2

    def test_capture_empties_cart(self, authenticated_client, test_user, test_product):
        _add_to_cart(authenticated_client, test_product, qty=2)
        order = Order.objects.get(pk=_place_retention(authenticated_client, 'ONLINE').data['order_id'])
        assert CartItem.objects.filter(cart__user=test_user).exists()

        Payment.objects.create(order=order, payment_id='order_CAP',
                               payment_gateway='razorpay', amount=order.total_amount,
                               status='pending')
        services.mark_payment_captured(
            'order_CAP', 'pay_CAP', source='verify',
            amount=int(round(float(order.total_amount) * 100)))

        order.refresh_from_db()
        assert order.payment_status == 'paid' and order.status == 'confirmed'
        assert not CartItem.objects.filter(cart__user=test_user).exists()

    def test_cod_order_empties_cart_immediately(
            self, authenticated_client, test_user, test_product):
        _add_to_cart(authenticated_client, test_product, qty=2)
        resp = _place_retention(authenticated_client, 'COD')
        assert resp.status_code == 201, resp.data
        assert not CartItem.objects.filter(cart__user=test_user).exists()


# --- From test_invoice.py ---

class TestMoneyFormatting:
    def test_basic_thousands_separator_and_two_decimals(self):
        assert _money(1234.5) == "Rs. 1,234.50"

    def test_none_is_zero(self):
        assert _money(None) == "Rs. 0.00"

    def test_zero(self):
        assert _money(0) == "Rs. 0.00"

    def test_decimal_max_numeric_10_2(self):
        assert _money(Decimal("99999999.99")) == "Rs. 99,999,999.99"

    def test_string_amount_is_accepted(self):
        assert _money("250") == "Rs. 250.00"


class TestOrderNumber:
    def test_zero_padded_to_six(self):
        assert _order_number(SimpleNamespace(id=42)) == "ORD-000042"

    def test_large_id_not_truncated(self):
        assert _order_number(SimpleNamespace(id=1234567)) == "ORD-1234567"


class TestCustomerName:
    def test_none_user_is_guest(self):
        assert _customer_name(None) == "Guest"

    def test_prefers_name_field(self):
        u = SimpleNamespace(name="Asha Verma", first_name="A", last_name="V", email="a@x.com")
        assert _customer_name(u) == "Asha Verma"

    def test_falls_back_to_first_last(self):
        u = SimpleNamespace(name="  ", first_name="Asha", last_name="Verma", email="a@x.com")
        assert _customer_name(u) == "Asha Verma"

    def test_falls_back_to_email_when_no_name(self):
        u = SimpleNamespace(name="", first_name="", last_name="", email="a@x.com")
        assert _customer_name(u) == "a@x.com"


class TestAmountInWords:
    @pytest.mark.parametrize("n,expected", [
        (0, "Zero"),
        (7, "Seven"),
        (19, "Nineteen"),
        (20, "Twenty"),
        (64, "Sixty Four"),
        (100, "One Hundred"),
        (264, "Two Hundred Sixty Four"),
        (1000, "One Thousand"),
        (150000, "One Lakh Fifty Thousand"),
        (10000000, "One Crore"),
        (1234567, "Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven"),
    ])
    def test_num_words(self, n, expected):
        assert _num_words(n) == expected

    def test_two_and_three_boundaries(self):
        assert _two(0) == ""
        assert _two(15) == "Fifteen"
        assert _three(305) == "Three Hundred Five"

    def test_words_zero(self):
        assert _amount_in_words(0) == "Rupees Zero Only"

    def test_words_whole_rupees(self):
        assert _amount_in_words(Decimal("264.00")) == "Rupees Two Hundred Sixty Four Only"

    def test_words_with_paise(self):
        assert _amount_in_words(Decimal("264.50")) == (
            "Rupees Two Hundred Sixty Four and Fifty Paise Only"
        )

    def test_words_none(self):
        assert _amount_in_words(None) == "Rupees Zero Only"

    def test_words_large_amount(self):
        assert _amount_in_words(Decimal("1050000.00")) == (
            "Rupees Ten Lakh Fifty Thousand Only"
        )


def _pdf_is_valid(data: bytes) -> bool:
    return isinstance(data, bytes) and data[:5] == b"%PDF-" and len(data) > 1000


def _invoice_for(order):
    """Issue the order's tax invoice and return it, for renderer tests.

    The renderer takes an issued `Invoice`, not an Order: its contents are
    frozen at issue (orders/invoicing.py). Tests that exercise the DOCUMENT go
    through here; the issuing rules themselves are covered in test_invoicing.py.
    """
    from orders.invoicing import issue_invoice
    invoice, _ = issue_invoice(order)
    return invoice


@pytest.mark.django_db
class TestGenerateInvoicePdf:
    def test_happy_path_returns_pdf_bytes(self, test_order):
        pdf = generate_invoice_pdf(_invoice_for(test_order))
        assert _pdf_is_valid(pdf)

    def test_cancelled_order_still_renders(self, test_order):
        test_order.status = "cancelled"
        test_order.save(update_fields=["status"])
        pdf = generate_invoice_pdf(_invoice_for(test_order))
        assert _pdf_is_valid(pdf)

    def test_free_shipping_and_zero_discount(self, test_order):
        assert test_order.shipping_charge == 0
        assert generate_invoice_pdf(_invoice_for(test_order))[:5] == b"%PDF-"

    def test_paid_shipping_and_coupon_discount(self, db, test_user, test_product):
        from orders.models import Order, OrderItem
        from admin_panel.models import Coupon
        from django.utils import timezone
        from datetime import timedelta
        import uuid

        code = f"SAVE10-{uuid.uuid4().hex[:6]}"
        coupon = Coupon.objects.create(
            code=code, discount_percent=10, is_active=True,
            valid_until=timezone.now() + timedelta(days=5),
        )
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd\nCity", phone_number="1234567890",
            payment_method="ONLINE", payment_status="paid",
            subtotal=Decimal("400.00"), discount_amount=Decimal("40.00"),
            shipping_charge=Decimal("50.00"), tax=Decimal("18.00"),
            total_amount=Decimal("428.00"), status="confirmed", coupon=coupon,
        )
        OrderItem.objects.create(
            order=order, product=test_product, item_type="product",
            product_name=test_product.name, product_weight="250 g",
            quantity=4, price=Decimal("100.00"), final_price=Decimal("360.00"),
        )
        assert order.coupon_code == code
        assert _pdf_is_valid(generate_invoice_pdf(_invoice_for(order)))

    def test_large_multi_lakh_total(self, db, test_user, test_product):
        from orders.models import Order, OrderItem
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="COD", subtotal=Decimal("1050000.00"),
            tax=Decimal("52500.00"), total_amount=Decimal("1102500.00"), status="pending",
        )
        OrderItem.objects.create(
            order=order, product=test_product, item_type="product",
            product_name=test_product.name, product_weight="1 kg",
            quantity=1, price=Decimal("1050000.00"), final_price=Decimal("1050000.00"),
        )
        assert _pdf_is_valid(generate_invoice_pdf(_invoice_for(order)))


@pytest.mark.django_db
class TestInvoiceEndpoint:
    def _url(self, order):
        return f"/api/orders/{order.id}/invoice/"

    def test_owner_downloads_pdf(self, authenticated_client, test_order):
        invoice = _invoice_for(test_order)
        r = authenticated_client.get(self._url(test_order))
        assert r.status_code == 200
        assert r["Content-Type"] == "application/pdf"
        assert "attachment" in r["Content-Disposition"]
        # Named by the INVOICE serial now, not the order id — that is the number
        # the customer's accountant looks for.
        assert invoice.number.replace("/", "-") in r["Content-Disposition"]
        assert r.content[:5] == b"%PDF-"

    def test_order_without_an_issued_invoice_is_refused(
            self, authenticated_client, test_order):
        """Downloading is a reprint, never an issue event — so an order with no
        invoice has nothing to serve. Previously this rendered a document headed
        TAX INVOICE for any order at all, including an unpaid one."""
        test_order.payment_status = "pending"
        test_order.status = "pending"
        test_order.save(update_fields=["payment_status", "status"])

        r = authenticated_client.get(self._url(test_order))

        assert r.status_code == 409
        assert r.json()["code"] == "invoice_not_issued"

    def test_anonymous_is_rejected(self, api_client, test_order):
        r = api_client.get(self._url(test_order))
        assert r.status_code in (401, 403)

    def test_other_user_cannot_download_bola(self, authenticated_client_user2, test_order):
        r = authenticated_client_user2.get(self._url(test_order))
        assert r.status_code in (403, 404)

    def test_staff_can_download_any_order(self, admin_client, test_order):
        _invoice_for(test_order)
        r = admin_client.get(self._url(test_order))
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"

    def test_unknown_order_is_not_found(self, authenticated_client):
        r = authenticated_client.get("/api/orders/999999999/invoice/")
        assert r.status_code in (403, 404)


# --- From test_delivery_bill.py ---

@pytest.fixture
def staff_client(test_admin):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(test_admin).access_token}")
    return client


PDF_BYTES = b"%PDF-1.4\n%fake pdf body for tests\n%%EOF"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _pdf_upload(name="receipt.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def _png_upload(name="receipt.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def _read_stream(response):
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


@pytest.mark.django_db
class TestDeliveryBillUpload:
    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_admin_uploads_pdf(self, admin_client, test_order):
        r = admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")
        assert r.status_code == 201
        assert r.data["has_delivery_bill"] is True
        assert r.data["delivery_bill_uploaded_at"] is not None

        test_order.refresh_from_db()
        assert bool(test_order.delivery_bill) is True
        assert test_order.delivery_bill.name.endswith(".pdf")
        assert test_order.delivery_bill_uploaded_at is not None

    def test_admin_uploads_image(self, admin_client, test_order):
        r = admin_client.post(self._url(test_order), {"file": _png_upload()}, format="multipart")
        assert r.status_code == 201
        test_order.refresh_from_db()
        assert test_order.delivery_bill.name.endswith(".png")

    def test_upload_replaces_existing_bill(self, admin_client, test_order):
        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")
        test_order.refresh_from_db()
        first_name = test_order.delivery_bill.name

        r = admin_client.post(self._url(test_order), {"file": _png_upload()}, format="multipart")
        assert r.status_code == 201
        test_order.refresh_from_db()
        assert test_order.delivery_bill.name != first_name
        assert test_order.delivery_bill.name.endswith(".png")

    def test_rejects_unsupported_type(self, admin_client, test_order):
        bad = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
        r = admin_client.post(self._url(test_order), {"file": bad}, format="multipart")
        assert r.status_code == 400
        test_order.refresh_from_db()
        assert not test_order.delivery_bill

    def test_rejects_missing_file(self, admin_client, test_order):
        r = admin_client.post(self._url(test_order), {}, format="multipart")
        assert r.status_code == 400

    def test_rejects_oversize_file(self, admin_client, test_order, monkeypatch):
        monkeypatch.setattr(OrderViewSet, "MAX_DELIVERY_BILL_BYTES", 4)
        big = SimpleUploadedFile("big.pdf", b"%PDF-and-then-some", content_type="application/pdf")
        r = admin_client.post(self._url(test_order), {"file": big}, format="multipart")
        assert r.status_code == 400
        test_order.refresh_from_db()
        assert not test_order.delivery_bill


@pytest.mark.django_db
class TestDeliveryBillView:
    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_admin_streams_uploaded_bill(self, admin_client, test_order):
        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")
        r = admin_client.get(self._url(test_order))
        assert r.status_code == 200
        assert r["Content-Type"] == "application/pdf"
        assert "inline" in r["Content-Disposition"]
        assert f"ORD-{test_order.id:06d}" in r["Content-Disposition"]
        assert _read_stream(r) == PDF_BYTES

    def test_view_when_none_uploaded_is_404(self, admin_client, test_order):
        r = admin_client.get(self._url(test_order))
        assert r.status_code == 404


@pytest.mark.django_db
class TestDeliveryBillDelete:
    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_admin_deletes_bill(self, admin_client, test_order):
        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")
        r = admin_client.delete(self._url(test_order))
        assert r.status_code == 200
        assert r.data["success"] is True
        test_order.refresh_from_db()
        assert not test_order.delivery_bill
        assert test_order.delivery_bill_uploaded_at is None
        assert admin_client.get(self._url(test_order)).status_code == 404

    def test_delete_when_none_is_idempotent(self, admin_client, test_order):
        r = admin_client.delete(self._url(test_order))
        assert r.status_code == 200


@pytest.mark.django_db
class TestDeliveryBillAccessControl:
    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_anonymous_rejected(self, api_client, test_order):
        assert api_client.get(self._url(test_order)).status_code in (401, 403)
        assert api_client.post(self._url(test_order), {"file": _pdf_upload()},
                               format="multipart").status_code in (401, 403)

    def test_owner_non_staff_cannot_upload(self, authenticated_client, test_order):
        r = authenticated_client.post(self._url(test_order), {"file": _pdf_upload()},
                                      format="multipart")
        assert r.status_code == 403
        test_order.refresh_from_db()
        assert not test_order.delivery_bill

    def test_owner_non_staff_cannot_view(self, staff_client, authenticated_client, test_order):
        assert staff_client.post(self._url(test_order), {"file": _pdf_upload()},
                                 format="multipart").status_code == 201
        assert authenticated_client.get(self._url(test_order)).status_code == 403

    def test_owner_non_staff_cannot_delete(self, staff_client, authenticated_client, test_order):
        assert staff_client.post(self._url(test_order), {"file": _pdf_upload()},
                                 format="multipart").status_code == 201
        assert authenticated_client.delete(self._url(test_order)).status_code == 403
        test_order.refresh_from_db()
        assert test_order.delivery_bill

    def test_other_user_rejected(self, authenticated_client_user2, test_order):
        r = authenticated_client_user2.get(self._url(test_order))
        assert r.status_code in (403, 404)


@pytest.mark.django_db
class TestDeliveryBillSerializerMetadata:
    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_list_flags_absence_then_presence(self, admin_client, test_order):
        # scope=all → the admin table. A bare /api/orders/ is the *customer*
        # surface and would return only the admin's own orders.
        before = admin_client.get("/api/orders/?scope=all").data
        row = next(o for o in before["results"] if o["id"] == test_order.id)
        assert row["has_delivery_bill"] is False
        assert row["delivery_bill_uploaded_at"] is None
        assert "delivery_bill" not in row

        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")

        after = admin_client.get("/api/orders/?scope=all").data
        row = next(o for o in after["results"] if o["id"] == test_order.id)
        assert row["has_delivery_bill"] is True
        assert row["delivery_bill_uploaded_at"] is not None
        assert "delivery_bill" not in row

    def test_detail_exposes_flag_not_url(self, admin_client, test_order):
        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")
        detail = admin_client.get(f"/api/orders/{test_order.id}/").data
        assert detail["has_delivery_bill"] is True
        assert "delivery_bill" not in detail


# --- From test_order_admin_extras.py ---

def _make_order(user, product, status='pending', payment='COD'):
    order = Order.objects.create(
        user=user, shipping_address='123 Test St, City', phone_number='9998887776',
        payment_method=payment, subtotal=Decimal('240.00'), tax=Decimal('24.00'),
        total_amount=Decimal('264.00'), status=status,
    )
    OrderItem.objects.create(
        order=order, product=product, item_type='product',
        product_name=product.name, product_weight=str(product.weight),
        quantity=2, price=product.final_price, final_price=product.final_price * 2,
    )
    return order


@pytest.mark.django_db
class TestOrderDateFilter:
    def test_date_range_filters_orders(self, admin_client, test_user, test_product):
        old = _make_order(test_user, test_product)
        Order.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        recent = _make_order(test_user, test_product)

        # localdate(), not now().date(): the filter reads its bounds as LOCAL
        # calendar days, so a UTC date silently excludes orders placed between
        # midnight and 05:30 IST.
        today = timezone.localdate()
        frm = (today - timedelta(days=7)).isoformat()
        resp = admin_client.get('/api/orders/', {'date_from': frm, 'date_to': today.isoformat()})
        assert resp.status_code == 200
        ids = [o['id'] for o in resp.data['results']]
        assert recent.id in ids
        assert old.id not in ids

    def test_bad_date_is_ignored_not_500(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = admin_client.get('/api/orders/', {'date_from': 'not-a-date'})
        assert resp.status_code == 200


@pytest.mark.django_db
class TestOrderCsvExport:
    def test_export_returns_csv_with_gst_columns(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = admin_client.get('/api/orders/', {'export': 'csv'})
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('text/csv')
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        header = body.splitlines()[0]
        assert 'GST' in header and 'Taxable Amount' in header
        assert 'ORD-' in body

    def test_export_respects_status_filter(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product, status='pending')
        _make_order(test_user, test_product, status='delivered')
        resp = admin_client.get('/api/orders/', {'export': 'csv', 'status': 'delivered'})
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        data_rows = [ln for ln in body.splitlines()[1:] if ln.strip()]
        assert len(data_rows) == 1
        assert 'delivered' in data_rows[0]

    def test_export_requires_staff(self, authenticated_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = authenticated_client.get('/api/orders/', {'export': 'csv'})
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('application/json')


@pytest.mark.django_db
class TestPackingSlip:
    def test_staff_gets_pdf(self, admin_client, test_user, test_product):
        order = _make_order(test_user, test_product)
        resp = admin_client.get(f'/api/orders/{order.id}/packing-slip/')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'
        assert resp.content[:4] == b'%PDF'

    def test_customer_cannot_download_packing_slip(self, authenticated_client, test_user, test_product):
        order = _make_order(test_user, test_product)
        resp = authenticated_client.get(f'/api/orders/{order.id}/packing-slip/')
        assert resp.status_code == 403


# --- From test_recycle_bin.py ---

def _order(user, **kw):
    kw.setdefault("shipping_address", "1 Test Rd")
    kw.setdefault("phone_number", "1234567890")
    kw.setdefault("payment_method", "COD")
    kw.setdefault("subtotal", Decimal("100.00"))
    kw.setdefault("total_amount", Decimal("100.00"))
    return Order.objects.create(user=user, **kw)


def _ids(resp):
    data = resp.data
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


@pytest.mark.django_db
class TestOrderSoftDelete:
    def test_admin_delete_soft_deletes(self, admin_client, test_user):
        order = _order(test_user)
        resp = admin_client.delete(f"/api/orders/{order.id}/")
        assert resp.status_code == 204
        order.refresh_from_db()
        assert order.is_deleted is True
        assert order.deleted_at is not None

    def test_deleted_hidden_from_default_list(self, admin_client, test_user):
        kept = _order(test_user)
        gone = _order(test_user)
        admin_client.delete(f"/api/orders/{gone.id}/")
        ids = _ids(admin_client.get("/api/orders/?scope=all"))
        assert kept.id in ids
        assert gone.id not in ids

    def test_deleted_shown_under_deleted_flag(self, admin_client, test_user):
        kept = _order(test_user)
        gone = _order(test_user)
        admin_client.delete(f"/api/orders/{gone.id}/")
        ids = _ids(admin_client.get("/api/orders/?deleted=true"))
        assert gone.id in ids
        assert kept.id not in ids

    def test_customer_never_sees_deleted_order(self, authenticated_client, test_user):
        order = _order(test_user)
        Order.objects.filter(pk=order.pk).update(is_deleted=True)
        ids = _ids(authenticated_client.get("/api/orders/"))
        assert order.id not in ids


@pytest.mark.django_db
class TestOrderRestore:
    def test_admin_restore(self, admin_client, test_user):
        order = _order(test_user)
        admin_client.delete(f"/api/orders/{order.id}/")
        resp = admin_client.post(f"/api/orders/{order.id}/restore/")
        assert resp.status_code == 200
        order.refresh_from_db()
        assert order.is_deleted is False
        assert order.deleted_at is None
        assert order.id in _ids(admin_client.get("/api/orders/?scope=all"))

    def test_restore_non_deleted_is_400(self, admin_client, test_user):
        order = _order(test_user)
        resp = admin_client.post(f"/api/orders/{order.id}/restore/")
        assert resp.status_code == 400
        order.refresh_from_db()
        assert order.is_deleted is False


@pytest.mark.django_db
class TestOrderRecycleBinPermissions:
    def test_regular_user_cannot_delete(self, authenticated_client, test_user):
        order = _order(test_user)
        resp = authenticated_client.delete(f"/api/orders/{order.id}/")
        assert resp.status_code == 403
        order.refresh_from_db()
        assert order.is_deleted is False

    def test_regular_user_cannot_restore(self, authenticated_client, test_user):
        order = _order(test_user)
        Order.objects.filter(pk=order.pk).update(is_deleted=True)
        resp = authenticated_client.post(f"/api/orders/{order.id}/restore/")
        assert resp.status_code in (403, 404)
        order.refresh_from_db()
        assert order.is_deleted is True


# --- Recycle Bin purge (purge_recycle_bin management command) ---

from django.core.management import call_command


def _aged(delta_days):
    """A timestamp delta_days in the past (positive = older)."""
    return timezone.now() - timedelta(days=delta_days)


@pytest.mark.django_db
class TestRecycleBinPurge:
    def test_old_deleted_order_is_purged(self, test_user):
        old = _order(test_user, is_deleted=True)
        Order.objects.filter(pk=old.pk).update(deleted_at=_aged(31))
        recent = _order(test_user, is_deleted=True)
        Order.objects.filter(pk=recent.pk).update(deleted_at=_aged(5))
        live = _order(test_user)  # not deleted at all
        call_command("purge_recycle_bin")
        assert not Order.objects.filter(pk=old.pk).exists()
        assert Order.objects.filter(pk=recent.pk).exists()
        assert Order.objects.filter(pk=live.pk).exists()

    def test_old_deactivated_product_and_combo_purged(self, test_category):
        prod = _product(test_category, "100.00", name="OldDelisted")
        Product.objects.filter(pk=prod.pk).update(is_active=False, deactivated_at=_aged(40))
        combo = ProductCombo.objects.create(name="OldCombo")
        ProductCombo.objects.filter(pk=combo.pk).update(is_active=False, deactivated_at=_aged(40))
        call_command("purge_recycle_bin")
        assert not Product.objects.filter(pk=prod.pk).exists()
        assert not ProductCombo.objects.filter(pk=combo.pk).exists()

    def test_active_and_recent_items_untouched(self, test_category, test_user):
        active = _product(test_category, "100.00", name="StillActive")
        recent = _product(test_category, "100.00", name="RecentlyDelisted")
        Product.objects.filter(pk=recent.pk).update(is_active=False, deactivated_at=_aged(5))
        # Inactive but with NO timestamp (unknown deletion date) is never purged.
        untimed = _product(test_category, "100.00", name="Untimed")
        Product.objects.filter(pk=untimed.pk).update(is_active=False, deactivated_at=None)
        call_command("purge_recycle_bin")
        assert Product.objects.filter(pk=active.pk).exists()
        assert Product.objects.filter(pk=recent.pk).exists()
        assert Product.objects.filter(pk=untimed.pk).exists()

    def test_product_referenced_by_order_is_skipped(self, test_category, test_user):
        prod = _product(test_category, "100.00", name="Ordered")
        order = _order(test_user)
        OrderItem.objects.create(
            order=order, product=prod, item_type="product",
            quantity=1, price=Decimal("100.00"))
        Product.objects.filter(pk=prod.pk).update(is_active=False, deactivated_at=_aged(40))
        call_command("purge_recycle_bin")
        # PROTECT keeps it alive; the job skips rather than crashes.
        assert Product.objects.filter(pk=prod.pk).exists()

    def test_days_zero_disables_purge(self, test_user):
        old = _order(test_user, is_deleted=True)
        Order.objects.filter(pk=old.pk).update(deleted_at=_aged(999))
        call_command("purge_recycle_bin", days=0)
        assert Order.objects.filter(pk=old.pk).exists()

    def test_dry_run_deletes_nothing(self, test_user):
        old = _order(test_user, is_deleted=True)
        Order.objects.filter(pk=old.pk).update(deleted_at=_aged(40))
        call_command("purge_recycle_bin", dry_run=True)
        assert Order.objects.filter(pk=old.pk).exists()


@pytest.mark.django_db
class TestDeactivatedAtLifecycle:
    """The soft-delete timestamp that drives the purge is stamped on delete and
    cleared on restore, through the real product API."""

    def test_delete_stamps_and_restore_clears(self, admin_client, test_category):
        prod = _product(test_category, "100.00", name="Lifecycle")
        admin_client.delete(f"/api/products/{prod.slug}/")
        prod.refresh_from_db()
        assert prod.is_active is False
        assert prod.deactivated_at is not None
        # Restore via the same PATCH the Recycle Bin UI uses.
        admin_client.patch(
            f"/api/products/{prod.slug}/", {"is_active": True}, format="json")
        prod.refresh_from_db()
        assert prod.is_active is True
        assert prod.deactivated_at is None


# --- GST-inclusive pricing ---

class TestExtractTax:
    """`extract_tax` carves GST OUT of an inclusive price rather than adding it.

    A ₹105 price at 5% contains ₹5 of GST — not ₹5.25, which is what the old
    additive formula would have produced from the same number.
    """

    def test_carves_tax_out_of_gross(self):
        from orders.pricing import extract_tax
        assert extract_tax(Decimal("105"), Decimal("5")) == Decimal("5.00")
        assert extract_tax(Decimal("118"), Decimal("18")) == Decimal("18.00")
        assert extract_tax(Decimal("400"), Decimal("5")) == Decimal("19.05")

    def test_exempt_and_empty_lines_are_zero(self):
        from orders.pricing import extract_tax
        assert extract_tax(Decimal("100"), Decimal("0")) == Decimal("0.00")  # papad
        assert extract_tax(Decimal("0"), Decimal("5")) == Decimal("0.00")
        assert extract_tax(None, None) == Decimal("0.00")


@pytest.mark.django_db
class TestTaxIsNotAddedToTotal:
    def test_cart_summary_total_excludes_tax(self, authenticated_client, test_user, test_category):
        """The cart preview must quote the same total the order will charge."""
        _cart_line(test_user, _product(test_category, "200.00"), 2)
        summary = authenticated_client.get("/api/cart/").json()["summary"]
        assert summary["subtotal"] == 400.0
        assert summary["tax"] == 19.05           # contained in subtotal
        # Goods GST is NOT added to the total; delivery GST is, because the fee
        # is quoted net. 400 + 59 + 10.62 = 469.62.
        assert summary["shipping_tax"] == 10.62
        assert summary["total_tax"] == 29.67
        assert summary["total"] == 469.62

    def test_coupon_preview_matches_placed_order(self, authenticated_client, test_user, test_category):
        """Preview and placement share `extract_tax`, so they cannot drift."""
        Coupon.objects.create(code="PREVIEW10", discount_percent=10, is_active=True,
                              valid_until=timezone.now() + timedelta(days=5))
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        preview = authenticated_client.post(
            f"{URL}validate_coupon/", {"coupon_code": "PREVIEW10"}, format="json").json()
        assert _place(authenticated_client, coupon_code="PREVIEW10").status_code == 201
        o = Order.objects.get(user=test_user)
        assert Decimal(str(preview["tax"])) == o.tax
        assert Decimal(str(preview["total_amount"])) == o.total_amount

    def test_exempt_product_pays_no_tax_but_same_price(self, authenticated_client, test_user, test_category):
        """A 0% (papad) line still costs its listed price — the rate only changes
        how the invoice splits it, never what the customer pays."""
        papad = _product(test_category, "100.00", name="Papad")
        papad.tax_rate = Decimal("0")
        papad.save(update_fields=["tax_rate"])
        _cart_line(test_user, papad, 1)
        assert _place(authenticated_client).status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.tax == Decimal("0.00")
        # 0% goods, but delivery is still an 18% taxable service:
        # 100 + 59 + 10.62 = 169.62
        assert o.shipping_tax == Decimal("10.62")
        assert o.total_amount == Decimal("169.62")


@pytest.mark.django_db
class TestInvoiceHonoursPricingConvention:
    """A reprinted historical bill must still reconcile, so the renderer branches
    on `tax_inclusive` rather than assuming the current convention."""

    @pytest.mark.parametrize("inclusive", [True, False])
    def test_renders_both_conventions(self, inclusive, test_user, test_product):
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="COD", subtotal=Decimal("400.00"),
            shipping_charge=Decimal("69.00"), tax=Decimal("19.05"),
            total_amount=Decimal("469.00"), status="pending", tax_inclusive=inclusive,
        )
        OrderItem.objects.create(
            order=order, product=test_product, item_type="product",
            product_name=test_product.name, product_weight="250 g",
            quantity=2, price=Decimal("200.00"), final_price=Decimal("400.00"),
        )
        assert _pdf_is_valid(generate_invoice_pdf(_invoice_for(order)))

    def test_new_orders_default_to_inclusive(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "200.00"), 1)
        assert _place(authenticated_client).status_code == 201
        assert Order.objects.get(user=test_user).tax_inclusive is True


# --- Combo stock symmetry (G2) ---

@pytest.mark.django_db
class TestComboCancelRestocksVariants:
    """Checkout draws a combo's components from VARIANT stock, so cancelling has
    to give it back to the same place.

    Crediting `Product.stock` instead — as the restore path used to — destroys
    the sellable inventory (nothing reads the legacy mirror at checkout) while
    inflating the mirror, so the loss compounds silently on every cancellation.
    """

    def _combo_of(self, category, qty_each=2):
        from products.models import ProductVariant
        combo = ProductCombo.objects.create(
            name="Restock Combo", description="x", is_active=True,
        )
        variants = []
        for i in (1, 2):
            product = _product(category, "200.00", stock=10, name=f"Combo Part {i}")
            variant = ProductVariant.objects.filter(product=product).first()
            assert variant is not None, "product save should mint a default size"
            variant.stock = 10
            variant.save(update_fields=["stock"])
            ProductComboItem.objects.create(
                combo=combo, variant=variant, quantity=qty_each)
            variants.append(variant)
        return combo, variants

    def _place_combo(self, client, user, combo, quantity=1):
        cart, _ = Cart.objects.get_or_create(user=user)
        CartItem.objects.create(
            cart=cart, combo=combo, item_type="combo", quantity=quantity)
        return _place(client)

    def test_cancel_returns_component_stock_to_the_variant(
            self, authenticated_client, test_user, test_category):
        combo, variants = self._combo_of(test_category)
        before = [v.stock for v in variants]

        assert self._place_combo(authenticated_client, test_user, combo).status_code == 201
        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was - 2, "checkout must draw from the variant"

        order = Order.objects.get(user=test_user)
        r = authenticated_client.post(f"{URL}{order.id}/cancel/")
        assert r.status_code == 200, r.content

        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was, "cancel must return it to the same variant"

    def test_cancel_does_not_inflate_the_legacy_product_mirror(
            self, authenticated_client, test_user, test_category):
        """The mirror tracks the default variant — a round trip must leave it
        exactly where it started, not credited a second time."""
        combo, variants = self._combo_of(test_category)
        products = [v.product for v in variants]
        before = [p.stock for p in products]

        assert self._place_combo(authenticated_client, test_user, combo).status_code == 201
        order = Order.objects.get(user=test_user)
        assert authenticated_client.post(f"{URL}{order.id}/cancel/").status_code == 200

        for product, was in zip(products, before):
            product.refresh_from_db()
            assert product.stock == was

    def test_cancel_restocks_from_the_order_snapshot_not_the_live_recipe(
            self, authenticated_client, test_user, test_category):
        """The combo is EDITED between placement and cancellation.

        Restoring from the live recipe credits whatever the combo contains today,
        which is not what the order consumed: the swapped-in component gains stock
        it never gave up, and the swapped-out one never gets its stock back. Both
        drifts are silent. `OrderItemComponent` records what actually moved, so
        the restore must read that.
        """
        from products.models import ProductVariant
        combo, variants = self._combo_of(test_category)
        before = [v.stock for v in variants]

        assert self._place_combo(authenticated_client, test_user, combo).status_code == 201
        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was - 2

        # An admin reworks the combo AFTER the order was placed: component 2 is
        # replaced by a different size entirely.
        intruder_product = _product(test_category, "150.00", stock=10, name="Swapped In")
        intruder = ProductVariant.objects.filter(product=intruder_product).first()
        intruder.stock = 10
        intruder.save(update_fields=["stock"])
        ProductComboItem.objects.filter(combo=combo, variant=variants[1]).delete()
        ProductComboItem.objects.create(combo=combo, variant=intruder, quantity=2)

        order = Order.objects.get(user=test_user)
        assert authenticated_client.post(f"{URL}{order.id}/cancel/").status_code == 200

        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was, (
                "both ORIGINAL components must be made whole — including the one "
                "the combo no longer contains")
        intruder.refresh_from_db()
        assert intruder.stock == 10, (
            "the swapped-in variant never left stock, so it must not be credited")

    def test_snapshot_restock_is_not_multiplied_twice_for_multi_quantity_lines(
            self, authenticated_client, test_user, test_category):
        """`OrderItemComponent.quantity` is ALREADY per-combo x line quantity.
        Multiplying by the line quantity again would over-credit every combo
        ordered more than once."""
        combo, variants = self._combo_of(test_category)   # 2 units of each per combo
        before = [v.stock for v in variants]

        assert self._place_combo(
            authenticated_client, test_user, combo, quantity=3).status_code == 201
        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was - 6, "3 combos x 2 units"

        order = Order.objects.get(user=test_user)
        assert authenticated_client.post(f"{URL}{order.id}/cancel/").status_code == 200

        for variant, was in zip(variants, before):
            variant.refresh_from_db()
            assert variant.stock == was, "exactly 6 back, not 18"


@pytest.fixture
def separate_admin_client(test_admin):
    """An admin client on its OWN APIClient.

    The shared `admin_client` fixture reuses the same `api_client` instance as
    `authenticated_client` and merely overwrites its credentials, so a test that
    needs BOTH ends up with whichever fixture resolved last — silently 403ing the
    admin calls. These tests need a customer to place the order and an admin to
    PATCH it, so the admin gets its own client.
    """
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(test_admin).access_token}')
    return client


@pytest.mark.django_db
class TestAdminUpdateAtomicity:
    """A rejected admin PATCH must leave NOTHING behind.

    `_perform_admin_update` runs inside `transaction.atomic()`, and a `return`
    from inside an atomic block exits the context manager WITHOUT an exception —
    so the transaction commits. Any write performed before a validation
    `return Response(400)` therefore survives the "failed" request. Restocking is
    the write that makes that dangerous: it credits inventory AND stamps
    `stock_restored_at`, which permanently disarms the real cancel later.
    """

    def _placed_order(self, client, user, category, stock=10, qty=2):
        product = _resilience_product(category, "AtomicItem", stock=stock)
        _cart_line(user, product, qty)
        assert _place(client).status_code == 201
        return Order.objects.get(user=user), default_variant_for(product.pk)

    @pytest.mark.parametrize("bad_field", [
        {"shipping_cost": "not-a-number"},
        {"shipping_cost": "-5"},
        # Decimal() accepts these happily; it is the `< 0` comparison that then
        # raises InvalidOperation, so without an explicit finite check the
        # request 500s instead of 400-ing.
        {"shipping_cost": "NaN"},
        {"shipping_cost": "Infinity"},
        {"place_of_supply_state_code": "99"},
    ])
    def test_rejected_cancel_does_not_restock(
            self, separate_admin_client, authenticated_client, test_user, test_category, bad_field):
        """Cancel + an invalid field in the same PATCH: the 400 must roll back the
        restock, not commit it and leave the order live."""
        order, variant = self._placed_order(
            authenticated_client, test_user, test_category)
        variant.refresh_from_db()
        after_checkout = variant.stock

        r = separate_admin_client.patch(f"{URL}{order.id}/",
                               {"status": "cancelled", **bad_field}, format="json")
        assert r.status_code == 400

        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status != "cancelled", "the order was never actually cancelled"
        assert order.stock_restored_at is None, (
            "stock_restored_at was committed by a REJECTED request — the real "
            "cancel would now be a silent no-op")
        assert variant.stock == after_checkout, (
            "inventory was credited for an order that is still live and will ship")

    def test_a_later_genuine_cancel_still_restocks(
            self, separate_admin_client, authenticated_client, test_user, test_category):
        """The point of the above: after a rejected attempt, cancelling for real
        must still return the units exactly once."""
        order, variant = self._placed_order(
            authenticated_client, test_user, test_category, stock=10, qty=2)

        separate_admin_client.patch(f"{URL}{order.id}/",
                           {"status": "cancelled", "shipping_cost": "oops"},
                           format="json")
        r = separate_admin_client.patch(f"{URL}{order.id}/", {"status": "cancelled"},
                               format="json")
        assert r.status_code == 200

        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status == "cancelled"
        assert order.stock_restored_at is not None
        assert variant.stock == 10, "all 2 units back, exactly once"

    def test_valid_cancel_with_a_valid_shipping_cost_still_works(
            self, separate_admin_client, authenticated_client, test_user, test_category):
        """Guard against 'fixing' the ordering by simply not restocking."""
        order, variant = self._placed_order(
            authenticated_client, test_user, test_category, stock=10, qty=2)

        r = separate_admin_client.patch(f"{URL}{order.id}/",
                               {"status": "cancelled", "shipping_cost": "40.00"},
                               format="json")
        assert r.status_code == 200

        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status == "cancelled"
        assert order.shipping_cost == Decimal("40.00")
        assert variant.stock == 10


@pytest.mark.django_db
class TestCourierTrackingEmail:
    """WP4: courier name + tracking link in the shipped email."""

    def _capture(self, monkeypatch):
        sent = []

        def fake_send(subject, message, recipient):
            sent.append({'subject': subject, 'message': message, 'recipient': recipient})

        monkeypatch.setattr('orders.emails._send_async', fake_send)
        return sent

    def test_email_contains_courier_and_url(self, admin_client, test_order, monkeypatch):
        sent = self._capture(monkeypatch)
        r = admin_client.patch(f"{URL}{test_order.id}/", {
            'tracking_number': 'TRK123',
            'courier_name': 'Delhivery',
            'tracking_url': 'https://track.example/abc',
        }, format='json')
        assert r.status_code == 200
        assert r.data['courier_name'] == 'Delhivery'
        assert r.data['tracking_url'] == 'https://track.example/abc'
        assert len(sent) == 1
        body = sent[0]['message']
        assert 'Delhivery' in body
        assert 'https://track.example/abc' in body

    def test_bad_url_400_changes_nothing(self, admin_client, test_order):
        r = admin_client.patch(f"{URL}{test_order.id}/", {
            'tracking_url': 'javascript:alert(1)',
        }, format='json')
        assert r.status_code == 400
        test_order.refresh_from_db()
        assert test_order.tracking_url == ''
        assert test_order.tracking_number == ''

    def test_resending_same_values_sends_no_second_email(
            self, admin_client, test_order, monkeypatch):
        sent = self._capture(monkeypatch)
        payload = {
            'tracking_number': 'TRK123',
            'courier_name': 'Delhivery',
            'tracking_url': 'https://track.example/abc',
        }
        assert admin_client.patch(f"{URL}{test_order.id}/", payload, format='json').status_code == 200
        assert len(sent) == 1
        assert admin_client.patch(f"{URL}{test_order.id}/", payload, format='json').status_code == 200
        assert len(sent) == 1
