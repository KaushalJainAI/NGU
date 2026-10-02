"""Thin Razorpay client factory — keeps all SDK construction in one place.

Every module that talks to Razorpay (create-order, verify, webhook, the L3
reconciliation command) imports `get_razorpay_client()` from here so keys are
read from settings exactly once and the rest of the code never touches
`razorpay.Client(...)` directly.
"""
import razorpay
from django.conf import settings


class RazorpayNotConfigured(RuntimeError):
    """Raised when Razorpay keys are missing — surfaced as a 503, never a 500."""


def get_razorpay_client():
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
    if not key_id or not key_secret:
        raise RazorpayNotConfigured(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured."
        )
    client = razorpay.Client(auth=(key_id, key_secret))
    client.set_app_details({"title": "NGU", "version": "1.0"})
    return client


def get_public_key_id():
    """The publishable key id sent to the browser (safe to expose)."""
    return getattr(settings, 'RAZORPAY_KEY_ID', '')
