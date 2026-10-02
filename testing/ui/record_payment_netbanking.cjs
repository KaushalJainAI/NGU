/**
 * Real end-to-end Razorpay payment via NETBANKING, in TEST MODE only.
 *
 * This is the one flow a pure-HTTP test cannot do: only Razorpay can mint a
 * valid razorpay_payment_id + signature, so we drive the actual hosted checkout
 * in a browser, pick Netbanking (no card/CVV/OTP needed), and click the test
 * "Success" button. The order should then flip to paid via BOTH the /verify/
 * browser callback AND the L2 webhook (your public IP lets Razorpay reach it).
 *
 *   node record_payment_netbanking.cjs [baseURL] [outDir] [credsFile]
 *
 * Credentials: uses NGU_TEST_ACCOUNT_EMAIL / NGU_TEST_ACCOUNT_PASSWORD if set,
 * else the JSON creds file (default reports/live/test-account.json), else fails.
 *
 * ── HARD SAFETY GUARD ─────────────────────────────────────────────────────
 * Before opening checkout the script calls /api/payments/create-order/ and reads
 * razorpay_key_id. If it is NOT an `rzp_test_` key it ABORTS without paying — so
 * this can never charge real money on live keys. Make the target test-mode first
 * (RAZORPAY_TEST_MODE=True) or it will (correctly) refuse.
 *
 * Residue: a PAID order remains on the reusable account (a customer cannot
 * self-cancel a paid order). That is expected, and it makes the product
 * reviewable — enabling the verified-review happy path in the pytest suite.
 */
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = (process.argv[2] || process.env.NGU_BASE_URL || "https://nidhimasala.com").replace(/\/$/, "");
const OUT = process.argv[3] || path.join(__dirname, "..", "reports", "live");
const CREDS = process.argv[4] || path.join(OUT, "test-account.json");
const API = `${BASE}/api`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const findings = [];
const record = (level, area, msg, extra) =>
  findings.push({ level, area, msg, ...(extra || {}), t: new Date().toISOString() });

async function step(label, fn) {
  process.stdout.write(`  • ${label}\n`);
  try { return await fn(); } catch (e) {
    const line = String(e).split("\n")[0];
    process.stdout.write(`    (issue: ${line})\n`);
    record("warn", "step", `step "${label}" threw: ${line}`);
  }
}
async function settle(page, ms = 1500) {
  try { await page.waitForLoadState("networkidle", { timeout: 8000 }); } catch {}
  await sleep(ms);
}

function loadCreds() {
  const email = process.env.NGU_TEST_ACCOUNT_EMAIL;
  const password = process.env.NGU_TEST_ACCOUNT_PASSWORD;
  if (email && password) return { email, password };
  if (fs.existsSync(CREDS)) {
    const c = JSON.parse(fs.readFileSync(CREDS, "utf8"));
    if (c.email && c.password) return c;
  }
  throw new Error(
    "No credentials. Set NGU_TEST_ACCOUNT_EMAIL/NGU_TEST_ACCOUNT_PASSWORD or " +
    `provide ${CREDS}.`
  );
}

// Fetch inside the page (carries the logged-in cookies).
async function probe(page, method, urlPath, body) {
  return page.evaluate(async ({ url, method, body }) => {
    try {
      const r = await fetch(url, {
        method, credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      let json = null; const text = await r.text();
      try { json = JSON.parse(text); } catch {}
      return { status: r.status, json, snippet: text.slice(0, 200) };
    } catch (e) { return { status: 0, error: String(e) }; }
  }, { url: `${API}${urlPath}`, method, body });
}

async function apiLogin(page, creds) {
  // Authenticate through the API so cookies are set, then land on the site.
  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
  const r = await probe(page, "POST", "/auth/login/", { email: creds.email, password: creds.password });
  if (r.status !== 200) throw new Error(`login failed: ${r.status} ${r.snippet}`);
  const token = r.json && r.json.access;
  if (token) {
    // Some SPA builds read the token from localStorage; set it best-effort.
    await page.evaluate((t) => { try { localStorage.setItem("access_token", t); } catch {} }, token);
  }
  record("info", "auth", `logged in as ${creds.email}`);
  return token;
}

// The core: place an ONLINE order over the API (deterministic), guard the mode,
// then hand the razorpay order to the hosted checkout UI.
async function placeOnlineOrderAndGuard(page) {
  // pick a cheap in-stock product to minimise the (test) amount
  const list = await probe(page, "GET", "/products/");
  const items = list.json && (list.json.results || list.json) || [];
  const product = items.find((p) => (p.stock || 0) >= 1);
  if (!product) throw new Error("no in-stock product to buy");

  await probe(page, "POST", "/cart/add_item/", { product_id: product.id, quantity: 1 });
  const order = await probe(page, "POST", "/orders/", {
    shipping_address: "1 E2E Test Rd, Test City",
    phone_number: "9999999999", payment_method: "ONLINE",
  });
  if (order.status !== 201) throw new Error(`order create failed: ${order.status} ${order.snippet}`);
  const orderId = order.json.order_id;

  const co = await probe(page, "POST", "/payments/create-order/", { order_id: orderId });
  if (co.status !== 200) throw new Error(`create-order failed: ${co.status} ${co.snippet}`);
  const key = co.json.razorpay_key_id || "";

  // ── the hard money guard ──
  if (!key.startsWith("rzp_test_")) {
    throw new Error(
      `ABORT: Razorpay key is ${JSON.stringify(key.slice(0, 9))} — NOT test mode. ` +
      `Refusing to pay real money. Set RAZORPAY_TEST_MODE=True on the target first.`
    );
  }
  record("info", "guard", `Razorpay TEST mode confirmed (${key.slice(0, 12)}…)`);
  return { orderId, product };
}

// Drive the hosted Razorpay checkout. Selectors are defensive because Razorpay's
// checkout markup changes; each stage tries a few strategies and logs what it did.
async function payWithNetbanking(page) {
  // The storefront checkout page invokes Razorpay's Checkout.open(). Go there and
  // click the pay button so the iframe mounts.
  await page.goto(`${BASE}/checkout`, { waitUntil: "domcontentloaded" });
  await settle(page, 2000);
  const payBtn = page.getByRole("button", { name: /pay|place order|proceed|checkout/i }).first();
  if (await payBtn.count()) { await payBtn.click().catch(() => {}); await settle(page, 3000); }

  // Razorpay Checkout renders in an iframe from api.razorpay.com.
  const frameHandle = await page.waitForSelector('iframe[src*="razorpay"]', { timeout: 20000 }).catch(() => null);
  if (!frameHandle) throw new Error("Razorpay checkout iframe never appeared");
  const frame = await frameHandle.contentFrame();
  if (!frame) throw new Error("could not attach to Razorpay iframe");
  await sleep(2500);

  const clickByText = async (f, re) => {
    const el = f.locator(`text=${re}`).first();
    if (await el.count()) { await el.click().catch(() => {}); return true; }
    return false;
  };

  await step("Choose Netbanking method", async () => {
    // Netbanking may be a labelled option or under "More"/"Other" banks.
    if (!(await clickByText(frame, /netbanking/i))) {
      await clickByText(frame, /net ?banking|other banks|more/i);
    }
    await sleep(2000);
  });

  await step("Pick a test bank", async () => {
    // Razorpay test checkout lists banks; any works. Prefer a common one.
    const search = frame.locator('input[type="search"], input[placeholder*="bank" i]').first();
    if (await search.count()) { await search.fill("HDFC").catch(() => {}); await sleep(1200); }
    const bank = frame.locator('text=/HDFC|SBI|ICICI|Axis|Kotak/i').first();
    if (await bank.count()) await bank.click().catch(() => {});
    await sleep(1500);
    // Continue / Pay within the frame.
    const cont = frame.locator('button:has-text("Pay"), button:has-text("Continue")').first();
    if (await cont.count()) await cont.click().catch(() => {});
    await sleep(3000);
  });

  await step("Click Success on the Razorpay test authorization page", async () => {
    // The test simulator page (may be a top-level nav, not the iframe) shows
    // Success / Failure. Try both the frame and the page.
    const trySuccess = async (ctx) => {
      const s = ctx.locator('button:has-text("Success"), text=/^Success$/i').first();
      if (await s.count()) { await s.click().catch(() => {}); return true; }
      return false;
    };
    let clicked = false;
    for (let i = 0; i < 10 && !clicked; i++) {
      clicked = (await trySuccess(page)) || (frame && (await trySuccess(frame).catch(() => false)));
      if (!clicked) await sleep(1000);
    }
    record(clicked ? "info" : "warn", "checkout",
      clicked ? "clicked Success on the test authorization page" : "could not find the Success button — checkout markup may have changed");
  });
}

async function waitForPaid(page, orderId, attempts = 30) {
  for (let i = 0; i < attempts; i++) {
    const r = await probe(page, "GET", `/payments/status/?order_id=${orderId}`);
    const ps = r.json && r.json.payment_status;
    process.stdout.write(`    status[${i}] payment_status=${ps} order_status=${r.json && r.json.order_status}\n`);
    if (ps === "paid") return r.json;
    if (ps === "failed" || ps === "rejected") throw new Error(`payment ended ${ps}`);
    await sleep(3000);
  }
  return null;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const creds = loadCreds();
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    recordVideo: { dir: OUT, size: { width: 1366, height: 900 } },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on("response", (r) => { if (r.status() >= 500) record("issue", "network", `${r.status()} ${r.request().method()} ${r.url().slice(0, 120)}`); });

  process.stdout.write(`\n=== NETBANKING PAYMENT (test mode) · ${BASE} ===\n`);
  let orderId = null, paid = null;
  try {
    await apiLogin(page, creds);
    const placed = await step("Place ONLINE order + guard test mode", () => placeOnlineOrderAndGuard(page));
    orderId = placed && placed.orderId;
    if (!orderId) throw new Error("no order to pay");
    await payWithNetbanking(page);
    paid = await step("Wait for order to become paid (verify + webhook)", () => waitForPaid(page, orderId));
    if (paid) record("info", "result", `order ${orderId} is PAID (order_status=${paid.order_status})`);
    else record("issue", "result", `order ${orderId} never reached paid within timeout`);
  } catch (e) {
    record("issue", "fatal", String(e).split("\n")[0]);
    process.stdout.write(`  FATAL: ${String(e).split("\n")[0]}\n`);
  }

  await context.close(); // flush video
  await browser.close();

  const vids = fs.readdirSync(OUT).filter((f) => f.endsWith(".webm"));
  const newest = vids.map((f) => ({ f, t: fs.statSync(path.join(OUT, f)).mtimeMs })).sort((a, b) => b.t - a.t)[0];
  if (newest && newest.f !== "payment-netbanking.webm") {
    try { fs.renameSync(path.join(OUT, newest.f), path.join(OUT, "payment-netbanking.webm")); } catch {}
  }
  const report = {
    flow: "netbanking-payment", base: BASE, orderId, paid: !!paid,
    when: new Date().toISOString(), findings,
    counts: { issues: findings.filter((f) => f.level === "issue").length },
  };
  fs.writeFileSync(path.join(OUT, "payment-netbanking.findings.json"), JSON.stringify(report, null, 2));
  process.stdout.write(`  paid=${!!paid} issues=${report.counts.issues} (see payment-netbanking.findings.json)\n`);
  process.exit(report.counts.issues > 0 && !paid ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
