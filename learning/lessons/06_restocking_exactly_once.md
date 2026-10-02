# 06 — Restocking Exactly Once

> Source: `Backend/orders/views.py::restore_order_stock`,
> `Backend/orders/refunds.py::record_refund`,
> `Backend/payments/management/commands/reconcile_payments.py`
> Changed: 2026-08-02 · Tests: `Backend/orders/test_refunds.py`,
> `Backend/orders/test_checkout_and_ops.py`

---

## The situation

When an order is placed, its units leave the shelf. When the sale is undone,
they must come back. There are four ways a sale gets undone:

| Path | Who | Code |
|---|---|---|
| The customer cancels | Customer | `OrderViewSet.cancel` |
| The owner sets the status to cancelled | Owner | `OrderViewSet.update` |
| An online order is unpaid for 15 minutes | Scheduler | `reconcile_payments._cancel_abandoned` |
| A refund is recorded | Owner | `record_refund` |

---

## Problem 1: the same units can come back twice

Two of those paths can happen to one order. The owner cancels a paid order,
then records the refund for it. Or the scheduler cancels an order and the owner
refunds it later.

If each path simply adds the units back, an order for 5 packs returns 10. The
shop then shows stock that does not exist, and sells packs it cannot send.

Nothing would crash. Counting the shelf is the only way anyone would find out.
This became a live risk on the day refunds started returning stock, so the
guard below was added in the same change.

### The fix: a function that remembers it has run

```python
def restore_order_stock(order):
    if order.stock_restored_at is not None:
        return False                      # already done: do nothing

    ...  # add the units back

    order.stock_restored_at = timezone.now()
    Order.objects.filter(pk=order.pk).update(stock_restored_at=order.stock_restored_at)
    return True
```

One timestamp on the order. The first call does the work and sets it. Every
later call sees it and returns. A function that is safe to call many times is
**idempotent**.

Two details in those last lines:

- The stamp is written with `.update()` **and** set on the object in memory.
  Some callers never save the order afterwards; the `.update()` makes sure the
  stamp is stored anyway. Other callers do a full `order.save()` afterwards;
  setting it in memory stops that save from writing an old empty value over it.
- The function must be called **inside a transaction with the order locked**.
  Otherwise two calls at the same moment could both read "not restored yet".

All four paths now call this one function. That is the second half of the fix:
**one place** that knows how to restock.

---

## Problem 2: the wrong shelf

A combo is a box of several sizes. At checkout, buying one box subtracts from
each component **variant** (the specific size). The tempting mistake when
writing the restore is to add the units back to `Product.stock` instead.

`Product.stock` is an old field that nothing sells from. So the real, sellable
stock would go down for ever, while a number nobody uses goes up. The code
comment puts it exactly: it "would destroy the sellable stock while inflating
the legacy display mirror nothing sells from."

The rule this teaches: **undo must mirror do.** Whatever checkout subtracts
from, restore must add to. The simplest way to guarantee that is to write the
two functions side by side and test them as a pair: place an order, cancel it,
and check every stock number is back where it started.

---

## Problem 3: undoing from today's recipe

To restore a combo line, the code needs to know which sizes were in the box.
The first idea is to look at the combo's recipe.

But the owner can edit a combo. Suppose that between the order and the
cancellation they swap the 100 g pack for a 200 g pack. Reading today's recipe
would add stock to the 200 g pack, which the order never took, and never return
the 100 g pack, which it did take. Two numbers wrong, silently.

### The fix: undo from what was recorded

At checkout the order writes one `OrderItemComponent` row per component: which
variant, how many units. Restore reads **those rows**, not the live recipe.

```python
components = list(item.components.all())
if components:
    for comp in components:
        variant_updates[comp.variant_id] = variant_updates.get(comp.variant_id, 0) + comp.quantity
```

There is a small trap here that the comments point out. `comp.quantity` is
already the total for the line (per-box amount × number of boxes). Multiplying
by the line quantity again would return too much.

For old orders made before these rows existed, the code falls back to the live
recipe. The comment admits this may be wrong if the combo was edited, and that
it is all there is.

---

## A deliberate simplification

A **partial** refund returns the stock of the **whole** order, once.

Why: a refund records an amount of money. It does not say which items came
back. The choices were to guess the items from the amount, or to return
everything on the first refund. Under-returning a real return was judged the
worse mistake, so the whole order is returned. This is a known imprecision, and
it is written down in the code.

Being able to say "here is a simplification, here is why, here is what it gets
wrong" is worth more in an interview than pretending the design is perfect.

---

## The general lesson

> **If more than one path can trigger an effect, the effect must be safe to
> trigger twice.** Put it in one function and give that function a memory.

And:

> **Undo from the record of what was done, not from the current state of the
> world.** The world has moved on.

The same shape appears in [Part 2 §7](../02_LLD_Object_Model_and_Flows.md)
(a payment confirmed once though three callers try) and in refunds (a gateway
refund id stored under a unique constraint).

---

## Interview questions

1. *What does idempotent mean? Give an example you built.*
   → Running it twice has the same effect as once. Restocking: the first call
   stamps a timestamp on the order, later calls do nothing.

2. *Why a timestamp and not a boolean?*
   → It answers "when" for free, which helps when investigating. `NULL` already
   means "not yet".

3. *Is the timestamp check enough under concurrency?*
   → Only with a lock. Two calls at once could both see it empty. The function
   requires the order row to be locked by the caller.

4. *You restore a bundle's stock from its definition. What can go wrong?*
   → The definition may have changed since the order. Restore from the snapshot
   written at order time.

5. *How would you test this?*
   → Record all stock numbers. Place an order, then undo it by each path, and
   by two paths in a row. The numbers must equal the starting values every
   time.
