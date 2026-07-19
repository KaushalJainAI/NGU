"""
PDF invoice / bill generation for orders.

`generate_invoice_pdf(order)` renders a tax invoice for an Order instance and
returns the raw PDF bytes. Data is pulled dynamically from the order, its user,
and its line items so every bill reflects the real purchase.

reportlab is imported lazily so the rest of the orders app keeps working even if
the dependency is missing in some environment; the view surfaces a clear error.
"""
from decimal import Decimal
from io import BytesIO

from django.conf import settings

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


def _order_number(order):
    return f"ORD-{order.id:06d}"


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


def generate_invoice_pdf(order) -> bytes:
    """Render a tax invoice PDF for the given Order and return its bytes."""
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

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Invoice {_order_number(order)}")
    el = []
    created = order.created_at

    # ---- Header band: brand (left) + TAX INVOICE (right) on a colored bar ----
    header = Table([[
        [Paragraph(SELLER_NAME, styles["BrandW"]),
         Paragraph(SELLER_TAGLINE, styles["TagW"])],
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

    # ---- Meta strip: invoice no / date / payment status ----
    pay_status = (order.payment_status or "pending").upper()
    try:
        pay_method = order.get_payment_method_display()
    except Exception:
        pay_method = order.payment_method or "-"

    def meta_cell(label, value):
        return [Paragraph(label, styles["MetaLabel"]), Paragraph(value, styles["MetaValue"])]

    meta = Table([[
        meta_cell("INVOICE NO.", _order_number(order)),
        meta_cell("DATE", created.strftime("%d %b %Y, %I:%M %p")),
        meta_cell("PAYMENT", f"{pay_method} — {pay_status}"),
    ]], colWidths=[59 * mm, 59 * mm, 60 * mm])
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

    # ---- Order status band ----
    # Every invoice states the current lifecycle status of the order so the bill
    # is self-explanatory. A cancelled order is called out in red so it can never
    # be mistaken for a live/fulfilled purchase.
    try:
        status_label = order.get_status_display()
    except Exception:
        status_label = (order.status or "Pending").replace("_", " ").title()
    is_cancelled = (order.status or "").lower() == "cancelled"
    status_bg = colors.HexColor("#B91C1C") if is_cancelled else colors.HexColor("#047857")
    status_note = (
        "This order has been cancelled. This document is retained for your records only."
        if is_cancelled else
        "Order Status"
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
    el.append(Spacer(1, 12))

    # ---- Seller / buyer cards ----
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
        Paragraph("BILL TO / SHIP TO", styles["SectionLabel"]),
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
    el.append(Paragraph(
        f"Place of Supply: {SELLER_STATE} ({SELLER_STATE_CODE})", styles["Nm"]))
    el.append(Spacer(1, 12))

    # ---- Line items ----
    rows = [["#", "Item", "Pack", "Qty", "Rate", "Amount"]]
    for i, item in enumerate(order.items.all(), 1):
        line_total = item.price * item.quantity
        rows.append([
            str(i),
            Paragraph(item.product_name, styles["N"]),
            item.product_weight or "-",
            str(item.quantity),
            _money(item.price),
            _money(line_total),
        ])

    tbl = Table(rows, colWidths=[8 * mm, 82 * mm, 22 * mm, 14 * mm, 26 * mm, 26 * mm],
                repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    el.append(tbl)
    el.append(Spacer(1, 10))

    # ---- Amount in words (left) + totals (right) ----
    tot_rows = [["Subtotal", _money(order.subtotal)]]
    if order.discount_amount and order.discount_amount > 0:
        label = "Discount"
        if order.coupon_code:
            label = f"Discount ({order.coupon_code})"
        tot_rows.append([label, "- " + _money(order.discount_amount)])
    tot_rows.append(["GST", _money(order.tax)])
    tot_rows.append([
        "Shipping",
        "FREE" if (order.shipping_charge or 0) == 0 else _money(order.shipping_charge),
    ])
    tot_rows.append(["Grand Total", _money(order.total_amount)])

    n_rows = len(tot_rows)
    tot = Table(tot_rows, colWidths=[40 * mm, 34 * mm])
    tot.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -2), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR", (0, 0), (-1, -2), DARK),
        ("TOPPADDING", (0, 0), (-1, -2), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 4),
        # Grand total row — highlighted band
        ("BACKGROUND", (0, n_rows - 1), (-1, n_rows - 1), BRAND),
        ("TEXTCOLOR", (0, n_rows - 1), (-1, n_rows - 1), colors.white),
        ("FONTNAME", (0, n_rows - 1), (-1, n_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, n_rows - 1), (-1, n_rows - 1), 11.5),
        ("TOPPADDING", (0, n_rows - 1), (-1, n_rows - 1), 7),
        ("BOTTOMPADDING", (0, n_rows - 1), (-1, n_rows - 1), 7),
        ("LEFTPADDING", (0, n_rows - 1), (0, n_rows - 1), 8),
        ("RIGHTPADDING", (-1, n_rows - 1), (-1, n_rows - 1), 8),
    ]))

    words_block = [
        Paragraph("AMOUNT IN WORDS", styles["SectionLabel"]),
        Spacer(1, 3),
        Paragraph(_amount_in_words(order.total_amount), styles["Words"]),
    ]
    summary = Table([[words_block, tot]], colWidths=[100 * mm, 78 * mm])
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

    # ---- Footer note ----
    el.append(HRFlowable(width="100%", thickness=0.5, color=LINE))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        f"Thank you for shopping with {SELLER_NAME}! For any query about this "
        f"invoice, contact {SELLER_EMAIL} or {SELLER_PHONE}.",
        styles["Nm"]))
    el.append(Spacer(1, 3))
    el.append(Paragraph(
        "This is a computer-generated invoice and does not require a signature or stamp.",
        styles["Nm"]))

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
