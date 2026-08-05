"""Customer-facing GST breakup + the admin-private courier cost.

Prices are GST-inclusive, so the bill must show the customer WHAT was taxed
(per rate slab), not just a single total. A real cart mixes slabs — papad is
0%, spices 5% — so the mixed case is the one that matters.
"""
from decimal import Decimal

import pytest

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.pricing import group_tax_by_rate
from products.models import Product

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _rated_product(category, price, rate, name):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price), stock=50,
        weight=Decimal("250"), unit="g", spice_form="powder", is_active=True,
        tax_rate=Decimal(rate), image=create_test_image(f"{name}.jpg"))


class TestGroupTaxByRate:
    def test_buckets_by_slab_and_reports_net_value(self):
        rows = group_tax_by_rate([(Decimal("400"), Decimal("5")),
                                  (Decimal("100"), Decimal("0"))])
        assert rows == [
            {"rate": 0.0, "taxable_value": 100.0, "tax_amount": 0.0},
            {"rate": 5.0, "taxable_value": 380.95, "tax_amount": 19.05},
        ]

    def test_same_slab_lines_merge_into_one_row(self):
        rows = group_tax_by_rate([(Decimal("100"), Decimal("5")),
                                  (Decimal("5"), Decimal("5"))])
        assert len(rows) == 1
        assert rows[0]["rate"] == 5.0
        assert rows[0]["tax_amount"] == 5.0    # 4.76 + 0.24, per-line rounding

    def test_empty_cart_has_no_rows(self):
        assert group_tax_by_rate([]) == []


@pytest.mark.django_db
class TestBreakupIsConsistentAcrossSurfaces:
    def _mixed_cart(self, user, category):
        cart, _ = Cart.objects.get_or_create(user=user)
        CartItem.objects.create(cart=cart, item_type="product", quantity=1,
                                product=_rated_product(category, "400", "5", "Spice"))
        CartItem.objects.create(cart=cart, item_type="product", quantity=1,
                                product=_rated_product(category, "100", "0", "Papad"))
        return cart

    def test_cart_summary_exposes_slabs_and_net_value(self, authenticated_client, test_user, test_category):
        self._mixed_cart(test_user, test_category)
        s = authenticated_client.get("/api/cart/").json()["summary"]
        assert s["subtotal"] == 500.0 and s["total"] == 500.0     # tax is inside
        assert s["taxable_value"] == 480.95
        assert s["tax_breakdown"] == [
            {"rate": 0.0, "taxable_value": 100.0, "tax_amount": 0.0},
            {"rate": 5.0, "taxable_value": 380.95, "tax_amount": 19.05},
        ]

    def test_placed_order_breakup_matches_the_cart_quote(self, authenticated_client, test_user, test_category):
        """The checkout page and the resulting bill must not disagree."""
        self._mixed_cart(test_user, test_category)
        quoted = authenticated_client.get("/api/cart/").json()["summary"]
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        placed = authenticated_client.get(URL).json()[0]
        assert placed["tax_breakdown"] == quoted["tax_breakdown"]
        assert Decimal(placed["taxable_value"]) == Decimal(str(quoted["taxable_value"]))

    def test_rate_is_snapshotted_so_reprice_cannot_rewrite_history(
            self, authenticated_client, test_user, test_category):
        self._mixed_cart(test_user, test_category)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        # The shop later re-rates every product to 12%.
        Product.objects.all().update(tax_rate=Decimal("12"))
        placed = authenticated_client.get(URL).json()[0]
        assert [r["rate"] for r in placed["tax_breakdown"]] == [0.0, 5.0]


@pytest.mark.django_db
class TestShippingCostIsAdminPrivate:
    """What the courier charged us is margin data, not the customer's business."""

    def test_customer_response_omits_it(self, authenticated_client, test_user, test_category):
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, item_type="product", quantity=1,
                                product=_rated_product(test_category, "400", "5", "S"))
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        assert "shipping_cost" not in authenticated_client.get(URL).json()[0]

    def test_admin_list_includes_it(self, admin_client, test_order):
        rows = admin_client.get(f"{URL}?scope=all").json()["results"]
        assert "shipping_cost" in next(r for r in rows if r["id"] == test_order.id)


@pytest.mark.django_db
class TestAdminRecordsCourierCost:
    def _order(self, client):
        return client.get(f"{URL}?scope=all").json()["results"][0]

    def test_admin_can_record_and_it_never_moves_the_total(self, admin_client, test_order):
        before = Decimal(str(test_order.total_amount))
        r = admin_client.patch(f"{URL}{test_order.id}/",
                               {"shipping_cost": "52.00"}, format="json")
        assert r.status_code == 200
        test_order.refresh_from_db()
        assert test_order.shipping_cost == Decimal("52.00")
        assert test_order.total_amount == before, "cost is internal, not billed"

    def test_blank_clears_to_zero(self, admin_client, test_order):
        admin_client.patch(f"{URL}{test_order.id}/", {"shipping_cost": "52"}, format="json")
        admin_client.patch(f"{URL}{test_order.id}/", {"shipping_cost": ""}, format="json")
        test_order.refresh_from_db()
        assert test_order.shipping_cost == Decimal("0")

    @pytest.mark.parametrize("bad", ["abc", "-5"])
    def test_garbage_is_rejected_with_400(self, admin_client, test_order, bad):
        r = admin_client.patch(f"{URL}{test_order.id}/",
                               {"shipping_cost": bad}, format="json")
        assert r.status_code == 400

    def test_customer_cannot_set_it(self, authenticated_client, test_order):
        authenticated_client.patch(f"{URL}{test_order.id}/",
                                   {"shipping_cost": "999"}, format="json")
        test_order.refresh_from_db()
        assert test_order.shipping_cost == Decimal("0")


@pytest.mark.django_db
class TestDashboardReportsGstAndDelivery:
    """Revenue stays GROSS; GST and delivery are reported alongside it."""

    def test_stats_expose_gst_and_delivery(self, admin_client, test_order):
        from django.core.cache import cache
        test_order.shipping_cost = Decimal("40.00")
        test_order.save(update_fields=["shipping_cost"])
        cache.clear()   # dashboard_stats caches for 60s

        d = admin_client.get("/api/dashboard/actions/").json()
        assert Decimal(d["today_revenue"]) == test_order.total_amount
        assert Decimal(d["today_gst_collected"]) == test_order.tax
        assert Decimal(d["mtd_gst_collected"]) >= test_order.tax
        assert Decimal(d["today_shipping_cost"]) == Decimal("40.00")
        assert (Decimal(d["today_shipping_margin"])
                == Decimal(d["today_shipping_collected"]) - Decimal("40.00"))
        # The average covers only orders with a cost recorded, never all orders.
        assert d["today_shipping_cost_recorded"] == 1
        assert Decimal(d["today_avg_shipping_cost"]) == Decimal("40.00")


@pytest.mark.django_db
class TestBreakupAlwaysReconciles:
    """The per-slab rows are printed on a tax invoice under a Total taken from
    `order.tax`. A table that disagrees with its own total is worse than no
    table, so anything the lines can't explain becomes an unattributed row."""

    def test_rows_sum_to_the_order_tax_on_a_legacy_order(self, test_order):
        """A pre-per-line-tax order carries the GST on the header only: its lines
        report nothing, so without the residual row the summary would print
        '0%: Rs. 0.00' under a Total of Rs. 24.00."""
        from orders.pricing import order_tax_breakdown

        rows = order_tax_breakdown(test_order)
        assert sum(Decimal(str(r["tax_amount"])) for r in rows) == test_order.tax
        assert any(r["rate"] is None for r in rows), "unexplained tax must not be labelled 0%"

    def test_a_modern_order_needs_no_residual_row(self, authenticated_client, test_user, test_category):
        from orders.models import Order
        from orders.pricing import order_tax_breakdown

        TestBreakupIsConsistentAcrossSurfaces()._mixed_cart(test_user, test_category)
        authenticated_client.post(URL, ADDR, format="json")
        order = Order.objects.latest("id")

        rows = order_tax_breakdown(order)
        assert sum(Decimal(str(r["tax_amount"])) for r in rows) == order.tax
        assert all(r["rate"] is not None for r in rows), "per-line tax explains all of it"


@pytest.mark.django_db
class TestOrderListDoesNotScaleWithRowCount:
    """`tax_breakdown` and the nested `refunds` list are rendered per order. Both
    walk relations, so an unprefetched list costs three extra round-trips PER ROW
    — invisible on a seeded test, crippling on a real admin table."""

    def _orders(self, user, category, n):
        from orders.models import Order, OrderItem
        spice = _rated_product(category, "400", "5", "Spice")
        for i in range(n):
            order = Order.objects.create(
                user=user, shipping_address="1 Rd", phone_number="1234567890",
                payment_method="ONLINE", payment_status="paid",
                subtotal=Decimal("400.00"), tax=Decimal("19.05"),
                total_amount=Decimal("400.00"))
            OrderItem.objects.create(
                order=order, product=spice, item_type="product",
                product_name=spice.name, quantity=1, tax_rate=Decimal("5"),
                price=Decimal("400.00"), final_price=Decimal("400.00"))

    def _count_list_queries(self, client):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            assert client.get(URL).status_code == 200
        return len(ctx.captured_queries)

    def test_query_count_is_flat_in_the_number_of_orders(
            self, authenticated_client, test_user, test_category):
        self._orders(test_user, test_category, 2)
        baseline = self._count_list_queries(authenticated_client)

        self._orders(test_user, test_category, 6)
        assert self._count_list_queries(authenticated_client) == baseline, (
            "adding orders added queries — a prefetch is missing on the order list"
        )
