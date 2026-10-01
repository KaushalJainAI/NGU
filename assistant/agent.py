"""The assistant agent loop.

A bounded, server-side ReAct-style loop over NATIVE function calls (AP9). The
LLM is advisory only: it calls functions, read tools execute here (scoped to
the user by the view), and write intents come back as proposals the UI must
confirm. Guardrails:
- max 4 tool iterations per turn (G4)
- closed tool registry + strict server-side validation (G3)
- untrusted retrieved data wrapped in <<DATA>> markers / spotlighting (G3)
- provider errors and unparseable output degrade to a friendly reply that
  NEVER escalates to a human (AP2/A4)
- only the customer's explicit request escalates, via escalate_to_human (AP9)
- graceful degrade when the LLM is unavailable (G4)

Turn contract (internal, also the unit-test seam): _complete() returns
{'content': str|None, 'tool_calls': [{'name': str, 'args': dict}],
 'finish': 'stop'|'length'}. run() returns {reply, proposed_action|None,
sources, escalate, llm_used, title, history_truncated, reason} with
reason in {ok, llm_error, loop_exhausted, customer_asked, llm_unavailable}.
"""

import json
import logging
import os

from dotenv import load_dotenv

from .prompts import (
    SYSTEM_PROMPT, ADMIN_SYSTEM_PROMPT, FALLBACK_REPLY, LOOP_EXHAUSTED_REPLY,
    HONEST_HANDOFF_REPLY, CONTINUED_SUFFIX, language_directive,
)
from . import tools as toolkit
from . import admin_tools

load_dotenv()
logger = logging.getLogger(__name__)

MAX_ITERATIONS = 4
MAX_MESSAGE_LEN = 1000         # input cap for a single *new* user turn (also enforced in the view)
# AP9: 1000 replaces 600 — replies cut off at 600 tokens were unparseable
# under the old envelope, and long list answers (especially in Indic scripts)
# need the headroom. Truncation is now detected via finish_reason instead.
MAX_OUTPUT_TOKENS = int(os.getenv('ASSISTANT_MAX_OUTPUT_TOKENS', '1000'))

# AP2: bound every LLM round trip so one slow provider response cannot hold a
# gunicorn slot indefinitely (3 workers x 2 threads = 6 slots shared with
# checkout). One retry only — more retries multiply tail latency for everyone.
LLM_REQUEST_TIMEOUT = int(os.getenv('ASSISTANT_LLM_TIMEOUT', '20'))
LLM_MAX_RETRIES = 1

# --- Conversation memory -----------------------------------------------------
# The assistant remembers as much of the thread as fits under a token budget,
# instead of a fixed message count. History is trimmed newest-first until the
# budget is reached, so long threads keep continuity without ever overflowing
# the model's context window.
#
# Token counts are *estimated* from characters (no tokenizer dependency at
# request time): 3 chars/token deliberately over-counts English (~4 chars/token)
# so the estimate errs toward staying under the real limit, never over it.
CHARS_PER_TOKEN = 3
# Hard ceiling — a single turn's prompt is never allowed to exceed this many
# estimated tokens, so we stay inside the model's context window (minimax-m2.5
# ~204k). Configurable per-deployment via env.
# AP7c/S8: a few thousand tokens of history per turn, not ~200k. The old
# default let one account's thread drag a novel's worth of context through up
# to 4 LLM calls per turn, 500 turns a day — pure spend. Env still overrides.
MODEL_CONTEXT_TOKENS = int(os.getenv('ASSISTANT_MODEL_CONTEXT_TOKENS', '12000'))
# Headroom reserved out of the ceiling for the reply and for <<DATA>> tool
# observations appended across up to MAX_ITERATIONS loop cycles, so the running
# prompt can't blow past MODEL_CONTEXT_TOKENS mid-turn.
# What is left for HISTORY is ceiling - reply - this reserve - system prompt
# (~2,100 estimated tokens). At 8000 that was ~800 tokens: the assistant forgot
# after about five exchanges and the "start a new chat" notice showed almost at
# once. 4000 leaves ~4,900 (roughly 25-30 ordinary messages).
TOOL_OBS_RESERVE_TOKENS = int(os.getenv('ASSISTANT_TOOL_OBS_RESERVE_TOKENS', '4000'))
# Safety bound on how many rows the view loads from the DB before the agent
# token-trims them (a runaway thread must not pull an unbounded queryset).
MAX_HISTORY_MESSAGES = int(os.getenv('ASSISTANT_MAX_HISTORY_MESSAGES', '500'))


def _estimate_tokens(text):
    """Conservative char-based token estimate (ceil division by CHARS_PER_TOKEN)."""
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def _build_llm():
    """Init the chat model from env. Returns None on failure (assistant degrades).

    Uses the shared LLM_API_KEY. Provider/model can be overridden per-assistant
    via ASSISTANT_MODEL_PROVIDER / ASSISTANT_LLM_MODEL (e.g. to point the
    assistant at a stronger chat model than the search synonym generator),
    falling back to the shared MODEL_PROVIDER / LLM_MODEL.
    """
    api_key = os.getenv('LLM_API_KEY')
    if not api_key:
        logger.warning("Assistant LLM disabled: LLM_API_KEY is not set.")
        return None
    provider = (os.getenv('ASSISTANT_MODEL_PROVIDER') or os.getenv('MODEL_PROVIDER') or 'openrouter').lower()
    model_name = os.getenv('ASSISTANT_LLM_MODEL') or os.getenv('LLM_MODEL') or 'openai/gpt-4o-mini'
    try:
        if provider == 'openrouter':
            from langchain_openai import ChatOpenAI
            from spices_backend.llm import openrouter_extra_body
            return ChatOpenAI(
                model=model_name,
                openai_api_key=api_key,
                openai_api_base=os.getenv('OPENROUTER_API_BASE', 'https://openrouter.ai/api/v1'),
                temperature=0.2,
                max_tokens=MAX_OUTPUT_TOKENS,
                extra_body=openrouter_extra_body(),
                request_timeout=LLM_REQUEST_TIMEOUT,
                max_retries=LLM_MAX_RETRIES,
            )
        from langchain.chat_models import init_chat_model
        return init_chat_model(
            model_name, model_provider=provider,
            temperature=0.2, api_key=api_key, max_tokens=MAX_OUTPUT_TOKENS,
            request_timeout=LLM_REQUEST_TIMEOUT, max_retries=LLM_MAX_RETRIES,
        )
    except Exception as e:
        logger.error("Assistant LLM init failed (%s/%s): %s", provider, model_name, e)
        return None


def _normalize_response(resp):
    """Provider reply (or test double) -> normalized turn dict. Never raises:
    anything unrecognisable becomes an unparseable turn, which run() degrades
    to the friendly llm_error fallback (never a 500, never an escalation)."""
    try:
        content = getattr(resp, 'content', None)
        if isinstance(content, list):
            # Multi-block content (some providers): keep text parts only.
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get('text', '')))
                else:
                    parts.append(str(getattr(block, 'text', block) or ''))
            content = ' '.join(p for p in parts if p)
        if content is not None and not isinstance(content, str):
            content = str(content)
        calls = []
        for tc in (getattr(resp, 'tool_calls', None) or []):
            if isinstance(tc, dict):
                fn = tc.get('function') or {}
                name = tc.get('name') or fn.get('name')
                args = tc.get('args', {})
                call_id = tc.get('id')
            else:
                fn = getattr(tc, 'function', None)
                name = getattr(tc, 'name', None) or getattr(fn, 'name', None)
                args = getattr(tc, 'args', {})
                call_id = getattr(tc, 'id', None)
            if not name or not isinstance(args, dict):
                continue
            calls.append({'name': name, 'args': args, 'id': call_id})
        meta = getattr(resp, 'response_metadata', None) or {}
        finish = meta.get('finish_reason') or getattr(resp, 'finish_reason', None) or 'stop'
        return {'content': content, 'tool_calls': calls, 'finish': finish}
    except Exception:
        logger.exception('Assistant response normalisation failed')
        return {'content': None, 'tool_calls': [], 'finish': 'stop', 'unparseable': True}


def _spotlight(label, data):
    """Wrap untrusted tool output as DATA the model must not treat as commands."""
    return f"<<DATA source={label}>>\n{json.dumps(data, ensure_ascii=False)}\n<</DATA>>"


class Agent:
    def __init__(self, user, completion=None, persona='customer'):
        """`user` is the authenticated user (or AnonymousUser/None).
        `completion` is an optional callable(messages)->turn-dict for tests; if
        not given, the real LLM is used with native function calling.
        `persona` selects the toolset + system prompt: 'customer' (default) uses
        the public/user-scoped tools; 'admin' uses the read-only reporting tools
        (admin_tools) and MUST only be constructed from an IsAdminUser endpoint —
        those tools read across all customers/orders."""
        self.user = user if (user is not None and getattr(user, 'is_authenticated', False)) else None
        self._completion = completion
        self._llm = None if completion else _build_llm()

        self.persona = persona
        if persona == 'admin':
            self._system_prompt = ADMIN_SYSTEM_PROMPT
            self._read_tools = admin_tools.ADMIN_READ_TOOLS
            self._run_read_tool = admin_tools.run_admin_read_tool
            self._action_builders = {}          # admin assistant is read-only
            self._build_action = None
            self._schemas = admin_tools.ADMIN_TOOL_SCHEMAS
        else:
            self._system_prompt = SYSTEM_PROMPT
            self._read_tools = toolkit.READ_TOOLS
            self._run_read_tool = toolkit.run_read_tool
            self._action_builders = toolkit.ACTION_BUILDERS
            self._build_action = toolkit.build_action
            self._schemas = toolkit.TOOL_SCHEMAS + toolkit.ACTION_SCHEMAS

        if self._llm is not None:
            binder = getattr(self._llm, 'bind_tools', None)
            if not callable(binder):
                # Test doubles stub _build_llm with a bare object() (they stub
                # _complete anyway) — leave it; a real client always binds.
                logger.warning('Assistant LLM has no bind_tools; continuing unbound.')
            else:
                try:
                    self._llm = binder(self._schemas)
                except Exception:
                    logger.exception('Assistant tool binding failed; degrading.')
                    self._llm = None

    @property
    def llm_available(self):
        return self._completion is not None or self._llm is not None

    def _complete(self, messages):
        if self._completion is not None:
            return self._completion(messages)
        return _normalize_response(self._llm.invoke(messages))

    def run(self, message, history=None, language=None):
        """Run one user turn. Returns a dict:
        { reply, proposed_action|None, sources, escalate, llm_used,
          title, history_truncated, reason }.

        `language` is the customer-selected reply language code (e.g. 'en',
        'hi', 'hinglish'); it only steers the final reply text, never the
        function names or args (which stay English). Only an explicit
        escalate_to_human call sets escalate (reason customer_asked)."""
        message = (message or '').strip()[:MAX_MESSAGE_LEN]
        sources = []

        if not self.llm_available:
            return {'reply': FALLBACK_REPLY, 'proposed_action': None,
                    'sources': sources, 'escalate': True, 'llm_used': False,
                    'history_truncated': False, 'reason': 'llm_unavailable'}

        # Build the message list: system + language directive + history + new turn.
        system_text = self._system_prompt + '\n\n' + language_directive(language)
        messages = [('system', system_text)]

        # Token-budgeted history: keep as many of the most recent turns as fit
        # under the ceiling, reserving room for the reply + tool observations so
        # the running prompt can never exceed MODEL_CONTEXT_TOKENS mid-loop.
        budget = MODEL_CONTEXT_TOKENS - MAX_OUTPUT_TOKENS - TOOL_OBS_RESERVE_TOKENS
        used = _estimate_tokens(system_text) + _estimate_tokens(message)
        kept = []
        supplied = list(history or [])
        for h in reversed(supplied):
            cost = _estimate_tokens(h.get('content', ''))
            if used + cost > budget:
                break            # older turns beyond the budget are dropped
            used += cost
            kept.append(h)
        kept.reverse()           # restore chronological order

        # The thread outgrew the context window: the oldest turns above are gone
        # from the prompt, so the assistant will answer without them. Surface it
        # instead of silently forgetting (the view passes it to the client, which
        # nudges the customer to start a fresh conversation).
        history_truncated = len(kept) < len(supplied)

        for h in kept:
            h_role = h.get('role', 'user')
            if h_role == 'admin':
                # Admin messages are passed to the LLM as assistant turns with a
                # clear label so the model knows a human team member spoke.
                name = h.get('sender_name') or 'Admin'
                content = f"[{name} — Nidhi Team]: {h.get('content', '')}"
                messages.append(('assistant', content))
            elif h_role == 'assistant':
                messages.append(('assistant', h.get('content', '')))
            else:
                messages.append(('user', h.get('content', '')))
        messages.append(('user', message))

        pending_action = None
        escalate = False
        for iteration in range(MAX_ITERATIONS):
            # AP2: a provider error (timeout, 5xx, revoked key) must be a
            # friendly reply, NOT a 500 and NOT a human escalation.
            try:
                turn = self._complete(messages)
            except Exception:
                logger.exception("Assistant LLM call failed")
                return {'reply': FALLBACK_REPLY, 'proposed_action': None,
                        'sources': sources, 'escalate': False, 'llm_used': True,
                        'title': None, 'history_truncated': history_truncated,
                        'reason': 'llm_error'}
            # AP9/A4: anything that is not a well-formed turn degrades to the
            # same friendly fallback — and NEVER flags a human.
            if not isinstance(turn, dict) or turn.get('unparseable'):
                logger.warning('Assistant unparseable turn; friendly fallback.')
                return {'reply': FALLBACK_REPLY, 'proposed_action': None,
                        'sources': sources, 'escalate': False, 'llm_used': True,
                        'title': None, 'history_truncated': history_truncated,
                        'reason': 'llm_error'}
            calls = turn.get('tool_calls') or []
            content = turn.get('content')

            # Execute every requested call in this round (A3: one round may
            # look up haldi AND jeera AND dhaniya). Observations feed back as
            # DATA for the next round.
            # `awaiting_answer`: this round produced something the model has
            # not seen yet (a lookup result, or a rejection). Text sent in the
            # SAME round was written before that — typically "Let me check
            # that for you" — so it is not the answer.
            awaiting_answer = False
            for call in calls:
                name = call.get('name')
                args = call.get('args') if isinstance(call.get('args'), dict) else {}
                if name in self._read_tools:
                    awaiting_answer = True
                    observation = self._run_read_tool(name, self.user, args)
                    sources.append({'tool': name, 'args': args})
                    messages.append(('assistant', f'[{name} called]'))
                    messages.append(('user', _spotlight(name, observation)))
                elif name in self._action_builders and self._build_action is not None:
                    action, err = self._build_action(name, self.user, args)
                    if action is None:
                        awaiting_answer = True
                        messages.append(('assistant', f'[{name} called]'))
                        messages.append((
                            'user',
                            f'Action "{name}" was rejected: {err or "invalid"}. '
                            f'Answer without it.',
                        ))
                    else:
                        # First valid proposal wins; later ones in the same
                        # turn are dropped (multi-proposals arrive in AP10).
                        if pending_action is None:
                            pending_action = action
                        if action.get('type') == 'escalate_to_human':
                            escalate = True
                        messages.append(('assistant', f'[{name} called]'))
                        messages.append(('user', _spotlight(
                            name, {'recorded': True, 'label': action.get('label', '')})))
                else:
                    # Unknown/invalid tool name -> tell the model, don't execute.
                    awaiting_answer = True
                    messages.append((
                        'user',
                        f'"{name}" is not a valid tool. Use only the listed '
                        f'tools or answer in plain text.',
                    ))

            last_round = iteration == MAX_ITERATIONS - 1
            if awaiting_answer and not last_round:
                # Go round again so the reply is written WITH the results.
                continue

            if content and content.strip():
                reply = self._clean_reply(content)
                if turn.get('finish') == 'length' and reply:
                    # AP9/A4: cut off by the output limit, not a failure — say
                    # so instead of escalating.
                    reply = f'{reply}\n\n{CONTINUED_SUFFIX}'
                if not reply and escalate:
                    reply = HONEST_HANDOFF_REPLY
                if not reply:
                    reply = FALLBACK_REPLY
                return {'reply': reply, 'proposed_action': pending_action,
                        'sources': sources, 'escalate': escalate, 'llm_used': True,
                        'title': self._make_title(message, history),
                        'history_truncated': history_truncated,
                        'reason': 'customer_asked' if escalate else 'ok'}

            # No readable reply this round — nudge once more; the loop cap
            # turns persistence into loop_exhausted, not an escalation.
            messages.append((
                'user',
                'Please answer the customer now in plain text (no tool call needed).',
            ))

        # Loop exhausted: a capacity problem, not a human problem (A4).
        return {'reply': LOOP_EXHAUSTED_REPLY, 'proposed_action': None,
                'sources': sources, 'escalate': False, 'llm_used': True, 'title': None,
                'history_truncated': history_truncated, 'reason': 'loop_exhausted'}

    # ------------------------------------------------------------------
    def _clean_reply(self, reply):
        """Plain text only (G6): remove any HTML tags and model-emitted URLs.

        The frontend renders replies as React text (inherently XSS-safe), so we
        strip tags rather than HTML-escape — escaping would surface visible
        entities like &#x27; in the chat. strip_tags drops a <script> wrapper
        while keeping apostrophes and punctuation readable. URLs are removed as
        anti-phishing defense (navigation happens only via the allowlist)."""
        if not isinstance(reply, str) or not reply.strip():
            return ''
        import re
        from django.utils.html import strip_tags
        text = strip_tags(reply)
        text = re.sub(r'https?://\S+', '', text)
        return text.strip()[:1500]

    def _make_title(self, message, history):
        """First-turn thread title, derived server-side (AP9).

        Deterministic — no LLM round spent on it: the opening words of the
        customer's first message, sanitised. Later turns return None (the view
        only stamps a title once).
        """
        if history:
            return None
        from django.utils.html import strip_tags
        return strip_tags(' '.join(message.split()[:8])).strip()[:80] or None
