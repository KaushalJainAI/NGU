"""Static-page policy text for the assistant (AP10).

Transcribed from the storefront's EN locale strings
(Frontend/nidhi-brand-forge/src/i18n/locales/en.json ::
pages.shipping / pages.returns — the SAME source the /shipping-policy and
/return-policy pages render). The retired admin_panel.Policy table is NOT read:
it has no rows and no routes, so the tool used to answer "no policy published".

If the pages change, update the matching block here too (keep the locale keys
cited in each docstring so the next editor can diff).
"""

SHIPPING_POLICY = """Shipping policy (see /shipping-policy for details):
- We ship all across India; no international shipping.
- Delivery: metro cities 3-5 business days, other cities 5-7, remote areas 7-10.
- Orders of Rs. 499 and above ship free; below Rs. 499 a Rs. 69.62 delivery charge applies (Rs. 59 + 18% GST).
- Orders are processed within 24-48 hours of payment confirmation (next business
  day after weekends/holidays). The courier makes 3 delivery attempts.
- Once shipped you get a tracking number by email/SMS, also visible on My Orders.
- Give a complete, correct address: we are not liable for wrong-address delays
  and no refund is issued for them. Address changes only within 1 hour of
  ordering (WhatsApp +91 93000 05040).
- Shipping queries: +91 93000 05040."""

RETURN_POLICY = """Return, replacement & refund policy (see /return-policy for details):
- 7 days from delivery, ONLY for: damaged/defective, wrong product, tampered or
  broken packaging, missing items.
- An unboxing video is MANDATORY (single continuous video from the sealed
  package; shipping label visible; cut/edited videos rejected).
- Non-returnable: opened seals (unless damaged on arrival), used/consumed
  products, change of mind.
- Process: contact support within 7 days with order number, reason and video;
  verification in 24-48 hours; approved pickups from your address in original
  packaging. Replacements for damaged/defective items ship free after receipt.
- Refunds within 5-7 business days after inspection: prepaid back to the original
  method; COD has no method to credit, so our team calls you to arrange UPI or
  bank transfer.
- Cancellation: free any time before shipping (full refund); after shipping it
  cannot be cancelled for a refund (refuse delivery or use returns; the delivery
  charge is not refunded).
- Contact: +91 93000 05040 (Mon-Sat, 9 AM-6 PM IST)."""

POLICIES = {
    'shipping': ('Shipping Policy', SHIPPING_POLICY, '/shipping-policy'),
    'return': ('Return & Refund Policy', RETURN_POLICY, '/return-policy'),
}
