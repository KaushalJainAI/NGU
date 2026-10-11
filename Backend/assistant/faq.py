"""File-backed FAQ + retrieval for the assistant.

The questions a shop gets asked every day (delivery time, COD, returns ...)
have fixed answers. They live in ``faq_data.json`` next to this module — a
plain file the owner can read and edit — and this module finds the entry that
matches a customer's wording. No LLM and no network: matching is fuzzy string
comparison (rapidfuzz), so a lookup costs no tokens.

Two callers, two levels of confidence:

- ``search()``  — the ``search_faq`` read tool. Returns the few best
  candidates above a LOW floor; the model reads them as DATA and decides
  whether one actually answers the question.
- ``direct_answer()`` — an answer safe to give WORD FOR WORD with no model
  call. Needs a HIGH score, a clear lead over the next entry, an entry marked
  ``direct`` and no open ``review`` note. When in doubt it returns None and
  the question goes to the model as usual.

Numbers that live in configuration (free-delivery threshold, delivery fee, COD
limit, support phone) are never typed into the file: answers carry
``{placeholders}`` filled from ``spices_backend.limits`` / settings at load, so
the FAQ cannot drift from what checkout charges.
"""

import json
import logging
import unicodedata
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

FAQ_PATH = Path(__file__).with_name('faq_data.json')

# Score scale is 0-100 (see _score).
SEARCH_FLOOR = 62        # below this a candidate is noise, not worth the tokens
DIRECT_THRESHOLD = 88    # word-for-word answers need a near-exact match ...
DIRECT_MARGIN = 8        # ... that clearly beats the runner-up entry ...
DIRECT_MIN_TOKENS = 2    # ... on a question with some substance ("delivery" alone is ambiguous)
MAX_QUERY_LEN = 300

DEFAULT_LANGUAGE = 'en'

# Words that carry no topic. Dropped from both sides before comparing, so
# "delivery charge kitna hai" and "what is the delivery charge" meet on
# "delivery charge". Question words that DO carry the topic (where / kahan,
# when / kab, why / kyu) are deliberately kept.
_STOPWORDS = frozenset("""
a an the is are am was do does did can could will would should may be been to of for in on at it its
this that these those i me my we our you your and or if so please tell about what how which
kya hai hain h ho hoga hogi hota hoti hote ka ki ke ko me mein se par pe aap aapka aapki aapke
mujhe mera meri mere hum hume hamara kaise kitna kitne kitni kar kare karna karni karte sakta
sakti sakte hu hun bhi toh to na ji wala wali
क्या है हैं हो होगा होगी होता होती का की के को में से पर आप आपका आपकी मुझे मेरा मेरी हम
कैसे कितना कितने कितनी कर करें करना सकते सकता सकती भी तो जी
""".split())


def _normalise(text):
    """Lowercase, strip punctuation/symbols, drop stopwords -> list of tokens.

    Punctuation is removed by Unicode category, NOT with ``\\w``: Devanagari
    vowel signs are combining marks, which ``\\w`` does not match, so a regex
    would cut every Hindi word in pieces.
    """
    if not isinstance(text, str):
        return []
    text = unicodedata.normalize('NFKC', text)[:MAX_QUERY_LEN].lower()
    cleaned = ''.join(
        ' ' if unicodedata.category(ch)[0] in ('P', 'S', 'Z', 'C') else ch
        for ch in text
    )
    return [tok for tok in cleaned.split() if tok not in _STOPWORDS]


def _score(query_tokens, variant_tokens):
    """0-100 similarity of two token lists.

    token_set_ratio alone is too generous (a one-word query that is a subset of
    a question scores 100); token_sort_ratio alone is too strict about extra
    words. The average rewards shared topic words and still penalises a query
    that covers only part of the question.
    """
    if not query_tokens or not variant_tokens:
        return 0.0
    q = ' '.join(query_tokens)
    v = ' '.join(variant_tokens)
    return (fuzz.token_set_ratio(q, v) + fuzz.token_sort_ratio(q, v)) / 2


def _money(value):
    """Decimal -> display text: 499 -> '499', 69.620 -> '69.62', 5000 -> '5,000'."""
    value = Decimal(value)
    if value == value.to_integral_value():
        return f'{int(value):,}'
    return f'{value.quantize(Decimal("0.01")):,}'


def _facts():
    """Live values for the {placeholders} in answers."""
    from django.conf import settings
    from spices_backend.limits import (
        SHIPPING_CHARGE_NET, SHIPPING_TAX_RATE, FREE_SHIPPING_THRESHOLD,
        COD_MAX_VALUE, COD_MAX_OPEN,
    )
    fee_total = SHIPPING_CHARGE_NET * (1 + SHIPPING_TAX_RATE / 100)
    return {
        'free_above': _money(FREE_SHIPPING_THRESHOLD),
        'delivery_fee': _money(fee_total),
        'fee_net': _money(SHIPPING_CHARGE_NET),
        'tax_rate': _money(SHIPPING_TAX_RATE),
        'cod_max': _money(COD_MAX_VALUE),
        'cod_open': str(COD_MAX_OPEN),
        'phone': getattr(settings, 'SELLER_PHONE', ''),
        'email': getattr(settings, 'SELLER_EMAIL', ''),
    }


class FAQEntry:
    """One question the shop gets asked, with its answers."""

    __slots__ = ('id', 'topic', 'questions', 'variants', 'answers', 'route',
                 'direct', 'review')

    def __init__(self, raw, facts):
        self.id = raw['id']
        self.topic = raw.get('topic', '')
        self.questions = list(raw['questions'])
        self.variants = [toks for toks in map(_normalise, self.questions) if toks]
        self.answers = {
            lang: text.format_map(facts) for lang, text in raw['answer'].items()
        }
        self.route = raw.get('route') or None
        self.review = raw.get('review') or ''
        # An entry the owner still has to confirm is never served word for word.
        self.direct = bool(raw.get('direct')) and not self.review

    def answer(self, language=None):
        """The answer in `language`, or English when that language was not written."""
        code = (language or DEFAULT_LANGUAGE).strip().lower()
        return self.answers.get(code) or self.answers[DEFAULT_LANGUAGE]

    def score(self, query_tokens):
        return max((_score(query_tokens, v) for v in self.variants), default=0.0)


@lru_cache(maxsize=1)
def load():
    """All FAQ entries, parsed once per process. A broken file must not take
    the assistant down: it logs and yields no entries (the model then answers
    from its other tools, as it did before this module existed)."""
    try:
        raw = json.loads(FAQ_PATH.read_text(encoding='utf-8'))
        facts = _facts()
        entries = tuple(FAQEntry(item, facts) for item in raw['entries'])
        ids = [e.id for e in entries]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate FAQ id')
        return entries
    except Exception:
        logger.exception('FAQ file %s could not be loaded; FAQ disabled.', FAQ_PATH)
        return ()


def _ranked(query):
    tokens = _normalise(query)
    if not tokens:
        return tokens, []
    scored = [(entry.score(tokens), entry) for entry in load()]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return tokens, scored


def search(query, limit=3):
    """Best-matching entries above SEARCH_FLOOR as [(entry, score)], best first."""
    _, scored = _ranked(query)
    return [(entry, round(score, 1)) for score, entry in scored[:max(1, limit)]
            if score >= SEARCH_FLOOR]


def direct_answer(query, language=None):
    """An answer that may be given with NO model call, or None.

    Returns {'id', 'answer', 'route', 'score'} only when the match is
    unambiguous; see the module docstring for the conditions.
    """
    tokens, scored = _ranked(query)
    if len(tokens) < DIRECT_MIN_TOKENS or not scored:
        return None
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if (best_score < DIRECT_THRESHOLD or best_score - runner_up < DIRECT_MARGIN
            or not best.direct):
        return None
    # Never hand a customer an answer in a language they did not ask for: an
    # entry that lacks their language goes to the model, which can write it.
    if (language or DEFAULT_LANGUAGE).strip().lower() not in best.answers:
        return None
    return {'id': best.id, 'answer': best.answer(language), 'route': best.route,
            'score': round(best_score, 1)}
