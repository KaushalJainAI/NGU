"""GST place of supply: resolving it, freezing it, and the heads it decides.

The amount of tax never depends on the place of supply — 5% is 5% whether it
splits into CGST 2.5 + SGST 2.5 or lands wholly as IGST 5. What depends on it is
WHICH GOVERNMENT gets credited and which GSTR-1 table the sale is reported in,
so these tests care about heads and about the snapshot never moving, not about
totals changing.
"""
from decimal import Decimal

import pytest

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.models import Order
from orders.place_of_supply import (
    head_rate_label, is_interstate, place_of_supply_for, resolve_state_code,
    split_gst, state_name,
)
from products.models import Product

URL = "/api/orders/"
SELLER = "23"          # Madhya Pradesh — settings.SELLER_STATE_CODE
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890",
        "payment_method": "COD"}


def _product(category, price="400", rate="5", name="Spice"):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price), stock=50,
        weight=Decimal("250"), unit="g", spice_form="powder", is_active=True,
        tax_rate=Decimal(rate), image=create_test_image(f"{name}.jpg"))


def _cart(user, category, **kw):
    cart, _ = Cart.objects.get_or_create(user=user)
    CartItem.objects.create(cart=cart, item_type="product", quantity=1,
                            product=_product(category, **kw))
    return cart


def _placed_order(user, place_of_supply=SELLER):
    """An already-placed order, straight through the ORM.

    Used by the admin/export tests, which need an order to EXIST but are not
    exercising checkout. Going through the API there would mean holding an
    admin and a customer client at once, and both fixtures configure the same
    shared `api_client` object — the second one silently wins.
    """
    return Order.objects.create(
        user=user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="COD", subtotal=Decimal("400"),
        tax=Decimal("19.05"), shipping_charge=Decimal("59"),
        shipping_tax=Decimal("10.62"), total_amount=Decimal("469.62"),
        place_of_supply_state_code=place_of_supply)


class TestResolveStateCode:
    """Turning what a customer typed into a two-digit GST state code."""

    @pytest.mark.parametrize("text,code", [
        ("Madhya Pradesh", "23"),
        ("madhya pradesh", "23"),
        ("MADHYA PRADESH", "23"),
        ("Maharashtra", "27"),
        ("Tamil Nadu", "33"),
        ("TamilNadu", "33"),
        ("West Bengal", "19"),
        ("Orissa", "21"),          # renamed state, still typed the old way
        ("Pondicherry", "34"),     # ditto
        ("Uttaranchal", "05"),     # ditto
    ])
    def test_full_names(self, text, code):
        assert resolve_state_code(state=text) == code

    @pytest.mark.parametrize("text,code", [
        ("M.P.", "23"), ("MP", "23"), ("mp", "23"),
        ("UP", "09"), ("TN", "33"), ("KA", "29"), ("DL", "07"),
    ])
    def test_abbreviations_in_the_state_field(self, text, code):
        assert resolve_state_code(state=text) == code

    @pytest.mark.parametrize("text,code", [
        ("मध्य प्रदेश", "23"), ("महाराष्ट्र", "27"), ("दिल्ली", "07"),
    ])
    def test_devanagari(self, text, code):
        """The storefront is multilingual; a Hindi state name must still resolve."""
        assert resolve_state_code(state=text) == code

    def test_punctuation_and_spacing_are_ignored(self):
        assert resolve_state_code(state="  madhya   pradesh, ") == "23"
        assert resolve_state_code(state="State of Kerala") == "32"

    def test_ampersand_written_either_way(self):
        assert resolve_state_code(state="Jammu & Kashmir") == "01"
        assert resolve_state_code(state="Jammu and Kashmir") == "01"

    def test_geocoded_state_field_carrying_a_city_too(self):
        """Autofill sometimes hands back "Indore, Madhya Pradesh"."""
        assert resolve_state_code(state="Indore, Madhya Pradesh") == "23"

    def test_falls_back_to_scanning_the_address_blob(self):
        assert resolve_state_code(
            address="12 MG Road, Pune, Maharashtra - 411001") == "27"

    def test_abbreviations_are_NOT_scanned_inside_an_address(self):
        """"up" and "as" are ordinary words; matching them would be a tax bug."""
        assert resolve_state_code(address="Flat 3, Up the hill, as agreed") is None

    def test_rightmost_state_wins_when_a_street_shares_a_name(self):
        """Indian addresses run narrow-to-wide, so the real state is last."""
        assert resolve_state_code(
            address="4 Goa Road, Indore, Madhya Pradesh") == "23"

    def test_explicit_state_field_beats_the_address(self):
        assert resolve_state_code(
            state="Maharashtra", address="1 Rd, Indore, Madhya Pradesh") == "27"

    def test_unresolvable_returns_none(self):
        assert resolve_state_code(state="Freedonia", address="1 Rd") is None
        assert resolve_state_code() is None


class TestDefaultsToSellerState:
    """"Default to Madhya Pradesh just in case" — the fallback rule."""

    def test_unresolvable_address_bills_intra_state(self):
        assert place_of_supply_for(state="Freedonia", address="???") == SELLER

    def test_empty_input_bills_intra_state(self):
        assert place_of_supply_for() == SELLER

    def test_a_resolvable_address_is_never_overridden_by_the_default(self):
        assert place_of_supply_for(state="Kerala") == "32"


class TestInterstateFlag:
    def test_seller_state_is_intra_state(self):
        assert is_interstate(SELLER) is False

    def test_any_other_state_is_inter_state(self):
        assert is_interstate("27") is True

    def test_blank_is_intra_state_so_historical_bills_do_not_move(self):
        """Orders predating this field were billed AND FILED as intra-state."""
        assert is_interstate("") is False
        assert is_interstate(None) is False


class TestSplitGst:
    def test_intra_state_halves_into_cgst_and_sgst(self):
        assert split_gst(Decimal("19.04"), SELLER) == {
            "cgst": Decimal("9.52"), "sgst": Decimal("9.52"), "igst": Decimal("0.00")}

    def test_inter_state_is_all_igst(self):
        assert split_gst(Decimal("19.04"), "27") == {
            "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("19.04")}

    def test_odd_paisa_goes_to_sgst_so_the_parts_still_sum(self):
        heads = split_gst(Decimal("19.05"), SELLER)
        assert heads["cgst"] == Decimal("9.53")
        assert heads["sgst"] == Decimal("9.52")
        assert heads["cgst"] + heads["sgst"] == Decimal("19.05")

    @pytest.mark.parametrize("amount", ["0", "0.01", "5", "19.05", "1234.57"])
    @pytest.mark.parametrize("pos", [SELLER, "27"])
    def test_heads_always_sum_back_to_the_tax(self, amount, pos):
        heads = split_gst(Decimal(amount), pos)
        assert heads["cgst"] + heads["sgst"] + heads["igst"] == Decimal(amount)

    def test_zero_tax_produces_zero_heads(self):
        assert split_gst(0, "27") == {
            "cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("0.00")}


class TestRateLabel:
    def test_intra_state_rate_is_shown_split(self):
        """Printing a bare "5%" beside two 2.5% columns invites adding to 10%."""
        assert head_rate_label(5, SELLER) == "2.5% + 2.5%"

    def test_inter_state_rate_is_whole(self):
        assert head_rate_label(5, "27") == "5%"

    def test_exempt_slab_is_not_split(self):
        """Papad is 0%; "0% + 0%" is noise, not information."""
        assert head_rate_label(0, SELLER) == "0%"

    def test_unattributed_slab_has_no_rate(self):
        assert head_rate_label(None, SELLER) == ""


class TestStateName:
    def test_known_code(self):
        assert state_name("23") == "Madhya Pradesh"

    def test_unpadded_code_still_resolves(self):
        assert state_name("7") == "Delhi"

    def test_unknown_code_is_blank_not_a_guess(self):
        assert state_name("99") == ""


@pytest.mark.django_db
class TestPlaceOfSupplyIsCapturedAtCheckout:
    def test_structured_state_from_the_form_is_used(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        payload = dict(ADDR, shipping_state="Maharashtra", shipping_pincode="411001",
                       shipping_address="12 MG Road, Pune, Maharashtra - 411001")
        assert authenticated_client.post(URL, payload, format="json").status_code == 201
        order = Order.objects.get()
        assert order.place_of_supply_state_code == "27"
        assert order.is_interstate is True
        assert order.shipping_state == "Maharashtra"
        assert order.shipping_pincode == "411001"

    def test_address_is_parsed_when_the_state_field_is_absent(
            self, authenticated_client, test_user, test_category):
        """Admin/legacy API callers don't send the structured fields."""
        _cart(test_user, test_category)
        payload = dict(ADDR, shipping_address="9 Marine Drive, Kochi, Kerala - 682001")
        assert authenticated_client.post(URL, payload, format="json").status_code == 201
        assert Order.objects.get().place_of_supply_state_code == "32"

    def test_unplaceable_address_defaults_to_the_seller_state(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        assert authenticated_client.post(URL, ADDR, format="json").status_code == 201
        order = Order.objects.get()
        assert order.place_of_supply_state_code == SELLER
        assert order.is_interstate is False

    def test_placing_an_order_never_fails_over_a_junk_state(
            self, authenticated_client, test_user, test_category):
        """A tax-reporting field must not be able to block a sale."""
        _cart(test_user, test_category)
        payload = dict(ADDR, shipping_state="Freedonia")
        assert authenticated_client.post(URL, payload, format="json").status_code == 201
        assert Order.objects.get().place_of_supply_state_code == SELLER

    def test_the_snapshot_does_not_follow_a_later_address_edit(
            self, admin_client, test_user, test_category):
        """Re-heading an already-issued invoice off an address fix is the bug."""
        order = _placed_order(test_user, "32")
        admin_client.patch(f"{URL}{order.id}/",
                           {"shipping_address": "1 New Rd, Pune, Maharashtra"},
                           format="json")
        order.refresh_from_db()
        assert order.place_of_supply_state_code == "32"

    def test_the_tax_TOTAL_is_identical_either_way(
            self, authenticated_client, authenticated_client_user2,
            test_user, test_user2, test_category):
        """Inter-state changes the heads, never the money. This is why the old
        behaviour was wrong but not an under-collection."""
        product = _product(test_category)
        for user in (test_user, test_user2):
            cart, _ = Cart.objects.get_or_create(user=user)
            CartItem.objects.create(cart=cart, item_type="product",
                                    quantity=1, product=product)

        authenticated_client.post(URL, dict(ADDR, shipping_state="Maharashtra"),
                                  format="json")
        authenticated_client_user2.post(URL, dict(ADDR, shipping_state="Madhya Pradesh"),
                                        format="json")
        far, near = (Order.objects.get(user=test_user),
                     Order.objects.get(user=test_user2))
        assert far.is_interstate is True and near.is_interstate is False
        assert far.total_tax == near.total_tax          # same money…
        assert far.gst_heads != near.gst_heads          # …different heads


@pytest.mark.django_db
class TestOrderGstHeads:
    def test_intra_state_order_reports_cgst_and_sgst(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        authenticated_client.post(URL, dict(ADDR, shipping_state="Madhya Pradesh"),
                                  format="json")
        order = Order.objects.get()
        heads = order.gst_heads
        assert heads["igst"] == Decimal("0.00")
        assert heads["cgst"] + heads["sgst"] == order.total_tax

    def test_inter_state_order_reports_igst(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        authenticated_client.post(URL, dict(ADDR, shipping_state="Karnataka"),
                                  format="json")
        order = Order.objects.get()
        assert order.gst_heads["igst"] == order.total_tax
        assert order.gst_heads["cgst"] == Decimal("0.00")
        assert order.place_of_supply_name == "Karnataka"

    def test_historical_order_reads_as_intra_state(self, test_user):
        """A row written before the column existed carries ''."""
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1",
            payment_method="COD", subtotal=Decimal("100"),
            tax=Decimal("4.76"), total_amount=Decimal("100"))
        assert order.place_of_supply_state_code == ""
        assert order.is_interstate is False
        assert order.place_of_supply_name == "Madhya Pradesh"
        assert order.gst_heads["igst"] == Decimal("0.00")


@pytest.mark.django_db
class TestPlaceOfSupplyOnTheApi:
    def test_order_response_carries_the_heads(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        authenticated_client.post(URL, dict(ADDR, shipping_state="Gujarat"),
                                  format="json")
        pos = authenticated_client.get(URL).json()[0]["place_of_supply"]
        assert pos["code"] == "24"
        assert pos["name"] == "Gujarat"
        assert pos["is_interstate"] is True
        assert Decimal(pos["igst"]) > 0
        assert Decimal(pos["cgst"]) == 0

    def test_heads_reconcile_with_total_tax_on_the_response(
            self, authenticated_client, test_user, test_category):
        _cart(test_user, test_category)
        authenticated_client.post(URL, ADDR, format="json")
        body = authenticated_client.get(URL).json()[0]
        pos = body["place_of_supply"]
        assert (Decimal(pos["cgst"]) + Decimal(pos["sgst"]) + Decimal(pos["igst"])
                == Decimal(body["total_tax"]))


@pytest.mark.django_db
class TestAdminCanCorrectPlaceOfSupply:
    """The resolver guesses the seller's state when it can't place an address.
    That guess has to be fixable before the return is filed."""

    def test_admin_can_set_a_valid_code(self, admin_client, test_user):
        order = _placed_order(test_user)
        r = admin_client.patch(f"{URL}{order.id}/",
                               {"place_of_supply_state_code": "27"}, format="json")
        assert r.status_code == 200
        order.refresh_from_db()
        assert order.place_of_supply_state_code == "27"
        assert order.is_interstate is True

    def test_a_code_that_is_not_a_real_state_is_rejected(self, admin_client, test_user):
        order = _placed_order(test_user)
        r = admin_client.patch(f"{URL}{order.id}/",
                               {"place_of_supply_state_code": "99"}, format="json")
        assert r.status_code == 400
        order.refresh_from_db()
        assert order.place_of_supply_state_code == SELLER

    def test_blanking_it_is_rejected(self, admin_client, test_user):
        """Blank means "historical"; letting an admin write it would silently
        reclassify a live order."""
        order = _placed_order(test_user)
        r = admin_client.patch(f"{URL}{order.id}/",
                               {"place_of_supply_state_code": ""}, format="json")
        assert r.status_code == 400

    def test_a_customer_cannot_change_it(self, authenticated_client, test_user):
        order = _placed_order(test_user)
        authenticated_client.patch(f"{URL}{order.id}/",
                                   {"place_of_supply_state_code": "27"}, format="json")
        order.refresh_from_db()
        assert order.place_of_supply_state_code == SELLER


@pytest.mark.django_db
class TestInvoiceShowsTheRightHeads:
    def _pdf(self, client, user, category, **kw):
        _cart(user, category)
        client.post(URL, dict(ADDR, **kw), format="json")
        order = Order.objects.get()
        from orders.invoice import generate_invoice_pdf
        from orders.invoicing import issue_invoice
        invoice, _ = issue_invoice(order)
        return order, generate_invoice_pdf(invoice)

    def test_intra_state_invoice_renders(
            self, authenticated_client, test_user, test_category):
        order, pdf = self._pdf(authenticated_client, test_user, test_category,
                               shipping_state="Madhya Pradesh")
        assert pdf[:4] == b"%PDF" and len(pdf) > 1000
        assert order.is_interstate is False

    def test_inter_state_invoice_renders(
            self, authenticated_client, test_user, test_category):
        order, pdf = self._pdf(authenticated_client, test_user, test_category,
                               shipping_state="Tamil Nadu")
        assert pdf[:4] == b"%PDF" and len(pdf) > 1000
        assert order.is_interstate is True

    def test_historical_order_still_renders(self, test_user):
        """No place of supply on the row — the bill must not crash, and must
        keep printing as the intra-state supply it was filed as."""
        from orders.invoice import generate_invoice_pdf
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1",
            payment_method="COD", subtotal=Decimal("100"),
            tax=Decimal("4.76"), total_amount=Decimal("100"))
        from orders.invoicing import issue_invoice
        invoice, _ = issue_invoice(order)
        assert generate_invoice_pdf(invoice)[:4] == b"%PDF"


@pytest.mark.django_db
class TestCsvExportCarriesPlaceOfSupply:
    """GSTR-1 Table 7 is bucketed BY place of supply — without these columns the
    return cannot be built from the export at all."""

    def test_columns_are_present_and_reconcile(self, admin_client, test_user):
        _placed_order(test_user, "27")           # Maharashtra — inter-state
        r = admin_client.get(f"{URL}?scope=all&export=csv")
        assert r.status_code == 200
        body = b"".join(r.streaming_content).decode()
        header, row = body.splitlines()[0], body.splitlines()[1]
        cols = header.split(",")
        for name in ("Place of Supply", "POS Code", "CGST", "SGST", "IGST"):
            assert name in cols
        cells = row.split(",")
        assert cells[cols.index("Place of Supply")] == "Maharashtra"
        assert cells[cols.index("POS Code")] == "27"
        # Inter-state: all of it under IGST, and equal to Total GST.
        assert Decimal(cells[cols.index("IGST")]) == Decimal(cells[cols.index("Total GST")])
        assert Decimal(cells[cols.index("CGST")]) == 0
