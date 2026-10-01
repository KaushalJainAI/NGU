"""HSN on order lines, and the HSN-wise summary GSTR-1 Table 12 is filed from.

The property that matters throughout: the summary is built from LINE SNAPSHOTS,
so re-classifying a product cannot rewrite a period that has already been filed.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.gst_reports import hsn_summary
from orders.models import Order
from products.models import Product, ProductCombo, ProductComboItem

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _product(category, name, price, rate, hsn):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price),
        stock=50, weight=Decimal("250"), unit="g", spice_form="powder",
        is_active=True, tax_rate=Decimal(rate), hsn_code=hsn,
        image=create_test_image(f"{name}.jpg"))


def _order_one(client, user, product, quantity=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    cart.items.all().delete()
    CartItem.objects.create(cart=cart, item_type="product",
                            quantity=quantity, product=product)
    response = client.post(URL, ADDR, format="json")
    assert response.status_code == 201, response.data
    return Order.objects.latest("id")


def _invoiced(order, when=None):
    """Issue the invoice so the order counts on the INVOICE basis."""
    from django.utils import timezone
    from orders.invoicing import issue_invoice
    invoice, _ = issue_invoice(order, when=when or timezone.now())
    return invoice


@pytest.mark.django_db
class TestSnapshotOnTheLine:
    def test_line_records_the_code_charged(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Haldi", "100", "5", "09103030")
        order = _order_one(authenticated_client, test_user, product)
        assert order.items.first().hsn_code == "09103030"

    def test_reclassifying_the_product_does_not_rewrite_the_order(
            self, authenticated_client, test_user, test_category):
        """The whole reason the column exists: a bill must reproduce what it was
        raised under, whatever the catalogue says today."""
        product = _product(test_category, "Blend", "100", "5", "09109100")
        order = _order_one(authenticated_client, test_user, product)
        product.hsn_code = "21039040"
        product.tax_rate = Decimal("18")
        product.save(update_fields=["hsn_code", "tax_rate"])
        item = order.items.first()
        assert item.hsn_code == "09109100" and item.tax_rate == Decimal("5.00")

    def test_unclassified_product_leaves_the_line_blank_not_guessed(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Mystery", "100", "5", "")
        order = _order_one(authenticated_client, test_user, product)
        assert order.items.first().hsn_code == ""

    def test_combo_line_is_blank_and_components_carry_the_codes(
            self, authenticated_client, test_user, test_category):
        """A bundle is a mixed supply — its components can sit in different
        headings, so there is no honest single code for the line."""
        spice = _product(test_category, "Spice", "100", "5", "09109100")
        papad = _product(test_category, "Papad", "100", "0", "19059040")
        combo = ProductCombo.objects.create(
            name="Festive box", description="x", discount_price=Decimal("180"),
            is_active=True, image=create_test_image("combo.jpg"))
        ProductComboItem.objects.create(
            combo=combo, variant=spice.variants.first(), quantity=1)
        ProductComboItem.objects.create(
            combo=combo, variant=papad.variants.first(), quantity=1)

        cart, _ = Cart.objects.get_or_create(user=test_user)
        cart.items.all().delete()
        CartItem.objects.create(cart=cart, item_type="combo", quantity=1, combo=combo)
        response = authenticated_client.post(URL, ADDR, format="json")
        assert response.status_code == 201, response.data

        item = Order.objects.latest("id").items.first()
        assert item.hsn_code == ""
        assert {c.hsn_code for c in item.components.all()} == {"09109100", "19059040"}

    def test_order_api_exposes_the_line_code(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Haldi", "100", "5", "09103030")
        order = _order_one(authenticated_client, test_user, product)
        body = authenticated_client.get(f"{URL}{order.id}/").json()
        assert body["items"][0]["hsn_code"] == "09103030"


@pytest.mark.django_db
class TestHsnSummary:
    def test_groups_by_code_and_rate(
            self, authenticated_client, test_user, test_category):
        spice = _product(test_category, "Haldi", "105", "5", "09103030")
        papad = _product(test_category, "Papad", "100", "0", "19059040")
        _invoiced(_order_one(authenticated_client, test_user, spice))
        _invoiced(_order_one(authenticated_client, test_user, papad))

        rows = {r["hsn_code"]: r for r in hsn_summary(YESTERDAY, TODAY)["rows"]}
        assert rows["09103030"]["rate"] == 5.0
        assert rows["09103030"]["tax_amount"] == Decimal("5.00")
        assert rows["09103030"]["taxable_value"] == Decimal("100.00")
        assert rows["19059040"]["tax_amount"] == Decimal("0.00")

    def test_quantity_counts_packs_sold(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Haldi", "100", "5", "09103030")
        _invoiced(_order_one(authenticated_client, test_user, product, quantity=3))
        row = next(r for r in hsn_summary(YESTERDAY, TODAY)["rows"]
                   if r["hsn_code"] == "09103030")
        assert row["quantity"] == 3 and row["uqc"] == "PAC"

    def test_totals_reconcile_against_the_orders(
            self, authenticated_client, test_user, test_category):
        """If the rows don't add up to the tax actually charged, the summary is
        worse than useless — it looks authoritative and isn't."""
        spice = _product(test_category, "Haldi", "105", "5", "09103030")
        papad = _product(test_category, "Papad", "100", "0", "19059040")
        o1 = _order_one(authenticated_client, test_user, spice)
        _invoiced(o1)
        o2 = _order_one(authenticated_client, test_user, papad)
        _invoiced(o2)
        orders = [o1, o2]

        data = hsn_summary(YESTERDAY, TODAY)
        charged = sum((o.total_tax for o in orders), Decimal("0.00"))
        assert data["totals"]["tax_amount"] == charged

    def test_combo_reports_its_components_not_the_bundle(
            self, authenticated_client, test_user, test_category):
        """And exactly once — counting the line AND its components would double
        the period's supply value."""
        spice = _product(test_category, "Spice", "100", "5", "09109100")
        papad = _product(test_category, "Papad", "100", "0", "19059040")
        combo = ProductCombo.objects.create(
            name="Festive box", description="x", discount_price=Decimal("180"),
            is_active=True, image=create_test_image("combo.jpg"))
        ProductComboItem.objects.create(
            combo=combo, variant=spice.variants.first(), quantity=1)
        ProductComboItem.objects.create(
            combo=combo, variant=papad.variants.first(), quantity=1)

        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, item_type="combo", quantity=1, combo=combo)
        response = authenticated_client.post(URL, ADDR, format="json")
        assert response.status_code == 201, response.data
        order = Order.objects.latest("id")
        _invoiced(order)

        data = hsn_summary(YESTERDAY, TODAY)
        goods_rows = [r for r in data["rows"] if not r["is_service"]]
        assert {r["hsn_code"] for r in goods_rows} == {"09109100", "19059040"}
        # The bundle's charged amount is split across the two headings, whole.
        goods = sum((r["total_value"] for r in goods_rows), Decimal("0.00"))
        assert goods == order.items.first().final_price

    def test_unclassified_lines_get_their_own_visible_row(
            self, authenticated_client, test_user, test_category):
        """Dropping them would produce a summary that quietly doesn't add up."""
        product = _product(test_category, "Mystery", "105", "5", "")
        _invoiced(_order_one(authenticated_client, test_user, product))
        data = hsn_summary(YESTERDAY, TODAY)
        row = data["rows"][-1]           # unclassified always sorts last
        assert row["is_unclassified"] and row["hsn_code"] == ""
        assert data["unclassified_value"] == Decimal("105.00")

    def test_cancelled_orders_are_excluded(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Haldi", "105", "5", "09103030")
        order = _order_one(authenticated_client, test_user, product)
        order.status = "cancelled"
        order.save(update_fields=["status"])
        assert hsn_summary(YESTERDAY, TODAY)["rows"] == []

    def test_orders_outside_the_window_are_excluded(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category, "Haldi", "105", "5", "09103030")
        _invoiced(_order_one(authenticated_client, test_user, product))
        past = TODAY - timedelta(days=30)
        assert hsn_summary(past, past - timedelta(days=1) + timedelta(days=1))["rows"] == []

    def test_delivery_is_reported_under_its_sac(
            self, authenticated_client, test_user, test_category):
        """Delivery is a taxable service billed net + 18%; omitting it leaves the
        summary short of the GST actually collected."""
        product = _product(test_category, "Haldi", "100", "5", "09103030")
        order = _order_one(authenticated_client, test_user, product)
        _invoiced(order)
        assert order.shipping_charge > 0, "fixture must be below the free-shipping threshold"

        data = hsn_summary(YESTERDAY, TODAY)
        ship = next(r for r in data["rows"] if r["is_service"])
        assert ship["hsn_code"] == "9968" and ship["uqc"] == "OTH"
        assert ship["tax_amount"] == order.shipping_tax
        assert data["totals"]["tax_amount"] == order.total_tax


@pytest.mark.django_db
class TestHsnSummaryEndpoint:
    URL = "/api/admin/hsn-summary/"

    def test_requires_staff(self, api_client, authenticated_client):
        assert api_client.get(self.URL).status_code in (401, 403)
        assert authenticated_client.get(self.URL).status_code == 403

    # NOTE: the order is placed BY the admin. `admin_client` and
    # `authenticated_client` wrap the same APIClient instance (see conftest), so
    # requesting both in one test leaves only the last-applied credentials —
    # which would silently 403 the report call.
    def test_returns_rows_for_the_requested_window(
            self, admin_client, test_admin, test_category):
        product = _product(test_category, "Haldi", "105", "5", "09103030")
        _invoiced(_order_one(admin_client, test_admin, product))
        body = admin_client.get(
            f"{self.URL}?from={YESTERDAY}&to={TODAY}").json()
        assert body["order_count"] == 1
        assert any(r["hsn_code"] == "09103030" for r in body["rows"])

    def test_csv_download_carries_the_totals_and_the_period(
            self, admin_client, test_admin, test_category):
        product = _product(test_category, "Haldi", "105", "5", "09103030")
        _invoiced(_order_one(admin_client, test_admin, product))
        response = admin_client.get(
            f"{self.URL}?from={YESTERDAY}&to={TODAY}&download=csv")
        assert response["Content-Type"].startswith("text/csv")
        body = b"".join(response.streaming_content).decode("utf-8-sig")
        assert "HSN/SAC" in body and "09103030" in body
        assert "TOTAL" in body and str(YESTERDAY) in body

    def test_lists_the_products_still_needing_a_code(
            self, admin_client, test_category):
        _product(test_category, "Mystery", "105", "5", "")
        body = admin_client.get(self.URL).json()
        assert [p["name"] for p in body["unclassified_products"]] == ["Mystery"]
