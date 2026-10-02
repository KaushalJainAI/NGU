"""
PDF invoice / bill generation for orders.

Three documents, sourcing their data in two very different ways:

* `generate_invoice_pdf(invoice)` takes an ISSUED `Invoice` and renders it from
  the frozen `Invoice.snapshot` — never live settings, never the live order. A
  bill handed to a customer must reprint identically years later, after the
  seller has moved office and an admin has corrected a delivery address. When
  an invoice is raised, and how it is numbered, is `orders/invoicing.py`.
* `generate_credit_note_pdf(refund)` renders the GST credit note for one row of
  the `OrderRefund` ledger, citing the original invoice's serial and date.
* `generate_packing_slip_pdf(order)` renders a warehouse picking sheet from the
  LIVE order and current seller details — correct here, because it describes a
  parcel going out today rather than a financial record.

reportlab is imported lazily so the rest of the orders app keeps working even if
the dependency is missing in some environment; the view surfaces a clear error.
"""
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from django.conf import settings
from django.utils import timezone

from spices_backend.limits import SHIPPING_TAX_RATE

from .place_of_supply import head_rate_label, is_interstate, split_gst, state_name
from .pricing import order_tax_breakdown

PAISA = Decimal("0.01")

# ---- Seller details (issuer of the invoice) ----
# Defaults live in settings.py and can be overridden per deployment.
SELLER_NAME = settings.SELLER_NAME
SELLER_PROPRIETOR = settings.SELLER_PROPRIETOR
SELLER_TAGLINE = settings.SELLER_TAGLINE
SELLER_ADDRESS = settings.SELLER_ADDRESS
SELLER_GSTIN = settings.SELLER_GSTIN
SELLER_FSSAI = settings.SELLER_FSSAI
SELLER_STATE = settings.SELLER_STATE
SELLER_STATE_CODE = settings.SELLER_STATE_CODE
SELLER_EMAIL = settings.SELLER_EMAIL
SELLER_PHONE = settings.SELLER_PHONE


def _money(value):
    """Format a Decimal/number as an INR amount string."""
    return f"Rs. {Decimal(str(value or 0)):,.2f}"


def _issued_on(invoice):
    """The invoice's date of issue, in the store's local time.

    Rendered from `issued_at` rather than the order's creation date: they are
    different instants (a COD order is invoiced at dispatch, days later) and the
    tax point is this one.
    """
    return timezone.localtime(invoice.issued_at).strftime("%d %b %Y, %I:%M %p")


def _place_of_supply_line(order):
    """The "Place of Supply" particular, and what it means for the tax heads.

    Rule 46 requires the place of supply on every tax invoice, and for an
    inter-state supply it is what justifies charging IGST instead of CGST+SGST.
    Spelling out which one applies means the reader never has to compare the
    code against the seller's GSTIN to know why the columns below look as they
    do.
    """
    code = order.place_of_supply_state_code or SELLER_STATE_CODE
    heads = ("inter-state supply — IGST" if is_interstate(order.place_of_supply_state_code)
             else "intra-state supply — CGST + SGST")
    return f"Place of Supply: {state_name(code) or SELLER_STATE} ({code}) &bull; {heads}"


def _snapshot_place_of_supply_line(pos):
    """The "Place of Supply" particular, from a frozen invoice snapshot.

    The live-order twin of this is `_place_of_supply_line`, still used by the
    credit note. This variant reads the RESOLVED intra/inter-state answer that
    was stored at issue rather than recomputing it, because `is_interstate`
    compares against the seller's current state — a seller who later registers
    elsewhere would otherwise flip the tax heads on every reprinted bill.
    """
    code = pos.get("code") or ""
    name = pos.get("name") or ""
    heads = ("inter-state supply — IGST" if pos.get("interstate")
             else "intra-state supply — CGST + SGST")
    return f"Place of Supply: {name} ({code}) &bull; {heads}"


def _snapshot_gst_summary_rows(gst_summary, interstate):
    """Per-slab GST summary table from a frozen snapshot.

    Same layout as `_gst_summary_rows` — which still serves the credit note off
    live data — but every figure is read, not recomputed. The head amounts were
    split once at issue and the totals row sums the printed rows, so the column
    always adds up to what the rows above it show.
    """
    if interstate:
        data = [["GST Rate", "Taxable Value", "IGST"]]
        widths = [24, 32, 26]
    else:
        data = [["GST Rate", "Taxable Value", "CGST", "SGST"]]
        widths = [26, 30, 22, 22]

    running = {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("0.00")}
    for row in gst_summary:
        for head in running:
            running[head] += Decimal(str(row.get(head) or 0))
        cells = [
            row.get("rate_label") or "—",
            "—" if row.get("taxable_value") is None else _money(row["taxable_value"]),
        ]
        cells += ([_money(row.get("igst"))] if interstate
                  else [_money(row.get("cgst")), _money(row.get("sgst"))])
        data.append(cells)

    total_cells = ["Total", ""]
    total_cells += ([_money(running["igst"])] if interstate
                    else [_money(running["cgst"]), _money(running["sgst"])])
    data.append(total_cells)
    return data, widths


def _gst_summary_rows(gst_rows, place_of_supply_code):
    """Per-slab GST summary split into tax heads.

    Returns ``(table_data, col_widths_mm)``. One row per rate slab, then a
    totals row; the head columns are CGST + SGST for an intra-state supply and
    a single IGST column for an inter-state one — the same money either way.

    The heads are computed PER SLAB and the totals row is the SUM of the rows
    above it — not a fresh split of `total_tax`. Halving each slab can leave an
    odd paisa (`split_gst` hands it to SGST), and splitting the total
    independently would round differently, printing a column that visibly fails
    to add up. Summing keeps CGST + SGST equal to `total_tax` regardless,
    because every slab's two heads sum to that slab's tax and the slabs sum to
    the total.
    """
    interstate = is_interstate(place_of_supply_code)
    if interstate:
        data = [["GST Rate", "Taxable Value", "IGST"]]
        widths = [24, 32, 26]
    else:
        data = [["GST Rate", "Taxable Value", "CGST", "SGST"]]
        widths = [26, 30, 22, 22]

    running = {"cgst": Decimal("0.00"), "sgst": Decimal("0.00"), "igst": Decimal("0.00")}
    for row in gst_rows:
        heads = split_gst(row["tax_amount"], place_of_supply_code)
        for head, value in heads.items():
            running[head] += value
        cells = [
            "—" if row["rate"] is None else head_rate_label(row["rate"], place_of_supply_code),
            "—" if row["taxable_value"] is None else _money(row["taxable_value"]),
        ]
        cells += ([_money(heads["igst"])] if interstate
                  else [_money(heads["cgst"]), _money(heads["sgst"])])
        data.append(cells)

    total_cells = ["Total", ""]
    total_cells += ([_money(running["igst"])] if interstate
                    else [_money(running["cgst"]), _money(running["sgst"])])
    data.append(total_cells)
    return data, widths


def _line_hsn(item):
    """HSN cell for one invoice line.

    A product line prints its own snapshotted code. A COMBO line has none —
    the bundle is a mixed supply whose components can sit in different headings
    — so it prints the distinct component codes instead, which is both truthful
    and what the HSN summary for that line will report.

    '-' when nothing is known: lines billed before this field existed, and
    products the admin has not classified yet. A dash is deliberate; inventing a
    code on a tax invoice is the one thing this must never do.
    """
    own = (getattr(item, "hsn_code", "") or "").strip()
    if own:
        return own
    codes = []
    for component in item.components.all():
        code = (component.hsn_code or "").strip()
        if code and code not in codes:
            codes.append(code)
    return "<br/>".join(codes) if codes else "-"


def _order_number(order):
    return f"ORD-{order.id:06d}"


def credit_note_number(refund):
    """The serial printed on `refund`'s credit note.

    The linked `orders.CreditNote` row's number (`CN/<FY>/<seq>`) when one has
    been issued, otherwise the legacy `CN-<pk>` fallback. The fallback covers
    refunds recorded before credit notes existed as rows (and any refund whose
    order never got an invoice, which can never have a note).
    """
    try:
        note = getattr(refund, 'credit_note', None)
        if note is None:
            from .models import CreditNote
            note = CreditNote.objects.filter(refund=refund).first()
        if note is not None:
            return note.number
    except Exception:  # noqa: BLE001 — numbering must never break rendering
        pass
    return f"CN-{refund.id:06d}"


def _credited_invoice_ref(order):
    """"<invoice no> dated <date>" for the invoice a credit note reverses.

    A credit note must identify the original invoice by its serial and date
    (Rule 53(1A)); that reference is what ties the reversal to the supply. Reads
    the issued `Invoice` — its real number and its date of ISSUE, not the order's
    creation date, which for a COD order is days earlier.

    Falls back to the order reference for a pre-invoicing order, which cannot
    cite a serial that was never issued. Such a refund still reverses the tax
    correctly; the note simply names the order instead, which is the most that
    is true about it.
    """
    invoice = getattr(order, 'invoice', None)
    if invoice is None:
        return f"{_order_number(order)} dated {order.created_at.strftime('%d %b %Y')}"
    return (f"{invoice.number} dated "
            f"{timezone.localtime(invoice.issued_at).strftime('%d %b %Y')}")


def credited_invoice_label(order):
    """The invoice serial a credit note cites, alone (no date)."""
    invoice = getattr(order, 'invoice', None)
    return invoice.number if invoice is not None else _order_number(order)


def credit_note_tax_rows(refund):
    """Per-slab GST reversed by `refund`, apportioned from the order's breakup.

    A refund is an amount, not a set of lines, so the slabs it reverses have to
    be inferred. Each row of the order's own breakup is scaled by the share of
    the order's GST this refund reverses (`refund.tax_amount / order GST`), which
    makes a FULL refund reproduce the invoice's summary exactly and a partial an
    apportionment at the order's blended rate — the same approximation
    `pricing.refund_tax_for` already made when it computed `tax_amount`, not a
    second, different one layered on top.

    The rounding residual is handed to the largest row so the printed slabs
    always sum to `refund.tax_amount`. A credit note whose rate-wise rows
    disagree with its own total is not evidence of anything.
    """
    rows = order_tax_breakdown(refund.order)
    reversed_tax = Decimal(str(refund.tax_amount or 0))
    charged = sum((Decimal(str(r["tax_amount"])) for r in rows), Decimal("0.00"))
    if not rows or charged <= 0 or reversed_tax <= 0:
        return []

    share = reversed_tax / charged
    out = []
    for row in rows:
        taxable = row["taxable_value"]
        out.append({
            "rate": row["rate"],
            "taxable_value": (
                None if taxable is None
                else float((Decimal(str(taxable)) * share).quantize(
                    PAISA, rounding=ROUND_HALF_UP))
            ),
            "tax_amount": float((Decimal(str(row["tax_amount"])) * share).quantize(
                PAISA, rounding=ROUND_HALF_UP)),
        })

    residual = reversed_tax - sum(
        (Decimal(str(r["tax_amount"])) for r in out), Decimal("0.00"))
    if residual:
        biggest = max(range(len(out)), key=lambda i: out[i]["tax_amount"])
        out[biggest]["tax_amount"] = float(
            (Decimal(str(out[biggest]["tax_amount"])) + residual).quantize(PAISA))
    return out


def _customer_name(user):
    if not user:
        return "Guest"
    name = (getattr(user, "name", "") or "").strip()
    if name:
        return name
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


# ---- Amount in words (Indian numbering) ----
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety"]


def _two(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three(n):
    h, r = n // 100, n % 100
    parts = []
    if h:
        parts.append(_ONES[h] + " Hundred")
    if r:
        parts.append(_two(r))
    return " ".join(parts)


def _num_words(n):
    if n == 0:
        return "Zero"
    parts = []
    crore, n = n // 10000000, n % 10000000
    lakh, n = n // 100000, n % 100000
    thousand, n = n // 1000, n % 1000
    if crore:
        parts.append(_num_words(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts)


def _amount_in_words(value):
    d = Decimal(str(value or 0))
    rupees = int(d)
    paise = int(round((d - rupees) * 100))
    words = "Rupees " + _num_words(rupees)
    if paise:
        words += " and " + _two(paise) + " Paise"
    return words + " Only"


def generate_invoice_pdf(invoice) -> bytes:
    """Render an ISSUED tax invoice PDF from its frozen snapshot.

    Takes an `Invoice`, not an Order, and reads its financial content ONLY from
    `invoice.snapshot` — never from live settings and never from the live order.
    That is what makes a reprint faithful: the seller can move office, an admin
    can correct a delivery address, the catalogue can be re-rated, and a bill
    already handed to a customer still prints exactly as issued.

    Two bands ARE live, and are labelled as such on the page: the order's
    current status and any refunds recorded since. Those are disclosures about
    what happened AFTER issue, dated at printing — they annotate the document,
    they do not restate it. The amounts below them stay as originally charged,
    because an invoice is never rewritten; a refund is evidenced by its own
    credit note (`generate_credit_note_pdf`).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    )

    BRAND = colors.HexColor("#B91C1C")
    BRAND_DK = colors.HexColor("#7F1212")
    DARK = colors.HexColor("#1F2937")
    MUTED = colors.HexColor("#6B7280")
    LIGHT = colors.HexColor("#F7F3F2")
    LINE = colors.HexColor("#E5E7EB")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BrandW", fontName="Helvetica-Bold", fontSize=22,
                              textColor=colors.white, leading=25))
    styles.add(ParagraphStyle("TagW", fontName="Helvetica", fontSize=8,
                              textColor=colors.HexColor("#FBD5D5"), leading=11))
    styles.add(ParagraphStyle("InvTitleW", fontName="Helvetica-Bold", fontSize=17,
                              textColor=colors.white, alignment=2, leading=19))
    styles.add(ParagraphStyle("InvSubW", fontName="Helvetica", fontSize=8,
                              textColor=colors.HexColor("#FBD5D5"), alignment=2, leading=11))
    styles.add(ParagraphStyle("MetaLabel", fontName="Helvetica", fontSize=7,
                              textColor=MUTED, leading=9))
    styles.add(ParagraphStyle("MetaValue", fontName="Helvetica-Bold", fontSize=9,
                              textColor=DARK, leading=12))
    styles.add(ParagraphStyle("H", fontName="Helvetica-Bold", fontSize=9.5,
                              textColor=DARK, leading=13))
    styles.add(ParagraphStyle("N", fontName="Helvetica", fontSize=9,
                              textColor=DARK, leading=13))
    styles.add(ParagraphStyle("Nm", fontName="Helvetica", fontSize=8,
                              textColor=MUTED, leading=12))
    styles.add(ParagraphStyle("SectionLabel", fontName="Helvetica-Bold", fontSize=7.5,
                              textColor=BRAND, leading=10))
    styles.add(ParagraphStyle("Words", fontName="Helvetica-Oblique", fontSize=8.5,
                              textColor=DARK, leading=12))

    # EVERY figure and party detail below comes from here. The live `order` is
    # used only for the two "since issue" bands, which say so on the page.
    snap = invoice.snapshot or {}
    seller = snap.get("seller", {})
    buyer_d = snap.get("buyer", {})
    order_d = snap.get("order", {})
    totals = snap.get("totals", {})
    pos = snap.get("place_of_supply", {})
    order = invoice.order

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Invoice {invoice.number}")
    el = []

    # ---- Header band: brand (left) + TAX INVOICE (right) on a colored bar ----
    header = Table([[
        [Paragraph(seller.get("name", ""), styles["BrandW"]),
         Paragraph(seller.get("tagline", ""), styles["TagW"])],
        [Paragraph("TAX INVOICE", styles["InvTitleW"]),
         Paragraph("Original for Recipient", styles["InvSubW"])],
    ]], colWidths=[108 * mm, 70 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    el.append(header)

    # ---- Meta strip: invoice no / date / order ref / payment ----
    # The invoice number and its DATE OF ISSUE are the document's identity, and
    # both are frozen. The order reference is a separate particular: it is our
    # internal handle on the supply, not the serial of this document, and it is
    # exactly the conflation that made `ORD-{id}` an unlawful invoice series.
    pay_status = (order_d.get("payment_status") or "pending").upper()
    pay_method = order_d.get("payment_method_label") or "-"

    def meta_cell(label, value):
        return [Paragraph(label, styles["MetaLabel"]), Paragraph(value, styles["MetaValue"])]

    meta = Table([[
        meta_cell("INVOICE NO.", invoice.number),
        meta_cell("DATE OF ISSUE", _issued_on(invoice)),
        meta_cell("ORDER REF.", order_d.get("number", "")),
        meta_cell("PAYMENT", f"{pay_method} — {pay_status}"),
    ]], colWidths=[47 * mm, 46 * mm, 40 * mm, 45 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEAFTER", (0, 0), (2, -1), 0.5, LINE),
    ]))
    el.append(meta)

    # ---- Order status band (LIVE — a disclosure, not part of the invoice) ----
    # Where the order stands when this copy is printed, so a reprint of a
    # cancelled order can never be mistaken for a live fulfilled purchase. Dated
    # at printing and worded to make clear it annotates the bill rather than
    # restating it — the figures below are what was charged at issue, always.
    try:
        status_label = order.get_status_display()
    except Exception:
        status_label = (order.status or "Pending").replace("_", " ").title()
    is_cancelled = (order.status or "").lower() == "cancelled"
    status_bg = colors.HexColor("#B91C1C") if is_cancelled else colors.HexColor("#047857")
    status_note = (
        "This order was cancelled after this invoice was issued. "
        "Retained for your records."
        if is_cancelled else
        f"Order status as at {timezone.localtime().strftime('%d %b %Y')}"
    )
    status_tbl = Table([[
        Paragraph(
            f'<font color="white"><b>ORDER STATUS:&nbsp;&nbsp;{status_label.upper()}</b></font>',
            styles["N"]),
        Paragraph(f'<font color="white">{status_note}</font>', styles["Nm"]),
    ]], colWidths=[70 * mm, 108 * mm])
    status_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), status_bg),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(Spacer(1, 4))
    el.append(status_tbl)

    # ---- Credit note band ----
    # A refunded order must not print a clean full-value bill: the amounts below
    # are what was ORIGINALLY charged and stay that way (an invoice is never
    # rewritten), so the reversal is disclosed here and carries the serial of the
    # credit note that evidences it. Chronological, and listing every instalment,
    # because each one is its own document.
    refunds = list(order.refunds.all())[::-1] if order.pk else []
    if refunds:
        returned = sum((Decimal(str(r.amount or 0)) for r in refunds), Decimal("0.00"))
        refs = "; ".join(
            f"{credit_note_number(r)} dated {r.created_at.strftime('%d %b %Y')} "
            f"({_money(r.amount)})"
            for r in refunds
        )
        cn_tbl = Table([[
            Paragraph(
                f'<font color="white"><b>REFUNDED:&nbsp;&nbsp;{_money(returned)}'
                f'</b></font>', styles["N"]),
            Paragraph(f'<font color="white">Credit Note {refs}</font>', styles["Nm"]),
        ]], colWidths=[46 * mm, 132 * mm])
        cn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#B45309")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        el.append(Spacer(1, 3))
        el.append(cn_tbl)
    el.append(Spacer(1, 12))

    # ---- Seller / buyer cards ----
    # Both parties as they were AT ISSUE. This is the "reprints mutate" fix in
    # its most visible form: changing SELLER_ADDRESS in the environment, or an
    # admin correcting the delivery address on the order, cannot alter a bill the
    # customer already holds.
    seller_block = [
        Paragraph("FROM", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(seller.get("name", ""), styles["H"]),
        Paragraph(f"Proprietor: {seller.get('proprietor', '')}", styles["Nm"]),
        Paragraph(seller.get("address", ""), styles["Nm"]),
        Paragraph(f"GSTIN: {seller.get('gstin', '')}", styles["Nm"]),
        Paragraph(f"FSSAI Lic. No: {seller.get('fssai', '')}", styles["Nm"]),
        Paragraph(f"{seller.get('email', '')} &bull; {seller.get('phone', '')}",
                  styles["Nm"]),
    ]
    ship_addr = (buyer_d.get("address") or "").replace("\n", "<br/>")
    buyer = [
        Paragraph("BILL TO / SHIP TO", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(buyer_d.get("name") or "Guest", styles["H"]),
        Paragraph(ship_addr or "-", styles["Nm"]),
        Paragraph(f"Phone: {buyer_d.get('phone') or '-'}", styles["Nm"]),
    ]
    if buyer_d.get("email"):
        buyer.append(Paragraph(buyer_d["email"], styles["Nm"]))

    party = Table([[seller_block, buyer]], colWidths=[89 * mm, 89 * mm])
    party.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (0, 0), 0.6, LINE),
        ("BOX", (1, 0), (1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    el.append(party)
    el.append(Paragraph(_snapshot_place_of_supply_line(pos), styles["Nm"]))
    el.append(Spacer(1, 12))

    # ---- Line items ----
    # HSN is a required particular on a tax invoice (Rule 46(g)), so it gets its
    # own column rather than being buried in the item name. Combo lines have no
    # single code — a bundle is a mixed supply — so they print the codes of their
    # components instead of a blank or, worse, a plausible wrong one.
    rows = [["#", "Item", "HSN", "Pack", "Qty", "Rate", "Amount"]]
    for i, item in enumerate(snap.get("items", []), 1):
        rows.append([
            str(i),
            Paragraph(item.get("name", ""), styles["N"]),
            Paragraph(item.get("hsn") or "-", styles["Nm"]),
            item.get("pack") or "-",
            str(item.get("quantity", "")),
            _money(item.get("rate")),
            _money(item.get("amount")),
        ])

    tbl = Table(rows,
                colWidths=[7 * mm, 63 * mm, 21 * mm, 21 * mm, 13 * mm, 26 * mm, 27 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        # Cols: 0 #, 1 Item, 2 HSN, 3 Pack, 4 Qty, 5 Rate, 6 Amount.
        ("ALIGN", (2, 0), (4, -1), "CENTER"),
        ("ALIGN", (5, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        # Tighter side padding than the 7pt elsewhere: the HSN column costs the
        # item name 19mm, and the name is the column a customer actually reads.
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 10))

    # ---- Amount in words (left) + totals (right) ----
    discount = Decimal(str(totals.get("discount_amount") or 0))
    tot_rows = [["Subtotal", _money(totals.get("subtotal"))]]
    if discount > 0:
        label = "Discount"
        if totals.get("coupon_code"):
            label = f"Discount ({totals['coupon_code']})"
        tot_rows.append([label, "- " + _money(discount)])
    # GST placement depends on the pricing convention the order was placed under.
    # Inclusive (all current orders): the tax is already inside Subtotal, so it is
    # shown as a non-summing disclosure line BELOW the grand total. Legacy orders
    # (tax_inclusive=False) had GST added on top, so it stays an addend here —
    # otherwise a reprinted historical bill would no longer reconcile.
    tax_inclusive = bool(order_d.get("tax_inclusive", True))
    if not tax_inclusive:
        tot_rows.append(["GST", _money(totals.get("tax"))])
    shipping_charge = Decimal(str(totals.get("shipping_charge") or 0))
    tot_rows.append([
        "Shipping",
        "FREE" if shipping_charge == 0 else _money(shipping_charge),
    ])
    # Delivery is billed NET + GST, unlike goods — so its tax is a real addend
    # and gets its own line above the grand total. Suppressed on free-shipping
    # orders and on historical orders placed before delivery was taxed, where a
    # "GST on Shipping Rs. 0.00" row would just be noise.
    shipping_tax = Decimal(str(totals.get("shipping_tax") or 0))
    if shipping_tax > 0:
        # The rate is snapshotted too: SHIPPING_TAX_RATE is an env-configurable
        # setting, and printing today's rate on last year's bill would misstate
        # the tax that was actually charged on that delivery.
        ship_rate = Decimal(str(totals.get("shipping_tax_rate") or SHIPPING_TAX_RATE))
        tot_rows.append([
            f"GST on Shipping ({ship_rate:g}%)", _money(shipping_tax)])
    tot_rows.append(["Grand Total", _money(totals.get("total_amount"))])
    grand = len(tot_rows) - 1
    if tax_inclusive:
        # Below the band, and worded so it can never be read as an extra charge.
        # Only the GOODS tax is "included" — the delivery GST was added above, so
        # folding it in here would tell the customer it was already in the price.
        tot_rows.append(["(incl. GST on goods", _money(totals.get("tax")) + ")"])

    tot_style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Grand total row — highlighted band
        ("BACKGROUND", (0, grand), (-1, grand), BRAND),
        ("TEXTCOLOR", (0, grand), (-1, grand), colors.white),
        ("FONTNAME", (0, grand), (-1, grand), "Helvetica-Bold"),
        ("FONTSIZE", (0, grand), (-1, grand), 11.5),
        ("TOPPADDING", (0, grand), (-1, grand), 7),
        ("BOTTOMPADDING", (0, grand), (-1, grand), 7),
        ("LEFTPADDING", (0, grand), (0, grand), 8),
        ("RIGHTPADDING", (-1, grand), (-1, grand), 8),
    ]
    if tax_inclusive:
        tot_style += [
            ("FONTSIZE", (0, grand + 1), (-1, grand + 1), 8),
            ("TEXTCOLOR", (0, grand + 1), (-1, grand + 1), MUTED),
        ]

    tot = Table(tot_rows, colWidths=[40 * mm, 34 * mm])
    tot.setStyle(TableStyle(tot_style))

    words_block = [
        Paragraph("AMOUNT IN WORDS", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(totals.get("amount_in_words", ""), styles["Words"]),
    ]

    # ---- GST summary (per rate slab) ----
    # A standard tax-invoice requirement: for each rate charged, the taxable
    # (net) value and the GST on it. An order mixing 0% papad with 5% spices must
    # show both lines, otherwise the single "GST" figure is unauditable.
    # The rows also carry the CGST/SGST vs IGST split, driven by the order's
    # place of supply. The totals row covers ALL output GST on the bill — goods
    # plus delivery — because the delivery slab is one of the rows above it.
    gst_rows = snap.get("gst_summary", [])
    if gst_rows:
        slab_data, slab_widths = _snapshot_gst_summary_rows(
            gst_rows, bool(pos.get("interstate")))
        slab = Table(slab_data, colWidths=[w * mm for w in slab_widths])
        last = len(slab_data) - 1
        slab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        words_block += [
            Spacer(1, 10),
            Paragraph("GST SUMMARY", styles["SectionLabel"]),
            Spacer(1, 3),
            slab,
        ]
        if tax_inclusive:
            ship_rate = Decimal(str(totals.get("shipping_tax_rate") or SHIPPING_TAX_RATE))
            words_block += [
                Spacer(1, 3),
                Paragraph(
                    "Product prices are inclusive of GST. Delivery is charged "
                    f"net plus {ship_rate:g}% GST.", styles["Nm"]),
            ]
    # 104mm for the left column: the intra-state GST summary carries four
    # columns (rate, taxable value, CGST, SGST) and needs 100mm of them. The
    # totals block on the right only ever uses 74mm, so the width comes out of
    # its slack rather than off the page.
    summary = Table([[words_block, tot]], colWidths=[104 * mm, 74 * mm])
    summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 0), (0, 0), 4),
    ]))
    el.append(summary)
    el.append(Spacer(1, 18))

    # ---- Signature ----
    sign = Table([[
        "",
        [Paragraph(f"For {seller.get('name', '')}", styles["H"]),
         Spacer(1, 22),
         Paragraph("Authorised Signatory", styles["Nm"])],
    ]], colWidths=[108 * mm, 70 * mm])
    sign.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    el.append(sign)
    el.append(Spacer(1, 12))

    # ---- Footer note ----
    el.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        f"Thank you for shopping with {seller.get('name', '')}! For any query "
        f"about this invoice, contact {seller.get('email', '')} or "
        f"{seller.get('phone', '')}.",
        styles["Nm"]))
    el.append(Spacer(1, 3))
    el.append(Paragraph(
        "This is a computer-generated invoice and does not require a signature or stamp.",
        styles["Nm"]))

    doc.build(el)
    return buf.getvalue()


def generate_credit_note_pdf(refund) -> bytes:
    """Render the GST credit note for one `OrderRefund` and return its bytes.

    The document that evidences a refund's tax reversal. The ledger row already
    computes the reversal correctly; this gives it the paperwork Rule 53(1A)
    asks for — a serial from a series of its own, an issue date, a reference to
    the original invoice and its date, and the taxable value and tax credited.

    Deliberately NOT itemised. A refund records an amount, not which lines came
    back, so listing the order's items here would assert a fact nobody entered.
    The single line names the invoice being credited; the rate-wise reversal is
    in the GST summary, apportioned by `credit_note_tax_rows`.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    )

    BRAND = colors.HexColor("#B91C1C")
    DARK = colors.HexColor("#1F2937")
    MUTED = colors.HexColor("#6B7280")
    LIGHT = colors.HexColor("#F7F3F2")
    LINE = colors.HexColor("#E5E7EB")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BrandW", fontName="Helvetica-Bold", fontSize=22,
                              textColor=colors.white, leading=25))
    styles.add(ParagraphStyle("TagW", fontName="Helvetica", fontSize=8,
                              textColor=colors.HexColor("#FBD5D5"), leading=11))
    styles.add(ParagraphStyle("InvTitleW", fontName="Helvetica-Bold", fontSize=17,
                              textColor=colors.white, alignment=2, leading=19))
    styles.add(ParagraphStyle("InvSubW", fontName="Helvetica", fontSize=8,
                              textColor=colors.HexColor("#FBD5D5"), alignment=2, leading=11))
    styles.add(ParagraphStyle("MetaLabel", fontName="Helvetica", fontSize=7,
                              textColor=MUTED, leading=9))
    styles.add(ParagraphStyle("MetaValue", fontName="Helvetica-Bold", fontSize=9,
                              textColor=DARK, leading=12))
    styles.add(ParagraphStyle("H", fontName="Helvetica-Bold", fontSize=9.5,
                              textColor=DARK, leading=13))
    styles.add(ParagraphStyle("N", fontName="Helvetica", fontSize=9,
                              textColor=DARK, leading=13))
    styles.add(ParagraphStyle("Nm", fontName="Helvetica", fontSize=8,
                              textColor=MUTED, leading=12))
    styles.add(ParagraphStyle("SectionLabel", fontName="Helvetica-Bold", fontSize=7.5,
                              textColor=BRAND, leading=10))
    styles.add(ParagraphStyle("Words", fontName="Helvetica-Oblique", fontSize=8.5,
                              textColor=DARK, leading=12))

    order = refund.order
    number = credit_note_number(refund)
    amount = Decimal(str(refund.amount or 0))
    tax = Decimal(str(refund.tax_amount or 0))
    taxable = amount - tax

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Credit Note {number}")
    el = []

    # ---- Header band ----
    header = Table([[
        [Paragraph(SELLER_NAME, styles["BrandW"]),
         Paragraph(SELLER_TAGLINE, styles["TagW"])],
        [Paragraph("CREDIT NOTE", styles["InvTitleW"]),
         Paragraph("Original for Recipient", styles["InvSubW"])],
    ]], colWidths=[108 * mm, 70 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    el.append(header)

    # ---- Meta strip: serial / date / the invoice being credited ----
    # The reference to the original invoice AND its date is what makes this a
    # credit note rather than a receipt; without it the reversal cannot be tied
    # to the supply it reverses.
    def meta_cell(label, value):
        return [Paragraph(label, styles["MetaLabel"]), Paragraph(value, styles["MetaValue"])]

    meta = Table([[
        meta_cell("CREDIT NOTE NO.", number),
        meta_cell("DATE", refund.created_at.strftime("%d %b %Y")),
        meta_cell("AGAINST INVOICE", _credited_invoice_ref(order)),
    ]], colWidths=[45 * mm, 45 * mm, 88 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEAFTER", (0, 0), (1, -1), 0.5, LINE),
    ]))
    el.append(meta)

    # ---- Scope band: whole order back, or part of it ----
    order_total = Decimal(str(order.total_amount or 0))
    returned = Decimal(str(order.refunded_amount or 0))
    partial = order_total > 0 and returned < order_total
    scope = "PARTIAL REFUND" if partial else "FULL REFUND"
    scope_note = (
        f"{_money(returned)} of {_money(order_total)} refunded to date"
        if partial else "The full invoice value has been refunded"
    )
    scope_tbl = Table([[
        Paragraph(f'<font color="white"><b>{scope}</b></font>', styles["N"]),
        Paragraph(f'<font color="white">{scope_note}</font>', styles["Nm"]),
    ]], colWidths=[46 * mm, 132 * mm])
    scope_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#B45309")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(Spacer(1, 4))
    el.append(scope_tbl)
    el.append(Spacer(1, 12))

    # ---- Seller / recipient cards ----
    user = order.user
    seller = [
        Paragraph("FROM", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(SELLER_NAME, styles["H"]),
        Paragraph(f"Proprietor: {SELLER_PROPRIETOR}", styles["Nm"]),
        Paragraph(SELLER_ADDRESS, styles["Nm"]),
        Paragraph(f"GSTIN: {SELLER_GSTIN}", styles["Nm"]),
        Paragraph(f"FSSAI Lic. No: {SELLER_FSSAI}", styles["Nm"]),
        Paragraph(f"{SELLER_EMAIL} &bull; {SELLER_PHONE}", styles["Nm"]),
    ]
    ship_addr = (order.shipping_address or "").replace("\n", "<br/>")
    buyer = [
        Paragraph("CREDIT TO", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(_customer_name(user), styles["H"]),
        Paragraph(ship_addr or "-", styles["Nm"]),
        Paragraph(f"Phone: {order.phone_number or '-'}", styles["Nm"]),
    ]
    if user and getattr(user, "email", None):
        buyer.append(Paragraph(user.email, styles["Nm"]))

    party = Table([[seller, buyer]], colWidths=[89 * mm, 89 * mm])
    party.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (0, 0), 0.6, LINE),
        ("BOX", (1, 0), (1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    el.append(party)
    el.append(Paragraph(_place_of_supply_line(order), styles["Nm"]))
    el.append(Spacer(1, 12))

    # ---- The credited line ----
    description = f"Refund against Tax Invoice {credited_invoice_label(order)}"
    if (refund.note or "").strip():
        description += f"<br/><font size=8 color='#6B7280'>{refund.note.strip()}</font>"
    rows = [
        ["Description", "Taxable Value", "GST", "Amount Credited"],
        [Paragraph(description, styles["N"]), _money(taxable), _money(tax), _money(amount)],
    ]
    tbl = Table(rows, colWidths=[94 * mm, 28 * mm, 26 * mm, 30 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 10))

    # ---- Words + totals ----
    tot_rows = [
        ["Taxable Value", _money(taxable)],
        ["GST Reversed", _money(tax)],
        ["Total Credited", _money(amount)],
    ]
    grand = len(tot_rows) - 1
    tot = Table(tot_rows, colWidths=[40 * mm, 34 * mm])
    tot.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, grand), (-1, grand), BRAND),
        ("TEXTCOLOR", (0, grand), (-1, grand), colors.white),
        ("FONTNAME", (0, grand), (-1, grand), "Helvetica-Bold"),
        ("FONTSIZE", (0, grand), (-1, grand), 11.5),
        ("TOPPADDING", (0, grand), (-1, grand), 7),
        ("BOTTOMPADDING", (0, grand), (-1, grand), 7),
        ("LEFTPADDING", (0, grand), (0, grand), 8),
        ("RIGHTPADDING", (-1, grand), (-1, grand), 8),
    ]))

    words_block = [
        Paragraph("AMOUNT IN WORDS", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(_amount_in_words(amount), styles["Words"]),
    ]

    # ---- GST summary (per rate slab) — the tax actually being reversed ----
    # Headed the same way as the invoice being credited — a credit note must
    # reverse the tax under the heads it was charged under, so it reads the
    # ORDER's place of supply rather than re-deriving one. The section label
    # above already says these are reversals, so the columns stay CGST/SGST/IGST
    # and mean "reversed" by context.
    gst_rows = credit_note_tax_rows(refund)
    if gst_rows:
        slab_data, slab_widths = _gst_summary_rows(
            gst_rows, order.place_of_supply_state_code)
        slab = Table(slab_data, colWidths=[w * mm for w in slab_widths])
        last = len(slab_data) - 1
        slab.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, last), (-1, last), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        words_block += [
            Spacer(1, 10),
            Paragraph("GST SUMMARY", styles["SectionLabel"]),
            Spacer(1, 3),
            slab,
        ]
        if partial:
            words_block += [
                Spacer(1, 3),
                Paragraph(
                    "Rate-wise values on a partial refund are apportioned at the "
                    "order's effective rate.", styles["Nm"]),
            ]

    # 104mm for the left column: the intra-state GST summary carries four
    # columns (rate, taxable value, CGST, SGST) and needs 100mm of them. The
    # totals block on the right only ever uses 74mm, so the width comes out of
    # its slack rather than off the page.
    summary = Table([[words_block, tot]], colWidths=[104 * mm, 74 * mm])
    summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 0), (0, 0), 4),
    ]))
    el.append(summary)
    el.append(Spacer(1, 18))

    # ---- Signature ----
    sign = Table([[
        "",
        [Paragraph(f"For {SELLER_NAME}", styles["H"]),
         Spacer(1, 22),
         Paragraph("Authorised Signatory", styles["Nm"])],
    ]], colWidths=[108 * mm, 70 * mm])
    sign.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    el.append(sign)
    el.append(Spacer(1, 12))

    el.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        f"This credit note reduces the output tax declared on invoice "
        f"{credited_invoice_label(order)} by {_money(tax)} in the period of its issue "
        f"({refund.created_at.strftime('%b %Y')}).", styles["Nm"]))
    el.append(Spacer(1, 3))
    el.append(Paragraph(
        "This is a computer-generated credit note and does not require a "
        "signature or stamp.", styles["Nm"]))

    doc.build(el)
    return buf.getvalue()


def generate_packing_slip_pdf(order) -> bytes:
    """Render a print-friendly packing slip for the given Order.

    Unlike the tax invoice this is a warehouse/courier document: big shipping
    address (readable when stuck on a parcel), the item list with quantities,
    and — for COD — the amount to collect. No unit prices or tax breakdown.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    )

    BRAND = colors.HexColor("#B91C1C")
    DARK = colors.HexColor("#1F2937")
    MUTED = colors.HexColor("#6B7280")
    LIGHT = colors.HexColor("#F7F3F2")
    LINE = colors.HexColor("#E5E7EB")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("BrandW", fontName="Helvetica-Bold", fontSize=20,
                              textColor=colors.white, leading=23))
    styles.add(ParagraphStyle("TitleW", fontName="Helvetica-Bold", fontSize=15,
                              textColor=colors.white, alignment=2, leading=18))
    styles.add(ParagraphStyle("SectionLabel", fontName="Helvetica-Bold", fontSize=8,
                              textColor=BRAND, leading=11))
    styles.add(ParagraphStyle("AddrName", fontName="Helvetica-Bold", fontSize=14,
                              textColor=DARK, leading=18))
    styles.add(ParagraphStyle("AddrBig", fontName="Helvetica", fontSize=12,
                              textColor=DARK, leading=17))
    styles.add(ParagraphStyle("N", fontName="Helvetica", fontSize=10,
                              textColor=DARK, leading=14))
    styles.add(ParagraphStyle("Nm", fontName="Helvetica", fontSize=8.5,
                              textColor=MUTED, leading=12))
    styles.add(ParagraphStyle("CodW", fontName="Helvetica-Bold", fontSize=13,
                              textColor=colors.white, leading=16))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Packing Slip {_order_number(order)}")
    el = []

    header = Table([[
        Paragraph(SELLER_NAME, styles["BrandW"]),
        Paragraph("PACKING SLIP", styles["TitleW"]),
    ]], colWidths=[108 * mm, 70 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    el.append(header)

    meta = Table([[
        Paragraph(f"<b>Order:</b> {_order_number(order)}", styles["N"]),
        Paragraph(f"<b>Date:</b> {order.created_at.strftime('%d %b %Y')}", styles["N"]),
        Paragraph(f"<b>Items:</b> {sum(i.quantity for i in order.items.all())}", styles["N"]),
    ]], colWidths=[59 * mm, 59 * mm, 60 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    el.append(meta)
    el.append(Spacer(1, 12))

    # ---- SHIP TO — deliberately large so it can be cut out / photographed ----
    ship_addr = (order.shipping_address or "").replace("\n", "<br/>")
    ship_block = [
        Paragraph("SHIP TO", styles["SectionLabel"]),
        Spacer(1, 4),
        Paragraph(_customer_name(order.user), styles["AddrName"]),
        Paragraph(ship_addr or "-", styles["AddrBig"]),
        Spacer(1, 4),
        Paragraph(f"Phone: {order.phone_number or '-'}", styles["AddrName"]),
    ]
    from_block = [
        Paragraph("FROM", styles["SectionLabel"]),
        Spacer(1, 4),
        Paragraph(SELLER_NAME, styles["N"]),
        Paragraph(SELLER_ADDRESS, styles["Nm"]),
        Paragraph(f"{SELLER_PHONE}", styles["Nm"]),
    ]
    party = Table([[ship_block, from_block]], colWidths=[110 * mm, 68 * mm])
    party.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 1.2, DARK),
        ("BOX", (1, 0), (1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    el.append(party)
    el.append(Spacer(1, 12))

    # ---- COD box: the one number the courier must collect ----
    is_cod = (order.payment_method or "").upper() == "COD"
    is_paid = (order.payment_status or "").lower() == "paid"
    if is_cod and not is_paid:
        cod = Table([[Paragraph(
            f"CASH ON DELIVERY — COLLECT {_money(order.total_amount)}",
            styles["CodW"])]], colWidths=[178 * mm])
        cod.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#B45309")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
    else:
        cod = Table([[Paragraph(
            "PREPAID — DO NOT COLLECT ANY MONEY", styles["CodW"])]],
            colWidths=[178 * mm])
        cod.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#047857")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
    el.append(cod)
    el.append(Spacer(1, 12))

    # ---- Items to pack (checklist, no prices) ----
    rows = [["#", "Item", "Pack", "Qty", "Packed?"]]
    for i, item in enumerate(order.items.all(), 1):
        rows.append([
            str(i),
            Paragraph(item.product_name, styles["N"]),
            item.product_weight or "-",
            str(item.quantity),
            "[   ]",
        ])
    tbl = Table(rows, colWidths=[10 * mm, 96 * mm, 26 * mm, 20 * mm, 26 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 14))

    el.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "Packing slip — not an invoice. Prices are on the tax invoice.",
        styles["Nm"]))

    doc.build(el)
    return buf.getvalue()
