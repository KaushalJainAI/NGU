"""Try a question against the assistant's FAQ file, or check the file itself.

    python manage.py faq_search "kitne din me delivery hogi"
    python manage.py faq_search "COD hai kya" --language hinglish
    python manage.py faq_search --check

Run it after editing assistant/faq_data.json. It shows which entries match,
their scores, and whether the question would be answered word for word with no
AI call (``direct``). ``--check`` loads the file and reports any question that
does not find its own entry first. No LLM, no network.
"""
from django.core.management.base import BaseCommand, CommandError

from assistant import faq


class Command(BaseCommand):
    help = "Look a question up in the assistant's FAQ file, or validate the file."

    def add_arguments(self, parser):
        parser.add_argument('question', nargs='?', default='')
        parser.add_argument('--language', default='en')
        parser.add_argument('--check', action='store_true',
                            help='Validate faq_data.json instead of searching.')

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
        entries = faq.load()
        if not entries:
            raise CommandError(f'No FAQ entries loaded from {faq.FAQ_PATH} (see the log).')

        if options['check']:
            return self._check(entries)

        question = options['question'].strip()
        if not question:
            raise CommandError('Give a question, or use --check.')

        matches = faq.search(question)
        if not matches:
            self._emit('No FAQ entry matches (the AI would answer from its other tools).',
                       self.style.WARNING)
            return
        for entry, score in matches:
            self._emit(f'{score:5.1f}  {entry.id}  -  {entry.questions[0]}')
        direct = faq.direct_answer(question, options['language'])
        if direct:
            self._emit(f"\ndirect answer ({direct['id']}):", self.style.SUCCESS)
            self._emit(direct['answer'])
        else:
            self._emit('\nNot a word-for-word answer: the AI reads the matches above '
                       'and writes the reply.', self.style.WARNING)

    def _check(self, entries):
        problems = 0
        for entry in entries:
            if entry.review:
                self._emit(f'review  {entry.id}: {entry.review}', self.style.WARNING)
            for question in entry.questions:
                found = faq.search(question, limit=1)
                if not found or found[0][0].id != entry.id:
                    problems += 1
                    got = found[0][0].id if found else 'nothing'
                    self._emit(f'MISS    {entry.id}: "{question}" finds {got}',
                               self.style.ERROR)
        if problems:
            raise CommandError(f'{problems} question(s) do not find their own entry.')
        self._emit(f'{len(entries)} entries OK.', self.style.SUCCESS)
