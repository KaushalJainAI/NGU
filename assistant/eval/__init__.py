"""Offline evaluation set for the shopping assistant (AP10).

Real customer-style requests (Hindi, Hinglish, English, Gujarati, Marathi;
multi-item; sizes; order status; policy) replayed through Agent.run with
scripted model turns but REAL tools, validators and fixtures. Measures task
completion, median reply latency and the false-escalation rate.

Live-model comparison: set ASSISTANT_EVAL_LIVE=1 to run the same cases against
the configured provider instead of the scripts (needs valid LLM_API_KEY; the
scripted expectations on exact tool order are then relaxed — see test_eval).
"""
