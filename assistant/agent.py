"""The assistant agent loop.

A bounded, server-side ReAct-style loop. The LLM is advisory only: it returns a
strict JSON envelope each step. Read tools execute here (scoped to the user);
write intents come back as proposals the UI must confirm. Guardrails:
- max 4 tool iterations per turn (G4)
- closed tool registry + strict validation (G3)
- untrusted retrieved data wrapped in <<DATA>> markers / spotlighting (G3)
- one repair retry then safe fallback on bad output (G3)
- graceful degrade when the LLM is unavailable (G4)
"""

import json
import logging
import os

from dotenv import load_dotenv

from .prompts import SYSTEM_PROMPT, ADMIN_SYSTEM_PROMPT, FALLBACK_REPLY, language_directive
from . import tools as toolkit
from . import admin_tools

load_dotenv()
logger = logging.getLogger(__name__)

MAX_ITERATIONS = 4
MAX_MESSAGE_LEN = 1000         # input cap for a single *new* user turn (also enforced in the view)
MAX_OUTPUT_TOKENS = int(os.getenv('ASSISTANT_MAX_OUTPUT_TOKENS', '600'))

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
MODEL_CONTEXT_TOKENS = int(os.getenv('ASSISTANT_MODEL_CONTEXT_TOKENS', '200000'))
# Headroom reserved out of the ceiling for the reply and for <<DATA>> tool
# observations appended across up to MAX_ITERATIONS loop cycles, so the running
# prompt can't blow past MODEL_CONTEXT_TOKENS mid-turn.
TOOL_OBS_RESERVE_TOKENS = int(os.getenv('ASSISTANT_TOOL_OBS_RESERVE_TOKENS', '8000'))
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
            )
        from langchain.chat_models import init_chat_model
        return init_chat_model(
            model_name, model_provider=provider,
            temperature=0.2, api_key=api_key, max_tokens=MAX_OUTPUT_TOKENS,
        )
    except Exception as e:
        logger.error("Assistant LLM init failed (%s/%s): %s", provider, model_name, e)
        return None


def _parse_envelope(raw):
    """Extract the JSON envelope from a model response. Returns dict or None."""
    if not isinstance(raw, str):
        raw = getattr(raw, 'content', '') or ''
    text = raw.strip()
    # Strip ```json fences if present.
    if text.startswith('```'):
        text = text.strip('`')
        if text.lower().startswith('json'):
            text = text[4:]
    # Grab the outermost object.
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def _spotlight(label, data):
    """Wrap untrusted tool output as DATA the model must not treat as commands."""
    return f"<<DATA source={label}>>\n{json.dumps(data, ensure_ascii=False)}\n<</DATA>>"


class Agent:
    def __init__(self, user, completion=None, persona='customer'):
        """`user` is the authenticated user (or AnonymousUser/None).
        `completion` is an optional callable(messages)->str for tests; if not
        given, the real LLM is used.
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
        else:
            self._system_prompt = SYSTEM_PROMPT
            self._read_tools = toolkit.READ_TOOLS
            self._run_read_tool = toolkit.run_read_tool
            self._action_builders = toolkit.ACTION_BUILDERS
            self._build_action = toolkit.build_action

    @property
    def llm_available(self):
        return self._completion is not None or self._llm is not None

    def _complete(self, messages):
        if self._completion is not None:
            return self._completion(messages)
        resp = self._llm.invoke(messages)
        return getattr(resp, 'content', resp)

    def run(self, message, history=None, language=None):
        """Run one user turn. Returns a dict:
        { reply, proposed_action|None, sources, escalate, llm_used }.

        `language` is the customer-selected reply language code (e.g. 'en',
        'hi', 'hinglish'); it only steers final_reply, not the JSON envelope."""
        message = (message or '').strip()[:MAX_MESSAGE_LEN]
        sources = []

        if not self.llm_available:
            return {'reply': FALLBACK_REPLY, 'proposed_action': None,
                    'sources': sources, 'escalate': True, 'llm_used': False,
                    'history_truncated': False}

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

        repaired = False
        for _ in range(MAX_ITERATIONS):
            raw = self._complete(messages)
            env = _parse_envelope(raw)

            if env is None:
                if not repaired:
                    repaired = True
                    messages.append((
                        'user',
                        'Your previous response was not valid JSON. Reply with ONLY '
                        'the JSON envelope object described in the instructions.',
                    ))
                    continue
                break  # give up -> fallback below

            tool = env.get('tool')
            args = env.get('args') if isinstance(env.get('args'), dict) else {}

            # READ tool requested -> execute, feed observation back as DATA.
            if tool and tool in self._read_tools:
                observation = self._run_read_tool(tool, self.user, args)
                sources.append({'tool': tool, 'args': args})
                messages.append(('assistant', json.dumps(env, ensure_ascii=False)))
                messages.append(('user', _spotlight(tool, observation)))
                continue

            # Unknown/invalid tool name -> tell the model, don't execute.
            if tool and tool not in self._read_tools:
                messages.append((
                    'user',
                    f'"{tool}" is not a valid read tool. Use only the listed tools '
                    f'or set tool to null and answer.',
                ))
                continue

            # No read tool -> this is the final answer.
            reply = env.get('final_reply')
            reply = self._clean_reply(reply)
            proposed_action, escalate = self._resolve_action(env.get('proposed_action'))
            if proposed_action is None and not reply:
                reply = FALLBACK_REPLY
            title = self._clean_title(env.get('title'))
            return {'reply': reply, 'proposed_action': proposed_action,
                    'sources': sources, 'escalate': escalate, 'llm_used': True,
                    'title': title, 'history_truncated': history_truncated}

        # Loop exhausted or unrecoverable -> safe fallback.
        return {'reply': FALLBACK_REPLY, 'proposed_action': None,
                'sources': sources, 'escalate': True, 'llm_used': True, 'title': None,
                'history_truncated': history_truncated}

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

    def _clean_title(self, title):
        """Sanitise the LLM-generated thread title (first turn only)."""
        if not isinstance(title, str) or not title.strip():
            return None
        from django.utils.html import strip_tags
        return strip_tags(title).strip()[:80] or None

    def _resolve_action(self, proposed):
        """Validate a proposed_action from the model and build it (G5).
        Returns (action_dict|None, escalate_bool)."""
        if not isinstance(proposed, dict):
            return None, False
        name = proposed.get('tool')
        if name not in self._action_builders or self._build_action is None:
            return None, False
        action, _err = self._build_action(name, self.user, proposed.get('args') or {})
        if action is None:
            return None, False
        escalate = action.get('type') == 'escalate_to_human'
        return action, escalate
