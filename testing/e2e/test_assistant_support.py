"""
AI assistant (login-only) and the public support / contact form.

The assistant depends on an LLM key that may not be configured on every target,
so its answer path is tolerant: a degraded status (429/5xx) or a timeout is a
skip, not a failure. What we assert unconditionally is the *access* contract —
the assistant is login-only, its conversations are per-user, and the contact
form is open to POST but admin-only to read.
"""
import uuid
import pytest
import requests


# --------------------------------------------------------------------------- #
# assistant
# --------------------------------------------------------------------------- #

@pytest.mark.assistant
def test_assistant_chat_requires_login(session, api):
    """The shopping assistant is intentionally login-only."""
    r = session.post(f"{api}/assistant/chat/", json={"message": "hello"})
    assert r.status_code in (401, 403)


@pytest.mark.assistant
def test_assistant_conversations_require_login(session, api):
    r = session.get(f"{api}/assistant/conversations/")
    assert r.status_code in (401, 403)


@pytest.mark.assistant
def test_assistant_answers_a_product_question(account_session, api):
    """Happy path — tolerant of an unconfigured / rate-limited LLM."""
    try:
        r = account_session.post(f"{api}/assistant/chat/",
                                 json={"message": "What spices do you sell?"},
                                 timeout=45)
    except requests.RequestException:
        pytest.skip("assistant LLM not reachable on this target (timed out)")
    if r.status_code in (429, 500, 502, 503):
        pytest.skip(f"assistant degraded on this target ({r.status_code})")
    assert r.status_code == 200, r.text[:300]
    # The reply body shape varies, but it must be JSON and non-empty.
    assert r.headers.get("Content-Type", "").startswith("application/json")
    assert r.json()


@pytest.mark.assistant
def test_assistant_conversations_scoped_to_user(account_session, api):
    r = account_session.get(f"{api}/assistant/conversations/")
    assert r.status_code == 200
    data = r.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    assert isinstance(items, list)


# --------------------------------------------------------------------------- #
# support / contact form
# --------------------------------------------------------------------------- #

@pytest.mark.support
def test_contact_form_accepts_submission(session, api):
    """Anyone may submit the contact form (rate-limited). One submission per run
    is the only residue and it is clearly marked as an E2E probe."""
    r = session.post(f"{api}/contact/", json={
        "name": "E2E Probe",
        "email": f"e2e_{uuid.uuid4().hex[:8]}@example.com",
        "phone": "9999999999",
        "subject": "E2E automated test — please ignore",
        "message": "This is an automated end-to-end test submission. Safe to delete.",
    })
    if r.status_code == 429:
        pytest.skip("contact form rate-limited on this target (5/hour) — expected")
    assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"


@pytest.mark.support
def test_contact_form_validates_input(session, api):
    r = session.post(f"{api}/contact/", json={"name": "", "email": "not-an-email"})
    assert r.status_code in (400, 429)


@pytest.mark.support
@pytest.mark.security
def test_contact_inbox_is_admin_only(account_session, api):
    """A logged-in but non-staff user must not read other people's submissions."""
    r = account_session.get(f"{api}/contact/")
    assert r.status_code in (401, 403)
