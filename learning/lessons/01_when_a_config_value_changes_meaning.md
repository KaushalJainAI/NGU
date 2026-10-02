# 01 — When a Config Value Changes Meaning

> Source: `Backend/spices_backend/limits.py`, `Backend/orders/apps.py`,
> `Frontend/nidhi-brand-forge/docker-entrypoint.d/40-runtime-config.sh`
> Changed: 2026-08-04

---

## The situation

Delivery used to cost a flat **₹69**, with no tax on it. The setting was:

```env
SHIPPING_CHARGE=69
```

Then delivery became a taxed service: **₹59 plus 18% GST = ₹69.62**. The
customer pays almost the same. But the number in the setting now has to mean
something different:

| | Before | After |
|---|---|---|
| What the number means | What the customer pays | The fee *before* tax |
| Value | 69 | 59 |
| Tax | none | 18% added on top |

Every deployed environment still had `SHIPPING_CHARGE=69` in its env file.

---

## The trap

Suppose the new code kept the old name. Look at what each order of steps does:

| Steps | What customers are charged |
|---|---|
| Ship the new code, forget the env | 69 + 18% = **₹81.42** (too much) |
| Change the env to 59 first, then ship the code | **₹59** with no tax, until the code arrives (too little) |
| Ship the code first, change the env a minute later | ₹81.42 for that minute |

There is **no safe order**. Any manual plan has a window where real customers
get a wrong bill. And the failure is silent: nothing crashes, the number is
simply wrong.

The root problem is that the *meaning* of the value changed while its *name*
stayed the same. Old values are valid input to the new code. They are just
interpreted differently.

---

## The fix: rename it

```python
# limits.py
SHIPPING_CHARGE_NET = config("SHIPPING_CHARGE_NET", default=Decimal("59"), cast=Decimal)
SHIPPING_TAX_RATE   = config("SHIPPING_TAX_RATE",   default=Decimal("18"), cast=Decimal)

# Read only so that start-up can warn about it. It never affects a price.
LEGACY_SHIPPING_CHARGE = config("SHIPPING_CHARGE", default=None)
```

Now an environment that still says `SHIPPING_CHARGE=69` is harmless. Nothing
reads that name for pricing. The new name is not set anywhere, so the correct
default (59) applies everywhere at once. **No env edit is needed to deploy
safely**, in any order.

Two more pieces finish the job.

**1. Say something at start-up.** A dead setting left in an env file is a trap
for the next person who reads it. So `orders/apps.py` logs a warning at boot if
the old variable is still set, and the storefront container prints one too.

**2. A warning, not a crash.** The code comment explains the choice: pricing is
already correct, and taking the whole API down over a leftover line would be a
far worse outage than the tidy-up it asks for. (Compare with
[lesson 04](04_a_boot_guard_and_the_whole_api.md), where a crash at
start-up *was* the right call.)

There is also a small compatibility line inside the code:

```python
SHIPPING_CHARGE = SHIPPING_CHARGE_NET   # the Python name the rest of the code imports
```

That is fine. The *Python* name can stay. It was the *environment variable* name
that had to change, because that is what the old deployments hold.

---

## The general lesson

> **If a value's meaning changes, change its name.** Then old values become
> unknown input, which is ignored, and not valid input, which is misread.

This applies far beyond env variables:

- A JSON field in an API whose unit changes from rupees to paise.
- A database column that used to hold a tax-inclusive amount and now holds a
  net amount.
- A queue message whose `amount` changes currency.

In each case, a new name (`amount_paise`, `net_amount`) lets old and new
readers and writers exist together during the rollout.

A related idea: **make the dangerous state impossible, instead of writing a
checklist.** "Remember to update the env before deploying" is a checklist. The
rename removes the step.

---

## Interview questions

1. *You need to change what a config value means. How do you roll it out?*
   → Add a new name with the new meaning. Stop reading the old name. Warn if
   the old one is still present. Remove it later. Never reuse the name.

2. *Why not just update the environment file at the same time as the deploy?*
   → "At the same time" does not exist across machines. There is always an
   order, and here both orders bill someone wrongly.

3. *When should a config problem crash the app, and when should it only warn?*
   → Crash when running would do real harm (charging real cards from a test
   build). Warn when the app is already behaving correctly and the problem is
   only untidiness.

4. *What is the difference between an additive change and a breaking one?*
   → Additive: old readers still work (a new field, a new name). Breaking: old
   input is now read differently. Turn breaking changes into additive ones by
   adding a new name.
