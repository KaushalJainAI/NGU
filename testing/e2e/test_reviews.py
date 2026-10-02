"""
Reviews — verified-purchase gating and the can-review UX hint.

The write path requires a *confirmed* order containing the item, which a
black-box client can only obtain by actually paying (see the netbanking browser
test). So the guard behaviours below run everywhere, and the happy path is
opportunistic: it runs only if the reusable account already has a reviewable
purchase (e.g. after a payment test), and cleans up the review it creates.
"""
import uuid
import pytest

from conftest import first_in_stock_product

MAX_REVIEW_COMMENT = 2000


@pytest.mark.review
def test_reviews_list_is_public(session, api):
    r = session.get(f"{api}/reviews/")
    assert r.status_code == 200


@pytest.mark.review
def test_post_review_requires_auth(session, api):
    p = first_in_stock_product(session, api)
    r = session.post(f"{api}/reviews/", json={
        "item_type": "product", "product": p["id"], "rating": 5,
        "title": "nice", "comment": "great"})
    assert r.status_code in (401, 403)


@pytest.mark.review
def test_review_without_purchase_is_rejected(account_session, api):
    """The core guard: you cannot review an item you never bought."""
    # Pick a product the reusable account is unlikely to have a confirmed order
    # for; if it happens to be reviewable, skip (the happy-path test covers that).
    p = first_in_stock_product(account_session, api)
    can = account_session.get(f"{api}/reviews/can-review/", params={"product": p["id"]})
    if can.status_code == 200 and can.json().get("can_review") is True:
        pytest.skip("account already eligible to review this product")
    r = account_session.post(f"{api}/reviews/", json={
        "item_type": "product", "product": p["id"], "rating": 5,
        "title": "t", "comment": "unverified"})
    assert r.status_code == 400
    assert "confirmed" in r.text.lower() or "deliver" in r.text.lower()


@pytest.mark.review
def test_can_review_requires_auth(session, api):
    r = session.get(f"{api}/reviews/can-review/", params={"product": 1})
    assert r.status_code in (401, 403)


@pytest.mark.review
def test_can_review_requires_exactly_one_target(account_session, api):
    both = account_session.get(f"{api}/reviews/can-review/",
                               params={"product": 1, "combo": 1})
    assert both.status_code == 400
    neither = account_session.get(f"{api}/reviews/can-review/")
    assert neither.status_code == 400


@pytest.mark.review
def test_can_review_reports_not_purchased(account_session, api):
    p = first_in_stock_product(account_session, api)
    r = account_session.get(f"{api}/reviews/can-review/", params={"product": p["id"]})
    assert r.status_code == 200
    body = r.json()
    assert "can_review" in body
    if body["can_review"] is False:
        assert body["reason"] in ("not_purchased", "already_reviewed")


@pytest.mark.review
def test_oversized_comment_rejected_not_500(account_session, api):
    p = first_in_stock_product(account_session, api)
    r = account_session.post(f"{api}/reviews/", json={
        "item_type": "product", "product": p["id"], "rating": 5,
        "title": "t", "comment": "x" * (MAX_REVIEW_COMMENT + 50)})
    assert r.status_code == 400


@pytest.mark.review
def test_verified_review_happy_path_when_eligible(account_session, api):
    """Opportunistic: if the account has a reviewable purchase, post a review and
    assert it comes back verified — then delete it to stay self-cleaning."""
    products = account_session.get(f"{api}/products/")
    data = products.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data
    target = None
    for p in items:
        can = account_session.get(f"{api}/reviews/can-review/", params={"product": p["id"]})
        if can.status_code == 200 and can.json().get("can_review") is True:
            target = p
            break
    if not target:
        pytest.skip("no reviewable (purchased + confirmed) product for this account")

    created = account_session.post(f"{api}/reviews/", json={
        "item_type": "product", "product": target["id"], "rating": 5,
        "title": f"E2E {uuid.uuid4().hex[:6]}", "comment": "Verified-purchase E2E review."})
    assert created.status_code in (200, 201), created.text[:300]
    review = created.json()
    assert review.get("is_verified_purchase") is True
    review_id = review.get("id")
    if review_id:
        account_session.delete(f"{api}/reviews/{review_id}/")  # cleanup
