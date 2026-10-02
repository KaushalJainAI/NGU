/**
 * Live-production storefront recorder + interaction/security probe.
 *
 * Drives https://nidhimasala.com in a real Chromium session, records the whole
 * session to a .webm, and collects interaction issues (console errors, page
 * exceptions, failed requests, unexpected 4xx/5xx) into a JSON findings file.
 *
 * Two personas × two device layouts:
 *   persona = normal    → browse, register/login, cart, favorites, checkout (stops before payment)
 *   persona = malicious → authorized, NON-DESTRUCTIVE abuse probes:
 *                         auth-gate bypass, unauth API hits, IDOR, search injection,
 *                         cookie tampering (verifies forceLogout), login rate-limit
 *   device  = desktop | mobile
 *
 * Usage:
 *   node record_live.cjs <normal|malicious> <desktop|mobile> [baseURL] [outDir] [credsFile]
 *
 * Non-destructive guarantees: never completes a payment, never deletes data,
 * caps the rate-limit probe at a handful of requests, creates at most ONE test
 * account (shared across runs via the creds file).
 */
const { chromium, devices } = require("playwright");
const fs = require("fs");
const path = require("path");

const persona = (process.argv[2] || "normal").toLowerCase();
const device = (process.argv[3] || "desktop").toLowerCase();
const BASE = (process.argv[4] || "https://nidhimasala.com").replace(/\/$/, "");
const OUT = process.argv[5] || path.join(__dirname, "..", "reports", "live");
const CREDS = process.argv[6] || path.join(OUT, "test-account.json");
const API = `${BASE}/api`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const findings = [];
const netLog = [];
const record = (level, area, msg, extra) =>
  findings.push({ level, area, msg, ...(extra || {}), t: new Date().toISOString() });

async function step(label, fn) {
  process.stdout.write(`  • ${label}\n`);
  try { await fn(); } catch (e) {
    const line = String(e).split("\n")[0];
    process.stdout.write(`    (issue: ${line})\n`);
    record("warn", "step", `step "${label}" threw: ${line}`);
  }
}
async function settle(page, ms = 1500) {
  try { await page.waitForLoadState("networkidle", { timeout: 6000 }); } catch {}
  await sleep(ms);
}
async function slowScroll(page) {
  for (const y of [250, 650, 1100, 0]) {
    await page.evaluate((v) => window.scrollTo({ top: v, behavior: "smooth" }), y).catch(() => {});
    await sleep(600);
  }
}

// Run a fetch INSIDE the page (real browser origin, real cookies) and capture status/body.
async function probe(page, method, urlPath, opts = {}) {
  const res = await page.evaluate(async ({ url, method, body, headers }) => {
    try {
      const r = await fetch(url, {
        method,
        credentials: "include",
        headers: { "Content-Type": "application/json", ...(headers || {}) },
        body: body ? JSON.stringify(body) : undefined,
      });
      const text = await r.text();
      return { status: r.status, len: text.length, snippet: text.slice(0, 180) };
    } catch (e) { return { status: 0, error: String(e) }; }
  }, { url: `${API}${urlPath}`, method, body: opts.body, headers: opts.headers });
  return res;
}

function makeAccount() {
  const s = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  return {
    first_name: "QA", last_name: "Bot",
    name: "QA Bot",
    username: `qabot_${s}`,
    email: `qa.bot.${s}@example.com`,
    phone: "9990001111",
    password: `Qa!${s}Aa9`,
  };
}

async function normalFlow(page) {
  await step("Home page", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await settle(page, 2000); await slowScroll(page);
  });
  await step("Browse products", async () => {
    await page.goto(`${BASE}/products`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800); await slowScroll(page);
  });
  await step("Open first product", async () => {
    const card = page.locator('a[href*="/products/"]').first();
    if (await card.count()) { await card.click(); await settle(page, 1800); await slowScroll(page); }
    else record("warn", "catalog", "no product cards found on /products");
  });
  await step("Search 'masala'", async () => {
    await page.goto(`${BASE}/search?q=masala`, { waitUntil: "domcontentloaded" });
    await settle(page, 1600);
  });
  await step("Combos", async () => {
    await page.goto(`${BASE}/combos`, { waitUntil: "domcontentloaded" });
    await settle(page, 1600); await slowScroll(page);
  });

  // Auth: register a fresh account (first run) or log in (subsequent runs).
  let creds;
  if (fs.existsSync(CREDS)) {
    creds = JSON.parse(fs.readFileSync(CREDS, "utf8"));
    await step(`Login as ${creds.email}`, async () => {
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await settle(page, 1200);
      await page.getByRole("textbox").first().fill(creds.email);
      await page.locator('input[type="password"]').first().fill(creds.password);
      await page.getByRole("button", { name: /log ?in|sign ?in/i }).first().click();
      await settle(page, 2500);
    });
  } else {
    creds = makeAccount();
    await step(`Register new account ${creds.email}`, async () => {
      await page.goto(`${BASE}/register`, { waitUntil: "domcontentloaded" });
      await settle(page, 1200);
      // Fill by input attributes; the register form has many fields.
      const setByName = async (names, val) => {
        for (const n of names) {
          const el = page.locator(`input[name="${n}"], input[id="${n}"]`).first();
          if (await el.count()) { await el.fill(val); return true; }
        }
        return false;
      };
      await setByName(["first_name", "firstName"], creds.first_name);
      await setByName(["last_name", "lastName"], creds.last_name);
      await setByName(["name"], creds.name);
      await setByName(["username"], creds.username);
      await setByName(["email"], creds.email);
      await setByName(["phone"], creds.phone);
      const pw = page.locator('input[type="password"]');
      const pwCount = await pw.count();
      if (pwCount >= 1) await pw.nth(0).fill(creds.password);
      if (pwCount >= 2) await pw.nth(1).fill(creds.password);
      // agree-to-privacy checkbox if present
      const chk = page.locator('input[type="checkbox"]').first();
      if (await chk.count()) await chk.check().catch(() => {});
      await page.getByRole("button", { name: /create|register|sign ?up/i }).first().click();
      await settle(page, 2500);
      fs.writeFileSync(CREDS, JSON.stringify(creds, null, 2));
      record("info", "auth", `registered test account ${creds.email}`);
      // Registration doesn't auto-login; go log in.
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await settle(page, 1000);
      await page.locator('input[type="email"], input[name="email"]').first().fill(creds.email);
      await page.locator('input[type="password"]').first().fill(creds.password);
      await page.getByRole("button", { name: /log ?in|sign ?in/i }).first().click();
      await settle(page, 2500);
    });
  }

  // Verify we actually became logged-in.
  await step("Confirm login state", async () => {
    const who = await probe(page, "GET", "/auth/profile/");
    if (who.status === 200) record("info", "auth", "profile 200 after login (session OK)");
    else record("warn", "auth", `profile returned ${who.status} after login attempt`, { snippet: who.snippet });
  });

  await step("Add a product to cart", async () => {
    await page.goto(`${BASE}/products`, { waitUntil: "domcontentloaded" });
    await settle(page, 1500);
    const card = page.locator('a[href*="/products/"]').first();
    if (await card.count()) { await card.click(); await settle(page, 1600); }
    const addBtn = page.getByRole("button", { name: /add to cart|add/i }).first();
    if (await addBtn.count()) { await addBtn.click(); await settle(page, 1500); }
    else record("warn", "cart", "no 'add to cart' button on product detail");
  });
  await step("View cart", async () => {
    await page.goto(`${BASE}/cart`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
  });
  await step("Favorites page", async () => {
    await page.goto(`${BASE}/favorites`, { waitUntil: "domcontentloaded" });
    await settle(page, 1500);
  });
  await step("My orders (protected)", async () => {
    await page.goto(`${BASE}/my-orders`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
    if (/\/login/.test(page.url())) record("warn", "auth", "logged-in user bounced from /my-orders to /login");
  });
  await step("Profile page", async () => {
    await page.goto(`${BASE}/profile`, { waitUntil: "domcontentloaded" });
    await settle(page, 1600);
  });
  await step("Proceed toward checkout (STOP before payment)", async () => {
    await page.goto(`${BASE}/cart`, { waitUntil: "domcontentloaded" });
    await settle(page, 1200);
    const co = page.getByRole("button", { name: /checkout|proceed/i }).first();
    if (await co.count()) { await co.click(); await settle(page, 2000); }
    record("info", "checkout", `reached ${page.url()} — halted before any real payment`);
  });
  await step("Logout", async () => {
    await probe(page, "POST", "/auth/logout/").catch(() => {});
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await settle(page, 1500);
  });
}

async function maliciousFlow(page) {
  // 1. Auth-gate: protected pages must bounce anonymous users to /login.
  for (const p of ["/my-orders", "/profile"]) {
    await step(`Anon visit ${p} (expect redirect to /login)`, async () => {
      await page.goto(`${BASE}${p}`, { waitUntil: "domcontentloaded" });
      await settle(page, 1800);
      const url = page.url();
      if (/\/login/.test(url)) record("info", "authz", `${p} correctly redirected anon → /login`);
      else record("issue", "authz", `${p} did NOT redirect anon user (landed ${url})`);
    });
  }
  // 2. Unauthenticated API access — must be 401/403.
  await step("Unauth API probes", async () => {
    for (const ep of ["/auth/profile/", "/orders/", "/cart/", "/favorites/", "/payment-methods/"]) {
      const r = await probe(page, "GET", ep);
      const ok = [401, 403].includes(r.status);
      record(ok ? "info" : "issue", "authz",
        `GET ${ep} unauth → ${r.status}${ok ? " (protected)" : " (EXPECTED 401/403)"}`, { snippet: r.snippet });
    }
  });
  // 3. IDOR / BOLA — object access by id without ownership must not leak data.
  await step("IDOR probes on orders", async () => {
    for (const id of [1, 2, 42, 99999]) {
      const r = await probe(page, "GET", `/orders/${id}/`);
      const leaked = r.status === 200;
      record(leaked ? "issue" : "info", "idor",
        `GET /orders/${id}/ → ${r.status}${leaked ? " (POSSIBLE DATA LEAK)" : ""}`, { snippet: r.snippet });
    }
  });
  // 4. Search injection — XSS/SQLi payloads must not execute or 500.
  await step("Search injection payloads", async () => {
    let alertFired = false;
    page.on("dialog", async (d) => { alertFired = true; await d.dismiss().catch(() => {}); });
    for (const payload of ['<img src=x onerror=alert(1)>', "' OR '1'='1", '"><script>alert(1)</script>']) {
      await page.goto(`${BASE}/search?q=${encodeURIComponent(payload)}`, { waitUntil: "domcontentloaded" });
      await settle(page, 1500);
    }
    record(alertFired ? "issue" : "info", "xss",
      alertFired ? "injected script EXECUTED (XSS)" : "injection payloads rendered inert (no script exec)");
  });
  // 5. Admin surface from storefront — must be forbidden to anon.
  await step("Admin endpoint probes", async () => {
    for (const ep of ["/admin/dashboard/", "/admin/coupons/", "/analytics/insights/"]) {
      const r = await probe(page, "GET", ep);
      const ok = [401, 403, 404].includes(r.status);
      record(ok ? "info" : "issue", "authz", `GET ${ep} anon → ${r.status}${ok ? "" : " (EXPECTED 401/403/404)"}`);
    }
  });
  // 6. Cookie tampering — a bogus access_token must be rejected and log the user out.
  await step("Tamper access_token cookie (expect rejection/logout)", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await page.evaluate(() => {
      document.cookie = "access_token=tampered.jwt.value; path=/";
      localStorage.setItem("user", JSON.stringify({ id: "x", email: "spoof@x.com" }));
    });
    await page.goto(`${BASE}/my-orders`, { waitUntil: "domcontentloaded" });
    await settle(page, 2500);
    const stillUser = await page.evaluate(() => localStorage.getItem("user"));
    const bounced = /\/login/.test(page.url());
    if (bounced || !stillUser) record("info", "authn", "tampered token rejected → forced logout / redirect (good)");
    else record("issue", "authn", `tampered token NOT rejected (url=${page.url()}, user cache present=${!!stillUser})`);
  });
  // 7. Login rate-limit — capped at a few requests; expect a 429 to appear.
  await step("Login rate-limit probe (capped)", async () => {
    const statuses = [];
    for (let i = 0; i < 7; i++) {
      const r = await probe(page, "POST", "/auth/login/", { body: { email: "nobody@example.com", password: "wrong-Pw-123" } });
      statuses.push(r.status);
      await sleep(200);
    }
    const throttled = statuses.includes(429);
    record(throttled ? "info" : "warn", "ratelimit",
      `login attempts → [${statuses.join(",")}] ${throttled ? "(429 throttle observed)" : "(no 429 within 7 tries)"}`);
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const base = device === "mobile" ? devices["Pixel 5"] : { viewport: { width: 1366, height: 820 } };
  const context = await browser.newContext({
    ...base,
    recordVideo: { dir: OUT, size: device === "mobile" ? { width: 393, height: 851 } : { width: 1366, height: 820 } },
    ignoreHTTPSErrors: false,
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  // Passive collectors — these surface interaction issues for ANY persona.
  // Expected noise is filtered so only genuine problems are flagged as issues:
  //  - 401/403 on API calls while browsing logged-out is normal (auth-gated data).
  //  - ERR_ABORTED comes from navigating away mid-request during fast probing.
  //  - The relative-/api build warning + Google GSI cosmetics are benign.
  const benignConsole = [
    /Failed to load resource.*status of 40[13]/i,
    /Authentication credentials were not provided/i,
    /API_BASE_URL is using relative path/i,
    /\[GSI_LOGGER\]/i,
    /Provider's accounts list is empty/i,     // Google GSI: browser not signed into Google
    /Not signed in with the identity provider/i,
    /status of 429/i,                          // our own rate-limit probe firing
  ];
  page.on("console", (m) => {
    if (!["error", "warning"].includes(m.type())) return;
    const txt = m.text().slice(0, 200);
    if (benignConsole.some((re) => re.test(txt))) { record("info", "console", txt); return; }
    record(m.type() === "error" ? "issue" : "warn", "console", txt);
  });
  page.on("pageerror", (e) => record("issue", "pageerror", String(e).slice(0, 200)));
  page.on("requestfailed", (r) => {
    const err = r.failure()?.errorText || "";
    if (/ERR_ABORTED/i.test(err)) return; // navigation race, not a defect
    record("warn", "network", `request failed: ${r.method()} ${r.url().slice(0, 120)} (${err})`);
  });
  page.on("response", (r) => {
    const s = r.status();
    if (s >= 500) record("issue", "network", `${s} ${r.request().method()} ${r.url().slice(0, 120)}`);
    netLog.push({ s, m: r.request().method(), u: r.url() });
  });

  process.stdout.write(`\n=== ${persona.toUpperCase()} user · ${device} · ${BASE} ===\n`);
  if (persona === "malicious") await maliciousFlow(page);
  else await normalFlow(page);

  await context.close(); // flush video
  await browser.close();

  // Name the video deterministically.
  const vids = fs.readdirSync(OUT).filter((f) => f.endsWith(".webm"));
  const newest = vids.map((f) => ({ f, t: fs.statSync(path.join(OUT, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t)[0];
  const finalName = `${persona}-${device}.webm`;
  if (newest && newest.f !== finalName) {
    try { fs.renameSync(path.join(OUT, newest.f), path.join(OUT, finalName)); } catch {}
  }
  const report = { persona, device, base: BASE, when: new Date().toISOString(), findings,
    counts: { issues: findings.filter((f) => f.level === "issue").length,
              warns: findings.filter((f) => f.level === "warn").length },
    requests: netLog.length };
  fs.writeFileSync(path.join(OUT, `${persona}-${device}.findings.json`), JSON.stringify(report, null, 2));

  process.stdout.write(`  video: ${finalName}\n`);
  process.stdout.write(`  issues=${report.counts.issues} warns=${report.counts.warns} (see ${persona}-${device}.findings.json)\n`);
})().catch((e) => { console.error(e); process.exit(1); });
