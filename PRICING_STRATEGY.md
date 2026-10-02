# Nidhi Masala — Competitor Prices, Shipping Policies and Pricing Strategy

**Date:** 2026-10-01
**Scope:** Spice / masala / papad sellers that matter in Madhya Pradesh, with weight on Indore–Malwa. Online prices, wholesale (IndiaMART) prices, shipping policies, and what Nidhi should do about them.
**Companion doc:** `LAGAT_AUR_CASHFLOW_HINDI.pdf` (5 Aug 2026) — that one covers *your costs*; this one covers *the market*. Read them together.

---

## 0. Read this first — what the numbers are and are not

| Data | Source | How much to trust it |
|---|---|---|
| Pushp / Munimji prices | Pushp's own store API, read 2026-10-01 | High — exact, per pack |
| Indore D2C stores (Prakash, Aakash, Om, Maa Kaa Achar, Panchal) | Their own websites, 2026-10-01 | High for what is quoted; some pages did not show pack size |
| National brands (Everest, MDH, Catch, Badshah, Tata Sampann) | BigBasket / Blinkit / Amazon listings via search | Medium — these change daily and by city |
| IndiaMART Indore listings | IndiaMART directory pages | Low–medium — these are sellers' *asking* prices, often for bulk, and quality varies wildly |
| **Nidhi prices** | §2: `Backend/demo/live_products.json`, a June 2026 snapshot. §5b: the live catalogue API, read 2026-10-01 | §2 covers the 25 June products at one size each and was not redone; the sale prices of those sizes are unchanged on the live site. §5b is the full live catalogue (28 products, 45 sizes). |
| Nidhi cost of goods | Not known. The August cost report *assumed* 65% of net price | ⚠ This is the single biggest unknown in the whole exercise |

**Not done — needs you on foot:** I could not get real shelf prices from Indore kirana stores, Siyaganj wholesalers or D-Mart, and I found no usable offline customer reviews (Google Maps / Justdial review text is not retrievable this way). "Offline" in this document therefore means printed MRP plus IndiaMART wholesale asks. §8 has a short checklist for a one-hour market visit that would close this gap.

---

## 1. Who you are actually competing with

The MP market splits into five groups. They price very differently, and you only need to beat one or two of them.

| Group | Who | How they price | Are they your competition? |
|---|---|---|---|
| **1. The regional giant** | **Pushp** (Indore, since 1974; claims ~20.7% of MP packaged spices) and its mass brand **Munimji** | Pushp: mid-premium MRP, 12–35% "sale" discount online. Munimji: 15–45% cheaper than Pushp | **Yes — directly.** Your whole catalogue was priced off Pushp in June |
| **2. National brands** | Everest, MDH, Catch, Badshah, Tata Sampann | Similar or lower than Pushp, delivered in 10 minutes by Blinkit/BigBasket | On plain powders (haldi, dhaniya, mirchi) — yes, and you lose. On Indori items — no |
| **3. Indore namkeen houses selling masala online** | Prakash Namkeen, Aakash Namkeen, Om Namkeen, Agrawal's 420 | Masala is a side item; shipping thresholds are high (₹699–900) | Yes for jeeravan, papad, katran |
| **4. Premium D2C** | Maa Kaa Achar (Indore), Zoff, Phoran, Home Kouzina | 2–3× the price, low free-shipping threshold (₹199–249) | They show the price ceiling for "authentic Indori" |
| **5. Unbranded / local Indore makers** | Hariom, Medatwal, Gupta, Sunder, Dilkhush, dozens more on IndiaMART | Very cheap, sold loose or in plain pouches to kirana and halwai | Offline only. You cannot and should not match them online |

---

## 2. Price comparison — product by product

All prices in ₹. "MRP / sale" = struck-through price / price actually charged.

### 2a. Nidhi vs Pushp (your direct benchmark)

Pushp has **raised six prices since you copied them in June**. You are now cheaper than Pushp on those without having decided to be.

| Nidhi product | Nidhi MRP / sale (June) | Pushp today MRP / sale | Gap on sale price |
|---|---|---|---|
| Pav Bhaji Masala 100g | 96 / 79 | 102 / 84 | Nidhi ₹5 cheaper |
| Kitchen King 100g | 96 / 78 | 102 / 83 | Nidhi ₹5 cheaper |
| Chana Masala 100g | 96 / 78 | 102 / 83 | Nidhi ₹5 cheaper |
| Garam Masala 100g | 105 / 87 | Box 106 / 81 · Jar 109 / 90 | Nidhi ₹6 dearer than box, ₹3 cheaper than jar |
| Chat Masala 100g | 89 / 73 | 89 / 73 | Same |
| Jeeravan 100g | 68 / 44 | Sprinkler 68 / 44 · Pouch 53 / 46 | Same |
| Garadu Masala 100g | 68 / 60 | 68 / 60 | Same |
| Tea Masala 50g | 72 / 53 | 72 / 53 | Same |
| Kashmiri Mirchi 100g | 130 / 104 | 130 / 104 | Same |
| Dry Ginger 100g | 100 / 86 | 100 / 86 | Same |
| Kasuri Methi 25g | 32 / 28 | 32 / 28 | Same |
| Haldi 500g | 235 / 202 | 244 / 210 | Nidhi ₹8 cheaper |
| Dhaniya 500g | 209 / 180 | 233 / 200 | Nidhi ₹20 cheaper |
| Amchur 500g | 290 / 238 | 307 / 252 | Nidhi ₹14 cheaper |
| Achar Masala 500g | 233 / 191 | 233 / 191 | Same |
| Achar Masala 200g (Hari Mirchi, Nimbu) | 94 / 79 | 94 / 79 | Same |
| VIP Teja Mirchi 500g | 328 / 280 | Tikha Tadka 328 / 280 | Same |
| Desi Tadka Mirchi 500g | 264 / 227 | Shahi Rangat 264 / 227 · Red Chilli 357 / 304 | See note |
| Patna Mirchi 500g | 381 / 324 | No Pushp chilli at this price today | See note |

**Note on the chillies.** `DATABASE_FILLING.md` says Patna was matched to Pushp "Shahi Rangat" and Desi Tadka to Pushp "Red Chilli". Today the numbers line up the other way round: Desi Tadka equals Shahi Rangat exactly, and Patna (₹324) sits ₹20 *above* Pushp's Red Chilli (₹304). Either Pushp repriced or the two were crossed in June. Worth a look, because Patna is currently your most expensive everyday chilli relative to the market.

**Munimji (Pushp's mass brand) — the floor Pushp itself sets:**

| Product | Munimji MRP / sale | Equivalent Nidhi sale price |
|---|---|---|
| Garam Masala 100g | 56 / 49 | 87 |
| Achar Masala 500g | 206 / 173 | 191 |
| Achar Masala 200g | 88 / 76 | 79 |
| Dhaniya 500g | 214 / 180 | 180 |
| Amchur 500g | 248 / 208 | 238 |
| Haldi 1kg | 493 / 404 (≈202 per 500g) | 202 |
| Red Chilli 1kg | 573 / 470 (≈235 per 500g) | 227–324 |

On plain powders Nidhi is priced at **Munimji** level, not Pushp level. On blends Nidhi is at Pushp level.

### 2b. Blended masalas, 100g — against national brands

| Product | Nidhi sale | Pushp sale | Everest | MDH | Catch | Badshah | Tata Sampann |
|---|---|---|---|---|---|---|---|
| Garam Masala | 87 | 81–90 | ~85 | ~96 | ~69 | ~71 | — |
| Kitchen King | 78 | 83 | 72–86 | ~92 | 67–73 (MRP 98) | — | ~86 |
| Chana / Chole | 78 | 83 | ~88 (MRP 90) | ~90 | ~70 | ~56 | — |
| Pav Bhaji | 79 | 84 | ~92 (MRP 96) | — | — | — | — |
| Chat Masala | 73 | 73 | 67–73 | — | — | ~56 | 81–89 |

**Reading:** on blends you sit in the middle of the pack — below MDH and Everest, above Catch and Badshah. That is a sensible place for an unknown brand, and there is ₹4–5 of room to move up on three of them just by following Pushp.

### 2c. Plain powders, 500g — against national brands

| Product | Nidhi sale | Pushp sale | Everest | Catch | Tata Sampann | Local Indore pack | Indore loose / bulk (per 500g) |
|---|---|---|---|---|---|---|---|
| Haldi | 202 | 210 | ~177 (MRP 220) | 137–160 | 175–204 (MRP 235) | Gupta ~200 | 80–140 |
| Dhaniya | 180 | 200 | ~190 | — | 157–193 (MRP 215–230) | — | 58–75 |
| Red chilli | 227 / 280 / 324 | 227 / 280 / 304 | Tikhalal 223–254 | — | ~270 | Dilkhush ~180, Gupta ~200 | 90–130 (Teja ~123) |

**Reading:** this is your weakest ground. A customer in Indore can get Everest or Catch haldi for less, from Blinkit, in ten minutes. A 500g pouch also pushes your parcel into the next courier weight slab. Plain powders should fill a basket, not lead it.

### 2d. Indori specialities — where you have room

| Product | Nidhi sale | Other sellers (per 100g unless stated) |
|---|---|---|
| **Jeeravan 100g** | **44** | Om Namkeen 28 · Pushp 44–46 · Panchal ~50 · Agrawal's 420 ~58 · Phoran 89 (MRP 189) · Prakash Namkeen 100 · Maa Kaa Achar 120 (MRP 149) · Home Kouzina 149. Bulk on IndiaMART Indore: mostly ₹120–200 per **kg** |
| **Garadu Masala 100g** | 60 | Pushp 60. Almost nobody else sells it online |
| **Moong / Chana Papad 200g** | 57 | Agrawal's 420 Moong Special 58 · 420 Premium Sada 71–88 · Lijjat Moong 60–80 (MRP ~77) |
| **Papad Katran 1kg** | 205 | Agrawal's 420 ~325–330 · unbranded Indore wholesale 160–180 |
| **Papad masala (Chana / Moong)** | 70 / 74 | No comparable product found anywhere. Pushp does not sell papad or papad masala at all |
| **Achar Masala 500g** | 191 | Pushp 191 · Munimji 173 · Panchal ~240 (premium 400) |

**Reading:** jeeravan is the product people search for when they want "Indore in a packet", and the branded range runs from ₹44 to ₹149. You are at the very bottom of it, level with a company a thousand times your size that is using it as a loss-leader ("35% off"). Papad katran is ₹120 a kilo under the brand leader.

---

## 3. Shipping policies compared

| Seller | Shipping fee | Free shipping from | COD | Delivery time |
|---|---|---|---|---|
| **Nidhi (today)** | ₹59 + 18% GST = **₹69.62** | **₹499** | Available, no extra charge | — |
| Pushp | ₹99 flat under ₹299 (fee between ₹299–499 not stated) | ₹499 | Not stated | 5–7 days |
| Prakash Namkeen | ₹49 prepaid · **₹79 COD** | ₹799 (site banner says ₹900) | Selected pincodes | 1–2 days dispatch + 3–7 days |
| Aakash Namkeen | By weight, ₹20–150 per kg | ₹699 | **Only on orders ₹699–999** | 7–10 days |
| Om Namkeen | Calculated at checkout, by city | None stated | Not stated | 5–7 days surface, 2–3 air |
| Panchal Masale | Not shown | Not shown | **Not available** | — |
| Maa Kaa Achar (Indore) | — | ₹199 | Not stated | 3–5 days |
| Zoff | — | ₹249 | — | — |
| Goldiee | By weight | ₹399 with code | Not stated | Dispatch in 5–7 working days |
| Amazon (non-Prime) | ₹40 + ₹5 marketplace fee | ₹499 | Yes | 1–4 days |
| Blinkit | Up to ₹30 + ₹4–11 handling | varies | Yes | 10–20 minutes |

Two patterns stand out:

1. **Low threshold goes with high prices.** Maa Kaa Achar (₹199) and Zoff (₹249) can ship cheaply because a 100g masala costs ₹120–205 there. The shipping is already inside the price.
2. **Sellers at your price level protect themselves.** The Indore namkeen houses sit at ₹699–900 and either charge more for COD (Prakash, +₹30), restrict it (Aakash), or refuse it (Panchal).

**Nidhi is the only seller in this table combining Pushp-level prices, a ₹499 threshold, a below-average shipping fee and free COD.** That is the most generous offer in the market, made by the seller least able to afford it. Your own August report worked out what it costs: about ₹14 left (2.9%) on a ₹500 order shipped free.

### What a real basket costs the customer

| Basket | Nidhi | Pushp |
|---|---|---|
| Jeeravan + Garadu (2 packs) | 104 + 69.62 = **₹173.62** | 104 + 99 = **₹203** |
| Jeeravan + Garam Masala + Chat Masala + Haldi 500g | 406 + 69.62 = **₹475.62** | 408 + shipping (unstated for ₹299–499) = **₹408–507** |
| The same + Kitchen King + Pav Bhaji | **₹563**, free shipping | **₹575**, free shipping |

You are already ₹12–30 cheaper than Pushp on every basket. There is room to give some of that back to yourself.

---

## 4. What this means

1. **You are a price-follower of Pushp without Pushp's costs.** Pushp buys raw material by the truck, ships at negotiated courier rates and sells in 3 lakh shops. Matching their online price rupee for rupee gives the customer no reason to pick you and gives you a thinner margin than they have.
2. **Your prices have drifted below Pushp by accident** on six products, with no marketing benefit because nobody was told. Being cheaper only works if the customer can see it.
3. **Plain powders cannot be won online.** National brands are cheaper and arrive in minutes.
4. **Your real advantage is the things Pushp does not make or does not push** — papad, papad katran, papad masala, garadu masala — plus jeeravan, where the market happily pays ₹60–120.
5. **Shipping is where the money is leaking**, more than product price. This matches the conclusion of the August cost report.

---

## 5. Pricing strategy — undercut the market, without a loss

**Direction (owner's decision, 2026-10-01):** be the cheapest branded option on the shelf for most products, never sell at a loss, and build a range that is Nidhi's own. This section replaces an earlier draft that proposed *raising* prices.

### 5a. Where the loss line is

The only cost figure available is the one you gave for the August report: **cost of goods ≈ 65% of what you receive today**. Holding that cost fixed in rupees gives a loss line for every product:

- **Loss line = 65% of today's sale price.** Below this the pack itself loses money before any courier is paid.
- **Working floor = keep at least 25% of the shelf price after product cost.** That allows a cut of up to about 13% from today's price. The remaining margin is what pays for courier, packing and gateway fees — so the floor is not optional.

⚠ 65% is one number applied to every product. It is certainly wrong for some: IndiaMART bulk prices suggest blends and jeeravan cost less than that, and plain chilli and haldi may cost more. The last column of the table is blank for your real cost per pack. Any product where your real cost is above the "loss line" column must not be cut.

### 5b. Price for every size — APPLIED to production 2026-10-01

**Status:** all 38 changes below went live on 2026-10-01 and were verified through the live API (38 of 38 match, held sizes and every MRP untouched). A database backup was taken first; the previous sale prices are saved on the server in `~/NGU/backups/price_update_2026-10-01.log`. ⚠ The free-shipping threshold in §5c has **not** been changed yet.

Only the **sale price** changes. MRP is printed on the pack, so it stays as it is — selling below MRP needs no new labels. "Now" is the **live catalogue as read on 2026-10-01**: 28 products in 45 sizes. 38 sizes change, 7 are held. The same list is in `price_update_2026_10.py`, which applies it.

"Left after cost" is the share of the new shelf price remaining after product cost, using the 65% estimate. A dash under Pushp means no same-size Pushp pack was found.

**Blends and seasonings**

| Product | Pack | MRP | Now | **Proposed** | Pushp, same pack | Loss line | Left after cost | Your real cost |
|---|---|---|---|---|---|---|---|---|
| Pav Bhaji Masala | 100g | 96 | 79 | **75** | 84 | 51 | 32% | |
| Kitchen King Masala | 100g | 96 | 78 | **74** | 83 | 51 | 31% | |
| Chana Masala | 100g | 96 | 78 | **74** | 83 | 51 | 31% | |
| Garam Masala (Box) | 50g | 57 | 47 | **43** | 47 | 31 | 29% | |
| Garam Masala (Box) | 100g | 105 | 87 | **78** | 81 box / 90 jar | 57 | 28% | |
| Garam Masala (Box) | 9g sachet | 9.96 | 9.94 | hold | — | — | — | |
| Chat Masala | 100g | 89 | 73 | **66** | 73 | 47 | 28% | |
| Jeeravan | 100g | 68 | 44 | **42** | 44 sprinkler / 46 pouch | 29 | 32% | |
| Garadu Masala | 100g | 68 | 60 | **55** | 60 | 39 | 29% | |
| Tea Masala | 50g | 72 | 53 | **49** | 53 | 34 | 30% | |
| Sambhar Masala | 100g | 95 | 78 | **68** | 67 | 51 | 25% | |
| Sev Masala | 100g | 96 | 79 | hold | none found | 51 | 35% | |
| Kashmiri Mirch Powder | 100g | 130 | 104 | **96** | 104 | 68 | 30% | |
| Sonth Powder (Dry Ginger) | 100g | 100 | 86 | **79** | 86 | 56 | 29% | |
| Safed Mirch Powder | 100g | 150 | 122 | hold | 284 (white pepper) | 79 | 35% | |
| Kasuri Methi | 25g | 32 | 28 | **26** | 28 | 18 | 30% | |
| Kasuri Methi | 100g | 114 | 100 | **92** | — | 65 | 29% | |
| Hari Mirch Achar Masala | 200g | 94 | 79 | **72** | 79 | 51 | 29% | |
| Nimbu Chutney Achar Masala | 200g | 94 | 79 | **72** | 79 | 51 | 29% | |
| Achar Masala | 500g | 233 | 191 | **175** | 191 | 124 | 29% | |

**Plain powders**

| Product | Pack | MRP | Now | **Proposed** | Pushp, same pack | Loss line | Left after cost | Your real cost |
|---|---|---|---|---|---|---|---|---|
| Turmeric Powder | 100g | 52 | 45 | **42** | 45 | 29 | 30% | |
| Turmeric Powder | 200g | 99 | 85 | **78** | 83 | 55 | 29% | |
| Turmeric Powder | 500g | 235 | 202 | **185** | 210 | 131 | 29% | |
| Turmeric Powder | 1kg | 444 | 382 | **349** | 398 | 248 | 29% | |
| Coriander Powder | 100g | 46 | 40 | **37** | — | 26 | 30% | |
| Coriander Powder | 200g | 88 | 76 | **71** | 87 | 49 | 30% | |
| Coriander Powder | 500g | 209 | 180 | **169** | 200 | 117 | 31% | |
| Coriander Powder | 1kg | 395 | 340 | **319** | 380 | 221 | 31% | |
| Desi Tadakan Mirch Powder | 500g | 264 | 227 | **209** | 227 (Shahi Rangat) | 148 | 29% | |
| Chilli Powder (VIP Teja) | 100g | 73 | 62 | **57** | — | 40 | 29% | |
| Chilli Powder (VIP Teja) | 200g | 138 | 118 | **105** | 103 (Tikha Tadka) | 77 | 27% | |
| Chilli Powder (VIP Teja) | 500g | 328 | 280 | **255** | 280 | 182 | 29% | |
| Chilli Powder (VIP Teja) | 1kg | 620 | 529 | **479** | 447 | 344 | 28% | |
| Chilli Powder (Patna) | 100g | 85 | 72 | **65** | — | 47 | 28% | |
| Chilli Powder (Patna) | 200g | 161 | 137 | **119** | 120 (Red Chilli) | 89 | 25% | |
| Chilli Powder (Patna) | 500g | 381 | 324 | **289** | 304 | 211 | 27% | |
| Chilli Powder (Patna) | 1kg | 720 | 612 | **545** | 602 | 398 | 27% | |
| Amchur Powder | 100g | 64 | 53 | **49** | 50 | 34 | 30% | |
| Amchur Powder | 500g | 290 | 238 | **219** | 252 | 155 | 29% | |

**Nidhi's own range — nothing to undercut**

| Product | Pack | MRP | Now | **Proposed** | Nearest competitor | Loss line | Left after cost | Your real cost |
|---|---|---|---|---|---|---|---|---|
| Moong Papad | 200g | 70 | 57 | hold | Agrawal's 420 58–88, Lijjat 60–80 | 37 | 35% | |
| Chana Papad | 200g | 70 | 57 | hold | same | 37 | 35% | |
| Chana Papad Masala | 130g | 86 | 70 | hold | none found | 46 | 35% | |
| Moong Papad Masala | 100g | 90 | 74 | hold | none found | 48 | 35% | |
| Papad Katran | 500g | 132 | 108 | **119** | Agrawal's 420 ≈ 165 | 70 | 41% | |
| Papad Katran | 1kg | 250 | 205 | **229** | Agrawal's 420 ≈ 325 | 133 | 42% | |

Why the held and raised rows are treated differently:

- **Papads, papad masalas, Sev Masala:** already the cheapest branded option, or nobody else sells them. A cut wins no customer and only gives away margin.
- **Safed Mirch:** already less than half of Pushp's white pepper. Check that the product is comparable before touching it — a gap that large usually means it is not the same thing, or the price is too low.
- **Papad Katran is the one increase.** A 1kg pack adds a full courier weight slab (about ₹40–77) to any parcel it rides in. Both sizes move together so that 1kg stays cheaper than two 500g packs; both remain about 30% under the brand leader.

**Three sizes where this list does not get under Pushp.** Sambhar 100g (68 against 67), VIP Teja 200g (105 against 103) and VIP Teja 1kg (479 against 447) all stop at the 25% floor. Pushp's 1kg chilli in particular is priced below what the 65% estimate says you can match.

**What this list beats, and what it cannot**

| You will be cheaper than | You will still be dearer than |
|---|---|
| Pushp on every other comparable size (2–16%) | Catch and Badshah blends (₹56–73 per 100g) |
| Everest and MDH on every blend | Everest and Catch haldi (₹137–177 per 500g) |
| Everest dhaniya (~190), Tata Sampann chilli (~270) | Munimji garam masala (49) and amchur (208) |
| Munimji on haldi, dhaniya and chilli | Om Namkeen jeeravan (28 — below your loss line) |
| Every branded jeeravan except Om Namkeen | Unbranded Indore chilli and haldi packs (₹180–200 per 500g) |

**Combos — not changed, but two need a decision.** A combo carries its own sale price, so the list above does not move them. Every combo stays cheaper than buying its parts singly at the new prices. Two of the eight, though, are priced under the estimated cost of their contents *today*:

| Combo | Sale price | Parts at today's sale prices | Loss line of the parts |
|---|---|---|---|
| Teekha Trio – Red Chilli Collection | 359 | 611 | **397** |
| Achar Ghar – Pickle Making Kit | 209 | 349 | **227** |

If the 65% estimate is right, each Teekha Trio sold loses about ₹38 and each Achar Ghar about ₹18 before courier. At the other end, Indore Chatpata (159) will save the customer only ₹4 over its parts (163) once the single prices drop.

### 5c. The condition: shipping must change on the same day

**These price cuts lose money if the free-shipping threshold stays at ₹499.** They take the average margin after product cost from about 35% to about 29%. A free-shipped order costs you roughly ₹141 in courier and packing (August report: ₹126 + ₹15), plus 2.36% gateway fee on card payments.

| Order value, shipped free, paid by card | Left for you at today's prices | Left for you at the proposed prices |
|---|---|---|
| ₹499 | about +₹14 | **about −₹15** |
| ₹560 | about +₹32 | about ₹0 (break-even) |
| ₹799 | about +₹106 | about +₹61 |
| ₹999 | about +₹168 | about +₹111 |

A COD order costs a further ₹40 courier fee plus about ₹23 of return risk, so a ₹799 COD order leaves only about ₹15 unless COD is charged for.

| Setting | Now | Required with the new prices | Where that puts you |
|---|---|---|---|
| Free-shipping threshold | ₹499 | **₹799** | Level with Prakash (₹799), near Aakash (₹699), above Pushp (₹499) |
| Shipping fee | ₹59 + GST = ₹69.62 | keep | Between Prakash (₹49) and Pushp (₹99) |
| COD | Free | **₹40 COD fee**, or the same amount as a "pay online" discount | Prakash charges ₹30 extra; Aakash and Panchal restrict COD |

This is the trade the strategy makes: **lowest price on the shelf, honest price for delivery.** A customer buying two packs pays less for the packs and the same for shipping as today. A customer filling a ₹800 basket gets it cheaper than anywhere else and delivered free. The customer who loses is the one with a ₹500–799 basket, who used to ship free and now pays ₹69.62 — on a ₹600 basket the product saving (about ₹45) does not fully cover it. §6 is how that customer is brought up to ₹799.

**Implementation note.** The storefront bakes the threshold in at build time. Changing `FREE_SHIPPING_THRESHOLD` in the backend env alone will re-create the "cart says free, checkout charges ₹69.62" bug fixed on 2026-08-05 — rebuild the frontend image, or set the variable in the frontend service env as well. A COD fee does not exist in the code today and would need to be built. Until it is, the simplest protection is a coupon or banner discount for prepaid orders.

### 5d. A market of your own

Undercutting gets a first order. These are what make the second one yours rather than the next cheaper seller's.

1. **Own the Indori shelf.** Jeeravan, garadu masala, papad, papad katran and papad masala are products the national brands do not make and Pushp barely pushes. Put them first on the home page and in every bundle. On these you set the price; on haldi you only follow it.
2. **Sell sizes nobody else sells.** A price can only be compared when the pack is the same. Pushp sells jeeravan in 100g and 500g only; a 250g Nidhi pack has no direct rival. For blends, Pushp's 200g pouches work out to ₹72–84 per 100g — a Nidhi 200g pouch near ₹135–139 would be the cheapest per gram in the market while earning more per parcel than two 100g packs (one pouch, one label, same courier slab). Cost this before launching.
3. **Bundles only you can make** — see §6. A kit with papad, papad masala and jeeravan cannot be price-matched by Pushp, because Pushp does not sell half of it.
4. **Use the fact that you are in Indore** — next section.

### 5e. An advantage none of them use: you are in Indore

Courier cost inside the city is about ₹33 per 500g and about ₹38 within MP, against ₹43–50 for the rest of India (rates from the August report). Every competitor above runs one national threshold.

Consider **two thresholds: ₹599 for Indore–Malwa pincodes, ₹799 elsewhere.** Local customers — the ones who already know what garadu masala is, and who reorder — get a better deal than anyone outside the region can offer them, and it costs you less to honour. (At the proposed prices ₹499 would be roughly break-even even locally, so ₹599 is the lowest safe number.) This needs development work (the system has a single threshold today), so it is a second step, not a first.

---

## 6. Getting the customer over the threshold

Raising a threshold only works if the customer has an easy way to cross it.

1. **Bundles that land just over the threshold.** Pushp does this hard: Trial Pack 581 → 399, Jain Combo 476 → 349, Sprinkler Combo 227 → 159 — roughly 27–31% off. Your combo list was empty in June. Three to start with:
   - *Indori Nashta Kit* — Jeeravan + Garadu masala + Chat masala + Papad katran
   - *Rasoi Starter* — Haldi + Dhaniya + Mirchi 500g each + Garam masala
   - *Papad Lover* — Moong papad + Chana papad + both papad masalas + katran
   
   Price each at no more than 5–8% below the sum of the new sale prices, so the total sits at ₹799–899. The single prices are already cut; a deeper bundle discount on top would take the bundle under the 25% floor. Pushp can afford 30% off because its sale prices start higher.
2. **"Add ₹X more for free delivery" in the cart**, with a one-tap suggestion of a cheap item (Kasuri methi ₹28, Jeeravan). This is the standard way to turn a threshold from an obstacle into a nudge.
3. **Reward quantity carefully.** Maa Kaa Achar gives buy 2 → extra 5%, buy 3 → extra 10%, but from prices 2–3× yours. At the proposed prices the most you can add is about 5% on three or more packs.
4. **Sell what the big brands cannot say.** Small-batch, made in Indore, a family *gruh udyog*, papad made by hand. Pushp's own marketing leans on "since 1974" and scale; yours should lean on the opposite. Prakash and Maa Kaa Achar charge ₹100–120 for jeeravan on exactly this story.
5. **Lead with the products nobody else has.** Papad masala and garadu masala should be on the home page above haldi and dhaniya.
6. **Push UPI at checkout.** No gateway fee on UPI — about ₹11 saved on a ₹470 order per the August report.
7. **Pack light.** The same report found that moving two 100g packs from a box to a mailer bag drops the parcel from the 1kg slab to the 500g slab — about ₹40 saved per order. That one change pays for the price cut on roughly eight packs.

---

## 7. Before you change anything

1. **Decide the two below-cost combos** in §5b (Teekha Trio, Achar Ghar) — raise them or accept them as deliberate loss-leaders.
2. **Fill in the "Your real cost" column in §5b** — raw material + pouch + label + labour per pack. The 65% figure is a single estimate spread over 25 products. Any product whose real cost is above its loss line must not be cut; any product well below it has room for a deeper cut.
3. **GST on blends: settled.** Owner's decision 2026-10-01 — blends stay at 5%. The live catalogue already charges 5% on every non-papad product and 0% on the three papads, so nothing needed changing.
4. **Never lower prices before the shipping change is live.** Shipping first, or both on the same day. Prices first means every ₹499–560 order ships at a loss.
5. **Watch three numbers for four weeks after each change:** orders per week, average order value, and share of orders that are COD.

---

## 8. Closing the offline gap — a one-hour market check

Take this list to one kirana store, one supermarket (D-Mart or similar) and one Siyaganj wholesaler. Note the printed MRP and the price actually charged.

| Product | Pushp | Munimji | Everest | Local brand (name it) |
|---|---|---|---|---|
| Garam masala 100g | | | | |
| Kitchen King 100g | | | | |
| Jeeravan 100g | | | | |
| Haldi 500g | | | | |
| Dhaniya 500g | | | | |
| Lal mirch 500g | | | | |
| Achar masala 500g | | | | |
| Moong papad 200g (Agrawal's 420 / Lijjat) | | | | |
| Papad katran 1kg | | | | |

Also ask the kirana owner what margin Pushp and Everest give him. If you ever sell through shops, your MRP has to leave room for that margin *and* still match the price on your own website — which is one more reason not to price at the very bottom online.

---

## Sources

Prices and policies read on 2026-10-01.

- Pushp — store API and policy pages: [pushponline.com](https://pushponline.com/), [shipping policy](https://pushponline.com/shipping-policy/), [jeeravan sprinkler](https://pushponline.com/jeeravan-masala-100g-sprinkler/), [company background](https://entrackr.com/news/a91-partners-backed-spice-maker-pushp-files-drhp-for-ofs-only-ipo-11878822), [Pushp's own brand ranking article](https://pushponline.com/top-10-masala-brands-in-india/)
- Prakash Namkeen — [jeeravan collection](https://prakashnamkeen.com/collections/instants-jeeravan), [shipping policy](https://prakashnamkeen.com/policies/shipping-policy)
- Aakash Namkeen — [shipping policy](https://aakashnamkeen.com/pages/shipping-policy)
- Om Namkeen — [jeeravan](https://www.omnamkeen.com/product/jeeravan-masala/), [shipping policy](https://www.omnamkeen.com/shipping-policy/)
- Maa Kaa Achar — [jeeravan](https://www.maakaaachar.com/products/indori-jeeravan-masala-authentic-spicy-zesty-taste-of-indore)
- Panchal Masale — [jeeravan](https://panchalmasale.in/product/jeeravan/), [shop](https://panchalmasale.in/shop/)
- Phoran — [jeeravan](https://phoranmasala.com/products/premium-jeeravan-chat-masala)
- Zoff — [zofffoods.com](https://zofffoods.com/)
- Goldiee — [delivery policy](https://www.goldieeonlinestore.com/pages/delivery-shipping-policy)
- IndiaMART Indore — [jeeravan](https://dir.indiamart.com/indore/jeeravan-powder.html), [garam masala](https://dir.indiamart.com/indore/garam-masala.html), [turmeric](https://dir.indiamart.com/indore/turmeric-powder.html), [red chilli](https://dir.indiamart.com/indore/red-chilli-powder.html), [papad](https://dir.indiamart.com/indore/papad.html)
- National brands — BigBasket: [Everest garam masala](https://www.bigbasket.com/pd/268943/everest-garam-masala-100-g-carton/), [MDH garam masala](https://www.bigbasket.com/pd/100004473/mdh-masala-garam-100-g-carton/), [Catch garam masala](https://www.bigbasket.com/pd/284268/catch-garam-masala-100-g-carton/), [Badshah garam masala](https://www.bigbasket.com/pd/100070024/badshah-powder-rajwadi-garam-masala-100-g-carton/), [MDH Kitchen King](https://www.bigbasket.com/pd/100004502/mdh-masala-kitchen-king-100-g-carton/), [Catch chana](https://www.bigbasket.com/pd/100099598/catch-chana-masala-100-g-carton/), [Everest Tikhalal 500g](https://www.bigbasket.com/pd/206778/everest-tikhalal-chilli-powder-500-g-pouch/), [Everest coriander 500g](https://www.bigbasket.com/pd/100004184/everest-powder-green-coriander-500-g-pouch/), [Catch turmeric 500g](https://www.bigbasket.com/pd/40019827/catch-turmeric-powder-500-g-pouch/); Blinkit: [Everest pav bhaji](https://blinkit.com/prn/everest-pav-bhaji-masala/prid/15459), [Catch Kitchen King](https://blinkit.com/prn/catch-kitchen-king-masala-100-g/prid/10904), [Tata Sampann turmeric](https://blinkit.com/prn/tata-sampann-turmeric-powderhaldi/prid/210169); Amazon: [Everest turmeric 500g](https://www.amazon.in/Everest-Turmeric-Powder-500g/dp/B00O0X78NA)
- Papad — [Agrawal's 420 Moong Special, BigBasket](https://www.bigbasket.com/pd/40076922/agrawals-420-papad-moong-special-200-g/), [420 Premium Sada](https://www.indore.online/products/420-premium-sada-papad-indore-200gm-pack-price-rs-71), [Lijjat moong 200g, BigBasket](https://www.bigbasket.com/pd/100004920/lijjat-papad-moong-200-g-pouch/)
- Marketplace fees — [Amazon delivery charges](https://www.amazon.in/gp/help/customer/display.html?nodeId=GRK3YG3G4Y3R4LWJ), [Amazon ₹5 marketplace fee](https://www.angelone.in/news/market-updates/amazon-india-introduces-5-fee-on-all-orders-including-prime), [quick-commerce fees](https://www.storyboard18.com/brand-marketing/blinkit-zepto-instamart-raise-fees-as-quick-commerce-goes-mainstream-ws-l-99758.htm)
- Nidhi — `Backend/demo/live_products.json` (June 2026 snapshot), `tmp/lagat_hindi_source.html` (cost report, 5 Aug 2026), `DATABASE_FILLING.md`
