"""
Tests for the admin-only delivery-bill store: the
`/api/orders/{id}/delivery_bill/` action (GET stream / POST upload / DELETE) and
the `has_delivery_bill` / `delivery_bill_uploaded_at` serializer metadata.

The delivery bill is the admin's PRIVATE record of the courier/delivery receipt,
so the security contract is the point of this suite: only staff may upload, view
or delete it, and the file is streamed through the endpoint — never exposed as a
storage URL. Happy AND sad paths: good uploads, bad types, oversize, missing
file, empty GET, replace, delete, and full access-control (owner / anon /
other-user / staff).

Uploads land in InMemoryStorage (see test_settings), so files round-trip in
memory without touching Cloudinary.
"""
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from orders.views import OrderViewSet


@pytest.fixture
def staff_client(test_admin):
    """An admin client on its OWN APIClient instance.

    The shared `admin_client`/`authenticated_client` fixtures both mutate the
    same `api_client`, so requesting both in one test leaves a single client
    with whichever credentials were set last. Cross-actor tests (admin uploads,
    customer is denied) need two genuinely separate clients — this is the
    independent admin one.
    """
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
    """Collect a (possibly streaming) FileResponse body into bytes."""
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
        # Extension is normalised from the trusted content-type, not the filename.
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
        # The bill was replaced, not appended: new object, image extension now.
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
        # Shrink the cap rather than build a real 10 MB payload.
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
        # And a subsequent view is now empty.
        assert admin_client.get(self._url(test_order)).status_code == 404

    def test_delete_when_none_is_idempotent(self, admin_client, test_order):
        r = admin_client.delete(self._url(test_order))
        assert r.status_code == 200


@pytest.mark.django_db
class TestDeliveryBillAccessControl:
    """The whole point: only staff may touch a delivery bill."""

    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_anonymous_rejected(self, api_client, test_order):
        assert api_client.get(self._url(test_order)).status_code in (401, 403)
        assert api_client.post(self._url(test_order), {"file": _pdf_upload()},
                               format="multipart").status_code in (401, 403)

    def test_owner_non_staff_cannot_upload(self, authenticated_client, test_order):
        # test_order belongs to test_user (a normal customer). Even the OWNER
        # must not be able to upload/see the admin's private delivery bill.
        r = authenticated_client.post(self._url(test_order), {"file": _pdf_upload()},
                                      format="multipart")
        assert r.status_code == 403
        test_order.refresh_from_db()
        assert not test_order.delivery_bill

    def test_owner_non_staff_cannot_view(self, staff_client, authenticated_client, test_order):
        # Admin uploads a bill; the customer who owns the order still can't read it.
        # Two independent clients — see the `staff_client` fixture docstring.
        assert staff_client.post(self._url(test_order), {"file": _pdf_upload()},
                                 format="multipart").status_code == 201
        assert authenticated_client.get(self._url(test_order)).status_code == 403

    def test_owner_non_staff_cannot_delete(self, staff_client, authenticated_client, test_order):
        assert staff_client.post(self._url(test_order), {"file": _pdf_upload()},
                                 format="multipart").status_code == 201
        assert authenticated_client.delete(self._url(test_order)).status_code == 403
        test_order.refresh_from_db()
        assert test_order.delivery_bill  # still there

    def test_other_user_rejected(self, authenticated_client_user2, test_order):
        r = authenticated_client_user2.get(self._url(test_order))
        assert r.status_code in (403, 404)


@pytest.mark.django_db
class TestDeliveryBillSerializerMetadata:
    """`has_delivery_bill` drives the admin UI's upload/view state and must never
    leak the storage URL."""

    def _url(self, order):
        return f"/api/orders/{order.id}/delivery_bill/"

    def test_list_flags_absence_then_presence(self, admin_client, test_order):
        # Before upload: admin order list reports no bill.
        before = admin_client.get("/api/orders/").data
        row = next(o for o in before["results"] if o["id"] == test_order.id)
        assert row["has_delivery_bill"] is False
        assert row["delivery_bill_uploaded_at"] is None
        # A URL to the file must never be present in the payload.
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
