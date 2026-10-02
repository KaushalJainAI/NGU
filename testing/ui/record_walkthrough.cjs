/**
 * Records a video walkthrough of the NGU storefront (Vite dev server proxying
 * the local seeded backend). Playwright captures the whole browser session to a
 * .webm; tools/make_video.py-free — we transcode to .mp4 afterwards.
 *
 * Prereqs (started by record_website.sh):
 *   - backend e2e server on 127.0.0.1:8000
 *   - vite dev server on 127.0.0.1:5173 (proxies /api -> :8000)
 *
 * Usage: node record_walkthrough.cjs [baseURL] [outDir]
 */
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://127.0.0.1:5173";
const OUT = process.argv[3] || "videos";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function step(page, label, fn) {
  process.stdout.write(`  • ${label}\n`);
  try {
    await fn();
  } catch (e) {
    process.stdout.write(`    (skipped: ${String(e).split("\n")[0]})\n`);
  }
}

async function settle(page, ms = 1600) {
  try { await page.waitForLoadState("networkidle", { timeout: 6000 }); } catch {}
  await sleep(ms);
}

async function slowScroll(page) {
  for (const y of [300, 700, 1200, 0]) {
    await page.evaluate((v) => window.scrollTo({ top: v, behavior: "smooth" }), y);
    await sleep(800);
  }
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: OUT, size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  await step(page, "Home page", async () => {
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    await settle(page, 2000);
    await slowScroll(page);
  });

  await step(page, "Browse all products", async () => {
    await page.goto(`${BASE}/products`, { waitUntil: "domcontentloaded" });
    await settle(page, 2000);
    await slowScroll(page);
  });

  await step(page, "Product detail (Turmeric Powder)", async () => {
    await page.goto(`${BASE}/products/turmeric-powder-250g`, { waitUntil: "domcontentloaded" });
    await settle(page, 2200);
    await slowScroll(page);
  });

  await step(page, "Search for 'masala'", async () => {
    await page.goto(`${BASE}/search?q=masala`, { waitUntil: "domcontentloaded" });
    await settle(page, 2000);
    await slowScroll(page);
  });

  await step(page, "Combos", async () => {
    await page.goto(`${BASE}/combos`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
    await slowScroll(page);
  });

  await step(page, "Offer zone", async () => {
    await page.goto(`${BASE}/offer-zone`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
  });

  await step(page, "Login page", async () => {
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
  });

  await step(page, "Register page", async () => {
    await page.goto(`${BASE}/register`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
  });

  await step(page, "Cart", async () => {
    await page.goto(`${BASE}/cart`, { waitUntil: "domcontentloaded" });
    await settle(page, 1800);
  });

  await step(page, "About", async () => {
    await page.goto(`${BASE}/about`, { waitUntil: "domcontentloaded" });
    await settle(page, 1500);
    await slowScroll(page);
  });

  await step(page, "Contact", async () => {
    await page.goto(`${BASE}/contact`, { waitUntil: "domcontentloaded" });
    await settle(page, 1500);
  });

  await context.close(); // flushes the video file
  await browser.close();
  process.stdout.write("done — video written under " + OUT + "\n");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
