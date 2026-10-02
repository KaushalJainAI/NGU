/**
 * Runs the full live-prod recorder matrix and compiles one markdown report.
 *
 *   normal   · desktop   (registers the shared test account)
 *   normal   · mobile    (logs in with it)
 *   malicious· desktop   (non-destructive abuse probes)
 *   malicious· mobile
 *
 * Order matters: normal runs first so the login flow isn't throttled by the
 * malicious rate-limit probe, which is fired last.
 *
 * Usage: node run_live_suite.cjs [baseURL]
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const BASE = process.argv[2] || "https://nidhimasala.com";
const OUT = path.join(__dirname, "..", "reports", "live");
const combos = [
  ["normal", "desktop"],
  ["normal", "mobile"],
  ["malicious", "desktop"],
  ["malicious", "mobile"],
];

fs.mkdirSync(OUT, { recursive: true });
for (const [persona, device] of combos) {
  process.stdout.write(`\n>>> ${persona} / ${device}\n`);
  const r = spawnSync("node", [path.join(__dirname, "record_live.cjs"), persona, device, BASE, OUT], {
    stdio: "inherit",
  });
  if (r.status !== 0) process.stdout.write(`    (run exited ${r.status})\n`);
}

// Compile combined markdown.
const lines = [`# Live-prod test run — ${BASE}`, "", `_Generated ${new Date().toISOString()}_`, ""];
let totalIssues = 0;
for (const [persona, device] of combos) {
  const fp = path.join(OUT, `${persona}-${device}.findings.json`);
  if (!fs.existsSync(fp)) { lines.push(`## ${persona} / ${device}\n\n_(no findings file — run failed)_\n`); continue; }
  const j = JSON.parse(fs.readFileSync(fp, "utf8"));
  totalIssues += j.counts.issues;
  lines.push(`## ${persona} / ${device}`, "");
  lines.push(`Video: \`${persona}-${device}.webm\` · requests: ${j.requests} · **issues: ${j.counts.issues}**, warns: ${j.counts.warns}`, "");
  const notable = j.findings.filter((f) => ["issue", "warn"].includes(f.level));
  if (!notable.length) { lines.push("_No issues or warnings captured._", ""); continue; }
  lines.push("| level | area | detail |", "|---|---|---|");
  for (const f of notable) lines.push(`| ${f.level} | ${f.area} | ${String(f.msg).replace(/\|/g, "\\|")} |`);
  lines.push("");
}
lines.unshift(`> **Total issues across matrix: ${totalIssues}**`, "");
const outMd = path.join(OUT, "LIVE_RUN_REPORT.md");
fs.writeFileSync(outMd, lines.join("\n"));
process.stdout.write(`\nCombined report: ${outMd}\n`);
