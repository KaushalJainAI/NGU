# E-Commerce Compliance & Readiness Checklist — Nidhi Grah Udyog

Audit of legal, regulatory, payment, data-protection and practical requirements for an Indian
food e-commerce website, with the **current status** of this codebase.

> **Scope:** India (packaged food / spices). Not legal advice — items marked ❌/⚠️ should be
> reviewed with a professional before go-live.
>
> **Last reviewed:** 9 July 2026

**Legend:** ✅ Done · ⚠️ Partial / needs attention · ❌ Missing

---

## 1. Legal documents & policies

| # | Requirement | Status | Notes / Action |
|---|-------------|--------|----------------|
| 1.1 | **Terms & Conditions** | ✅ | Added at `/terms` ([TermsAndConditions.tsx](Frontend/nidhi-brand-forge/src/pages/TermsAndConditions.tsx)); linked in footer. Governing law = Ujjain, MP. |
| 1.2 | **Privacy Policy** | ✅ | Static page at `/privacy-policy` (DPDP-aligned, consistent with the other policy pages). Backend `Policy` model/endpoint retired (kept but inactive). |
| 1.3 | **Shipping Policy** | ✅ | Charge unified to **₹69 up to ₹500, free above ₹500** across backend, checkout, policy page and marketing copy. |
| 1.4 | **Return / Refund / Cancellation Policy** | ✅ | Exists at `/return-policy`; covers eligibility, non-returnable food items, refund timeline, cancellation. |
| 1.5 | **FAQ** | ✅ | Added at `/faq`; footer link fixed (was a dead `#`). |
| 1.6 | **Grievance Officer details** | ✅ | Added on the Contact page — **Ankur Jain**, +91 93000 05040, with 48-hr acknowledgement / 30-day resolution timelines. |
| 1.8 | **Certificates downloadable on site** | ✅ | GST Registration Certificate and FSSAI License are downloadable from the footer (GSTIN / FSSAI numbers link to the PDFs). |
| 1.7 | **"Last updated" date on every policy** | ⚠️ | Present on new pages (Terms/Privacy). Missing on Shipping/Return. |

---

## 2. Regulatory disclosures (India food e-commerce)

| # | Requirement | Status | Notes / Action |
|---|-------------|--------|----------------|
| 2.1 | **FSSAI license number displayed** | ✅ | FSSAI Lic `11414730000288` shown in the footer (links to the license PDF) and on invoices. License confirmed renewed. |
| 2.2 | **GSTIN displayed on site** | ✅ | GSTIN `23ABUPJ8925C1ZI` now in the footer and on invoices. |
| 2.3 | **GST tax invoice** | ✅ | [invoice.py](Backend/orders/invoice.py) now uses real seller details: Nidhi Grah Udyog, Ujjain address, real GSTIN + FSSAI. |
| 2.4 | **Legal seller name & entity type** | ✅ | Footer shows "Nidhi Grah Udyog (Proprietor: Lalit Kumar Jain)". |
| 2.5 | **Country of origin on listings** | ⚠️ | `Product.origin_country` field exists (translated). Confirm it renders on product pages. |
| 2.6 | **Legal Metrology disclosures** | ⚠️ | Pre-packaged goods need net quantity, MRP (incl. taxes), mfg/packer details, month/year, best-before, consumer-care. Confirm these are on listings/packaging. |
| 2.7 | **Total price with all taxes before purchase** | ✅ | Checkout shows subtotal, GST, shipping, total before payment. |

---

## 3. Payments & transactions

| # | Requirement | Status | Notes / Action |
|---|-------------|--------|----------------|
| 3.1 | **Real payment gateway** | ❌ | Checkout uses a manual UPI QR + an **"I have completed the payment" self-declaration checkbox** ([Billing.tsx](Frontend/nidhi-brand-forge/src/pages/Billing.tsx)), then redirects to `/interest-success`. Razorpay is in the stack but **not wired into checkout**. |
| 3.2 | **Automatic payment verification / reconciliation** | ❌ | No transaction ID captured, no gateway callback. Orders are trust-based → fake "paid" orders possible. |
| 3.3 | **Refund mechanism** | ⚠️ | Manual only; policy states 5–7 days. No automated refund path (depends on 3.1). |
| 3.4 | **HTTPS / TLS** | ✅ | Live over `https://nidhimasala.com`. |
| 3.5 | **PCI-DSS** | ✅ (N/A) | No card data captured (UPI only). Becomes relevant if cards are added — use a compliant gateway, never store PAN. |
| 3.6 | **Payment methods disclosed in Terms** | ⚠️ | Terms references "methods at checkout"; update once a real gateway/COD is added. |

---

## 4. Data protection & security (DPDP Act 2023, IT Rules)

| # | Requirement | Status | Notes / Action |
|---|-------------|--------|----------------|
| 4.1 | **Privacy consent at signup** | ✅ | Register has a required Privacy Policy consent checkbox ([Register.tsx](Frontend/nidhi-brand-forge/src/pages/Register.tsx)). |
| 4.2 | **Cookie / tracking consent banner** | ✅ | `CookieConsent` banner added (Accept all / Essential only), linked to Privacy Policy. Behavioral analytics (`trackEvent`/`trackAnon`) now **gated on explicit consent**. |
| 4.3 | **Data access / correction / deletion rights** | ⚠️ | Stated in Privacy Policy; profile edit exists, but no self-serve data-deletion/export request flow. |
| 4.4 | **Password security** | ✅ | Min 8 chars + upper/lower/digit enforced; JWT httpOnly cookie auth. |
| 4.5 | **Children's data** | ✅ | Privacy Policy states under-18 not targeted. |
| 4.6 | **Marketing opt-in/opt-out** | ⚠️ | Confirm promotional email/SMS has explicit opt-in and unsubscribe. |

---

## 5. Practical / correctness issues found in code

| # | Issue | Status | Notes / Action |
|---|-------|--------|----------------|
| 5.1 | **Shipping charge mismatch** | ✅ | Unified to **₹69 up to ₹500 / free above ₹500** everywhere (backend authoritative in `orders/views.py`); the old ₹299 free-shipping marketing copy corrected to ₹500. |
| 5.2 | **Broken support email** | ✅ | Now `nidhispicesandfood@gmail.com` everywhere (Contact page, footer, error page, all six locales, invoice, stored privacy policy). ⚠️ The **FSSAI license lists `nidhigrahudyog@rediffmail.com`** — the licensed record and the published support address now differ; update the FSSAI/GST records or keep the old mailbox monitored. |
| 5.3 | **Footer "email" is a website URL** | ✅ | Footer now shows the real email as a `mailto:` link. |
| 5.4 | **Dead social links** | ✅ | Footer now links to `facebook.nidhimasala.com` and `instagram.nidhimasala.com` (new tab). |
| 5.5 | **Stale copyright year** | ✅ | Footer now auto-updates to the current year. |
| 5.6 | **Invoice seller details fake** | ✅ | Fixed — see 2.3. |
| 5.7 | **Mobile bill download** | ✅ | Fixed — "Bill" button now visible on mobile in [MyOrders.tsx](Frontend/nidhi-brand-forge/src/pages/MyOrders.tsx). |
| 5.8 | **FAQ dead link** | ✅ | Fixed — footer now points to `/faq`. |

---

## 6. Standard e-commerce feature completeness

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 6.1 | Product catalog, categories, combos | ✅ | |
| 6.2 | Search (AI/synonym) | ✅ | |
| 6.3 | Cart & favorites/wishlist | ✅ | |
| 6.4 | Order placement & history | ✅ | |
| 6.5 | Order tracking | ✅ | `/track-order` + status in My Orders |
| 6.6 | Verified-purchase reviews | ✅ | |
| 6.7 | Reorder | ✅ | |
| 6.8 | Multilingual (6 languages) | ✅ | i18next UI + backend catalog translation |
| 6.9 | Invoice/bill download | ✅ | PDF on demand (fix seller details, 2.3) |
| 6.10 | Guest checkout | ⚠️ | Checkout appears to require login/profile. Consider guest checkout. |
| 6.11 | Cash on Delivery (COD) | ✅ (by choice) | COD not offered for now; all COD marketing removed from ribbon/trust chips to match. |

---

## Priority actions

**Before taking real money / go-live:**
1. Wire a **real payment gateway** (Razorpay/UPI) with verified transaction IDs and reconciliation (3.1–3.3). — **the main remaining blocker.**

**Still open (lower effort):**
2. Self-serve **data deletion/export** request path (4.3); confirm marketing opt-in/unsubscribe (4.6).
3. Verify **country of origin** and **Legal Metrology** fields render on product listings (2.5–2.6).
4. Consider **guest checkout** (6.10).

> **Deploy note:** run `python manage.py migrate` so migration `0008_create_save10_coupon`
> creates the **SAVE10** coupon (10% off, min order ₹1500).

---

## Already completed in this pass

- ✅ Terms & Conditions page (`/terms`) + footer link
- ✅ FAQ page (`/faq`) + fixed dead footer link
- ✅ Privacy Policy full static fallback (never empty)
- ✅ Bill/invoice download now works on mobile
- ✅ **GSTIN + FSSAI** displayed in footer and on invoices; real legal entity name shown
- ✅ **Invoice** now uses real seller details (name, address, GSTIN, FSSAI)
- ✅ **Grievance Officer** (Ankur Jain, +91 93000 05040) added on Contact page with resolution timelines
- ✅ **Support email** is `nidhispicesandfood@gmail.com`; footer email is a live `mailto:` link (see 5.2 — differs from the FSSAI-listed address)
- ✅ Footer copyright year auto-updates
- ✅ **GST + FSSAI certificates** downloadable from the footer (`/gst-registration-certificate.pdf`, `/fssai-license.pdf`)
- ✅ **Invoice redesigned** — colored header band, place-of-supply, amount-in-words, highlighted grand total, signature block; verified rendering with real data only
- ✅ **Shipping unified** to ₹69 up to ₹500 / free above ₹500 (backend, checkout, policy, marketing)
- ✅ **Social links** wired (facebook/instagram.nidhimasala.com)
- ✅ **COD removed** from all marketing (not offered for now)
- ✅ **DPDP:** cookie-consent banner + analytics gated on consent
- ✅ **All policy pages are static frontend** (Privacy, Shipping, Return, Terms, FAQ) — consistent; backend `Policy` model/endpoint/admin retired but kept inactive
- ✅ **SAVE10** coupon (10% off ≥ ₹1500) via migration `0008`
