"""Place of supply resolution and the CGST/SGST vs IGST split.

Under GST every supply is either **intra-state** (the place of supply is the
seller's own state → the tax splits equally into CGST + SGST) or **inter-state**
(→ the same tax is charged wholly as IGST). The *amount* is identical either
way, which is why getting this wrong never under-collects — but the two heads
credit different governments, and GSTR-1 Table 7 (B2C others) is reported *by*
place of supply, so a bill that can't name one can't be filed correctly.

For B2C goods the place of supply is the delivery address (CGST Act s.10(1)(a)).
This module turns the address a customer typed into a two-digit GST state code.

Resolution is by STATE NAME only, deliberately:

* Checkout already asks for state as its own required field, so the name is
  present for every new order and the alias table below absorbs the realistic
  variations ("M.P.", "Madhya Pradesh", "मध्य प्रदेश").
* A PIN-code lookup was considered and rejected. India's 3-digit prefixes split
  across state lines in enough places (Uttarakhand inside UP's block, Jharkhand
  inside Bihar's, Chandigarh inside Punjab's) that a compact table produces
  *confidently wrong* tax heads, which is worse than a declared fallback.

When nothing resolves we fall back to the seller's own state — the historical
behaviour, and the safe one for a store whose orders are mostly local. Such an
order is billed intra-state; an admin can correct it on the order before the
return is filed.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

PAISA = Decimal('0.01')

# ---- GST state codes (as published in the GST state code list) ----
STATE_NAMES = {
    '01': 'Jammu and Kashmir',
    '02': 'Himachal Pradesh',
    '03': 'Punjab',
    '04': 'Chandigarh',
    '05': 'Uttarakhand',
    '06': 'Haryana',
    '07': 'Delhi',
    '08': 'Rajasthan',
    '09': 'Uttar Pradesh',
    '10': 'Bihar',
    '11': 'Sikkim',
    '12': 'Arunachal Pradesh',
    '13': 'Nagaland',
    '14': 'Manipur',
    '15': 'Mizoram',
    '16': 'Tripura',
    '17': 'Meghalaya',
    '18': 'Assam',
    '19': 'West Bengal',
    '20': 'Jharkhand',
    '21': 'Odisha',
    '22': 'Chhattisgarh',
    '23': 'Madhya Pradesh',
    '24': 'Gujarat',
    '26': 'Dadra and Nagar Haveli and Daman and Diu',
    '27': 'Maharashtra',
    '29': 'Karnataka',
    '30': 'Goa',
    '31': 'Lakshadweep',
    '32': 'Kerala',
    '33': 'Tamil Nadu',
    '34': 'Puducherry',
    '35': 'Andaman and Nicobar Islands',
    '36': 'Telangana',
    '37': 'Andhra Pradesh',
    '38': 'Ladakh',
    '97': 'Other Territory',
}

# Full names / unambiguous long forms. These are safe to scan for inside a
# free-text address blob because they can't collide with an ordinary word.
_LONG_ALIASES = {
    '01': ['jammu and kashmir', 'jammu kashmir', 'jammu', 'जम्मू और कश्मीर', 'जम्मू कश्मीर'],
    '02': ['himachal pradesh', 'himachal', 'हिमाचल प्रदेश', 'हिमाचल'],
    '03': ['punjab', 'पंजाब'],
    '04': ['chandigarh', 'चंडीगढ़'],
    '05': ['uttarakhand', 'uttaranchal', 'उत्तराखंड'],
    '06': ['haryana', 'हरियाणा'],
    '07': ['delhi', 'new delhi', 'nct of delhi', 'दिल्ली', 'नई दिल्ली'],
    '08': ['rajasthan', 'राजस्थान'],
    '09': ['uttar pradesh', 'उत्तर प्रदेश'],
    '10': ['bihar', 'बिहार'],
    '11': ['sikkim', 'सिक्किम'],
    '12': ['arunachal pradesh', 'arunachal', 'अरुणाचल प्रदेश'],
    '13': ['nagaland', 'नागालैंड'],
    '14': ['manipur', 'मणिपुर'],
    '15': ['mizoram', 'मिजोरम'],
    '16': ['tripura', 'त्रिपुरा'],
    '17': ['meghalaya', 'मेघालय'],
    '18': ['assam', 'असम'],
    '19': ['west bengal', 'westbengal', 'पश्चिम बंगाल'],
    '20': ['jharkhand', 'झारखंड'],
    '21': ['odisha', 'orissa', 'ओडिशा', 'उड़ीसा'],
    '22': ['chhattisgarh', 'chattisgarh', 'छत्तीसगढ़'],
    '23': ['madhya pradesh', 'madhyapradesh', 'madya pradesh', 'मध्य प्रदेश'],
    '24': ['gujarat', 'गुजरात'],
    '26': ['dadra and nagar haveli and daman and diu', 'dadra and nagar haveli',
           'daman and diu', 'dadra nagar haveli', 'daman', 'diu'],
    '27': ['maharashtra', 'maharastra', 'महाराष्ट्र'],
    '29': ['karnataka', 'कर्नाटक'],
    '30': ['goa', 'गोवा'],
    '31': ['lakshadweep', 'लक्षद्वीप'],
    '32': ['kerala', 'केरल'],
    '33': ['tamil nadu', 'tamilnadu', 'तमिलनाडु', 'तमिल नाडु'],
    '34': ['puducherry', 'pondicherry', 'पुदुचेरी'],
    '35': ['andaman and nicobar islands', 'andaman and nicobar', 'andaman',
           'nicobar', 'अंडमान और निकोबार'],
    '36': ['telangana', 'telengana', 'तेलंगाना'],
    '37': ['andhra pradesh', 'andhrapradesh', 'आंध्र प्रदेश'],
    '38': ['ladakh', 'लद्दाख'],
    '97': ['other territory'],
}

# Short abbreviations. Accepted ONLY when the customer typed them into the
# dedicated `state` field — never scanned for inside a free-text address, where
# "up", "ap" and "wb" collide with ordinary words and house numbers.
_SHORT_ALIASES = {
    'jk': '01', 'hp': '02', 'pb': '03', 'ch': '04', 'uk': '05', 'ua': '05',
    'hr': '06', 'dl': '07', 'nct': '07', 'rj': '08', 'up': '09', 'br': '10',
    'sk': '11', 'ar': '12', 'nl': '13', 'mn': '14', 'mz': '15', 'tr': '16',
    'ml': '17', 'as': '18', 'wb': '19', 'jh': '20', 'or': '21', 'od': '21',
    'cg': '22', 'ct': '22', 'mp': '23', 'gj': '24', 'dn': '26', 'dd': '26',
    'mh': '27', 'ka': '29', 'ga': '30', 'ld': '31', 'kl': '32', 'tn': '33',
    'py': '34', 'an': '35', 'ts': '36', 'tg': '36', 'ap': '37', 'la': '38',
}


def _normalize(text):
    """Lower-case, de-punctuate and collapse whitespace for alias matching.

    "M.P." and "Madhya  Pradesh," both have to land on something the tables
    below can key on, and "&" is written both ways in "Dadra & Nagar Haveli".
    """
    text = (text or '').strip().lower()
    text = text.replace('&', ' and ')
    text = re.sub(r'[^\w\sऀ-ॿ]+', ' ', text, flags=re.UNICODE)
    text = re.sub(r'\b(the\s+)?state\s+of\b', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


# alias -> code, longest first so "andhra pradesh" wins over a shorter prefix.
_ALIAS_TO_CODE = {}
for _code, _aliases in _LONG_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_CODE[_normalize(_alias)] = _code
_SORTED_ALIASES = sorted(_ALIAS_TO_CODE, key=len, reverse=True)


def seller_state_code():
    """The seller's own GST state code — the intra-state pivot.

    Read through settings on every call rather than bound at import so a
    deployment that changes SELLER_STATE_CODE doesn't need a code change.
    """
    return str(getattr(settings, 'SELLER_STATE_CODE', '23') or '23').zfill(2)


def state_name(code):
    """Human name for a GST state code, or a readable placeholder."""
    code = (code or '').strip().zfill(2) if code else ''
    return STATE_NAMES.get(code, '')


def resolve_state_code(state=None, address=None):
    """GST state code for a delivery address, or None if nothing matched.

    `state` is the dedicated checkout field and is tried first, both as a full
    name and as an abbreviation. `address` is the free-text blob and is only
    *scanned* for full state names — see the module docstring for why
    abbreviations are excluded there.

    Returns None rather than a default so the caller decides what an
    unresolvable address means; `place_of_supply_for` applies the fallback.
    """
    normalized = _normalize(state)
    if normalized:
        if normalized in _ALIAS_TO_CODE:
            return _ALIAS_TO_CODE[normalized]
        compact = normalized.replace(' ', '')
        if compact in _SHORT_ALIASES:
            return _SHORT_ALIASES[compact]
        # A state field holding "Indore, Madhya Pradesh" is common enough
        # (autofill, geocoders) to be worth scanning rather than rejecting.
        found = _scan(normalized)
        if found:
            return found

    return _scan(_normalize(address))


def _scan(text):
    """Find the last full state name mentioned in `text`.

    LAST, not first: an Indian address runs narrow-to-wide ("12 Goa Road,
    Indore, Madhya Pradesh"), so when a street name collides with a state name
    the real state is the one further right.
    """
    if not text:
        return None
    best = None
    for alias in _SORTED_ALIASES:
        for match in re.finditer(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', text):
            # Prefer the right-most match; on a tie the longer alias wins
            # because _SORTED_ALIASES is longest-first and > is strict.
            if best is None or match.start() > best[0]:
                best = (match.start(), _ALIAS_TO_CODE[alias])
    return best[1] if best else None


def place_of_supply_for(state=None, address=None):
    """Resolve a place of supply, falling back to the seller's own state.

    The fallback is the whole point of the "default to Madhya Pradesh" rule:
    an order we cannot geographically place is billed the way every order was
    billed before this existed, so nothing regresses and no bill is left
    without a place of supply.
    """
    return resolve_state_code(state=state, address=address) or seller_state_code()


def is_interstate(place_of_supply_code):
    """True when this supply attracts IGST instead of CGST + SGST.

    A blank code means a historical order placed before place of supply was
    captured. Those were billed, and filed, as intra-state — so they must keep
    rendering that way or a reprinted bill would contradict a filed return.
    """
    if not place_of_supply_code:
        return False
    return str(place_of_supply_code).zfill(2) != seller_state_code()


def split_gst(tax_amount, place_of_supply_code):
    """Split a GST amount into its heads for the given place of supply.

    Returns ``{'cgst', 'sgst', 'igst'}`` as Decimals; the unused heads are 0.00
    and the three always sum back to `tax_amount` exactly — the odd paisa of an
    intra-state split goes to SGST, so the parts can never fail to reconcile
    against the total printed on the bill.
    """
    tax = Decimal(str(tax_amount or 0)).quantize(PAISA, rounding=ROUND_HALF_UP)
    zero = Decimal('0.00')
    if tax <= 0:
        return {'cgst': zero, 'sgst': zero, 'igst': zero}
    if is_interstate(place_of_supply_code):
        return {'cgst': zero, 'sgst': zero, 'igst': tax}
    cgst = (tax / 2).quantize(PAISA, rounding=ROUND_HALF_UP)
    return {'cgst': cgst, 'sgst': tax - cgst, 'igst': zero}


def head_rate_label(rate, place_of_supply_code):
    """How a slab's rate reads once split into heads.

    A 5% supply is "5%" of IGST inter-state but "2.5% + 2.5%" of CGST/SGST
    intra-state, and an invoice that prints a bare "5%" next to two 2.5%
    columns invites the reader to add them to 10%.
    """
    if rate is None:
        return ''
    rate = Decimal(str(rate))
    # An exempt slab has nothing to split; "0% + 0%" is just noise on a bill.
    if rate <= 0 or is_interstate(place_of_supply_code):
        return f"{rate:g}%"
    half = rate / 2
    return f"{half:g}% + {half:g}%"
