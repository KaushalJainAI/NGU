"""
Tests for coupons: is_valid() unit matrix and /api/coupons/validate/ endpoint.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from admin_panel.models import Coupon

URL = "/api/coupons/validate/"


# --- From test_coupon_validity.py ---

def _coupon(**kw):
    kw.setdefault("code", "C" + str(abs(hash(frozenset(kw.items()))) % 100000))
    kw.setdefault("discount_percent", 10)
    kw.setdefault("is_active", True)
    return Coupon.objects.create(**kw)


@pytest.mark.django_db
class TestCouponIsValid:
    # ---- happy ----------------------------------------------------------- #
    def test_active_unexpired_is_valid(self):
        c = _coupon(valid_until=timezone.now() + timedelta(days=1))
        assert c.is_valid() is True

    def test_no_expiry_is_valid_forever(self):
        assert _coupon(valid_until=None).is_valid() is True

    def test_no_max_usage_is_unlimited(self):
        c = _coupon(max_usage=None, usage_count=10_000)
        assert c.is_valid() is True

    def test_no_order_amount_skips_minimum_check(self):
        c = _coupon(minimum_order_amount=Decimal("1000.00"))
        assert c.is_valid(order_amount=None) is True

    # ---- sad ------------------------------------------------------------- #
    def test_inactive_is_invalid(self):
        assert _coupon(is_active=False).is_valid() is False

    def test_expired_is_invalid(self):
        c = _coupon(valid_until=timezone.now() - timedelta(seconds=1))
        assert c.is_valid() is False

    def test_usage_at_max_is_invalid(self):
        c = _coupon(max_usage=5, usage_count=5)        # >= max
        assert c.is_valid() is False

    def test_usage_over_max_is_invalid(self):
        c = _coupon(max_usage=5, usage_count=6)
        assert c.is_valid() is False

    def test_order_below_minimum_is_invalid(self):
        c = _coupon(minimum_order_amount=Decimal("500.00"))
        assert c.is_valid(order_amount=Decimal("499.99")) is False

    # ---- boundaries ------------------------------------------------------ #
    def test_one_use_remaining_is_valid(self):
        c = _coupon(max_usage=5, usage_count=4)
        assert c.is_valid() is True

    def test_order_exactly_minimum_is_valid(self):
        c = _coupon(minimum_order_amount=Decimal("500.00"))
        assert c.is_valid(order_amount=Decimal("500.00")) is True

    # ---- truthful reasons: the message must name the ACTUAL problem -------- #
    def test_reason_none_when_valid(self):
        c = _coupon(valid_until=timezone.now() + timedelta(days=1))
        assert c.get_invalid_reason() is None

    def test_reason_inactive(self):
        assert "no longer active" in _coupon(is_active=False).get_invalid_reason()

    def test_reason_expired(self):
        c = _coupon(valid_until=timezone.now() - timedelta(seconds=1))
        assert "expired" in c.get_invalid_reason().lower()

    def test_reason_usage_limit(self):
        c = _coupon(max_usage=2, usage_count=2)
        assert "usage limit" in c.get_invalid_reason().lower()

    def test_reason_minimum_order_states_shortfall(self):
        c = _coupon(minimum_order_amount=Decimal("500.00"))
        msg = c.get_invalid_reason(order_amount=Decimal("300.00"))
        assert "200" in msg and "500" in msg   # shortfall and the minimum

    def test_reason_prioritises_expiry_over_minimum(self):
        # An expired coupon below the minimum reports expiry (the first blocker),
        # not a misleading "add more to your cart".
        c = _coupon(valid_until=timezone.now() - timedelta(seconds=1),
                    minimum_order_amount=Decimal("9999"))
        assert "expired" in c.get_invalid_reason(order_amount=Decimal("1")).lower()

    def test_all_constraints_together(self):
        c = _coupon(
            valid_until=timezone.now() + timedelta(hours=1),
            max_usage=10, usage_count=9,
            minimum_order_amount=Decimal("250.00"),
        )
        assert c.is_valid(order_amount=Decimal("250.00")) is True
        # flip the one failing condition at a time
        c.is_active = False
        assert c.is_valid(order_amount=Decimal("250.00")) is False


# --- From test_coupon_validate.py ---

@pytest.mark.django_db
class TestCouponValidateEndpoint:
    def test_valid_coupon(self, admin_client):
        Coupon.objects.create(code="SAVE20", discount_percent=20, is_active=True)
        resp = admin_client.post(URL, {"code": "SAVE20"}, format="json")
        assert resp.status_code == 200
        assert resp.data["valid"] is True
        assert resp.data["reason"] is None
        assert resp.data["coupon"]["code"] == "SAVE20"

    def test_case_insensitive_lookup(self, admin_client):
        Coupon.objects.create(code="SAVE20", discount_percent=20, is_active=True)
        resp = admin_client.post(URL, {"code": "save20"}, format="json")
        assert resp.status_code == 200
        assert resp.data["valid"] is True

    def test_inactive_coupon(self, admin_client):
        Coupon.objects.create(code="OFF", discount_percent=10, is_active=False)
        resp = admin_client.post(URL, {"code": "OFF"}, format="json")
        assert resp.status_code == 200
        assert resp.data["valid"] is False
        assert "inactive" in resp.data["reason"]

    def test_expired_coupon(self, admin_client):
        Coupon.objects.create(
            code="OLD", discount_percent=10, is_active=True,
            valid_until=timezone.now() - timedelta(days=1),
        )
        resp = admin_client.post(URL, {"code": "OLD"}, format="json")
        assert resp.status_code == 200
        assert resp.data["valid"] is False
        assert "expired" in resp.data["reason"]

    def test_usage_limit_reached(self, admin_client):
        Coupon.objects.create(
            code="MAXED", discount_percent=10, is_active=True,
            max_usage=5, usage_count=5,
        )
        resp = admin_client.post(URL, {"code": "MAXED"}, format="json")
        assert resp.data["valid"] is False
        assert "usage limit" in resp.data["reason"]

    def test_missing_code_is_400(self, admin_client):
        resp = admin_client.post(URL, {"code": "  "}, format="json")
        assert resp.status_code == 400
        assert resp.data["valid"] is False

    def test_nonexistent_code_is_404(self, admin_client):
        resp = admin_client.post(URL, {"code": "NOPE"}, format="json")
        assert resp.status_code == 404
        assert resp.data["valid"] is False
        assert "error" in resp.data

    def test_requires_admin(self, authenticated_client):
        Coupon.objects.create(code="SAVE20", discount_percent=20, is_active=True)
        resp = authenticated_client.post(URL, {"code": "SAVE20"}, format="json")
        assert resp.status_code == 403

    def test_requires_authentication(self, api_client):
        resp = api_client.post(URL, {"code": "SAVE20"}, format="json")
        assert resp.status_code in (401, 403)
