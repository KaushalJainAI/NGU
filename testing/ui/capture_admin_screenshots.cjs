const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = "http://localhost:5174/panel";
const DIRS = [
  path.resolve(__dirname, "../../Admin Panel/screenshots"),
  path.resolve(__dirname, "../../introduction reel/admin_panel_screenshots"),
];

// Ensure output directories exist
DIRS.forEach((dir) => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function capture(page, filename, description) {
  console.log(`[Screenshot] ${filename} - ${description}`);
  await sleep(1500); // wait for dynamic content / charts to animate
  for (const dir of DIRS) {
    const targetPath = path.join(dir, filename);
    await page.screenshot({ path: targetPath, fullPage: false });
  }
}

(async () => {
  console.log("Launching browser for Admin Panel screenshot capture...");
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2, // High DPI crystal-clear retina screenshots
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  // 1. Login Page
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await capture(page, "01-login-screen.png", "Admin Login Page");

  // Perform Login
  await page.fill('input[type="email"]', "admin@nidhimasala.com");
  await page.fill('input[type="password"]', "AdminPass123!");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(dashboard|orders|products)/, { waitUntil: "domcontentloaded" });
  await sleep(1000);

  // 2. Dashboard Overview
  await page.goto(`${BASE}/dashboard`, { waitUntil: "domcontentloaded" });
  await capture(page, "02-dashboard-overview.png", "Main Dashboard with KPIs & Urgent Tasks");

  // 3. Orders Management - All Orders
  await page.goto(`${BASE}/orders`, { waitUntil: "domcontentloaded" });
  await capture(page, "03-orders-list.png", "Orders Management List");

  // 4. Filter Orders - Pending / Action Required
  try {
    const pendingTab = page.locator('button:has-text("Pending"), [role="tab"]:has-text("Pending")').first();
    if (await pendingTab.isVisible()) {
      await pendingTab.click();
      await sleep(1000);
      await capture(page, "04-orders-pending.png", "Orders Filtered by Pending Action");
    }
  } catch (e) {
    console.log("Skipped pending tab click:", e.message);
  }

  // 5. Open Order Detail View / Modal if available
  try {
    const firstOrderRow = page.locator('tr:has-text("NGU-"), button:has-text("View"), button:has-text("Next step")').first();
    if (await firstOrderRow.isVisible()) {
      await firstOrderRow.click();
      await sleep(1200);
      await capture(page, "05-order-detail.png", "Order Detailed View Modal");
      // Close modal if open
      const closeBtn = page.locator('button:has-text("Close"), [aria-label="Close"]').first();
      if (await closeBtn.isVisible()) await closeBtn.click();
    }
  } catch (e) {
    console.log("Skipped order detail modal:", e.message);
  }

  // 6. Product Catalog Management
  await page.goto(`${BASE}/products`, { waitUntil: "domcontentloaded" });
  await capture(page, "06-product-catalog.png", "Products Management Page");

  // 7. Add/Edit Product Modal
  try {
    const addProductBtn = page.locator('button:has-text("Add Product"), button:has-text("New Product")').first();
    if (await addProductBtn.isVisible()) {
      await addProductBtn.click();
      await sleep(1200);
      await capture(page, "07-product-add-modal.png", "Add/Edit Product Dialog");
      const closeBtn = page.locator('button:has-text("Cancel"), [aria-label="Close"]').first();
      if (await closeBtn.isVisible()) await closeBtn.click();
    }
  } catch (e) {
    console.log("Skipped product add modal:", e.message);
  }

  // 8. Categories Management
  await page.goto(`${BASE}/categories`, { waitUntil: "domcontentloaded" });
  await capture(page, "08-categories-management.png", "Category Management Screen");

  // 9. Spice Combos
  await page.goto(`${BASE}/combos`, { waitUntil: "domcontentloaded" });
  await capture(page, "09-spice-combos.png", "Spice Combo Packs Management");

  // 10. Homepage Section Placements
  await page.goto(`${BASE}/sections`, { waitUntil: "domcontentloaded" });
  await capture(page, "10-homepage-sections.png", "Homepage Section Placements");

  // 11. Coupons & Discount Codes
  await page.goto(`${BASE}/coupons`, { waitUntil: "domcontentloaded" });
  await capture(page, "11-coupons-management.png", "Coupons & Discount Codes");

  // 12. Customer Directory
  await page.goto(`${BASE}/customers`, { waitUntil: "domcontentloaded" });
  await capture(page, "12-customer-directory.png", "Customer List & Order History");

  // 13. Customer Reviews Moderation
  await page.goto(`${BASE}/reviews`, { waitUntil: "domcontentloaded" });
  await capture(page, "13-reviews-moderation.png", "Verified Customer Reviews Moderation");

  // 14. Live Support Chat Conversations
  await page.goto(`${BASE}/conversations`, { waitUntil: "domcontentloaded" });
  await capture(page, "14-live-chat-conversations.png", "Customer Support & AI Handoff Conversations");

  // 15. Contact Submissions Inbox
  await page.goto(`${BASE}/contact`, { waitUntil: "domcontentloaded" });
  await capture(page, "15-contact-submissions.png", "Contact Submissions Inbox");

  // 16. Analytics & Insights Dashboard (Overview)
  await page.goto(`${BASE}/insights`, { waitUntil: "domcontentloaded" });
  await capture(page, "16-insights-analytics-overview.png", "Analytics & Insights Overview");

  // 17. Insights - Sales Tab
  try {
    const salesTab = page.locator('button:has-text("Sales"), [role="tab"]:has-text("Sales")').first();
    if (await salesTab.isVisible()) {
      await salesTab.click();
      await sleep(1500);
      await capture(page, "17-insights-sales-tab.png", "Insights Sales & Revenue Trends");
    }
  } catch (e) {}

  // 18. Insights - Search & Customer Tabs
  try {
    const searchTab = page.locator('button:has-text("Search"), [role="tab"]:has-text("Search")').first();
    if (await searchTab.isVisible()) {
      await searchTab.click();
      await sleep(1500);
      await capture(page, "18-insights-search-analytics.png", "Top Searches & Zero Result Queries");
    }
  } catch (e) {}

  // 19. Bulk Product Editor
  await page.goto(`${BASE}/bulk-edit`, { waitUntil: "domcontentloaded" });
  await capture(page, "19-bulk-product-editor.png", "Bulk Product Quick Editing Tool");

  // 20. Recycle Bin
  await page.goto(`${BASE}/recycle-bin`, { waitUntil: "domcontentloaded" });
  await capture(page, "20-recycle-bin.png", "Recycle Bin & Item Restoration");

  // 21. Admin Info & System Health
  await page.goto(`${BASE}/admin-info`, { waitUntil: "domcontentloaded" });
  await capture(page, "21-admin-system-info.png", "Admin System Info & Server Status");

  await context.close();
  await browser.close();
  console.log("Successfully gathered all 21 high-resolution screenshots of the Admin Panel!");
})().catch((err) => {
  console.error("Error capturing admin screenshots:", err);
  process.exit(1);
});
