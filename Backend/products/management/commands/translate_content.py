"""Machine-translate all storefront content into the configured languages.

Walks every model registered with django-modeltranslation (Product, Category,
ProductCombo, Review) and, for each translatable field, fills the per-language
columns from the English source using the configured LLM (OpenRouter).

It is idempotent: a field that already has a translation is skipped unless
--force is given, so you can run it repeatedly as new products/reviews are
added. English is always the fallback, so partial runs never break the site.

Examples:
    python manage.py translate_content --dry-run
    python manage.py translate_content                      # fill all gaps
    python manage.py translate_content --models product,review --langs hi,gu
    python manage.py translate_content --force               # re-translate all
    python manage.py translate_content --limit 5 --sleep 0.5
"""
import time

import requests
from decouple import config
from django.conf import settings
from django.core.management.base import BaseCommand
from modeltranslation.translator import translator

DEFAULT_LANG = "en"

# Human descriptions used in the translation prompt.
LANG_NAMES = {
    "hi": "Hindi (Devanagari script)",
    "hinglish": "Hinglish — Hindi written in the Latin/Roman alphabet",
    "gu": "Gujarati (Gujarati script)",
    "mr": "Marathi (Devanagari script)",
    "pa": "Punjabi (Gurmukhi script)",
}

# Name-like fields are transliterated (keep the brand recognizable) rather than
# literally translated word-by-word.
NAME_FIELDS = {"name", "title"}

OPENROUTER_URL = config("OPENROUTER_CHAT_COMPLETIONS_URL", default="https://openrouter.ai/api/v1/chat/completions")


class Command(BaseCommand):
    help = "Machine-translate all modeltranslation content into the configured languages."

    def add_arguments(self, parser):
        parser.add_argument("--models", default="",
                            help="Comma list to limit (e.g. product,category,productcombo,review). Default: all.")
        parser.add_argument("--langs", default="",
                            help="Comma list of target language codes. Default: all non-English in settings.LANGUAGES.")
        parser.add_argument("--fields", default="",
                            help="Comma list to limit which fields are translated. Default: all registered.")
        parser.add_argument("--force", action="store_true",
                            help="Overwrite existing translations instead of only filling blanks.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Show what would be translated without calling the LLM or writing.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Process at most N objects per model (0 = all).")
        parser.add_argument("--sleep", type=float, default=0.0,
                            help="Seconds to pause between LLM calls (rate-limit friendliness).")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.dry_run = opts["dry_run"]
        self.force = opts["force"]
        self.sleep = opts["sleep"]

        self.api_key = (config("LLM_API_KEY", default="") or "").strip().strip('"').strip("'")
        self.model = (config("LLM_MODEL", default="openai/gpt-4o-mini") or "").strip().strip('"').strip("'")
        if not self.dry_run and not self.api_key:
            self.stderr.write(self.style.ERROR("LLM_API_KEY is not set; cannot translate. Use --dry-run to preview."))
            return
        self.session = requests.Session()

        # Target languages.
        all_langs = [c for c, _ in settings.LANGUAGES if c != DEFAULT_LANG]
        wanted_langs = [s.strip() for s in opts["langs"].split(",") if s.strip()] or all_langs
        target_langs = [l for l in wanted_langs if l in all_langs]
        if not target_langs:
            self.stderr.write(self.style.ERROR(f"No valid target languages. Available: {all_langs}"))
            return

        wanted_models = {s.strip().lower() for s in opts["models"].split(",") if s.strip()}
        wanted_fields = {s.strip() for s in opts["fields"].split(",") if s.strip()}
        limit = opts["limit"]

        total_calls = total_written = total_skipped = total_failed = 0

        for model in translator.get_registered_models(abstract=False):
            mname = model._meta.model_name
            if wanted_models and mname not in wanted_models:
                continue
            raw_fields = translator.get_options_for_model(model).fields
            field_names = list(raw_fields.keys()) if hasattr(raw_fields, "keys") else list(raw_fields)
            if wanted_fields:
                field_names = [f for f in field_names if f in wanted_fields]
            if not field_names:
                continue

            qs = model.objects.all().order_by("pk")
            if limit:
                qs = qs[:limit]
            count = qs.count()
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{model._meta.label}  ({count} objects)  fields={field_names}  langs={target_langs}"))

            for obj in qs.iterator():
                updates = {}
                for field in field_names:
                    source = (getattr(obj, f"{field}_{DEFAULT_LANG}", None) or getattr(obj, field, None) or "")
                    source = source.strip() if isinstance(source, str) else ""
                    if not source:
                        continue
                    for lang in target_langs:
                        existing = getattr(obj, f"{field}_{lang}", None)
                        if existing and existing.strip() and not self.force:
                            total_skipped += 1
                            continue
                        if self.dry_run:
                            total_calls += 1
                            self.stdout.write(f"  [dry] {mname}#{obj.pk}.{field}_{lang} <- {source[:50]!r}")
                            continue
                        translated = self._translate(source, lang, field in NAME_FIELDS)
                        total_calls += 1
                        if translated:
                            updates[f"{field}_{lang}"] = translated
                        else:
                            total_failed += 1
                        if self.sleep:
                            time.sleep(self.sleep)
                if updates and not self.dry_run:
                    # .update() bypasses model save()/full_clean() (avoids unrelated
                    # validation, e.g. image-extension checks) and writes columns directly.
                    model.objects.filter(pk=obj.pk).update(**updates)
                    total_written += len(updates)
                    self.stdout.write(self.style.SUCCESS(
                        f"  {mname}#{obj.pk}: wrote {len(updates)} fields "
                        f"({', '.join(sorted(updates.keys()))})"))

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. LLM calls: {total_calls} | fields written: {total_written} | "
            f"skipped (already translated): {total_skipped} | failed: {total_failed}"))
        if self.dry_run:
            self.stdout.write("Dry run — nothing was written. Re-run without --dry-run to apply.")

    # ------------------------------------------------------------------
    def _translate(self, text, lang_code, is_name):
        lang = LANG_NAMES.get(lang_code, lang_code)
        if is_name:
            system = (
                f"You translate Indian spice-store product/combo names into {lang}. "
                "Fully translate generic/descriptive words (e.g. 'Powder', 'Whole', "
                "'Combo', 'Daily Essentials', 'Turmeric') into natural {lang} in the "
                "target script. Keep proper brand names and well-known spice names that "
                "have no common local equivalent recognizable (transliterate those into "
                "the target script). The result must read naturally to a native speaker, "
                "not as English in foreign letters. Reply with ONLY the translated name "
                "— no quotes, notes, or alternatives."
            ).replace("{lang}", lang)
        else:
            system = (
                f"You are a professional e-commerce translator. Translate the user's "
                f"text into {lang}. Keep it natural, concise, and faithful — do not add "
                "or remove information, and keep any Markdown/bullet structure. Reply "
                "with ONLY the translation — no quotes or notes."
            )
        try:
            resp = self.session.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "temperature": 0.2,
                    "max_tokens": 1200,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=90,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return (content or "").strip().strip('"').strip("'").strip()
        except Exception as e:  # noqa: BLE001 — never abort the whole run on one failure
            self.stderr.write(self.style.WARNING(f"    translate failed ({lang_code}): {e}"))
            return ""
