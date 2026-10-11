"""Questions customers asked that the FAQ file could not answer.

    python manage.py faq_gaps
    python manage.py faq_gaps --days 30 --top 20

Every time the assistant calls ``search_faq`` the customer's wording is saved on
the reply (``meta.sources``). This command takes those, looks each one up again
against the FAQ file as it is NOW, and lists the ones that still match nothing,
most frequent first. That list is what to write next in ``faq_data.json``.

Questions answered word for word (``reason`` 'faq') never appear here - they
were found. Read-only; no LLM, no network.
"""
from collections import Counter
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from assistant import faq
from assistant.models import AssistantMessage


class Command(BaseCommand):
    help = "List customer questions the assistant's FAQ file could not answer."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=14, help='Look back this many days.')
        parser.add_argument('--top', type=int, default=30, help='Show at most this many.')

    def _emit(self, text, style=None):
        """Write to stdout, surviving non-UTF8 consoles (e.g. Windows cp1252)."""
        try:
            self.stdout.write(style(text) if style else text)
        except UnicodeEncodeError:
            enc = getattr(self.stdout._out, 'encoding', None) or 'ascii'
            safe = text.encode(enc, errors='replace').decode(enc)
            self.stdout.write(style(safe) if style else safe)

    def handle(self, *args, **options):
        faq.load.cache_clear()
        since = timezone.now() - timedelta(days=options['days'])
        asked = Counter()
        for meta in AssistantMessage.objects.filter(
                role='assistant', created_at__gte=since).values_list('meta', flat=True):
            for src in (meta or {}).get('sources', []):
                if src.get('tool') != 'search_faq':
                    continue
                query = (src.get('args') or {}).get('query')
                if isinstance(query, str) and query.strip():
                    asked[query.strip().lower()] += 1

        gaps = [(n, q) for q, n in asked.most_common() if not faq.search(q)]
        if not gaps:
            self._emit(f'No unanswered FAQ questions in the last {options["days"]} days '
                       f'({sum(asked.values())} lookups).', self.style.SUCCESS)
            return
        self._emit(f'Asked, but nothing in the FAQ file matches (last {options["days"]} days):')
        for count, query in gaps[:options['top']]:
            self._emit(f'{count:4d}  {query}')
