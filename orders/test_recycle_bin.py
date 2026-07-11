"""
Recycle Bin for orders — soft-delete + restore (admin only).

DELETE on an order must NOT destroy the row (orders are financial records); it
flips is_deleted so an admin can recover it. Deleted orders drop out of the
normal admin list and the customer's own list, but surface under ?deleted=true
and can be restored.
"""
from decimal import Decimal

import pytest

from orders.models import Order


def _order(user, **kw):
    kw.setdefault("shipping_address", "1 Test Rd")
    kw.setdefault("phone_number", "1234567890")
    kw.setdefault("payment_method", "COD")
    kw.setdefault("subtotal", Decimal("100.00"))
    kw.setdefault("total_amount", Decimal("100.00"))
    return Order.objects.create(user=user, **kw)


def _ids(resp):
    """Order ids from a list response, tolerant of pagination envelope."""
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
        # Back in the normal list.
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
        # Either 403 (permission) or 404 (outside their non-deleted queryset) is
        # acceptable — the invariant is that the order stays deleted.
        assert resp.status_code in (403, 404)
        order.refresh_from_db()
        assert order.is_deleted is True
