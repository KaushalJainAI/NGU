"""Generate a send-ready PDF of the Nidhi Masala Reel Campaign Brief."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
import os

OUT = os.path.join(os.path.dirname(__file__), "Nidhi_Masala_Reel_Campaign_Brief.pdf")

# Brand colours
SAFFRON = HexColor("#C45C26")
TURMERIC = HexColor("#D4A017")
CHILLI = HexColor("#B33A1A")
CREAM = HexColor("#FFF8F0")
DARK = HexColor("#2C1810")
MUTED = HexColor("#5C4033")
LIGHT_BG = HexColor("#FDF6EE")
SOFT_LINE = HexColor("#E8D5C4")
CARD_BG = HexColor("#FFFBF7")
PROMPT_BG = HexColor("#FFF3E6")

page_w, page_h = A4
MARGIN = 16 * mm


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(SAFFRON)
    canvas.rect(0, page_h - 10 * mm, page_w, 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(
        MARGIN, page_h - 6.5 * mm, "NIDHI MASALA  |  Launch Reel Campaign Brief"
    )
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(
        page_w - MARGIN, page_h - 6.5 * mm, "Confidential — Production Brief"
    )
    canvas.setFillColor(DARK)
    canvas.rect(0, 0, page_w, 10 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN, 4 * mm, "nidhigrahudyog.com  ·  +91 93000 05040")
    canvas.drawRightString(page_w - MARGIN, 4 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=DARK,
            alignment=TA_CENTER,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSub",
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=MUTED,
            alignment=TA_CENTER,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BigMid",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=CHILLI,
            alignment=TA_CENTER,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHead",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=SAFFRON,
            spaceBefore=12,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHead",
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=DARK,
            spaceBefore=8,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            textColor=DARK,
            spaceAfter=3,
            alignment=TA_JUSTIFY,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyTight",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=DARK,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BriefBullet",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=DARK,
            leftIndent=10,
            spaceAfter=1.5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Script",
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=12.5,
            textColor=DARK,
            leftIndent=4,
            rightIndent=4,
            spaceBefore=2,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Caption",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=11,
            textColor=CHILLI,
            spaceBefore=2,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Small",
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=MUTED,
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableCell",
            fontName="Helvetica",
            fontSize=8,
            leading=10.5,
            textColor=DARK,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableHeader",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10.5,
            textColor=white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="FooterNote",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SceneTitle",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=white,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="PromptBox",
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=DARK,
            spaceAfter=2,
        )
    )
    return styles


def kv_table(styles, rows, col1=38 * mm):
    col2 = page_w - 2 * MARGIN - col1
    data = []
    for k, v in rows:
        data.append(
            [
                Paragraph(f"<b>{k}</b>", styles["TableCell"]),
                Paragraph(v, styles["TableCell"]),
            ]
        )
    t = Table(data, colWidths=[col1, col2])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT_BG),
                ("BACKGROUND", (1, 0), (1, -1), CARD_BG),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("GRID", (0, 0), (-1, -1), 0.4, SOFT_LINE),
                ("BOX", (0, 0), (-1, -1), 0.8, SAFFRON),
            ]
        )
    )
    return t


def two_col_table(styles, headers, rows, widths=None):
    if widths is None:
        w = page_w - 2 * MARGIN
        widths = [w * 0.32, w * 0.68]
    data = [[Paragraph(h, styles["TableHeader"]) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c), styles["TableCell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), SAFFRON),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("GRID", (0, 0), (-1, -1), 0.35, SOFT_LINE),
        ("BOX", (0, 0), (-1, -1), 0.8, SAFFRON),
    ]
    for i in range(1, len(data)):
        bg = LIGHT_BG if i % 2 == 0 else CARD_BG
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    t.setStyle(TableStyle(style_cmds))
    return t


def scene_banner(styles, title, timing):
    data = [
        [
            Paragraph(
                f'{title}  <font color="#FFF8F0">|</font>  {timing}',
                styles["SceneTitle"],
            )
        ]
    ]
    t = Table(data, colWidths=[page_w - 2 * MARGIN])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CHILLI),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def script_box(styles, text):
    p = Paragraph(f"<i>“{text}”</i>", styles["Script"])
    t = Table([[p]], colWidths=[page_w - 2 * MARGIN])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PROMPT_BG),
                ("BOX", (0, 0), (-1, -1), 1, TURMERIC),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def note_box(styles, title, body_text):
    data = [[Paragraph(f"<b>{title}</b><br/>{body_text}", styles["BodyTight"])]]
    t = Table(data, colWidths=[page_w - 2 * MARGIN])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
                ("BOX", (0, 0), (-1, -1), 1.2, SAFFRON),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def bullet(styles, text):
    return Paragraph(f"•  {text}", styles["BriefBullet"])


def main():
    styles = build_styles()
    story = []

    # ---- Cover ----
    story.append(Spacer(1, 18 * mm))
    story.append(Paragraph("NIDHI MASALA", styles["CoverTitle"]))
    story.append(Paragraph("Nidhi Grah Udyog", styles["CoverSub"]))
    story.append(Spacer(1, 3 * mm))
    line = Table([[""]], colWidths=[55 * mm])
    line.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, -1), 2.5, SAFFRON),
            ]
        )
    )
    wrapper = Table([[line]], colWidths=[page_w - 2 * MARGIN])
    wrapper.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    story.append(wrapper)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Reel Campaign Brief", styles["BigMid"]))
    story.append(
        Paragraph(
            "“We’re Live Online!” — 60-second Launch Reel", styles["CoverSub"]
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(
        kv_table(
            styles,
            [
                ("Campaign", "Online store launch — pan-India announcement"),
                ("Brand", "Nidhi Masala (Nidhi Grah Udyog)"),
                ("Live store", "https://nidhigrahudyog.com"),
                (
                    "Format",
                    "Vertical Instagram / YouTube Shorts Reel · 9:16",
                ),
                ("Length", "~60 seconds · 4 scenes"),
                (
                    "Audience",
                    "Video creator / creative director / AI video agent",
                ),
                ("Document type", "Production-ready creative brief"),
            ],
            col1=40 * mm,
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(
        note_box(
            styles,
            "Purpose of this document",
            "This brief gives a creative partner everything needed to script, storyboard, "
            "and produce the Nidhi Masala launch Reel — brand facts, accurate shipping/returns, "
            "real product names, scene-by-scene host scripts, UI sequences, and accuracy "
            "guardrails. Use only the facts listed here; do not invent features or policies.",
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Reference composition: host talking to camera + large phone UI overlay + "
            "finger pointing at key action + big captions (see accompanying reference image).",
            styles["Small"],
        )
    )
    story.append(
        Paragraph(
            "Prepared for Nidhi Masala · Internal / Agency use",
            styles["FooterNote"],
        )
    )

    story.append(PageBreak())

    # ---- 1. Overview ----
    story.append(Paragraph("1. Video Overview", styles["SectionHead"]))
    story.append(
        kv_table(
            styles,
            [
                (
                    "Campaign",
                    "Online store launch — “We’re live across India”",
                ),
                (
                    "Brand",
                    "<b>Nidhi Masala</b> (legal: Nidhi Grah Udyog)",
                ),
                (
                    "Product",
                    "Authentic Indian spices &amp; masalas — pure blends, hand-packed in Barnagar",
                ),
                (
                    "Platform",
                    "Mobile-first <b>website</b> (not a native app). Show a phone browser UI of the live storefront.",
                ),
                ("Live URL", "https://nidhigrahudyog.com"),
                (
                    "Goal",
                    "1) Announce the online store  2) Show how easy ordering is  "
                    "3) Highlight real storefront features  4) Cover online-only payment (No COD), shipping, returns &amp; support honestly",
                ),
                ("Format", "Vertical Instagram / YouTube Shorts Reel — <b>9:16</b>"),
                ("Length", "~60 seconds (4 scenes)"),
                (
                    "Tone",
                    "Warm, energetic, kitchen-table friendly — “family spice brand that finally went digital”",
                ),
                (
                    "Presenter",
                    "Young adult host, smart-casual (mustard / warm spice tones OK), talks to camera, points at a large 2D phone overlay",
                ),
                (
                    "Language",
                    "Primary script in <b>English</b> with light Hinglish energy optional on captions; "
                    "store supports EN / HI / Hinglish / GU / MR / PA",
                ),
            ],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        note_box(
            styles,
            "⚠️ Important Payment Policy",
            "<b>Cash on Delivery (COD) is NOT available.</b> Nidhi Masala operates on a <b>100% online prepaid model</b>. "
            "Orders are dispatched upon payment confirmation via Razorpay (UPI, Google Pay, PhonePe, Cards, Netbanking, Wallets). "
            "The presenter script and visual overlays MUST clearly show online payment and clarify <b>No COD</b>.",
        )
    )

    # ---- 2. Brand facts ----
    story.append(
        Paragraph(
            "2. Brand Facts (use only these — do not invent)",
            styles["SectionHead"],
        )
    )
    story.append(Paragraph("2.1 Identity", styles["SubHead"]))
    for line_t in [
        "<b>Est. 1995</b> · Barnagar, Ujjain, Madhya Pradesh",
        "Tagline energy: <i>“Taste of Tradition in Every Spice”</i>",
        "FREE shipping on orders above <b>₹499</b>",
        "100% pure &amp; natural — no fillers",
        "Hand-packed in Barnagar",
        "Trusted by <b>1.1M+ kitchens</b>",
        "<b>50+</b> products · <b>100%</b> pure &amp; natural",
        "<b>Payment Policy:</b> 100% Online Prepaid Only (<b>No COD / Cash on Delivery</b>)",
        "Address: 7, Industrial Area, Runija Road, Barnagar, Ujjain, MP 456771",
        "Support phone / WhatsApp: <b>+91 93000 05040</b>",
        "Email: nidhispicesandfood@gmail.com",
    ]:
        story.append(bullet(styles, line_t))

    story.append(
        Paragraph("2.2 Hero products to show on screen", styles["SubHead"])
    )
    story.append(
        Paragraph(
            "Nidhi <b>Jeeravan Masala</b> · <b>Achar Masala</b> · <b>Haldi Powder</b> · "
            "<b>Kashmiri Mirchi</b> · <b>Kasuri Methi</b> · <b>Kitchen King Masala</b> · "
            "<b>Pav Bhaji Masala</b> · <b>Garam Masala</b> / <b>Tea Chai Masala</b> / "
            "<b>Papad</b> · <b>Combo packs</b> from the Combos section. "
            "Use real pack shots wherever available.",
            styles["Body"],
        )
    )

    story.append(
        Paragraph(
            "2.3 Real storefront features (show these)", styles["SubHead"]
        )
    )
    story.append(
        two_col_table(
            styles,
            ["Feature", "What it is on Nidhi Masala"],
            [
                ["Product catalog", "Categories, search with autocomplete, filters"],
                ["Combos &amp; Offers", "Combo packs + Offer Zone / coupons"],
                ["Cart &amp; checkout", "Add to cart → address → online pay"],
                [
                    "Payments",
                    "<b>100% Online Prepaid Only (Razorpay)</b> — UPI, Google Pay, Cards, Netbanking, Wallets (<b>NO Cash on Delivery / COD</b>)",
                ],
                ["My Orders", "Order history &amp; status tracking"],
                [
                    "Recommendations",
                    "“Recommended For You” from browse/buy behaviour",
                ],
                [
                    "AI Shopping Assistant",
                    "In-site chat widget (login) — product Q&amp;A, cart help, human handoff",
                ],
                ["Voice", "Voice input on the assistant (self-hosted STT)"],
                [
                    "Multilingual",
                    "English, Hindi, Hinglish, Gujarati, Marathi, Punjabi",
                ],
                ["Favorites", "Wishlist / save for later"],
                ["Reviews", "Verified-purchase reviews"],
            ],
        )
    )

    story.append(Paragraph("2.4 Shipping (accurate copy)", styles["SubHead"]))
    for line_t in [
        "Ships <b>all India only</b> (no international)",
        "<b>Free shipping</b> on orders <b>above ₹499</b> (else ₹69)",
        "Delivery: Metro <b>3–5</b> days · Other cities <b>5–7</b> · Remote <b>7–10</b> business days",
        "Processed in <b>24–48 hours</b> after payment confirmation",
        "Tracking via email/SMS + <b>My Orders</b> page",
    ]:
        story.append(bullet(styles, line_t))

    story.append(
        Paragraph(
            "2.5 Returns &amp; support (accurate — do not claim false 24/7)",
            styles["SubHead"],
        )
    )
    for line_t in [
        "Returns/replacements within <b>7 days</b> of delivery for damaged / wrong / missing / tampered only",
        "<b>Unboxing video required</b> for claims",
        "Opened/used food products are non-returnable (hygiene)",
        "Support: <b>Mon–Sat, 9 AM – 6 PM IST</b> · phone/WhatsApp <b>+91 93000 05040</b>",
        "In-site: AI shopping assistant + human-admin chat handoff (login)",
    ]:
        story.append(bullet(styles, line_t))

    story.append(PageBreak())

    # ---- 3. Scenes ----
    story.append(Paragraph("3. Scene-by-Scene Breakdown", styles["SectionHead"]))

    # Scene 1
    story.append(Spacer(1, 3 * mm))
    story.append(
        scene_banner(styles, "Scene 1 — The Big Announcement", "0–10 seconds")
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Visual", styles["SubHead"]))
    for line_t in [
        "Host in a bright Indian home kitchen / warm studio (turmeric gold, saffron, rust red palette).",
        "Large flat <b>2D phone</b> (~25–30% of frame) pops in beside them — host + phone composition like the reference image.",
        "Phone shows the <b>Nidhi Masala homepage</b> (hero: “Taste of Tradition in Every Spice”, spice product tiles, trust ribbon).",
    ]:
        story.append(bullet(styles, line_t))
    story.append(Paragraph("Host script", styles["SubHead"]))
    story.append(
        script_box(
            styles,
            "Huge news! Nidhi Masala is officially ONLINE! "
            "From metros to every corner of India — our pure, hand-packed spices from Barnagar "
            "can now land straight at your doorstep. "
            "50+ blends. 1.1 million kitchens already trust us. Now shop anytime at nidhigrahudyog.com!",
        )
    )
    story.append(Paragraph("UI / motion on phone", styles["SubHead"]))
    for line_t in [
        "Homepage loads with brand logo + hero spices.",
        "Quick flash of India map lighting up (metros → towns).",
        "Trust chips scroll: Free shipping ₹499+ · 100% pure · Hand-packed in Barnagar.",
    ]:
        story.append(bullet(styles, line_t))
    story.append(
        Paragraph(
            "On-screen caption: <b>Nidhi Masala is LIVE — Shop all-India</b>",
            styles["Caption"],
        )
    )

    # Scene 2
    story.append(Spacer(1, 2 * mm))
    story.append(
        scene_banner(styles, "Scene 2 — How to Place an Order", "10–25 seconds")
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Visual", styles["SubHead"]))
    story.append(
        bullet(styles, "Host gestures at the phone. UI animates the real checkout path.")
    )
    story.append(Paragraph("Host script", styles["SubHead"]))
    story.append(
        script_box(
            styles,
            "Ordering takes under a minute. "
            "Open nidhigrahudyog.com, browse categories — Jeeravan, Haldi, Achar Masala, combos… "
            "Tap Add to Cart, hit checkout, enter your address, and pay securely online with UPI, card, netbanking, or wallet. (Note: online pay only — no Cash on Delivery!) Done!",
        )
    )
    story.append(Paragraph("UI sequence on phone", styles["SubHead"]))
    for line_t in [
        "<b>Products / category grid</b> — real spice cards (e.g. Jeeravan, Kashmiri Mirchi).",
        "Product detail → <b>Add to Cart</b>.",
        "Cart with floating cart bar → Checkout.",
        "Payment sheet: <b>Razorpay</b> options only (UPI / Cards / Netbanking / Wallets) — <b>NO Cash on Delivery (COD)</b>.",
        "Success → “Order placed” / My Orders status.",
    ]:
        story.append(bullet(styles, line_t))
    story.append(
        Paragraph(
            "On-screen caption: <b>Browse → Cart → Secure Online Pay (UPI/Card) [No COD]</b>",
            styles["Caption"],
        )
    )

    # Scene 3
    story.append(Spacer(1, 2 * mm))
    story.append(
        scene_banner(
            styles, "Scene 3 — Store Features (Shopper POV)", "25–45 seconds"
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Visual", styles["SubHead"]))
    story.append(
        bullet(
            styles,
            "Tighter crop on phone UI; host still frames and points at each feature as it appears.",
        )
    )
    story.append(Paragraph("Host script", styles["SubHead"]))
    story.append(
        script_box(
            styles,
            "We built the store the way you actually shop: "
            "Track every order on My Orders. "
            "Get picks recommended for you from what you browse. "
            "Grab combo deals and offer-zone coupons. "
            "And if you’re stuck — open our AI shopping assistant, even with voice, in Hindi or English!",
        )
    )
    story.append(Paragraph("UI sequence on phone", styles["SubHead"]))
    for line_t in [
        "<b>My Orders</b> — status steps (Placed → Packed → Shipped → Delivered).",
        "Home <b>“Recommended For You”</b> product slider.",
        "<b>Combos / Offer Zone</b> with a coupon apply animation.",
        "<b>Assistant chat bubble</b> opens — sample: “Best masala for poha?” → product card reply → Add to cart.",
        "Language selector flash: EN · HI · Hinglish · GU · MR · PA.",
    ]:
        story.append(bullet(styles, line_t))
    story.append(
        Paragraph(
            "Caption chips (one at a time): Order tracking · Personal picks · Combos &amp; coupons · AI + voice help",
            styles["Caption"],
        )
    )

    # Scene 4
    story.append(Spacer(1, 2 * mm))
    story.append(
        scene_banner(
            styles,
            "Scene 4 — Delivery, Returns, Support + CTA",
            "45–60 seconds",
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Visual", styles["SubHead"]))
    story.append(
        bullet(
            styles,
            "Host holds a <b>Nidhi-branded spice pack</b> or points at pop-up policy cards beside the phone.",
        )
    )
    story.append(Paragraph("Host script", styles["SubHead"]))
    story.append(
        script_box(
            styles,
            "Shipping? All India — free on orders above ₹499. "
            "Pay online securely with UPI or card — we process and ship directly from Barnagar! "
            "Track every step on My Orders. "
            "Something wrong on delivery? 7-day easy return for damaged or wrong items — just keep that unboxing video. "
            "Questions? WhatsApp us on 93000 05040, or chat right inside the site. "
            "Shop pure spices now — nidhigrahudyog.com!",
        )
    )
    story.append(Paragraph("UI / card pop-ups", styles["SubHead"]))
    for line_t in [
        "Pan-India delivery · Free above ₹499",
        "100% Prepaid Online Payment (No COD)",
        "Track on My Orders",
        "7-day return for damaged / wrong items",
        "Support chat + WhatsApp +91 93000 05040",
        "End card (see Section 5)",
    ]:
        story.append(bullet(styles, line_t))
    story.append(
        Paragraph(
            "On-screen caption: <b>Free shipping ₹499+ · Prepaid Online Pay (No COD) · Shop now</b>",
            styles["Caption"],
        )
    )

    story.append(PageBreak())

    # ---- 4. Audio ----
    story.append(
        Paragraph("4. Audio &amp; On-Screen Elements", styles["SectionHead"])
    )
    story.append(
        two_col_table(
            styles,
            ["Element", "Direction"],
            [
                [
                    "Music",
                    "Upbeat modern Indian-pop / electronic instrumental. Warm percussion; light sitar/flute motif optional. Duck under speech; lift on transitions.",
                ],
                [
                    "Voice",
                    "Clear, friendly Indian English; smile in the voice. Optional soft Hinglish on one line (“bilkul simple!”).",
                ],
                [
                    "Subtitles",
                    "High-legibility <b>white text + dark outline/shadow</b>, lower-third, Instagram-native.",
                ],
                [
                    "SFX",
                    "Soft whoosh on phone pop-in; UI tap clicks; subtle success chime on order placed.",
                ],
                [
                    "Do not show",
                    "Fake “Download on App Store / Play Store” buttons — this is a <b>website</b>. Do NOT show COD payment buttons.",
                ],
            ],
        )
    )

    # ---- 5. End card ----
    story.append(
        Paragraph("5. End Card (final 3–4 seconds)", styles["SectionHead"])
    )
    story.append(
        kv_table(
            styles,
            [
                ("Logo", "Nidhi Masala / Nidhi Grah Udyog logo"),
                ("Headline", "<b>Shop pure spices online</b>"),
                ("Primary CTA", "<b>nidhigrahudyog.com</b>"),
                (
                    "Subline",
                    "Free shipping above ₹499 · Hand-packed in Barnagar since 1995",
                ),
                ("Secondary", "WhatsApp: +91 93000 05040 · Online Pay Only (No COD)"),
                (
                    "Spoken CTA (optional)",
                    "“Open nidhigrahudyog.com and spice up your kitchen today!”",
                ),
            ],
        )
    )

    # ---- 6. Production ----
    story.append(Paragraph("6. Production Notes", styles["SectionHead"]))
    story.append(Paragraph("6.1 Visual style", styles["SubHead"]))
    for line_t in [
        "<b>9:16 vertical</b>; Instagram Reel chrome optional.",
        "Host left / center-left; <b>oversized phone mockup</b> right (~25–35% of frame).",
        "Finger pointing at the primary CTA on the phone (Add to Cart / Pay / Shop Now).",
        "Bright living-room or modern kitchen bokeh — warm, inviting, not corporate grey.",
        "Colour palette: <b>saffron, turmeric gold, chilli red, cream, deep brown</b>.",
    ]:
        story.append(bullet(styles, line_t))

    story.append(Paragraph("6.2 Phone UI fidelity", styles["SubHead"]))
    for line_t in [
        "Prefer <b>real screenshots</b> from https://nidhigrahudyog.com (home, products, cart, checkout, my orders, assistant).",
        "If generating UI, brand it <b>Nidhi Masala</b> — not a generic demo app.",
        "Show <b>₹</b> pricing, Indian payment icons (UPI, cards, netbanking, wallets — <b>strictly NO Cash on Delivery / COD</b>), and spice product photography.",
    ]:
        story.append(bullet(styles, line_t))

    story.append(
        Paragraph("6.3 Accuracy guardrails (critical)", styles["SubHead"])
    )
    story.append(
        two_col_table(
            styles,
            ["Do NOT say / show", "Say / show instead"],
            [
                [
                    "“Download the app”",
                    "“Open nidhigrahudyog.com” / “Shop on our website”",
                ],
                [
                    "“Cash on Delivery available” / “Pay COD”",
                    "“100% Secure Online Payment (UPI, Cards, Netbanking)” / “No COD — prepaid dispatch”",
                ],
                [
                    "Show COD option on checkout UI",
                    "Show Razorpay payment sheet with UPI/Cards/Wallets only",
                ],
                [
                    "“24/7 customer support”",
                    "“In-site chat + WhatsApp support (Mon–Sat, 9–6)”",
                ],
                [
                    "“Same-day pan-India”",
                    "“Pan-India delivery, free above ₹499”",
                ],
                [
                    "“Return anything anytime”",
                    "“7-day return for damaged / wrong / missing items”",
                ],
                ["Fake product names", "Real Nidhi SKUs listed in Section 2.2"],
            ],
        )
    )

    story.append(Paragraph("6.4 Timing summary", styles["SubHead"]))
    w = page_w - 2 * MARGIN
    story.append(
        two_col_table(
            styles,
            ["Scene", "Time &amp; focus"],
            [
                [
                    "1 — Announcement",
                    "0–10s · Launch + brand trust (1.1M kitchens, Barnagar, pan-India)",
                ],
                ["2 — Order flow", "10–25s · Browse → cart → online pay (UPI / card) [No COD]"],
                [
                    "3 — Features",
                    "25–45s · Tracking, recs, combos, AI/voice, languages",
                ],
                [
                    "4 — Policies + CTA",
                    "45–60s · Shipping, prepaid policy, returns, support + end card",
                ],
            ],
            widths=[w * 0.28, w * 0.72],
        )
    )

    story.append(Paragraph("6.5 Suggested assets", styles["SubHead"]))
    story.append(
        two_col_table(
            styles,
            ["Asset", "Use"],
            [
                ["Brand logo", "End card"],
                [
                    "spices-hero / product pack shots",
                    "Scene 1 backdrop &amp; phone product grid",
                ],
                ["Kitchen / spice grinding B-roll", "Optional cutaways"],
                ["Live site screenshots", "Phone UI fidelity"],
                ["Reference composition image", "Host + phone framing style"],
            ],
        )
    )

    story.append(PageBreak())

    # ---- 7. One-shot prompt ----
    story.append(
        Paragraph(
            "7. One-Shot Prompt (for AI video tools)", styles["SectionHead"]
        )
    )
    story.append(
        Paragraph(
            "Copy-paste the block below into a video generation agent:",
            styles["Body"],
        )
    )
    story.append(Spacer(1, 2 * mm))

    prompt_text = (
        "Vertical 9:16 Instagram Reel, ~60 seconds. Energetic young adult host in a warm Indian kitchen, "
        "mustard hoodie or smart-casual, talking to camera. Large 2D smartphone overlay (~30% of frame) shows the "
        "<b>Nidhi Masala</b> mobile website (nidhigrahudyog.com). Style like a product demo Reel: host points at UI, "
        "big lower-third captions, upbeat Indian-pop instrumental ducked under speech.<br/><br/>"
        "<b>0–10s:</b> “Huge news — Nidhi Masala is officially ONLINE!” India map lights up; homepage with pure spices, "
        "“Since 1995 · Barnagar”, “Trusted by 1.1M+ kitchens”.<br/>"
        "<b>10–25s:</b> Order demo — browse Jeeravan / Haldi / Achar Masala → Add to Cart → checkout → pay online with UPI, Google Pay, card, netbanking or wallet (100% online prepaid only, NO Cash on Delivery / COD).<br/>"
        "<b>25–45s:</b> Features montage — My Orders tracking, Recommended For You, combo offers, AI shopping assistant with voice, language switcher.<br/>"
        "<b>45–60s:</b> Policy cards — Free shipping above ₹499, pan-India delivery, prepaid payment policy (No COD), 7-day returns for damaged/wrong items, "
        "WhatsApp +91 93000 05040. End card: Nidhi Masala logo + <b>nidhigrahudyog.com</b> + “Shop pure spices now”.<br/><br/>"
        "Colour palette: saffron, turmeric gold, chilli red, cream. High-legibility English captions. "
        "No App Store badges. Photoreal host, clean UI mockups, smooth transitions."
    )
    pt = Table(
        [[Paragraph(prompt_text, styles["PromptBox"])]],
        colWidths=[page_w - 2 * MARGIN],
    )
    pt.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PROMPT_BG),
                ("BOX", (0, 0), (-1, -1), 1.5, SAFFRON),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.append(pt)

    story.append(Spacer(1, 10 * mm))
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=SAFFRON, spaceBefore=4, spaceAfter=8
        )
    )
    story.append(
        Paragraph(
            "<b>Nidhi Masala · Nidhi Grah Udyog</b><br/>"
            "7, Industrial Area, Runija Road, Barnagar, Ujjain, MP 456771<br/>"
            "Web: nidhigrahudyog.com  ·  WhatsApp: +91 93000 05040  ·  "
            "Email: nidhispicesandfood@gmail.com",
            styles["FooterNote"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        Paragraph(
            "This document is a production brief for the online store launch Reel. "
            "All product, shipping, and support claims must match the live store policies.",
            styles["FooterNote"],
        )
    )

    doc = SimpleDocTemplate(
        OUT,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title="Nidhi Masala — Reel Campaign Brief",
        author="Nidhi Grah Udyog",
        subject="Launch Reel production brief — We’re Live Online",
        pageCompression=1,
    )
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    
    # Post-process optimization with PyMuPDF
    import fitz
    tmp_out = OUT + ".tmp"
    opt_doc = fitz.open(OUT)
    opt_doc.save(tmp_out, deflate=True, garbage=4, clean=True)
    opt_doc.close()
    os.replace(tmp_out, OUT)

    print(f"WROTE {OUT}")
    print(f"SIZE {os.path.getsize(OUT)} bytes")


if __name__ == "__main__":
    main()
