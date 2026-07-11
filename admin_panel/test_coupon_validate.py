"""
Admin coupon-validation endpoint: POST /api/coupons/validate/.

An admin utility to check whether a code exists and is redeemable (active, not
expired, under its usage limit). Distinct from the checkout-time validation in
orders — it does NOT fail on per-customer concerns (assignment / minimum order).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from admin_panel.models import Coupon

URL = "/api/coupons/validate/"


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
