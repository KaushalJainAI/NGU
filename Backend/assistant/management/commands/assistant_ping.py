"""Verify the assistant's LLM key/config end-to-end.

Run after setting LLM_API_KEY in the environment:

    python manage.py assistant_ping
    python manage.py assistant_ping --message "do you sell haldi?"

It reports whether the LLM initialised, then runs one real (anonymous) turn
through the agent and prints the reply, so you can confirm the key works and
the model returns the expected JSON envelope.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check that the AI assistant's LLM is configured and reachable."

    def add_arguments(self, parser):
        parser.add_argument('--message', default='Hi, what can you help me with?')

    def _emit(self, text, style=None):
        """Write to stdout, surviving non-UTF8 consoles (e.g. Windows cp1252)."""
        try:
            self.stdout.write(style(text) if style else text)
        except UnicodeEncodeError:
            enc = getattr(self.stdout._out, 'encoding', None) or 'ascii'
            safe = text.encode(enc, errors='replace').decode(enc)
            self.stdout.write(style(safe) if style else safe)

    def handle(self, *args, **options):
        from assistant.agent import _build_llm, Agent

        llm = _build_llm()
        if llm is None:
            self._emit(
                "LLM not initialised. Set LLM_API_KEY (and optionally "
                "ASSISTANT_MODEL_PROVIDER / ASSISTANT_LLM_MODEL) in the environment.",
                self.style.ERROR,
            )
            return

        self._emit(f"LLM initialised: {type(llm).__name__}", self.style.SUCCESS)
        self._emit("Running one test turn (anonymous user)...\n")

        # Anonymous run: only public read tools are reachable (G1).
        result = Agent(user=None).run(options['message'])

        self._emit(f"llm_used:   {result.get('llm_used')}")
        self._emit(f"escalate:   {result.get('escalate')}")
        self._emit(f"sources:    {result.get('sources')}")
        self._emit(f"action:     {result.get('proposed_action')}")
        self._emit(f"\nreply: {result.get('reply')}", self.style.SUCCESS)

        if not result.get('llm_used'):
            self._emit(
                "\nThe model wasn't used (degraded fallback). Check the key/model and try again.",
                self.style.WARNING,
            )
