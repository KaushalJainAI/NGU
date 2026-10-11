"""Rolling summary of a long chat thread ("auto-compaction").

The problem: the model is shown only as much of a thread as fits a small token
budget (agent.py - about 6,000 estimated tokens of history). Beyond that the
oldest messages used to be dropped and forgotten: a customer who said "no chilli,
it is for a toddler" at the start was asked again 30 messages later.

The fix: when the part of the thread that has not been summarised grows past a
trigger, the OLDEST of it is folded into a short running summary, kept on the
conversation row. The prompt then carries

    system prompt  +  summary  +  the messages after it  +  the new message

and the summary costs a few hundred tokens instead of thousands.

What this does NOT do:
- It never deletes or hides a message. The customer and the admin still see the
  whole thread; the summary is only what the MODEL reads in place of the old part.
- It never blocks a reply. It runs in a background thread after the reply has
  been saved, and if it fails (model down, timeout) nothing changes: the thread
  behaves exactly as before and a later turn tries again.

Size, in plain numbers (estimated tokens, see agent.estimate_tokens):
- ASSISTANT_COMPACT_AFTER_TOKENS (default 4,500): compact when more than this
  much of the thread is unsummarised. Clamped to 80% of the prompt's real room
  for history - a trigger above the room would let messages fall out of the
  prompt BEFORE they were summarised, which is the loss this exists to prevent.
  A trigger like 500,000 would therefore be clamped: the model is never shown
  anything near that much (see docs/ASSISTANT.md, "Context management").
- ASSISTANT_COMPACT_KEEP_TOKENS (default 2,000): the newest messages stay word
  for word and are never folded.
- ASSISTANT_SUMMARY_MAX_TOKENS (default 700): the summary is cut to this size.
"""

import logging
import os
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from .agent import estimate_tokens
from .models import AssistantConversation
from .prompts import SUMMARISER_PROMPT

logger = logging.getLogger(__name__)

ENABLED = os.getenv('ASSISTANT_COMPACT_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', '')
COMPACT_AFTER_TOKENS = int(os.getenv('ASSISTANT_COMPACT_AFTER_TOKENS', '4500'))
KEEP_RECENT_TOKENS = int(os.getenv('ASSISTANT_COMPACT_KEEP_TOKENS', '2000'))
SUMMARY_MAX_TOKENS = int(os.getenv('ASSISTANT_SUMMARY_MAX_TOKENS', '700'))
# A summarising call should not think hard: it copies facts, it does not reason.
SUMMARY_REASONING_EFFORT = os.getenv('ASSISTANT_SUMMARY_REASONING_EFFORT', 'low').strip().lower()

TRIGGER_FRACTION = 0.8        # of the prompt's history room; see the module docstring
MIN_TRIGGER_TOKENS = 1000     # never compact a thread this short, whatever the settings
MIN_FOLD_MESSAGES = 4         # not worth a model call to fold fewer
MIN_KEEP_MESSAGES = 2         # the latest exchange always stays word for word
TRANSCRIPT_MAX_TOKENS = 12000  # most text one summarising call reads; the rest waits
LOCK_SECONDS = 120            # one summariser per thread at a time
BACKOFF_SECONDS = 600         # after a failure, leave the thread alone this long
HISTORY_ROLES = ('user', 'assistant', 'admin')
ROLE_LABELS = {'user': 'Customer', 'assistant': 'Assistant', 'admin': 'Team member'}


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------

def history_room():
    """How many estimated tokens of history the prompt really has room for, using
    the same arithmetic as Agent.run (ceiling - reply - tool reserve - system
    prompt), less what the summary itself will take."""
    from . import agent
    from .prompts import SYSTEM_PROMPT
    return (agent.MODEL_CONTEXT_TOKENS - agent.MAX_OUTPUT_TOKENS
            - agent.TOOL_OBS_RESERVE_TOKENS - estimate_tokens(SYSTEM_PROMPT)
            - SUMMARY_MAX_TOKENS)


def trigger_tokens():
    return max(MIN_TRIGGER_TOKENS,
               min(COMPACT_AFTER_TOKENS, int(history_room() * TRIGGER_FRACTION)))


def plan(conversation):
    """The messages to fold into the summary now, oldest first, or [] if none.

    Each is {id, role, content, sender_name}. Messages after the last summary are
    counted; if they exceed the trigger, everything older than the newest
    KEEP_RECENT_TOKENS (and at least the latest exchange) is chosen, bounded so a
    single summarising call never reads more than TRANSCRIPT_MAX_TOKENS.
    """
    rows = list(conversation.messages
                .filter(role__in=HISTORY_ROLES, id__gt=conversation.summary_upto or 0)
                .order_by('id').values('id', 'role', 'content', 'sender_name'))
    sizes = [estimate_tokens(r['content']) for r in rows]
    if sum(sizes) <= trigger_tokens():
        return []

    kept, cut = 0, len(rows)
    for i in range(len(rows) - 1, -1, -1):
        if kept + sizes[i] > KEEP_RECENT_TOKENS:
            break
        kept += sizes[i]
        cut = i
    cut = min(cut, len(rows) - MIN_KEEP_MESSAGES)
    if cut < MIN_FOLD_MESSAGES:
        return []

    chosen, total = [], 0
    for row, size in zip(rows[:cut], sizes):
        if chosen and total + size > TRANSCRIPT_MAX_TOKENS:
            break
        chosen.append(row)
        total += size
    return chosen


# ---------------------------------------------------------------------------
# Summarising
# ---------------------------------------------------------------------------

def transcript(rows):
    lines = []
    for r in rows:
        who = ROLE_LABELS.get(r['role'], r['role'])
        if r['role'] == 'admin' and r.get('sender_name'):
            who = f"Team member ({r['sender_name']})"
        lines.append(f"{who}: {(r['content'] or '').strip()}")
    return '\n'.join(lines)


def summarise(previous, text):
    """Ask the model for the updated summary. Raises on any failure - the caller
    treats that as "try again later". (A seam: tests replace this function.)"""
    from . import agent
    llm = agent._build_llm(max_tokens=SUMMARY_MAX_TOKENS * 2,
                           reasoning_effort=SUMMARY_REASONING_EFFORT, temperature=0)
    if llm is None:
        raise RuntimeError('assistant LLM is not configured')
    body = ('PREVIOUS MEMORY:\n' + (previous.strip() or '(empty)')
            + '\n\nNEWER MESSAGES:\n' + text)
    turn = agent._normalize_response(llm.invoke([('system', SUMMARISER_PROMPT), ('user', body)]))
    if turn.get('unparseable') or not (turn.get('content') or '').strip():
        raise RuntimeError('the model returned no summary')
    return turn['content']


def fit(text):
    """The summary, cut to SUMMARY_MAX_TOKENS. Whole lines are dropped from the
    end, so what survives is complete sentences."""
    lines = [ln.rstrip() for ln in (text or '').strip().splitlines() if ln.strip()]
    while lines and estimate_tokens('\n'.join(lines)) > SUMMARY_MAX_TOKENS:
        lines.pop()
    if not lines:                      # one enormous line: hard cut
        return (text or '').strip()[:SUMMARY_MAX_TOKENS * 3]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def compact(conversation_id):
    """Fold the oldest unsummarised messages of one thread into its summary, if
    the trigger is met. Returns True if the summary changed. Synchronous."""
    conv = AssistantConversation.objects.filter(pk=conversation_id).first()
    if conv is None:
        return False
    rows = plan(conv)
    if not rows:
        return False
    new_summary = fit(summarise(conv.summary, transcript(rows)))
    if not new_summary:
        return False
    # Compare-and-set: if another worker advanced the summary meanwhile, ours is
    # built on stale input and is simply discarded.
    changed = AssistantConversation.objects.filter(
        pk=conv.pk, summary_upto=conv.summary_upto,
    ).update(summary=new_summary, summary_upto=rows[-1]['id'],
             summary_updated_at=timezone.now())
    return bool(changed)


def run(conversation_id):
    """Background entry point: one summariser per thread, never raises, and a
    failed attempt backs off so a broken model is not retried every turn."""
    lock, backoff = (f'ngu:chat:compact:{conversation_id}',
                     f'ngu:chat:compact:backoff:{conversation_id}')
    if cache.get(backoff) or not cache.add(lock, 1, timeout=LOCK_SECONDS):
        return False
    try:
        return compact(conversation_id)
    except Exception:
        logger.exception('Thread compaction failed for conversation %s', conversation_id)
        cache.set(backoff, 1, timeout=BACKOFF_SECONDS)
        return False
    finally:
        cache.delete(lock)


def _thread_main(conversation_id):
    try:
        run(conversation_id)
    finally:
        connection.close()          # a thread owns its own DB connection


def _spawn(conversation_id):
    # Tests run inside a transaction that another thread cannot see (and SQLite
    # cannot share), so a real thread there is only noise.
    if getattr(settings, 'TESTING', False):
        return
    threading.Thread(target=_thread_main, args=(conversation_id,),
                     name=f'compact-{conversation_id}', daemon=True).start()


def schedule(conversation_id):
    """Called after a turn is saved. Costs the request nothing: the work, and even
    the check whether any is due, happens in a background thread."""
    if not ENABLED:
        return
    try:
        _spawn(conversation_id)
    except Exception:
        # Can't start a thread (resource limits, shutdown): the reply is already
        # saved and the summary is only an aid, so this must never surface.
        logger.exception('Could not start thread compaction for %s', conversation_id)
