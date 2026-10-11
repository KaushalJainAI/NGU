# 10 — Timeouts That Nest, and Replies in the Right Language

> Source: `Backend/assistant/agent.py`, `Backend/assistant/prompts.py`,
> `Backend/assistant/lang.py`, `Backend/assistant/faq.py`,
> `Backend/assistant/views.py`; plan in `ASSISTANT_FIX_PLAN_2026-10.md`
> Fixed: 2026-10-03 · Tests: `Backend/assistant/tests.py` (sections chat_improvements,
> faq)

---

## The symptom

The shop owner said three things about the chat assistant:

1. "Sometimes it does not answer."
2. "When it can't answer, it always speaks English."
3. "It spends tokens on questions that have the same answer every day."

They sound like three problems. They have one thing in common: **nobody had
checked how the limits fit together.**

---

## 1. Limits that are each fine and together are not

Every limit on the chat had a reason:

| Limit | Value | Reason |
|---|---|---|
| One model call | 20 s | do not hold a web worker for ever |
| Retries | 1 | one transient error should not fail a message |
| Rounds per message | 4 | bound the cost |
| The storefront's web server (nginx) waits for `/api/` | 60 s | its default for slow requests |

Multiply the first three: 4 rounds × 20 s × 2 attempts = **160 seconds**. The web
server gives up at 60. For a slow model the customer saw "something went wrong"
at 60 seconds while the backend carried on, finished the answer at 100 seconds,
saved it, and paid for it. Nobody saw it.

> Timeouts must **nest**: each inside the one around it. A call timeout is only
> meaningful if the total it can add up to still fits inside the outer limit.

The fix gave the whole message a budget, which is the missing middle layer:

```python
if iteration and _clock() - started + LLM_REQUEST_TIMEOUT > TURN_BUDGET_SECONDS:
    return {'reply': canned('slow'), ... 'reason': 'loop_exhausted'}
```

A new round starts only if it could still finish inside 45 seconds. The retry was
removed (a retry of a 20 s timeout is another 20 s of waiting). The result is an
order that is easy to state and easy to test:

```
model call 20 s  <  whole message 45 s  <  nginx 60 s
```

The tests do not wait 45 real seconds. `_clock()` is a one-line function so a
test can replace it with a fake clock that jumps 30 seconds per reading.

A related trap: a "reasoning" model spends output tokens on thinking. If it uses
them all, the reply is **empty** and `finish_reason` is `length`. The old code
then asked again — and got the same result. Now it answers at once with the
fallback. Prod had the reasoning effort on `high`, which made both the slowness
and the emptiness more likely.

---

## 2. A fallback is also a reply

The four canned replies (sorry, too many items, handed to the team, "continued")
were English strings. They are shown exactly when no model wrote the answer — so
the model's language instructions cannot help. A Hindi customer got an English
apology.

The fix is a table, `FAILURE_REPLIES[kind][language]`, and a function that picks
the language: the customer's choice if they made one, otherwise **the script of
their message** (Devanagari → Hindi, Gujarati script → Gujarati, and so on).
Roman letters with two or more common Hindi words are Hinglish.

Two things are worth noticing:

- **Devanagari cannot tell Hindi from Marathi.** Detection stops there. A Marathi
  customer has to have picked Marathi — so the storefront sends the site language
  along with the suggested-question buttons.
- **A test makes the table complete.** It fails if any kind is missing a language
  or if a translation is just a copy of the English. Add a seventh language and
  the test tells you everything you forgot.

---

## 3. A question with one answer should not need a model

"How long does delivery take?" has the same answer for every customer. Sending it
to a language model costs money, takes seconds, and can be wrong.

The answers now live in a plain file, `faq_data.json`, which the owner can read
and edit. `faq.py` finds the right entry by fuzzy string comparison
(`rapidfuzz`) — no model, no network, no tokens.

Two details matter more than the matching itself:

- **Numbers are placeholders.** The file says `{free_above}`, not `499`. The real
  value is read from `limits.py` when the file loads. This is the same bug as the
  499/500 split of 2026-08-05, prevented. A test fails if `499` is ever typed into
  an answer.
- **Two confidence levels.** The `search_faq` tool shows the model up to three
  candidates above a low score. The *word-for-word* path needs a very high score,
  a clear lead over the runner-up, at least two meaningful words, `direct: true`
  in the file, no open `review` note, and an answer in the customer's language.
  When in doubt it returns nothing and the question goes to the model as before.

  "delivery" alone does not qualify (time? charge? area?). "I want to talk to a
  human" must never be swallowed. "Where is order 123?" depends on the customer, so
  that entry is marked `direct: false`.

The suggested-question buttons under the greeting are worded exactly like
questions in the file, so a tap is a certain hit. A test reads the six locale
files and fails if a button stops matching.

---

## 4. Measure a saving before you claim it

The plan said: "the tool list is sent twice — once as text, once as function
schemas — remove the text copy." The first attempt removed ~1,000 tokens of text,
and then added ~600 back with longer schema descriptions and two new tools. A
measurement script showed the net saving was **21 tokens**.

Trimming the new descriptions and the prompt's repeated sections gave the real
number: **4,122 → 3,543 estimated tokens per model call (−14%)**, roughly 1,700
tokens over a three-round message. A test pins the bound so it cannot creep back.

> The plan's number was a prediction. The measured number is the one to write
> down.

---

## What to remember

> Every limit is fine on its own. Check that they add up to less than the limit
> outside them — and that the words shown when something fails are in the
> customer's language.

---

## Interview questions

**1. A request makes up to 4 calls, each with a 20-second timeout and one retry,
behind a 60-second proxy timeout. What is wrong, and how do you fix it?**
The worst case (160 s) is longer than the outer limit (60 s), so the client gives
up while the server keeps working. Add a budget for the whole request that is
smaller than the proxy timeout, and only start a step that can still finish
inside it.

**2. Why make the clock a function you can replace?**
So a test can simulate 30 seconds passing without waiting. Time is an input; tests
control inputs.

**3. Why are canned error messages a design problem and not just copy?**
They are shown precisely when the smart part has failed, so nothing can adapt them.
They need to be complete in every supported language, and a test should enforce it.

**4. When is it safe to answer without calling the model?**
Only when a wrong answer is unlikely: a very close match, a clear gap to the
second-best, enough words to mean something, a human-approved answer, and nothing
that depends on the customer's own data. Otherwise fall through to the model.

**5. Why put `{free_above}` in an answer instead of the number?**
So the answer cannot disagree with what checkout charges. There is one source of
truth, and the text reads from it.

**6. A change was meant to cut token cost. How do you know it did?**
Measure before and after with the same estimator, on the real prompt and schemas.
Adding a feature in the same change can cancel the saving.
