"""
Tests for the PDF tax-invoice feature (orders/invoice.py + the
`/api/orders/{id}/invoice/` action). This is a recent addition, so it gets full
coverage: pure formatting/number helpers, end-to-end PDF rendering, and the
view-level access-control contract (owner / anon / other-user / staff).

Happy AND sad paths: guest names, zero/None money, paise, lakh/crore amounts,
cancelled orders, coupon/discount lines, free vs paid shipping, and BOLA.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest

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


# --------------------------------------------------------------------------- #
# Pure helpers — no DB needed
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# PDF generation — needs a real Order with items
# --------------------------------------------------------------------------- #
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
        # test_order has shipping_charge default 0 (FREE) and no discount.
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
        assert order.coupon_code == code          # exercises the coupon-label branch
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


# --------------------------------------------------------------------------- #
# View-level contract — /api/orders/{id}/invoice/
# --------------------------------------------------------------------------- #
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
        # test_order belongs to test_user; user2 must not read it.
        r = authenticated_client_user2.get(self._url(test_order))
        assert r.status_code in (403, 404)

    def test_staff_can_download_any_order(self, admin_client, test_order):
        r = admin_client.get(self._url(test_order))
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"

    def test_unknown_order_is_not_found(self, authenticated_client):
        r = authenticated_client.get("/api/orders/999999999/invoice/")
        assert r.status_code in (403, 404)
