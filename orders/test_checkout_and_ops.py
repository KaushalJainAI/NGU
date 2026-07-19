"""
Checkout invariants, PDF invoices, delivery bills, date filtering, CSV export, packing slips, and recycle bin.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

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
from products.models import Product, ProductCombo, ProductComboItem

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
        assert o.shipping_charge == Decimal("69")
        assert o.tax == Decimal("20.00")
        assert o.total_amount == Decimal("489.00")

    def test_subtotal_exactly_500_is_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "250.00"), 2)
        r = _place(authenticated_client)
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")
        assert o.tax == Decimal("25.00")
        assert o.total_amount == Decimal("525.00")

    def test_subtotal_above_threshold_free_shipping(self, authenticated_client, test_user, test_category):
        _cart_line(test_user, _product(test_category, "300.00"), 2)
        o_resp = _place(authenticated_client)
        assert o_resp.status_code == 201
        o = Order.objects.get(user=test_user)
        assert o.shipping_charge == Decimal("0")
        assert o.total_amount == Decimal("630.00")


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
        assert o.tax == Decimal("27.00")
        assert o.total_amount == Decimal("567.00")
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


# --- From test_resilience.py ---

def _resilience_product(cat, name, price="100.00", stock=5):
    return Product.objects.create(
        name=name, category=cat, description="x", price=Decimal(price), stock=stock,
        weight=Decimal("250.00"), unit="g", spice_form="powder", is_active=True,
        image=create_test_image(f"{name}.jpg"),
    )


def _combo(name, *components):
    combo = ProductCombo.objects.create(name=name, price=Decimal("300.00"), is_active=True)
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


@pytest.mark.django_db
class TestGenerateInvoicePdf:
    def test_happy_path_returns_pdf_bytes(self, test_order):
        pdf = generate_invoice_pdf(test_order)
        assert _pdf_is_valid(pdf)

    def test_cancelled_order_still_renders(self, test_order):
        test_order.status = "cancelled"
        test_order.save(update_fields=["status"])
        pdf = generate_invoice_pdf(test_order)
        assert _pdf_is_valid(pdf)

    def test_free_shipping_and_zero_discount(self, test_order):
        assert test_order.shipping_charge == 0
        assert generate_invoice_pdf(test_order)[:5] == b"%PDF-"

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
        assert _pdf_is_valid(generate_invoice_pdf(order))

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
        assert _pdf_is_valid(generate_invoice_pdf(order))


@pytest.mark.django_db
class TestInvoiceEndpoint:
    def _url(self, order):
        return f"/api/orders/{order.id}/invoice/"

    def test_owner_downloads_pdf(self, authenticated_client, test_order):
        r = authenticated_client.get(self._url(test_order))
        assert r.status_code == 200
        assert r["Content-Type"] == "application/pdf"
        assert "attachment" in r["Content-Disposition"]
        assert f"ORD-{test_order.id:06d}" in r["Content-Disposition"]
        assert r.content[:5] == b"%PDF-"

    def test_anonymous_is_rejected(self, api_client, test_order):
        r = api_client.get(self._url(test_order))
        assert r.status_code in (401, 403)

    def test_other_user_cannot_download_bola(self, authenticated_client_user2, test_order):
        r = authenticated_client_user2.get(self._url(test_order))
        assert r.status_code in (403, 404)

    def test_staff_can_download_any_order(self, admin_client, test_order):
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
        before = admin_client.get("/api/orders/").data
        row = next(o for o in before["results"] if o["id"] == test_order.id)
        assert row["has_delivery_bill"] is False
        assert row["delivery_bill_uploaded_at"] is None
        assert "delivery_bill" not in row

        admin_client.post(self._url(test_order), {"file": _pdf_upload()}, format="multipart")

        after = admin_client.get("/api/orders/").data
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

        today = timezone.now().date()
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
        ids = _ids(admin_client.get("/api/orders/"))
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
        assert order.id in _ids(admin_client.get("/api/orders/"))

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
