"""HSN classification: the reference table, the field, and the admin surfaces.

The order-side half — snapshotting onto lines and the Table 12 summary — lives
in orders/test_hsn_summary.py.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from conftest import create_test_image
from products.bulk_views import MAX_BULK_ROWS
from products.hsn import HSN_BY_CODE, HSN_REFERENCE, describe, suggest, validate_hsn_code
from products.models import Product


def _product(category, name, **kwargs):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal("100"),
        stock=10, weight=Decimal("100"), unit="g", spice_form="powder",
        is_active=True, image=create_test_image(f"{name}.jpg"), **kwargs)


class TestValidator:
    @pytest.mark.parametrize("code", ["0910", "091091", "09109100", ""])
    def test_accepts_4_6_8_digits_and_blank(self, code):
        validate_hsn_code(code)          # must not raise

    @pytest.mark.parametrize("code", ["091", "09109", "091091001", "0910AB", "09-10"])
    def test_rejects_anything_else(self, code):
        """A malformed code surfaces as a rejected RETURN months later, so it has
        to be caught at entry, not at filing time."""
        with pytest.raises(ValidationError):
            validate_hsn_code(code)


class TestReferenceTable:
    def test_every_row_is_itself_a_valid_code(self):
        for row in HSN_REFERENCE:
            validate_hsn_code(row["code"])

    def test_codes_are_unique(self):
        codes = [row["code"] for row in HSN_REFERENCE]
        assert len(codes) == len(set(codes))

    def test_papad_is_nil_rated_and_masala_blends_are_five(self):
        """The two rates this catalogue actually turns on."""
        assert HSN_BY_CODE["19059040"]["gst_rate"] == Decimal("0")
        assert HSN_BY_CODE["09109100"]["gst_rate"] == Decimal("5")

    def test_mixed_condiments_carry_the_post_2025_18_percent(self):
        """2103 went 12% -> 18% on 22 Sep 2025. If this row ever silently reads
        12 again, every blend reclassified under it under-charges by 6 points."""
        assert HSN_BY_CODE["21039040"]["gst_rate"] == Decimal("18")

    def test_describe_falls_back_to_a_prefix_match(self):
        """A product stored at 4 digits still resolves for display."""
        assert describe("0910")["code"].startswith("0910")

    def test_describe_returns_none_for_unknown_and_blank(self):
        assert describe("") is None
        assert describe("99999999") is None


class TestSuggest:
    """The keyword classifier, checked against the real catalogue names."""

    @pytest.mark.parametrize("name,code", [
        ("Nidhi patna Mirchi 500g", "09042211"),
        ("Nidhi VIP teja Mirchi 500g", "09042211"),
        ("Desi tadaka mirchi 500g", "09042211"),
        ("Nidhi kashmari mirchi 100g", "09042211"),
        ("Nidhi Dhaniya powder 500g", "09092200"),
        ("Nidhi Haldi powder 500g", "09103030"),
        ("Nidhi Dry Ginger powder 100g", "09101210"),
        ("Nidhi kasuri methi 25g", "09109924"),
        ("Nidhi Amchur powder 500g", "09109990"),
        ("Nidhi garam masala 100g", "09109100"),
        ("Nidhi chat masala 100g", "09109100"),
        ("Nidhi Pav Bhaji masala 100g", "09109100"),
        ("Nidhi Kichan king masala 100g", "09109100"),
        ("NIdhi Tea Chai masala 50g", "09109100"),
        ("Nidhi jeeravan 100g", "09109100"),
        ("Nidhi garadu masala 100g", "09109100"),
        ("Nidhi chana masala 100g", "09109100"),
        ("Nidhi nimbu chatani achar masala 200g", "09109100"),
        ("NIdhi Chana papad 200g", "19059040"),
        ("NIdhi Moong Papad 200g", "19059040"),
        ("Nidhi papad katran 1kg", "19059040"),
    ])
    def test_classifies_the_live_catalogue(self, name, code):
        assert suggest(name)[0] == code

    def test_a_masala_that_names_a_spice_is_still_a_masala(self):
        """'Hari mirchi achar masala' contains 'mirchi' but is a blend. Coding it
        as chilli powder would look entirely plausible and be wrong."""
        assert suggest("Nidhi Hari mirchi Achar masala 200g")[0] == "09109100"

    def test_papad_masala_is_a_masala_not_papad(self):
        """Papad is NIL; a masala is taxable. Getting this backwards under-declares
        tax on every papad-masala sale."""
        assert suggest("Nidhi Chana papad masala 130g")[0] == "09109100"
        assert suggest("Nidhi Moong papad Masala 100g")[0] == "09109100"

    def test_blends_are_low_confidence(self):
        """5% (09109100) vs 18% (21039040) turns on the ingredient list, which a
        name cannot settle — so a human must confirm."""
        assert suggest("Nidhi garam masala 100g")[1] == "low"
        assert suggest("Nidhi Haldi powder 500g")[1] == "high"

    def test_unrecognised_name_suggests_nothing(self):
        assert suggest("Stainless steel gift box") == (None, None)


@pytest.mark.django_db
class TestProductField:
    def test_defaults_to_blank_not_to_a_guess(self, test_category):
        """An unclassified product must LOOK unclassified. A plausible wrong code
        is more expensive than an obviously missing one."""
        assert _product(test_category, "Unclassified").hsn_code == ""

    def test_rejects_a_malformed_code_on_save(self, test_category):
        with pytest.raises(ValidationError):
            _product(test_category, "Bad code", hsn_code="12").full_clean()

    def test_is_exposed_on_the_product_api(self, api_client, test_category):
        product = _product(test_category, "Haldi", hsn_code="09103030")
        body = api_client.get(f"/api/products/{product.slug}/").json()
        assert body["hsn_code"] == "09103030"

    def test_admin_can_set_it_through_the_product_form(self, admin_client, test_category):
        product = _product(test_category, "Haldi")
        response = admin_client.patch(
            f"/api/products/{product.slug}/", {"hsn_code": "09103030"}, format="json")
        assert response.status_code == 200, response.data
        product.refresh_from_db()
        assert product.hsn_code == "09103030"

    def test_admin_can_clear_a_code_they_decided_was_wrong(
            self, admin_client, test_category):
        """Blank is a real value ('not classified yet'), so it must be settable —
        otherwise a mis-classification is permanent."""
        product = _product(test_category, "Haldi", hsn_code="09103030")
        response = admin_client.patch(
            f"/api/products/{product.slug}/", {"hsn_code": ""}, format="json")
        assert response.status_code == 200, response.data
        product.refresh_from_db()
        assert product.hsn_code == ""

    def test_product_form_rejects_a_malformed_code(self, admin_client, test_category):
        product = _product(test_category, "Haldi")
        response = admin_client.patch(
            f"/api/products/{product.slug}/", {"hsn_code": "12"}, format="json")
        assert response.status_code == 400
        product.refresh_from_db()
        assert product.hsn_code == ""


@pytest.mark.django_db
class TestHsnReferenceEndpoint:
    URL = "/api/admin/hsn-reference/"

    def test_requires_staff(self, api_client, authenticated_client):
        assert api_client.get(self.URL).status_code in (401, 403)
        assert authenticated_client.get(self.URL).status_code == 403

    def test_returns_the_dated_code_list(self, admin_client):
        body = admin_client.get(self.URL).json()
        assert body["rates_as_of"] == "2025-09-22"
        codes = {row["code"]: row for row in body["codes"]}
        assert codes["19059040"]["gst_rate"] == 0
        assert codes["09109100"]["gst_rate"] == 5
        assert codes["21039040"]["gst_rate"] == 18


@pytest.mark.django_db
class TestHsnCoverageEndpoint:
    URL = "/api/admin/hsn-coverage/"

    def test_requires_staff(self, api_client, authenticated_client):
        assert api_client.get(self.URL).status_code in (401, 403)
        assert authenticated_client.get(self.URL).status_code == 403

    def test_lists_products_with_no_code(self, admin_client, test_category):
        _product(test_category, "Unclassified spice")
        body = admin_client.get(self.URL).json()
        assert [p["name"] for p in body["unclassified"]] == ["Unclassified spice"]
        assert body["unclassified_count"] == 1

    def test_flags_a_rate_that_disagrees_with_the_code(self, admin_client, test_category):
        """The papad-masala case: coded as a 5% blend but still charging the 0%
        that migration 0024 set for anything named '...papad...'."""
        _product(test_category, "Chana papad masala",
                 hsn_code="09109100", tax_rate=Decimal("0"))
        body = admin_client.get(self.URL).json()
        assert body["rate_mismatch_count"] == 1
        row = body["rate_mismatch"][0]
        assert row["tax_rate"] == 0 and row["expected_rate"] == 5

    def test_a_matching_rate_is_not_flagged(self, admin_client, test_category):
        _product(test_category, "Haldi", hsn_code="09103030", tax_rate=Decimal("5"))
        body = admin_client.get(self.URL).json()
        assert body["rate_mismatch_count"] == 0

    def test_never_writes_a_rate(self, admin_client, test_category):
        """Reporting a mismatch must not 'fix' it — what is charged is the
        owner's decision, not the reference table's."""
        product = _product(test_category, "Chana papad masala",
                           hsn_code="09109100", tax_rate=Decimal("0"))
        admin_client.get(self.URL)
        product.refresh_from_db()
        assert product.tax_rate == Decimal("0")


@pytest.mark.django_db
class TestBulkToolsCarryHsn:
    def test_export_includes_the_code(self, admin_client, test_category):
        _product(test_category, "Haldi", hsn_code="09103030")
        response = admin_client.get("/api/admin/products-export/")
        body = b"".join(response.streaming_content).decode("utf-8-sig")
        assert "hsn_code" in body.splitlines()[0]
        assert "09103030" in body

    def test_apply_writes_the_code_to_the_product(self, admin_client, test_category):
        product = _product(test_category, "Haldi")
        response = admin_client.post(
            "/api/admin/bulk-products/apply/",
            {"changes": [{"id": product.id, "hsn_code": "09103030"}]}, format="json")
        assert response.status_code == 200
        product.refresh_from_db()
        assert product.hsn_code == "09103030"

    def test_apply_writes_to_the_product_even_when_the_row_targets_a_size(
            self, admin_client, test_category):
        """HSN belongs to the goods, not the packaging — a 100g and a 500g pack of
        one masala are the same tariff line."""
        product = _product(test_category, "Haldi")
        variant = product.variants.first()
        admin_client.post(
            "/api/admin/bulk-products/apply/",
            {"changes": [{"id": product.id, "variant_id": variant.id,
                          "hsn_code": "09103030"}]}, format="json")
        product.refresh_from_db()
        assert product.hsn_code == "09103030"

    def test_apply_rejects_a_malformed_code_and_saves_nothing(
            self, admin_client, test_category):
        product = _product(test_category, "Haldi")
        response = admin_client.post(
            "/api/admin/bulk-products/apply/",
            {"changes": [{"id": product.id, "hsn_code": "12"}]}, format="json")
        assert response.status_code == 400
        product.refresh_from_db()
        assert product.hsn_code == ""


@pytest.mark.django_db
class TestBulkApplyGuardsItsInput:
    """Malformed ids and oversized batches are the client's problem, not a 500.

    Ids arrive as JSON, so anything can turn up in them. Handing a non-numeric
    id to `filter(id__in=…)` raises ValueError from inside the ORM, which DRF
    renders as a server error on what is simply a bad request.
    """
    URL = "/api/admin/bulk-products/apply/"

    @pytest.mark.parametrize("bad_id", ["abc", None, {}, [], "12x"])
    def test_a_non_numeric_id_is_reported_not_crashed(
            self, admin_client, test_category, bad_id):
        _product(test_category, "Haldi")
        response = admin_client.post(
            self.URL, {"changes": [{"id": bad_id, "price": "120"}]}, format="json")
        assert response.status_code == 400
        assert response.json()["errors"][0]["error"] == "Product not found."

    def test_a_boolean_id_does_not_become_product_one(
            self, admin_client, test_category):
        """`int(True)` is 1 — coercing blindly would edit whichever product
        happens to hold that id."""
        product = _product(test_category, "Haldi")   # _product prices at 100
        response = admin_client.post(
            self.URL, {"changes": [{"id": True, "price": "999"}]}, format="json")
        assert response.status_code == 400
        product.refresh_from_db()
        assert product.price == Decimal("100")

    def test_a_variant_id_that_is_not_a_number_is_reported(
            self, admin_client, test_category):
        product = _product(test_category, "Haldi")
        response = admin_client.post(
            self.URL,
            {"changes": [{"id": product.id, "variant_id": "abc", "price": "120"}]},
            format="json")
        assert response.status_code == 400
        assert "Size not found" in response.json()["errors"][0]["error"]

    def test_an_oversized_batch_is_refused(self, admin_client, test_category):
        """apply() locks every row it touches in ONE transaction — the same rows
        checkout locks — so an unbounded batch can stall the shop."""
        product = _product(test_category, "Haldi")
        changes = [{"id": product.id, "price": "120"}] * (MAX_BULK_ROWS + 1)
        response = admin_client.post(self.URL, {"changes": changes}, format="json")
        assert response.status_code == 400
        assert "Too many changes" in response.json()["error"]
