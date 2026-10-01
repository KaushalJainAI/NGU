import logging
import re
from typing import Any, Dict, List, Optional, Union

from django.utils import timezone
from rapidfuzz import process, fuzz
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain.chat_models import init_chat_model
from asgiref.sync import sync_to_async
from dotenv import load_dotenv
import os

from .models import ProductSearchKB, ProductComboSearchKB, Product, Category, ProductCombo
from .serializers import SearchProductSerializer, SearchComboSerializer
from .cache import (
    get_cached_or_set,
    get_search_corpus_key,
    TTL_LONG,
)

load_dotenv()
api_key = os.getenv('LLM_API_KEY')
provider = os.getenv('MODEL_PROVIDER')
llm_model = os.getenv('LLM_MODEL')
logger = logging.getLogger(__name__)


# ============== SEARCH CORPUS ==============

SEARCH_CORPUS_KEY = get_search_corpus_key()

# How strongly each corpus entry kind counts toward the final score.
KIND_WEIGHTS = {'name': 1.0, 'token': 0.95, 'category': 0.9, 'synonym': 0.85}


def _weight_token(obj) -> Optional[str]:
    """'500g' style token from a product/combo's weight + unit, if both set."""
    weight = getattr(obj, 'weight', None)
    unit = getattr(obj, 'unit', None)
    if weight and unit:
        return f"{format(weight, 'g')}{unit}"
    return None


def _name_tokens(name: str) -> List[str]:
    """Word tokens worth matching on their own. Weight/number tokens ('500g',
    '100') are excluded — token_set_ratio scores any shared token at 100, so
    they would make every same-weight product match every weight query."""
    return [
        t for t in re.split(r'[^a-z0-9]+', name.lower())
        if len(t) >= 3 and not re.fullmatch(r'\d+[a-z]{0,2}', t)
    ]


def build_search_corpus() -> List[Dict[str, Any]]:
    """One DB pass producing every matchable text for products and combos.

    Names, slugs, name tokens and categories are always included, so search
    keeps working even when a KB row is missing or LLM generation failed.
    Out-of-stock products stay in the corpus on purpose: stock is re-filtered
    when results are fetched, so stock changes don't invalidate this cache.
    """
    entries: List[Dict[str, Any]] = []
    seen = set()

    def add(text: Optional[str], obj_id: int, obj_type: str, kind: str):
        text = (text or '').strip().lower()
        text = re.sub(r'\s+', ' ', text)
        if len(text) < 2:
            return
        key = (text, obj_id, obj_type)
        if key in seen:
            return
        seen.add(key)
        entries.append({'text': text, 'id': obj_id, 'type': obj_type, 'kind': kind})

    products = Product.objects.filter(is_active=True).select_related('category')
    product_kbs = {
        kb.product_id: kb
        for kb in ProductSearchKB.objects.filter(product__is_active=True)
    }
    for product in products:
        add(product.name, product.id, 'product', 'name')
        add(product.slug.replace('-', ' '), product.id, 'product', 'name')
        for token in _name_tokens(product.name):
            add(token, product.id, 'product', 'token')
        wt = _weight_token(product)
        if wt:
            add(f"{product.name} {wt}", product.id, 'product', 'token')
        if product.category_id:
            add(product.category.name, product.id, 'product', 'category')
        kb = product_kbs.get(product.id)
        if kb:
            for syn in kb.get_synonyms_list():
                add(syn, product.id, 'product', 'synonym')

    combos = ProductCombo.objects.filter(is_active=True).prefetch_related('products')
    combo_kbs = {
        kb.combo_id: kb
        for kb in ProductComboSearchKB.objects.filter(combo__is_active=True)
    }
    for combo in combos:
        add(combo.name, combo.id, 'combo', 'name')
        add(combo.slug.replace('-', ' '), combo.id, 'combo', 'name')
        for token in _name_tokens(combo.name):
            add(token, combo.id, 'combo', 'token')
        for member in combo.products.all()[:5]:
            add(member.name, combo.id, 'combo', 'token')
        kb = combo_kbs.get(combo.id)
        if kb:
            for syn in kb.get_synonyms_list():
                add(syn, combo.id, 'combo', 'synonym')

    return entries


def get_search_corpus() -> List[Dict[str, Any]]:
    return get_cached_or_set(SEARCH_CORPUS_KEY, build_search_corpus, TTL_LONG)


def _score_matches(query: str, entries: List[Dict], threshold: int) -> Dict[int, float]:
    """Score corpus entries against a query. Returns {object_id: score (<=100)}."""
    if not entries:
        return {}
    query = re.sub(r'\s+', ' ', query.strip().lower())
    if not query:
        return {}

    scored: Dict[int, float] = {}

    def record(entry: Dict, base: float):
        text = entry['text']
        final = base * KIND_WEIGHTS.get(entry['kind'], 0.85)
        # No bonuses for bare token entries: a shared brand/word token would
        # otherwise cap at 100 and erase the kind weighting that ranks the
        # actually-named product first.
        if entry['kind'] != 'token':
            if fuzz.ratio(query, text) > 95:
                final += 30
            elif len(query) >= 4 and (text.startswith(query) or fuzz.partial_ratio(query, text) > 90):
                final += 15
        final = min(final, 100)
        if final >= threshold:
            oid = entry['id']
            scored[oid] = max(scored.get(oid, 0), final)

    if len(query) <= 3:
        # token_set_ratio on 2-3 char queries matches half the catalog;
        # require a prefix or near-exact match instead.
        effective = max(threshold, 85)
        for entry in entries:
            text = entry['text']
            if text.startswith(query):
                base = 90.0
            else:
                base = fuzz.ratio(query, text)
                if base < 90:
                    continue
            final = min(base * KIND_WEIGHTS.get(entry['kind'], 0.85), 100)
            if final >= effective:
                oid = entry['id']
                scored[oid] = max(scored.get(oid, 0), final)
        return scored

    texts = [e['text'] for e in entries]
    bases: Dict[int, float] = {}
    for scorer in (fuzz.token_set_ratio, fuzz.WRatio):
        for _, score, idx in process.extract(
            query, texts, scorer=scorer, score_cutoff=threshold, limit=None
        ):
            bases[idx] = max(bases.get(idx, 0), score)
    for idx, base in bases.items():
        record(entries[idx], base)
    return scored


# Preference order when the same object matches through several entry kinds.
KIND_RANK = {'name': 0, 'token': 1, 'category': 2, 'synonym': 3}


def build_suggestions(query: str, limit: int) -> Dict[str, Any]:
    """Tiny autocomplete payload: prefix matches first, fuzzy top-up after."""
    query = re.sub(r'\s+', ' ', query.strip().lower())
    corpus = get_search_corpus()

    candidates: Dict[tuple, tuple] = {}  # (type, id) -> sort key
    for e in corpus:
        if e['text'].startswith(query):
            key = (e['type'], e['id'])
            rank = (KIND_RANK.get(e['kind'], 3), 0)
            if key not in candidates or rank < candidates[key]:
                candidates[key] = rank

    if len(candidates) < limit:
        texts = [e['text'] for e in corpus]
        for _, score, idx in process.extract(
            query, texts, scorer=fuzz.WRatio, score_cutoff=75, limit=30
        ):
            entry = corpus[idx]
            key = (entry['type'], entry['id'])
            if key not in candidates:
                candidates[key] = (4, -score)

    ordered = [key for key, _ in sorted(candidates.items(), key=lambda kv: kv[1])]

    product_ids = [oid for otype, oid in ordered if otype == 'product']
    combo_ids = [oid for otype, oid in ordered if otype == 'combo']
    products = {
        p.id: p for p in Product.objects.filter(
            id__in=product_ids, is_active=True, stock__gt=0
        ).only('id', 'name', 'slug', 'price', 'discount_price', 'image', 'thumbnail')
    } if product_ids else {}
    combos = {
        # NOTE: no 'price' here — ProductCombo has no price COLUMN (its MRP is a
        # @property derived from components); .only('price') raises
        # FieldDoesNotExist the moment a combo matches (AP1/A1).
        c.id: c for c in ProductCombo.objects.filter(
            id__in=combo_ids, is_active=True
        ).only('id', 'name', 'slug', 'discount_price', 'image', 'thumbnail')
    } if combo_ids else {}

    suggestions = []
    for otype, oid in ordered:
        obj = products.get(oid) if otype == 'product' else combos.get(oid)
        if obj is None:
            continue
        img = getattr(obj, 'thumbnail', None) or getattr(obj, 'image', None)
        suggestions.append({
            'id': obj.id,
            'name': obj.name,
            'slug': obj.slug,
            'type': otype,
            'price': float(obj.final_price),
            'image': img.url if img else None,
        })
        if len(suggestions) >= limit:
            break

    return {'query': query, 'suggestions': suggestions}


# ============== SYNONYM GENERATION (KB) ==============

# Standalone generics match too many products to be useful synonyms.
GENERIC_BLOCKLIST = {
    'powder', 'spice', 'spices', 'masala', 'masale', 'organic', 'pack', 'packet',
    'best', 'fresh', 'pure', 'natural', 'premium', 'quality', 'india', 'indian',
    'buy', 'online', 'price', 'cheap', 'original', 'authentic', 'food', 'cooking',
    'whole', 'raw', 'new', 'combo', 'offer', 'sale', 'tasty', 'homemade',
}

COMMON_BOOSTS = {
    'haldi': ['haldi', 'haldee', 'haldhi', 'turmeric', 'tumeric', 'haldi powder',
              'turmeric powder', 'manjal', 'pasupu'],
    'turmeric': ['haldi', 'haldee', 'turmeric', 'tumeric', 'turmeric powder', 'haldi powder'],
    'mirch': ['mirch', 'chilli', 'chili', 'lal mirch', 'mirchi', 'vip mirch', 'red chilli'],
    'chilli': ['mirch', 'chilli powder', 'green chilli', 'lal mirch', 'vip mirch'],
}

SYNONYM_PROMPT = ChatPromptTemplate.from_template("""
Generate 25-35 e-commerce search terms Indian shoppers would type to find this {context_type}: "{name}"

Product details:
{context}

REQUIRED coverage:
- Regional Indian names, Hindi/English (Hinglish) mixes, transliteration variants
- Common misspellings and typos shoppers actually make
- Weight-qualified terms matching the actual pack size (e.g. "{name_lower} 100g")
- Forms (powder/whole/raw) only when they match this product

STRICT RULES:
- NO standalone generic words ("powder", "spice", "masala", "organic", "pack", "best", "fresh")
- NO marketing phrases or full sentences
- NO names of other, unrelated products
- Every term must be something a shopper would type in a search box

Return ONLY valid JSON: {{"synonyms": ["term1", "term2", ...]}} NO EXPLANATIONS
""")


def _clean_synonyms(raw: List, name: str = '', cap: int = 30) -> List[str]:
    """Normalize, validate and dedupe synonym terms (LLM output is untrusted)."""
    cleaned: List[str] = []
    seen = set()
    name_lower = (name or '').strip().lower()
    for item in raw or []:
        if not isinstance(item, str):
            continue
        if '\n' in item:
            continue
        term = re.sub(r'\s+', ' ', item).strip().lower()
        if not 2 <= len(term) <= 60:
            continue
        if term.isdigit():
            continue
        if '{' in term or '}' in term or 'http' in term:
            continue
        if term in GENERIC_BLOCKLIST:
            continue
        if term == name_lower:
            continue  # the name is always in the corpus already
        if term in seen:
            continue
        seen.add(term)
        cleaned.append(term)
        if len(cleaned) >= cap:
            break
    return cleaned


def _deterministic_synonyms(product_or_combo) -> List[str]:
    """LLM-free synonym set derived from the object itself; always merged in
    so a KB row is never empty even when the LLM is down."""
    name = product_or_combo.name
    name_lower = name.lower()
    terms = [name_lower]
    terms += _name_tokens(name)
    slug = getattr(product_or_combo, 'slug', '') or ''
    terms += _name_tokens(slug.replace('-', ' '))
    category = getattr(product_or_combo, 'category', None)
    if category is not None:
        terms.append(category.name.lower())
    if getattr(product_or_combo, 'spice_form', '') == 'powder':
        terms.append(f"{name_lower} powder")
    wt = _weight_token(product_or_combo)
    if wt:
        terms.append(f"{name_lower} {wt}")
    return terms


def _build_kb_context(product_or_combo) -> str:
    """Rich prompt context from the object's actual catalog content."""
    parts = []
    if isinstance(product_or_combo, Product):
        category = getattr(product_or_combo.category, 'name', '')
        parts.append(f"Category: {category}")
        parts.append(f"Form: {product_or_combo.spice_form}")
        wt = _weight_token(product_or_combo)
        if wt:
            parts.append(f"Pack size: {wt}")
        if product_or_combo.ingredients:
            parts.append(f"Ingredients: {product_or_combo.ingredients[:200]}")
        if product_or_combo.description:
            parts.append(f"Description: {product_or_combo.description[:400]}")
    else:
        names = [p.name for p in product_or_combo.products.all()[:5]]
        parts.append(f"Combo containing: {', '.join(names)}")
        if product_or_combo.description:
            parts.append(f"Description: {product_or_combo.description[:400]}")
    return '\n'.join(parts)


class SpiceSearchEngine:
    def __init__(self, model: str = None):
        # Fallbacks to ensure it doesn't crash if env vars are missing
        self.provider = provider or "perplexity"
        self.model_name = model or llm_model or "sonar"

        # Search must keep working without an LLM: a failed init only
        # disables synonym generation, deterministic fallbacks take over.
        self.llm = None
        try:
            if self.provider.lower() == 'openrouter':
                from langchain_openai import ChatOpenAI
                from spices_backend.llm import openrouter_extra_body
                self.llm = ChatOpenAI(
                    model=self.model_name,
                    openai_api_key=api_key,
                    openai_api_base="https://openrouter.ai/api/v1",
                    temperature=0.1,
                    extra_body=openrouter_extra_body(),
                )
            else:
                self.llm = init_chat_model(
                    self.model_name,
                    model_provider=self.provider,
                    temperature=0.1,
                    api_key=api_key
                )
        except Exception as e:
            logger.error(f"LLM init failed ({self.provider}/{self.model_name}): {e}")

        self._product_cache = {}

    # ----- synonym generation -----

    def _finalize_synonyms(self, llm_terms: List, name: str, deterministic: List[str]) -> List[str]:
        name_lower = name.lower()
        boosted: List[str] = []
        for base, variants in COMMON_BOOSTS.items():
            if base in name_lower:
                boosted = variants
                break
        return _clean_synonyms(list(llm_terms) + boosted + list(deterministic), name, cap=35)

    def _prompt_payload(self, name: str, context: str, is_combo: bool) -> Dict[str, str]:
        return {
            "name": name,
            "name_lower": name.lower(),
            "context": context or "(no extra details)",
            "context_type": "spice combo" if is_combo else "individual spice",
        }

    def generate_synonyms(self, name: str, context: str = "", is_combo: bool = False,
                          deterministic: Optional[List[str]] = None) -> List[str]:
        """LLM-generated Hinglish/regional search terms, validated and merged
        with deterministic fallbacks. Never raises, never returns empty."""
        deterministic = deterministic or []
        if self.llm is not None:
            chain = SYNONYM_PROMPT | self.llm | JsonOutputParser()
            payload = self._prompt_payload(name, context, is_combo)
            for attempt in (1, 2):
                try:
                    result = chain.invoke(payload)
                    llm_terms = result.get("synonyms", [])
                    if llm_terms:
                        return self._finalize_synonyms(llm_terms, name, deterministic)
                    logger.warning(f"Synonym LLM returned no terms for '{name}' (attempt {attempt})")
                except Exception as e:
                    logger.error(f"Synonym generation failed for '{name}' (attempt {attempt}): {e}")
        return self._finalize_synonyms([], name, deterministic)

    async def a_generate_synonyms(self, name: str, context: str = "", is_combo: bool = False,
                                  deterministic: Optional[List[str]] = None) -> List[str]:
        """Asynchronous version of generate_synonyms"""
        deterministic = deterministic or []
        if self.llm is not None:
            chain = SYNONYM_PROMPT | self.llm | JsonOutputParser()
            payload = self._prompt_payload(name, context, is_combo)
            for attempt in (1, 2):
                try:
                    result = await chain.ainvoke(payload)
                    llm_terms = result.get("synonyms", [])
                    if llm_terms:
                        return self._finalize_synonyms(llm_terms, name, deterministic)
                    logger.warning(f"Synonym LLM returned no terms for '{name}' (attempt {attempt})")
                except Exception as e:
                    logger.error(f"Async synonym generation failed for '{name}' (attempt {attempt}): {e}")
        return self._finalize_synonyms([], name, deterministic)

    def _kb_target(self, product_or_combo):
        if isinstance(product_or_combo, Product):
            return ProductSearchKB, 'product', False
        if isinstance(product_or_combo, ProductCombo):
            return ProductComboSearchKB, 'combo', True
        return None, None, None

    def ensure_search_kb(self, product_or_combo: Union[Product, ProductCombo], force: bool = False) -> None:
        """Ensure search KB exists and is fresh (7 days). force=True regenerates
        unconditionally — required after direct-SQL catalog changes."""
        kb_model, kb_field, is_combo = self._kb_target(product_or_combo)
        if kb_model is None:
            logger.error(f"Invalid type: {type(product_or_combo)}")
            return

        kb, created = kb_model.objects.get_or_create(**{kb_field: product_or_combo})
        days_old = (timezone.now() - kb.last_updated).days

        if created or force or days_old > 7:
            context = _build_kb_context(product_or_combo)
            deterministic = _deterministic_synonyms(product_or_combo)
            synonyms = self.generate_synonyms(
                product_or_combo.name, context, is_combo=is_combo, deterministic=deterministic
            )
            kb.synonyms = synonyms
            kb.save()
            reason = 'Created' if created else ('Forced' if force else f'Refreshed ({days_old}d)')
            logger.info(f"{reason} KB for {product_or_combo.name} ({len(synonyms)} synonyms)")

    async def a_ensure_search_kb(self, product_or_combo: Union[Product, ProductCombo], force: bool = False) -> None:
        """Asynchronous version of ensure_search_kb"""
        kb_model, kb_field, is_combo = self._kb_target(product_or_combo)
        if kb_model is None:
            logger.error(f"Invalid type: {type(product_or_combo)}")
            return

        kb, created = await self._get_or_create_kb(kb_model, {kb_field: product_or_combo})
        days_old = (timezone.now() - kb.last_updated).days

        if created or force or days_old > 7:
            context = await sync_to_async(_build_kb_context)(product_or_combo)
            deterministic = await sync_to_async(_deterministic_synonyms)(product_or_combo)
            synonyms = await self.a_generate_synonyms(
                product_or_combo.name, context, is_combo=is_combo, deterministic=deterministic
            )
            kb.synonyms = synonyms
            await self._save_kb(kb)
            reason = 'Created' if created else ('Forced' if force else f'Refreshed ({days_old}d)')
            logger.info(f"{reason} Async KB for {product_or_combo.name} ({len(synonyms)} synonyms)")

    @sync_to_async
    def _get_or_create_kb(self, kb_model, kwargs):
        return kb_model.objects.get_or_create(**kwargs)

    @sync_to_async
    def _save_kb(self, kb):
        kb.save()

    # ----- search -----

    def unified_search(self, query: str, top_k: int = 20, score_threshold: int = 70) -> Dict[str, Any]:
        """SINGLE ENDPOINT: Unified search + recommendations ranked by score"""
        query = query.strip().lower()

        # 1. Direct fuzzy search (highest priority)
        direct_results = self._fuzzy_search_all(query, top_k, score_threshold)

        # 2. Recommendations top up a thin result set — but ONLY when the query
        # actually matched something. With zero direct matches they used to be
        # returned as `products`, so a nonsense query like "zzzzqqq" still came
        # back with a product and the UI could never say "no results".
        # A no-match query returns no products; the recommendations ride along
        # under `suggestions` so the UI can offer them as an honest fallback.
        other_recs = []
        if 0 < len(direct_results) < 3:
            other_recs = self._other_recommendations(query, top_k // 2)

        all_results = direct_results + other_recs
        scored_results = self._rank_and_dedupe(all_results, top_k)

        products = [r for r in scored_results if r['type'] == 'product']
        combos = [r for r in scored_results if r['type'] == 'combo']

        suggestions = []
        if not scored_results:
            suggestions = self._rank_and_dedupe(
                self._other_recommendations(query, top_k // 2), top_k // 2
            )

        return {
            'query': query,
            'total_results': len(scored_results),
            'products': products,
            'combos': combos,
            # Never search results — only shown when there are none.
            'suggestions': suggestions,
            'stats': {
                'direct_matches': len(direct_results),
                'other_recs': len(other_recs)
            }
        }

    def _fuzzy_search_all(self, query: str, top_k: int, threshold: int) -> List[Dict]:
        """Fuzzy match against the cached corpus (no per-query DB scan)."""
        corpus = get_search_corpus()
        results: List[Dict] = []

        product_scores = _score_matches(
            query, [e for e in corpus if e['type'] == 'product'], threshold
        )
        if product_scores:
            top_ids = [
                pid for pid, _ in
                sorted(product_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
            ]
            products = Product.objects.filter(
                id__in=top_ids, is_active=True, stock__gt=0
            ).select_related('category')
            results.extend(self._format_products(products, product_scores))

        combo_scores = _score_matches(
            query, [e for e in corpus if e['type'] == 'combo'], threshold
        )
        if combo_scores:
            top_ids = [
                cid for cid, _ in
                sorted(combo_scores.items(), key=lambda x: x[1], reverse=True)[:max(top_k // 2, 1)]
            ]
            combos = ProductCombo.objects.filter(
                id__in=top_ids, is_active=True
            ).prefetch_related('products')
            serialized = SearchComboSerializer(combos, many=True).data
            for item in serialized:
                item['score'] = combo_scores.get(item['id'], 0)
                item['score_type'] = 'direct'
            results.extend(serialized)

        results.sort(key=lambda r: r['score'], reverse=True)
        return results[:top_k]

    def _format_products(self, products, scored_scores: Dict, score_type: str = 'direct') -> List[Dict]:
        """Batch formatting via serializer for safety"""
        serialized = SearchProductSerializer(products, many=True).data
        # Merge score info into each serialized item
        for item in serialized:
            item['score'] = scored_scores.get(item['id'], 0)
            item['score_type'] = score_type
        return serialized

    def _other_recommendations(self, query: str, top_k: int) -> List[Dict]:
        """Fast category + trending fallback (only used when direct matches are scarce)"""
        results = []

        # Category match
        category_match = Category.objects.filter(name__icontains=query).first()
        if category_match:
            products = Product.objects.filter(
                category=category_match, is_active=True, stock__gt=0
            ).select_related('category')[:max(top_k // 4, 1)]
            results.extend(self._format_products(
                products, {p.id: 75 for p in products}, score_type='category'
            ))

        # Trending/featured
        trending_products = Product.objects.filter(
            is_featured=True, is_active=True, stock__gt=0
        ).select_related('category')[:max(top_k // 4, 1)]
        results.extend(self._format_products(
            trending_products, {p.id: 60 for p in trending_products}, score_type='trending'
        ))

        return results[:top_k]

    def _rank_and_dedupe(self, results: List[Dict], top_k: int) -> List[Dict]:
        """
        Apply the score-type weight exactly once, dedupe by (type, id), and rank.

        The weight is folded into a final score up front so dedupe compares like
        with like. (The previous version compared an incoming raw score against a
        stored *weighted* score, mixing scales — a direct hit could lose its slot
        to a weaker fallback.) Because direct matches clear the fuzzy threshold
        (>=70) while category/trending fallbacks are capped at 75/60 and then
        down-weighted, a genuine match always outranks a padded recommendation.
        """
        score_weights = {'direct': 1.0, 'category': 0.8, 'trending': 0.5}
        scored = {}

        for item in results:
            item_id = (item['type'], item['id'])
            final_score = item['score'] * score_weights.get(item['score_type'], 0.5)
            existing = scored.get(item_id)
            if existing is None or final_score > existing['score']:
                scored[item_id] = {**item, 'score': final_score}

        return sorted(scored.values(), key=lambda x: x['score'], reverse=True)[:top_k]
