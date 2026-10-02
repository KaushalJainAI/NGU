# 07 — An AI Assistant That Fails Politely

> Source: `Backend/assistant/agent.py`, `Backend/assistant/views.py`,
> `Backend/assistant/tools.py`; findings A2–A5 in `AUDIT_AND_PLAN_2026-10.md`
> Fixed: 2026-10-01 · Tests: `Backend/assistant/test_llm_failure.py`,
> `test_agent_escalation.py`, `test_chat_limits.py`, `test_guardrails.py`

---

## What an audit of the assistant found

The chat assistant worked in the demo. An audit that deliberately broke things
found four problems. None of them is about how clever the model is. All of them
are about what happens around it.

| # | Finding | What the customer saw |
|---|---|---|
| A2 | A provider error became a 500 | Their message saved, no reply, an error |
| A3 | A request with several items failed | "haldi, jeera, dhaniya, mirch" → an apology |
| A4 | Every failure was escalated to a human | — (the owner's inbox filled up) |
| A5 | "Our team has been notified" was not true | A promise nobody kept |

---

## A2 — The model call can fail, and nothing caught it

The agent called the model and used the answer. If the provider timed out,
returned an error, or the API key had been revoked, the exception travelled up
and the customer got a server error.

An outside service **will** fail. The fix is to decide in advance what the
customer sees:

```python
try:
    turn = self._complete(messages)
except Exception:
    logger.exception("Assistant LLM call failed")
    return {'reply': FALLBACK_REPLY, 'proposed_action': None,
            'escalate': False, 'llm_used': True, 'reason': 'llm_error', ...}
```

Two more limits were added, because "it failed" was not the only bad outcome.
"It hung" is worse:

- **20 seconds per model call**, with one retry. The web server can handle six
  requests at a time. A chat request that waits two minutes holds one of those
  six, and checkout shares them.
- **One message in progress per account.** `cache.add` sets a key only if it is
  absent. A second message while the first is still running gets a 429. The key
  is claimed *before* the message is saved, so a refused message leaves nothing
  behind in the thread.

## A3 — One tool call per round was too few

The loop allowed four rounds, and the model made one lookup per round. Four
spices used all four rounds and there was none left for the answer.

The fix was to let one round contain several tool calls. The loop runs all of
them and sends all the results back together:

```python
for call in calls:
    if name in self._read_tools:
        observation = self._run_read_tool(name, self.user, args)
        messages.append(('user', _spotlight(name, observation)))
```

The limit of four rounds stayed. Limits like this are what keep the cost of one
message bounded.

## A4 — A failure is not a reason to call a human

The old rule was "if the assistant could not answer, flag the conversation for
a human". It sounds caring. In practice every timeout, every unreadable reply
and every exhausted loop became a ticket. With a revoked API key, *every chat*
would have become one.

A reply cut off by the output limit also counted as "unreadable". Long list
answers, especially in Hindi or Gujarati script (which use more tokens), were
the most likely to be cut.

The fix is to say **why** a turn ended, and act on the reason:

| `reason` | Meaning | Flag a human? |
|---|---|---|
| `ok` | Answered | No |
| `llm_error` | Provider failed or the reply was unreadable | No |
| `loop_exhausted` | Four rounds used up | No |
| `customer_asked` | The customer asked for a person | **Yes** |

```python
if result.get('reason') == 'customer_asked' and not conversation.needs_human:
    conversation.needs_human = True
    ...
```

Only one thing flags a human: the model calling the `escalate_to_human` tool,
which it is told to do only when the customer asks. A model failure is *our*
problem. It should show up in our logs, not in the owner's inbox.

A reply that was cut off is now detected from the provider's `finish_reason`,
and a line is added telling the customer the answer was shortened.

## A5 — Do not say what is not true

When a conversation was flagged, the customer was told the team had been
notified and would join shortly. But flagging only set a field in the database.
The owner found out the next morning, in the daily email.

The fix: when a conversation is flagged, an email is sent to the owner at once.
The sentence became true.

This is the smallest change of the four and maybe the most important. A system
that says friendly things it does not do is worse than a plain one.

---

## One more: "Let me check that for you"

Models often write a short sentence and call a tool in the same reply. The old
loop took any text as the final answer. So the customer got "Let me check that
for you" and nothing else.

The loop now tracks whether this round produced something the model has not
seen yet:

```python
if awaiting_answer and not last_round:
    continue        # go round again so the reply is written WITH the results
```

Text written before a lookup returned is not the answer to the question.

---

## The general lesson

> **Design the failure before the feature.** For every outside call, decide:
> how long will I wait, what does the user see if it fails, who is told, and
> what does it cost if someone repeats it a thousand times?

For an AI feature specifically:

1. **The model is a slow outside service.** Give it a timeout and a fallback,
   like any other.
2. **Bound the cost.** Rounds per message, messages per minute and per day,
   one in progress at a time, a token budget for history.
3. **Separate "our failure" from "the user needs help".** They need different
   reactions.
4. **Do not let it act alone.** Read tools run on the server for the logged-in
   user. Anything that changes state is a proposal the customer confirms.
5. **Only promise what the code does.**

A last honest point about testing. Most of the assistant's tests replace the
model with a scripted fake. They prove the loop, the tools and the checks work.
They do not prove the real model behaves well. There is a separate live mode
for that. Know which one you are quoting when you say "it's tested".

---

## Interview questions

1. *Your app calls an LLM. What happens when the provider is down?*
   → The call has a timeout. The error is caught and the user gets a fallback
   message. Nothing is escalated and nothing returns a 500.

2. *How do you stop a chat feature from eating your web workers?*
   → A timeout per model call, a cap on rounds, one request in progress per
   account, and rate limits per minute and per day.

3. *When should an AI assistant hand over to a human?*
   → When the customer asks. Not when the model fails. Give each outcome a
   reason code and only act on the right one.

4. *The model returns text and a tool call together. Which is the answer?*
   → Neither yet. Run the tool, feed the result back, and take the text from
   the next round.

5. *How do you keep cost per message bounded?*
   → A fixed number of rounds, a limit on output tokens, and a budget for how
   much history is sent, dropping the oldest messages first.

6. *How do you test an agent?*
   → A scripted fake model for the loop and tools. Separate runs against the
   real model for behaviour. Report them separately.
