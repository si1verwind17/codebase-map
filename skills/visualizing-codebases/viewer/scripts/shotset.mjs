// Pixel guard for refactors: renders a fixed set of views of the built viewer (Still motion, 1440×900) as PNGs,
// and compares a fresh render with a baseline set. Needs `npm run build` first.
//   VIZ_CHROMIUM=/usr/bin/chromium node scripts/shotset.mjs <out-dir>                      render the set
//   VIZ_CHROMIUM=/usr/bin/chromium npm run shots:compare <baseline-dir> [out-dir] [--x-range x0,x1]   render and compare (only columns x0 ≤ x < x1 with --x-range); exit 1 on any difference
// The page is written to .shot-page.html (gitignored), overwritten for each view; scripts/viewer-page.mjs opens and walks it.
// Still motion only: entering/leaving floors, travel, moving items and cross-fades are not drawn here; the e2e covers them.
import { mkdirSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { launch, openView, pixels, runSteps, settle } from "./viewer-page.mjs";

const DEMO = new URL("../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const SHOP = new URL("../test/fixtures/shop.code-map.json", import.meta.url);

/** Each view: a map and the steps that reach it from a freshly opened page. */
const VIEWS = [
  { name: "01-demo-f0-factory-legend", map: DEMO, steps: [] },
  { name: "02-demo-f0-factory-airfields", map: DEMO, steps: [["wheel", 560, 500, -400, 1]] },
  { name: "03-demo-dags-floor", map: DEMO, steps: [["find", "S7·P1"], ["pick"], ["down"], ["floor", /dags/]] },
  { name: "04-demo-billing-package-floor", map: DEMO, steps: [["find", "S2·P1"], ["pick"], ["down"], ["floor", /city\.parking\.billing/]] },
  { name: "05-demo-demand-forecast-floor", map: DEMO, steps: [["find", "S4·P1"], ["pick"], ["floor", /demand-forecast/]] },
  { name: "08-shop-site-factory", map: SHOP, steps: [] },
  { name: "09-demo-f0-factory-selected", map: DEMO, steps: [["tap", 620, 232]] },
  { name: "10-demo-dags-floor-layer", map: DEMO, steps: [["find", "S7·P1"], ["pick"], ["down"], ["floor", /dags/], ["layer", "S7·P1·F1"]] },
  { name: "11-demo-dags-floor-peek", map: DEMO, steps: [["find", "S7·P1"], ["pick"], ["down"], ["floor", /dags/], ["find", "bq_tariff_snapshot.py"], ["pick"]] },
];

async function render(out) {
  mkdirSync(out, { recursive: true });
  const browser = await launch();
  const errors = [];
  try {
    for (const v of VIEWS) {
      const page = await openView(browser, v.map, v.name, errors);
      await runSteps(page, v.steps);
      await settle(page, v.steps);
      await page.screenshot({ path: join(out, `${v.name}.png`) });
      await page.close();
    }
  } finally {
    await browser.close();
  }
  if (errors.length) { console.error(errors.join("\n")); process.exitCode = 1; }
  return errors;
}

function differing(a, b, [x0, x1] = [0, Infinity]) {
  const p = pixels(a), q = pixels(b);
  if (p.w !== q.w || p.h !== q.h) return Infinity;
  let n = 0;
  for (let i = 0; i < p.out.length; i += 4) {
    const x = (i / 4) % p.w;
    if (x >= x0 && x < x1 && p.out.readUInt32BE(i) !== q.out.readUInt32BE(i)) n++;
  }
  return n;
}

const args = process.argv.slice(2);
// --x-range x0,x1: compare only those columns (e.g. the floor, when the rail or inspector changed on purpose)
const rangeAt = args.indexOf("--x-range");
const range = rangeAt >= 0 ? args.splice(rangeAt, 2)[1].split(",").map(Number) : [0, Infinity];
if (args[0] === "--compare") {
  const base = args[1];
  if (!base) { console.error("usage: shotset.mjs --compare <baseline-dir> [out-dir]"); process.exit(2); }
  const out = args[2] ?? mkdtempSync(join(tmpdir(), "shotset-"));
  const errors = await render(out);
  let bad = errors.length;
  const want = readdirSync(base).filter((f) => f.endsWith(".png")).sort();
  const names = VIEWS.map((v) => `${v.name}.png`);
  for (const f of names) {
    if (!want.includes(f)) { console.log(`MISSING in baseline  ${f}`); bad++; continue; }
    const a = readFileSync(join(base, f)), b = readFileSync(join(out, f));
    const n = a.equals(b) ? 0 : differing(a, b, range);
    console.log(`${n === 0 ? "same" : "DIFF"}  ${f}${n ? `  (${n === Infinity ? "size differs" : `${n} px`})` : ""}`);
    if (n) bad++;
  }
  console.log(`${names.length} views, ${bad} difference(s); this render: ${out}`);
  process.exit(bad ? 1 : 0);
} else {
  if (!args[0]) { console.error("usage: shotset.mjs <out-dir> | --compare <baseline-dir> [out-dir]"); process.exit(2); }
  const errors = await render(args[0]);
  console.log(`${VIEWS.length} views in ${args[0]}${errors.length ? `; ${errors.length} page error(s)` : ", no page errors"}`);
}
