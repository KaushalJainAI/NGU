"""Combo pricing: derived MRP, and GST charged PER COMPONENT.

A combo is one priced line to the customer but several taxable goods to the GST
return. A festive box mixing 0% papad with 5% masala is a mixed supply, and the
old model — one hand-entered rate on the combo — reported it at a blended rate
no auditor could reconcile against the goods.

Two invariants carry the whole design and are asserted from several angles:

1. The components' allocations sum EXACTLY to what was charged for the line.
2. The cart's quoted GST equals the placed order's GST, to the paisa.
"""
from decimal import Decimal

import pytest

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.models import Order, OrderItem, OrderItemComponent
from orders.pricing import allocate_combo_components
from products.models import Product, ProductCombo, ProductComboItem, ProductVariant

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _rated_product(category, price, rate, name, stock=50):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price), stock=stock,
        weight=Decimal("250"), unit="g", spice_form="powder", is_active=True,
        tax_rate=Decimal(rate), image=create_test_image(f"{name}.jpg"))


def _combo(name, components, discount_price=None):
    """`components` is a list of (product, qty)."""
    combo = ProductCombo.objects.create(
        name=name, is_active=True,
        **({"discount_price": Decimal(discount_price)} if discount_price else {}))
    for product, qty in components:
        ProductComboItem.objects.create(combo=combo, product=product, quantity=qty)
    return combo


@pytest.mark.django_db
class TestDerivedMRP:
    """The MRP is the components, not a number an admin typed."""

    def test_mrp_is_the_sum_of_component_sizes(self, test_category):
        spice = _rated_product(test_category, "400", "5", "Masala")
        papad = _rated_product(test_category, "100", "0", "Papad")
        combo = _combo("Box", [(spice, 1), (papad, 2)])
        assert combo.price == Decimal("600")            # 400 + 2x100
        assert combo.total_original_price == combo.price

    def test_repricing_a_component_moves_the_mrp(self, test_category):
        spice = _rated_product(test_category, "400", "5", "Masala")
        combo = _combo("Box", [(spice, 1)])
        assert combo.price == Decimal("400")
        ProductVariant.objects.filter(product=spice).update(price=Decimal("450"))
        assert ProductCombo.objects.get(pk=combo.pk).price == Decimal("450")

    def test_annotation_matches_the_python_property(self, test_category):
        spice = _rated_product(test_category, "400", "5", "Masala")
        papad = _rated_product(test_category, "100", "0", "Papad")
        combo = _combo("Box", [(spice, 3), (papad, 1)])
        annotated = ProductCombo.objects.with_mrp().get(pk=combo.pk)
        assert annotated.price == Decimal("1300") == ProductCombo.objects.get(pk=combo.pk).price

    def test_selling_price_above_mrp_is_rejected(self, test_category):
        from django.core.exceptions import ValidationError
        spice = _rated_product(test_category, "400", "5", "Masala")
        combo = _combo("Box", [(spice, 1)])
        combo.discount_price = Decimal("400.01")
        with pytest.raises(ValidationError):
            combo.save()

    def test_selling_price_equal_to_mrp_is_allowed(self, test_category):
        """A bundle sold at exactly the sum of its parts is a curation, not an
        error — and since the MRP is derived, a component re-price can bring the
        two level at any time without anyone touching the combo."""
        spice = _rated_product(test_category, "400", "5", "Masala")
        combo = _combo("Box", [(spice, 1)])
        combo.discount_price = Decimal("400")
        combo.save()
        assert combo.final_price == Decimal("400")
        assert combo.discount_percentage == 0

    def test_combo_with_no_components_has_zero_mrp(self, db):
        # Must not raise: `clean()` asks for the MRP on the very first save,
        # before any component row can exist.
        combo = ProductCombo.objects.create(name="Empty Box", is_active=True)
        assert combo.price == Decimal("0")


@pytest.mark.django_db
class TestAllocationIsExact:
    """Rounding must never lose or invent a paisa."""

    def test_split_is_linear_in_component_mrp(self, test_category):
        a = _rated_product(test_category, "300", "5", "A")
        b = _rated_product(test_category, "100", "5", "B")
        combo = _combo("Box", [(a, 1), (b, 1)])           # MRP 400, weights 3:1
        rows = allocate_combo_components(combo, Decimal("200.00"))
        assert [r["allocated"] for r in rows] == [Decimal("150.00"), Decimal("50.00")]

    def test_awkward_split_still_sums_to_the_charged_amount(self, test_category):
        """Three equal components on ₹449 divide to 149.666… — the residual has
        to land somewhere rather than vanish."""
        parts = [_rated_product(test_category, "200", "5", f"P{i}") for i in range(3)]
        combo = _combo("Box", [(p, 1) for p in parts], discount_price="449")
        rows = allocate_combo_components(combo, Decimal("449.00"))
        assert sum(r["allocated"] for r in rows) == Decimal("449.00")

    def test_component_quantities_scale_with_line_quantity(self, test_category):
        a = _rated_product(test_category, "100", "5", "A")
        combo = _combo("Box", [(a, 3)])
        rows = allocate_combo_components(combo, Decimal("100.00"), line_quantity=2)
        assert rows[0]["quantity"] == 6          # 3 per combo x 2 combos
        # ...but the split itself is unaffected by how many were bought.
        assert rows[0]["allocated"] == Decimal("100.00")

    def test_zero_amount_line_allocates_nothing(self, test_category):
        a = _rated_product(test_category, "100", "5", "A")
        combo = _combo("Box", [(a, 1)])
        assert allocate_combo_components(combo, Decimal("0")) == []


@pytest.mark.django_db
class TestMixedSlabComboIsBilledPerComponent:
    def _cart_with_mixed_combo(self, user, category, quantity=1):
        """A combo of ₹400 5% masala + ₹100 0% papad, selling for ₹450."""
        spice = _rated_product(category, "400", "5", "Masala")
        papad = _rated_product(category, "100", "0", "Papad")
        combo = _combo("Festive Box", [(spice, 1), (papad, 1)], discount_price="450")
        cart, _ = Cart.objects.get_or_create(user=user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=quantity)
        return combo

    def test_tax_uses_each_component_rate_not_one_blended_rate(
            self, authenticated_client, test_user, test_category):
        self._cart_with_mixed_combo(test_user, test_category)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201

        order = Order.objects.get()
        # ₹450 splits 400:100 -> 360 masala @5%, 90 papad @0%.
        # GST = 360 x 5/105 = 17.14, and NOTHING from the papad share.
        assert order.tax == Decimal("17.14")
        # A single 5% rate on the whole line would have been 21.43 — the bug
        # this change fixes. Assert we are not doing that.
        assert order.tax != Decimal("21.43")

    def test_breakdown_shows_one_row_per_slab_for_a_single_combo_line(
            self, authenticated_client, test_user, test_category):
        self._cart_with_mixed_combo(test_user, test_category)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        placed = authenticated_client.get(URL).json()[0]
        assert placed["tax_breakdown"] == [
            {"rate": 0.0, "taxable_value": 90.0, "tax_amount": 0.0},
            {"rate": 5.0, "taxable_value": 342.86, "tax_amount": 17.14},
            # Delivery is its own taxable supply (SAC 9968) and gets its own
            # slab, or the invoice's GST summary would omit it and stop
            # reconciling against the grand total.
            {"rate": 18.0, "taxable_value": 59.0, "tax_amount": 10.62},
        ]

    def test_components_sum_to_the_line_total(
            self, authenticated_client, test_user, test_category):
        self._cart_with_mixed_combo(test_user, test_category, quantity=3)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        item = OrderItem.objects.get(item_type="combo")
        components = list(item.components.all())
        assert len(components) == 2
        assert sum(c.allocated_amount for c in components) == item.final_price
        assert sum(c.tax_amount for c in components) == item.tax_amount

    def test_cart_quote_matches_the_placed_order(
            self, authenticated_client, test_user, test_category):
        """The checkout page and the resulting bill must not disagree."""
        self._cart_with_mixed_combo(test_user, test_category)
        quoted = authenticated_client.get("/api/cart/").json()["summary"]
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        placed = authenticated_client.get(URL).json()[0]
        assert placed["tax_breakdown"] == quoted["tax_breakdown"]
        assert Decimal(placed["tax"]) == Decimal(str(quoted["tax"]))

    def test_component_snapshots_survive_a_reprice_and_a_re_rate(
            self, authenticated_client, test_user, test_category):
        combo = self._cart_with_mixed_combo(test_user, test_category)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        before = authenticated_client.get(URL).json()[0]["tax_breakdown"]

        # The shop later re-rates everything to 12% and re-prices the parts.
        Product.objects.all().update(tax_rate=Decimal("12"))
        ProductVariant.objects.all().update(price=Decimal("999"))
        ProductComboItem.objects.filter(combo=combo).delete()   # even recomposed

        assert authenticated_client.get(URL).json()[0]["tax_breakdown"] == before

    def test_coupon_stacks_on_a_combo_and_still_reconciles(
            self, authenticated_client, test_user, test_category):
        from admin_panel.models import Coupon
        self._cart_with_mixed_combo(test_user, test_category)
        Coupon.objects.create(code="COMBO10", discount_percent=10, is_active=True)

        payload = dict(ADDR, coupon_code="COMBO10")
        assert authenticated_client.post(URL, payload, format="json").status_code == 201

        order = Order.objects.get()
        item = order.items.get()
        components = list(item.components.all())
        # The coupon comes off before the split, so the parts still sum to the
        # (now smaller) line total and the header tax matches their sum.
        assert sum(c.allocated_amount for c in components) == item.final_price
        assert order.tax == sum(c.tax_amount for c in components)


@pytest.mark.django_db
class TestHistoricalComboLines:
    """Orders placed before the split shipped must still print."""

    def test_line_without_components_falls_back_to_its_stored_rate(
            self, authenticated_client, test_user, test_category):
        self_spice = _rated_product(test_category, "400", "5", "Masala")
        combo = _combo("Box", [(self_spice, 1)], discount_price="350")
        cart, _ = Cart.objects.get_or_create(user=test_user)
        CartItem.objects.create(cart=cart, combo=combo, item_type="combo", quantity=1)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201

        # Simulate a pre-migration order: the line exists, the split does not.
        OrderItemComponent.objects.all().delete()

        placed = authenticated_client.get(URL).json()[0]
        assert placed["tax_breakdown"], "a legacy combo line must still report GST"
        # The rows reconcile against TOTAL output tax — goods plus the delivery
        # slab — not against `tax`, which is the goods figure alone.
        assert sum(Decimal(str(r["tax_amount"])) for r in placed["tax_breakdown"]) \
            == Decimal(placed["total_tax"])
