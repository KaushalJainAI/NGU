"""Eval runner (AP10): replays assistant/eval/cases.py through Agent.run.

Scripted model turns, REAL tools/validators/fixtures. Prints task completion,
median reply latency and the false-escalation rate; the closing summary test
fails the suite if any case escalated without being asked.
"""
import os
import statistics
import time
from copy import deepcopy
from decimal import Decimal

import pytest

from assistant.agent import Agent
from assistant.eval.cases import CASES
from products.models import Product, ProductVariant

RESULTS = []
LIVE = os.getenv('ASSISTANT_EVAL_LIVE') == '1'


def _make_product(test_category, name, variants=()):
    from conftest import create_test_image
    p = Product.objects.create(
        name=name, category=test_category, description=f'{name} description',
        price=Decimal('100.00'), stock=50, weight=Decimal('100.00'), unit='g',
        spice_form='powder', is_active=True,
        image=create_test_image(f'{name[:4]}.jpg'))
    ProductVariant.objects.filter(product=p).update(is_default=False)
    out = []
    for i, (weight, price, stock, default) in enumerate(variants):
        out.append(ProductVariant.objects.create(
            product=p, weight=Decimal(str(weight)), unit='g',
            price=Decimal(str(price)), stock=stock,
            is_default=default, is_active=True, display_order=i))
    return p, out


@pytest.fixture
def refs(db, test_category, test_user, test_user2, test_order, test_combo):
    """Live catalog ids the scripted turns reference symbolically."""
    from orders.models import Order
    haldi, (h100, h500, h1kg_oos) = _make_product(
        test_category, 'Eval Haldi Powder',
        [(100, 100, 10, True), (500, 450, 8, False), (1000, 800, 0, False)])
    jeera, (j100,) = _make_product(
        test_category, 'Eval Jeera Whole', [(100, 120, 10, True)])
    jeeravan, _ = _make_product(test_category, 'Nidhi Jeeravan', [])
    other = Order.objects.create(
        user=test_user2, shipping_address='1 St', phone_number='9999999999',
        payment_method='COD', subtotal=Decimal('240.00'), tax=Decimal('24.00'),
        total_amount=Decimal('264.00'), status='pending')
    item = test_order.items.first()
    if item is not None and item.item_type == 'product' and item.product_id:
        reorder = {'product_id': item.product_id, 'item_type': 'product', 'quantity': 1}
    else:
        reorder = {'product_id': test_combo.id, 'item_type': 'combo', 'quantity': 1}
    return {
        '$haldi500': h500.id, '$haldi100': h100.id, '$haldi500_oos': h1kg_oos.id,
        '$jeera100': j100.id, '$combo': test_combo.id,
        '$haldi_slug': haldi.slug, '$jeeravan_slug': jeeravan.slug,
        '$myorder': f'ORD-{test_order.id:06d}',
        '$otherorder': f'ORD-{other.id:06d}',
        '$reorder_lines': [reorder],
    }


def _resolve(node, refs):
    if isinstance(node, dict):
        if set(node) == {'$reorder_line'}:
            return {'__reorder__': True}
        return {k: _resolve(v, refs) for k, v in node.items()}
    if isinstance(node, tuple):
        # Scripted calls are (name, args) tuples — recurse into the args.
        return tuple(_resolve(v, refs) for v in node)
    if isinstance(node, list):
        flat = []
        for v in node:
            r = _resolve(v, refs)
            if isinstance(r, dict) and set(r) == {'__reorder__'}:
                flat.extend(refs['$reorder_lines'])
            else:
                flat.append(r)
        return flat
    if isinstance(node, str) and node in refs and not node.startswith('$reorder'):
        return refs[node]
    return node


def _fake_completion(script):
    it = iter(deepcopy(script))

    def run(messages):
        turn = next(it)
        if isinstance(turn, dict) and 'raise' in turn:
            raise TimeoutError('eval simulated outage')
        content = turn.get('content')
        calls = [{'name': n, 'args': a} for n, a in turn.get('calls', ())]
        return {'content': content, 'tool_calls': calls,
                'finish': turn.get('finish', 'stop')}
    return run


def _case_ids():
    return [c['id'] for c in CASES]


@pytest.mark.django_db
@pytest.mark.parametrize('case', CASES, ids=_case_ids())
def test_eval_case(case, refs, test_user, test_admin, monkeypatch):
    user = test_admin if case.get('persona') == 'admin' else test_user
    script = _resolve(case['script'], refs)
    if LIVE:
        agent = Agent(user, persona=case.get('persona', 'customer'))
    else:
        monkeypatch.setattr('assistant.agent._build_llm', lambda: object())
        agent = Agent(user, completion=_fake_completion(script),
                      persona=case.get('persona', 'customer'))
    start = time.perf_counter()
    out = agent.run(case['message'], language=case.get('lang', 'en'))
    ms = (time.perf_counter() - start) * 1000
    RESULTS.append({'id': case['id'], 'ms': ms,
                    'escalate': bool(out.get('escalate')),
                    'expected_escalate': bool(case['expect']['escalate'])})
    if LIVE:
        assert out.get('reply'), 'live run produced no reply'
        assert out.get('escalate') is False
        return
    expect = case['expect']
    assert [s['tool'] for s in out['sources']] == expect['tools']
    proposal = out.get('proposed_action')
    assert (proposal or {}).get('type') == expect['proposal']
    assert out.get('escalate') is expect['escalate']
    for needle in expect.get('reply_contains', ()):
        assert needle.lower() in (out.get('reply') or '').lower()


def test_zz_eval_summary():
    assert RESULTS, 'no eval cases ran'
    total = len(RESULTS)
    completed = sum(1 for r in RESULTS if r['expected_escalate'] == r['escalate'])
    false_escalations = [r['id'] for r in RESULTS
                         if r['escalate'] and not r['expected_escalate']]
    median_ms = statistics.median(r['ms'] for r in RESULTS)
    print(f'\nEVAL: {completed}/{total} completion, '
          f'median {median_ms:.1f} ms/turn, '
          f'false escalations: {false_escalations or "none"}')
    assert not false_escalations
