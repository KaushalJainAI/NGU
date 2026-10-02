# Upcoming Work

Roadmap of planned-but-not-yet-built features for NGU. Each item is a proposal —
**no code changes made yet**. Update the status line when work starts / ships.

_Last updated: 2026-07-31_

| # | Item | Status | Detailed plan |
|---|------|--------|---------------|
| 1 | SMS / WhatsApp OTP | Proposal | [`OTP_SMS_WHATSAPP_PLAN.md`](OTP_SMS_WHATSAPP_PLAN.md) |

> **Dropped 2026-07-31** — "COD unlocked by a single-use coupon". Never
> implemented; the proposal was removed on the owner's instruction. COD remains
> backend-only and unexposed in the storefront (checkout hard-codes
> `payment_method: 'ONLINE'`). `Coupon` has no `enables_cod` field and none was
> ever migrated.

---

## 1. SMS / WhatsApp OTP

**Status:** Proposal · full spec in [`OTP_SMS_WHATSAPP_PLAN.md`](OTP_SMS_WHATSAPP_PLAN.md)

Today every OTP and notification is **email-only**. This adds SMS and WhatsApp as
delivery channels for:

1. Password-reset OTP (existing flow → multi-channel).
2. Phone verification (a number must be verified before it's trusted).
3. Mobile-number OTP login (passwordless auth).
4. Order-lifecycle SMS (confirmation + status/tracking updates).

Includes layered rate limits / anti-abuse (throttle by IP **+ phone + user**, no
phone enumeration, India DLT + Meta template compliance). Longest lead time is
**provider onboarding + DLT template approval** — start that first.

See the linked plan for provider choice, schema changes, endpoints, and the
rollout order.
