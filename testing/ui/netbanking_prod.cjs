/**
 * REAL end-to-end Razorpay payment via NETBANKING against production, TEST MODE.
 *
 * Runs from THIS machine using the installed Chrome (playwright-core). Everything
 * happens same-origin on the prod domain so cookie-auth and Razorpay's allowed
 * origin both work:
 *   login → add to cart → ONLINE order → create-order → open real Razorpay
 *   checkout → Netbanking → a test bank → "Success" → handler POSTs /verify/.
 *
 *   node netbanking_prod.cjs
 *
 * Env: NGU_BASE_URL, NGU_TEST_ACCOUNT_EMAIL, NGU_TEST_ACCOUNT_PASSWORD.
 * Hard guard: aborts unless create-order returns an rzp_test_ key (no real money).
 * Screenshots + a findings JSON land in ../reports/live for diagnosis.
 */
const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const BASE = (process.env.NGU_BASE_URL || "https://nidhigrahudyog.com").replace(/\/$/, "");
const EMAIL = process.env.NGU_TEST_ACCOUNT_EMAIL || "qa.e2e@nidhimasala.com";
// The QA account's password is never kept in the repo — pass it in the env.
const PASSWORD = process.env.NGU_TEST_ACCOUNT_PASSWORD;
if (!PASSWORD) {
  process.stderr.write("Set NGU_TEST_ACCOUNT_PASSWORD before running this script.\n");
  process.exit(2);
}
const OUT = path.join(__dirname, "..", "reports", "live");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => process.stdout.write(a.join(" ") + "\n");
const findings = [];
const rec = (level, msg, extra) => findings.push({ level, msg, ...(extra || {}), t: new Date().toISOString() });

let shot = 0;
async function snap(page, label) {
  const f = path.join(OUT, `nb_${String(++shot).padStart(2, "0")}_${label}.png`);
  try { await page.screenshot({ path: f, fullPage: false }); log("   shot:", path.basename(f)); } catch (e) { log("   shot failed:", String(e).split("\n")[0]); }
}

// Run a fetch inside the prod page. Uses Bearer JWT (not cookies) so DRF picks
// JWTAuthentication and skips CSRF — exactly what the pytest suite does.
async function api(page, method, path_, body, token) {
  return page.evaluate(async ({ method, url, body, token }) => {
    try {
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      const r = await fetch(url, {
        method, credentials: "include", headers,
        body: body ? JSON.stringify(body) : undefined,
      });
      let json = null; const text = await r.text();
      try { json = JSON.parse(text); } catch {}
      return { status: r.status, json, text: text.slice(0, 300) };
    } catch (e) { return { status: 0, error: String(e) }; }
  }, { method, url: `${BASE}${path_}`, body, token });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  // Cooldown so per-account throttles (order 10/min, login 5/min) are fully reset
  // before we touch the system again. Configurable via COOLDOWN_MS.
  const cooldown = parseInt(process.env.COOLDOWN_MS || "0", 10);
  if (cooldown > 0) { log(`(cooldown ${Math.round(cooldown / 1000)}s to clear throttles…)`); await sleep(cooldown); }
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    recordVideo: { dir: OUT, size: { width: 1366, height: 900 } },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) rec("console", m.text().slice(0, 160)); });

  // Razorpay's test-mode netbanking simulator (Success/Failure) opens in a POPUP.
  // Catch every new page and click "Success" so the payment authorizes.
  context.on("page", async (pp) => {
    rec("info", "popup opened: " + pp.url());
    try {
      await pp.waitForLoadState("domcontentloaded", { timeout: 15000 });
      await pp.waitForTimeout(1500);
      await snap(pp, "popup");
      for (const sel of ['text=/^Success$/i', 'button:has-text("Success")', 'a:has-text("Success")',
                         'input[value="Success" i]', 'button:has-text("Submit")', 'text=/success/i']) {
        try { const l = pp.locator(sel).first(); if (await l.count()) { await l.click({ timeout: 4000 }); rec("info", "popup: clicked " + sel); await pp.waitForTimeout(1500); break; } } catch {}
      }
    } catch (e) { rec("warn", "popup handling: " + String(e).split("\n")[0]); }
  });

  let orderId = null, paid = false;
  try {
    log("\n=== NETBANKING E2E (test mode) ·", BASE, "===");
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });

    // 1. login → capture Bearer token (avoids CSRF on unsafe methods)
    const login = await api(page, "POST", "/api/auth/login/", { email: EMAIL, password: PASSWORD });
    if (login.status !== 200) throw new Error(`login failed: ${login.status} ${login.text}`);
    const token = login.json && login.json.access;
    if (!token) throw new Error("no access token in login response");
    rec("info", "logged in");
    log(" • logged in as", EMAIL);

    // 2. cart — cheapest in-stock product to keep the test amount small
    const prods = await api(page, "GET", "/api/products/", null, token);
    const items = (prods.json && (prods.json.results || prods.json)) || [];
    const inStock = items.filter((p) => (p.stock || 0) >= 1);
    inStock.sort((a, b) => (a.final_price || a.price || 9e9) - (b.final_price || b.price || 9e9));
    const product = inStock[0];
    if (!product) throw new Error("no in-stock product");
    const addResp = await api(page, "POST", "/api/cart/add_item/", { product_id: product.id, quantity: 1 }, token);
    if (![200, 201].includes(addResp.status)) throw new Error(`add_item failed: ${addResp.status} ${addResp.text}`);
    log(" • added to cart:", product.name);

    // 3. ONLINE order
    const order = await api(page, "POST", "/api/orders/", {
      shipping_address: "1 E2E Test Rd, Test City", phone_number: "9999999999", payment_method: "ONLINE",
    }, token);
    if (order.status !== 201) throw new Error(`order failed: ${order.status} ${order.text}`);
    orderId = order.json.order_id;
    log(" • ONLINE order placed:", orderId);

    // 4. create-order + HARD test-mode guard
    const co = await api(page, "POST", "/api/payments/create-order/", { order_id: orderId }, token);
    if (co.status !== 200) throw new Error(`create-order failed: ${co.status} ${co.text}`);
    const { razorpay_order_id, razorpay_key_id, amount } = co.json;
    if (!String(razorpay_key_id).startsWith("rzp_test_"))
      throw new Error(`ABORT: key ${razorpay_key_id} is NOT test mode — refusing to pay`);
    rec("info", `test-mode confirmed ${razorpay_key_id.slice(0, 12)} amount=${amount}`);
    log(" • Razorpay order:", razorpay_order_id, "amount(paise)=", amount, "key=", razorpay_key_id.slice(0, 12));

    // 5. open the real Razorpay checkout on the prod page
    await page.addScriptTag({ url: "https://checkout.razorpay.com/v1/checkout.js" });
    await page.evaluate(({ key, order_id, amount, token }) => {
      window.__rzp_done = null;
      const rzp = new window.Razorpay({
        key, order_id, amount, currency: "INR",
        name: "NGU E2E", description: "netbanking e2e test",
        // Prefill skips the "enter mobile number" contact gate and pre-selects
        // netbanking so we land on the bank list.
        prefill: { name: "QA E2E", email: "qa.e2e@nidhimasala.com", contact: "9082345671", method: "netbanking" },
        handler: (resp) => {
          fetch("/api/payments/verify/", {
            method: "POST", credentials: "include",
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
            body: JSON.stringify({
              razorpay_order_id: resp.razorpay_order_id,
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature,
            }),
          }).then((r) => r.json().then((j) => { window.__rzp_done = { status: r.status, body: j }; }))
            .catch((e) => { window.__rzp_done = { status: 0, body: String(e) }; });
        },
        modal: { ondismiss: () => { window.__rzp_done = { status: -1, body: "dismissed" }; } },
      });
      rzp.open();
    }, { key: razorpay_key_id, order_id: razorpay_order_id, amount, token });
    await sleep(4000);
    await snap(page, "checkout_open");

    // 6. drive the checkout iframe: [contact gate] → Netbanking → bank → Success
    const frame = page.frameLocator('iframe.razorpay-checkout-frame, iframe[src*="api.razorpay.com"]');
    const clickFirst = async (selectors, label, timeout = 4000) => {
      for (const sel of selectors) {
        const loc = frame.locator(sel).first();
        try { if (await loc.count()) { await loc.click({ timeout }); rec("info", `clicked ${label} via ${sel}`); return true; } } catch {}
      }
      return false;
    };
    const fillFirst = async (selectors, value, label) => {
      for (const sel of selectors) {
        const loc = frame.locator(sel).first();
        try { if (await loc.count()) { await loc.fill(value, { timeout: 4000 }); rec("info", `filled ${label}`); return true; } } catch {}
      }
      return false;
    };

    // (a) contact gate fallback — if prefill didn't skip it, fill mobile + Continue
    if (await fillFirst(['input[type="tel"]', 'input[name="contact"]', 'input[autocomplete="tel"]'], "9082345671", "mobile")) {
      await clickFirst(['button:has-text("Continue")', 'text=/^Continue$/i'], "Continue");
      await sleep(3000);
    }
    await snap(page, "methods");

    // (b) select the Netbanking method (may need to reveal it)
    await clickFirst(['text=/netbanking/i', '[data-testid*="netbanking" i]', 'div:has-text("Netbanking")'], "Netbanking");
    await sleep(2500); await snap(page, "netbanking");

    // (c) pick a bank from the list, then the Pay/Continue button it reveals
    await clickFirst(['text=/HDFC/i', 'text=/State Bank|SBI/i', 'text=/ICICI/i', 'text=/Axis/i', 'input[type="radio"]'], "bank");
    await sleep(1500);
    await clickFirst(['button:has-text("Pay")', 'button:has-text("Continue")', 'text=/Pay Now/i', 'text=/^Pay ₹/i'], "Pay/Continue");
    await sleep(4000); await snap(page, "after_pay");

    // (d) test-mode simulator: Success / Failure (in-frame or top-level)
    let clickedSuccess = false;
    for (let i = 0; i < 15 && !clickedSuccess; i++) {
      for (const sel of ['button:has-text("Success")', 'text=/^Success$/i', 'a:has-text("Success")']) {
        try { const l = frame.locator(sel).first(); if (await l.count()) { await l.click({ timeout: 3000 }); clickedSuccess = true; break; } } catch {}
        try { const l = page.locator(sel).first(); if (await l.count()) { await l.click({ timeout: 3000 }); clickedSuccess = true; break; } } catch {}
      }
      if (!clickedSuccess) { if (i === 3) await snap(page, "await_success"); await sleep(1500); }
    }
    rec(clickedSuccess ? "info" : "warn", clickedSuccess ? "clicked Success" : "Success button not found");
    await sleep(2000); await snap(page, "after_success");

    // 7. wait for handler → /verify/ result, and confirm via status API
    for (let i = 0; i < 25 && !paid; i++) {
      const done = await page.evaluate(() => window.__rzp_done);
      if (done) rec("info", `verify handler: status=${done.status} body=${JSON.stringify(done.body).slice(0, 120)}`);
      const st = await api(page, "GET", `/api/payments/status/?order_id=${orderId}`, null, token);
      const ps = st.json && st.json.payment_status;
      log(`   poll[${i}] payment_status=${ps} order_status=${st.json && st.json.order_status}`);
      if (ps === "paid") { paid = true; break; }
      if (ps === "failed" || ps === "rejected") { rec("issue", `payment ended ${ps}`); break; }
      await sleep(3000);
    }
    await snap(page, "final");
    rec(paid ? "info" : "issue", paid ? `order ${orderId} PAID` : `order ${orderId} not paid within timeout`);
  } catch (e) {
    rec("issue", "fatal: " + String(e).split("\n")[0]);
    log(" FATAL:", String(e).split("\n")[0]);
    await snap(page, "error");
  }

  await context.close();
  await browser.close();
  const report = { flow: "netbanking-prod", base: BASE, orderId, paid, when: new Date().toISOString(), findings };
  fs.writeFileSync(path.join(OUT, "netbanking_prod.findings.json"), JSON.stringify(report, null, 2));
  log(`\n paid=${paid} orderId=${orderId} — see reports/live/netbanking_prod.findings.json + nb_*.png`);
  process.exit(paid ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
