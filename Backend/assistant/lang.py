"""Which language is the customer using?

The storefront sends the language the customer picked ('en', 'hi', 'hinglish',
'gu', 'mr', 'pa') or 'auto'. Two places need a definite answer even for 'auto':
the canned replies (failure messages, FAQ answers) have no model to write them
in the customer's language, so we choose the language ourselves.

Detection is by script, which is reliable and free: Devanagari -> Hindi,
Gujarati script -> Gujarati, Gurmukhi -> Punjabi. Latin text is English unless
it contains common Hindi words in Roman letters, which makes it Hinglish.
Devanagari is shared by Hindi and Marathi and cannot be told apart this way;
a customer who picked Marathi explicitly keeps it.
"""

import re

SUPPORTED = ('en', 'hi', 'hinglish', 'gu', 'mr', 'pa')

# (first, last) code points of each script block.
_SCRIPTS = (
    ('hi', 0x0900, 0x097F),   # Devanagari
    ('gu', 0x0A80, 0x0AFF),   # Gujarati
    ('pa', 0x0A00, 0x0A7F),   # Gurmukhi
)

# Hindi words that are not English words, so two of them in a Latin-script
# message make it Hinglish. Deliberately leaves out words that are also English
# ("hi", "me", "to", "do", "main", "he", "per", "pan", "the").
_HINGLISH_WORDS = frozenset("""
kya hai hain kitna kitne kitni kaise kab kahan kyun kyu kaun nahi nahin haan
mujhe mera meri mere hum hume hamara aap aapka aapki aapke tum tumhara
chahiye chahie karna karo kare karein kar sakta sakte sakti milega milegi milta
milti hoga hogi hota hoti ho gaya gayi aaya aayi aaye bhej bhejo dena dijiye
dikhao bataiye batao batayein ka ki ke ko se mein par aur ya lekin toh bhi
abhi jaldi pehle baad kuch sab bahut thoda zyada kam accha achha theek thik
wapas paisa rupaye
""".split())


def detect(text):
    """'hi' / 'gu' / 'pa' by script, 'hinglish' by Roman Hindi words, else 'en'."""
    if not isinstance(text, str):
        return 'en'
    counts = {code: 0 for code, _, _ in _SCRIPTS}
    for ch in text:
        point = ord(ch)
        for code, low, high in _SCRIPTS:
            if low <= point <= high:
                counts[code] += 1
                break
    best = max(counts, key=counts.get)
    if counts[best] > 0:
        return best
    words = [w.strip('.,?!;:"\'()').lower() for w in text.split()]
    if sum(1 for w in words if w in _HINGLISH_WORDS) >= 2:
        return 'hinglish'
    return 'en'


def resolve(code, message=''):
    """The customer's explicit choice if there is one, else the message's language.

    An explicit in-chat language request ("reply in English only",
    "English me baat karo") always wins over the dropdown setting, so a
    customer who cannot read the current language is never trapped."""
    override = detect_override(message)
    if override:
        return override
    code = (code or '').strip().lower()
    if code in SUPPORTED:
        return code
    return detect(message)


# Explicit language requests inside the chat override the dropdown. A language
# name alone ("English masala") is not a request — it needs a request verb.
_OVERRIDE_LANGUAGES = (
    ('en', ('english', 'angrezi', 'angreji')),
    ('hi', ('hindi', 'devanagari')),
    ('hinglish', ('hinglish', 'hinglis', 'roman hindi')),
    ('gu', ('gujarati', 'gujrati', 'gujrati')),
    ('mr', ('marathi',)),
    ('pa', ('punjabi', 'panjabi')),
)
_OVERRIDE_REQUEST = re.compile(
    r'reply|speak|talk|answer|respond|switch|change|likho|batao|baat karo|me baat|me jawab|me bolo|me likho',
    re.IGNORECASE,
)


def detect_override(text):
    """A language code the customer explicitly asked for, or None."""
    if not isinstance(text, str) or not text:
        return None
    if not _OVERRIDE_REQUEST.search(text):
        return None
    lowered = text.lower()
    for code, names in _OVERRIDE_LANGUAGES:
        if any(name in lowered for name in names):
            return code
    return None
