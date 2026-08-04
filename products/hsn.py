"""HSN classification reference for the catalogue.

WHY THIS EXISTS
---------------
`Product.tax_rate` records *what we charge*. It cannot record *why*, and a GST
return needs both. GSTR-1 Table 12 is an HSN summary — for every HSN code sold
in the period, the quantity, taxable value and tax. There is no way to derive an
HSN code from a rate:

  * one rate spans many headings — 5% covers 0904 (pepper/chilli), 0909
    (coriander/cumin), 0910 (turmeric/ginger/masala mixes) and more;
  * one heading can change slab when the law changes — 2103 went 12% -> 18% on
    22 Sep 2025 without any product changing.

So the code has to be *stored* per product, and snapshotted onto the order line
at checkout exactly like `tax_rate` is, for the identical reason: re-coding a
product next year must not silently rewrite last year's invoice.

WHAT THIS MODULE IS (AND IS NOT)
--------------------------------
`HSN_REFERENCE` below is a curated *lookup table* of the headings this catalogue
actually needs, with the statutory GST rate published for each. It is a
CONVENIENCE for the admin — the panel shows the code list and the rate that goes
with it, and the admin still types the rate they want onto the product. The rate
here is never applied automatically:

  * `Product.tax_rate` remains the single source of truth for what is charged;
  * classification is a judgement call with money attached (see the 0910 91 vs
    2103 90 40 note below) and belongs to the seller and their CA, not to code;
  * a wrong auto-applied rate would change customer-facing prices' GST split on
    every future order, silently.

Rates are as published for the GST 2.0 schedule effective **22 September 2025**
(Notification 9/2025-CT(Rate)). `RATES_AS_OF` is surfaced in the admin UI so the
figure on screen is never mistaken for something the app keeps live.

THE ONE CLASSIFICATION JUDGEMENT THAT MATTERS HERE
--------------------------------------------------
A blended masala made only of spices stays in Chapter 9 under **0910 91 00 at
5%**. Add a material non-spice ingredient — salt, sugar, starch, edible oil,
dried vegetable — and the revenue's position is that it becomes a "mixed
condiment / mixed seasoning" under **2103 90 40, now 18%**. Most of this
catalogue's masala blends do contain salt. That is a 13-point swing on roughly
half the catalogue, so the reference lists BOTH codes and flags the trade-off;
it does not choose. Get it confirmed by a CA before filing.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError

# GST law recognises 4-, 6- and 8-digit HSN. Anything else is a typo, and a typo
# in this field surfaces as a rejected return months later, so reject it at the
# form instead. Blank is allowed (= not yet classified) and handled by the field.
_HSN_RE = re.compile(r'^\d{4}(\d{2}(\d{2})?)?$')


def validate_hsn_code(value):
    """Reject anything that is not a 4-, 6- or 8-digit HSN code."""
    value = (value or '').strip()
    if not value:
        return
    if not _HSN_RE.match(value):
        raise ValidationError(
            'HSN code must be 4, 6 or 8 digits (e.g. 0910, 091091 or 09109100).'
        )


# The date the rates below were published from. Shown in the admin panel next to
# every suggested rate so nobody reads a cached number as today's law.
RATES_AS_OF = '2025-09-22'
RATES_SOURCE = 'Notification 9/2025-Central Tax (Rate), effective 22 Sep 2025'

# Chapter-level grouping, only for how the picker is ordered/labelled in the UI.
CHAPTERS = {
    '09': 'Chapter 9 — Coffee, tea, mate and spices',
    '19': 'Chapter 19 — Preparations of cereals, flour, starch',
    '21': 'Chapter 21 — Miscellaneous edible preparations',
}

# Curated codes for THIS catalogue. Deliberately short: an admin scrolling 1,200
# tariff lines picks the wrong one. `keywords` drives the suggestion helper below
# and the admin panel's search box.
HSN_REFERENCE = [
    # --- 0904: pepper, chilli (genus Capsicum) ---
    {
        'code': '09042211',
        'description': 'Chilli powder (capsicum, crushed or ground)',
        'gst_rate': Decimal('5'),
        'keywords': ['mirchi', 'mirch', 'chilli', 'chili', 'chilly', 'teja',
                     'patna', 'kashmiri', 'kashmari', 'desi tadaka', 'desi tadka'],
        'note': 'Red chilli powder of any variety. Whole dried chilli (not ground) is 09042110.',
    },
    {
        'code': '09042110',
        'description': 'Dried chilli, whole (neither crushed nor ground)',
        'gst_rate': Decimal('5'),
        'keywords': ['whole chilli', 'sabut mirchi', 'dried chilli'],
        'note': '',
    },
    {
        'code': '09041200',
        'description': 'Pepper, crushed or ground (black pepper powder)',
        'gst_rate': Decimal('5'),
        'keywords': ['kali mirch', 'black pepper', 'pepper powder'],
        'note': '',
    },

    # --- 0909: seed spices ---
    {
        'code': '09092200',
        'description': 'Coriander, crushed or ground (dhaniya powder)',
        'gst_rate': Decimal('5'),
        'keywords': ['dhaniya', 'dhania', 'coriander'],
        'note': 'Whole coriander seed is 09092190.',
    },
    {
        'code': '09092190',
        'description': 'Coriander seeds, whole',
        'gst_rate': Decimal('5'),
        'keywords': ['coriander seed', 'sabut dhaniya'],
        'note': '',
    },
    {
        'code': '09093200',
        'description': 'Cumin, crushed or ground (jeera powder)',
        'gst_rate': Decimal('5'),
        'keywords': ['jeera powder', 'cumin powder'],
        'note': 'Whole cumin seed is 09093129.',
    },
    {
        'code': '09093129',
        'description': 'Cumin seeds, whole (other than black cumin)',
        'gst_rate': Decimal('5'),
        'keywords': ['jeera', 'cumin', 'sabut jeera'],
        'note': '',
    },

    # --- 0910: ginger, turmeric, other spices, and SPICE MIXTURES ---
    {
        'code': '09103030',
        'description': 'Turmeric powder (haldi)',
        'gst_rate': Decimal('5'),
        'keywords': ['haldi', 'turmeric', 'curcuma'],
        'note': 'Dried whole turmeric is 09103020. FRESH turmeric is 09103010 and NIL-rated.',
    },
    {
        'code': '09101210',
        'description': 'Ginger powder (dry ginger / sonth)',
        'gst_rate': Decimal('5'),
        'keywords': ['ginger', 'sonth', 'saunth', 'adrak'],
        'note': 'Dried whole ginger is 09101120. FRESH ginger is 09101110 and NIL-rated.',
    },
    {
        'code': '09109924',
        'description': 'Fenugreek powder / dried fenugreek leaves (kasuri methi)',
        'gst_rate': Decimal('5'),
        'keywords': ['methi', 'kasuri', 'kasoori', 'fenugreek'],
        'note': 'Fenugreek SEEDS are 09109912.',
    },
    {
        'code': '09109912',
        'description': 'Fenugreek seeds (methi dana)',
        'gst_rate': Decimal('5'),
        'keywords': ['methi dana', 'fenugreek seed'],
        'note': '',
    },
    {
        'code': '09109100',
        'description': 'Mixtures of spices (masala blends — spices only)',
        'gst_rate': Decimal('5'),
        'keywords': ['masala', 'garam', 'chat', 'chaat', 'pav bhaji', 'sambhar',
                     'chana', 'kitchen king', 'kichan king', 'jeeravan', 'garadu',
                     'achar', 'tea masala', 'chai masala', 'blend', 'mixture'],
        'note': ('Chapter 9 Note 1(b) mixtures — blends of two or more spices and '
                 'NOTHING ELSE. If the blend contains salt, sugar, starch, oil or '
                 'dried vegetable, the department will usually push it to 21039040 '
                 'at 18%. Check the ingredient list before choosing this.'),
    },
    {
        'code': '09109990',
        'description': 'Other spices, not elsewhere specified',
        'gst_rate': Decimal('5'),
        'keywords': ['amchur', 'amchoor', 'dry mango', 'other spice'],
        'note': ('Commonly used for amchur (dried mango powder). Some traders '
                 'instead classify amchur as a dried-fruit powder (11063030 / '
                 '08045090) — both are 5%, so the rate does not change, but pick '
                 'one and stay consistent across returns.'),
    },

    # --- 1905: papad ---
    {
        'code': '19059040',
        'description': 'Papad (un-fried), including papad katran',
        'gst_rate': Decimal('0'),
        'keywords': ['papad', 'appalam', 'katran', 'khatran'],
        'note': ('NIL-rated, branded or not — settled by AAAR for papad of any '
                 'shape or size. Does NOT cover fryums / extruded kachri papad, '
                 'which are taxable. Papad MASALA is a spice blend, not papad — '
                 'code it under 09109100 or 21039040.'),
    },

    # --- 2103: prepared condiments / seasonings ---
    {
        'code': '21039040',
        'description': 'Mixed condiments and mixed seasonings (masala with salt etc.)',
        'gst_rate': Decimal('18'),
        'keywords': ['condiment', 'seasoning', 'sprinkler', 'ready masala'],
        'note': ('Rose from 12% to 18% on 22 Sep 2025. This is where a masala '
                 'blend lands once it contains a material non-spice ingredient. '
                 'The 5% vs 18% call between this and 09109100 is the single '
                 'biggest tax decision in this catalogue — confirm it with a CA.'),
    },
    {
        'code': '21039010',
        'description': 'Curry paste',
        'gst_rate': Decimal('18'),
        'keywords': ['curry paste', 'paste'],
        'note': '',
    },
]

# code -> row, for O(1) lookups.
HSN_BY_CODE = {row['code']: row for row in HSN_REFERENCE}


def describe(code):
    """Reference row for `code`, or None if it is not one of ours.

    Falls back to a prefix match so a product stored at 4 or 6 digits ('0910')
    still resolves to the nearest curated row for display purposes.
    """
    code = (code or '').strip()
    if not code:
        return None
    if code in HSN_BY_CODE:
        return HSN_BY_CODE[code]
    return next((row for row in HSN_REFERENCE if row['code'].startswith(code)), None)


def suggest(name, ingredients=''):
    """Best-guess HSN code for a product from its name — a HINT, never a default.

    Used by the `suggest_hsn_codes` management command to produce a starting
    spreadsheet. It is intentionally not wired into save(): a guess written
    silently onto a tax field is worse than a blank one, because a blank is
    visibly missing and a wrong code is not.

    Returns (code, confidence) where confidence is 'high' | 'low' | None.
    """
    text = f"{name or ''} {ingredients or ''}".lower()

    # 1. Papad. Tested first, but only when the name does NOT also say "masala":
    #    "chana papad masala" is a spice blend sold to season papad, not papad,
    #    and coding it NIL would under-declare tax on a taxable good.
    if 'masala' not in text and any(k in text for k in ('papad', 'katran', 'appalam')):
        return '19059040', 'high'

    # 2. Blends, BEFORE single spices — deliberately. "Hari mirchi achar masala"
    #    contains "mirchi", but it is a masala, not chilli powder; letting the
    #    single-spice test run first would code it 09042211 and look right.
    #    Confidence is 'low' on purpose: 09109100 (5%) vs 21039040 (18%) turns on
    #    the ingredient list, which a name cannot settle. A human must confirm.
    blends = HSN_BY_CODE['09109100']
    if any(k in text for k in blends['keywords']) or 'blend' in text:
        return '09109100', 'low'

    # 3. Single spices.
    singles = ('09042211', '09092200', '09103030', '09101210', '09109924',
               '09109990', '09093200')
    for code in singles:
        if any(k in text for k in HSN_BY_CODE[code]['keywords']):
            return code, 'high'

    return None, None
