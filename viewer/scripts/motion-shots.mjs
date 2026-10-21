// Pixel guard for what moves: the demo with motion on (drones, trains and smoke on the site; trains, drones inside) at
// fixed moments of a fake clock, as PNGs; compares a fresh render with a baseline set. shotset.mjs covers Still motion.
// Needs `npm run build` first.
//   VIZ_CHROMIUM=/usr/bin/chromium node scripts/motion-shots.mjs <out-dir>                            render the set
//   VIZ_CHROMIUM=/usr/bin/chromium node scripts/motion-shots.mjs --compare <baseline-dir> [out-dir]   exit 1 on any difference
// The page runs on Playwright's fake clock, paused and moved a frame at a time by hand, with animation frames on a fixed
// grid of it, so every frame falls at the same fake moment on every render.
import { mkdirSync, mkdtempSync, readdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { launch, pixels, W, H, writePage } from "./viewer-page.mjs";

const DEMO = new URL("../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const RUN_MS = 2500;   // motion shown before each shot
const FRAME = 16;
const STEP_MS = 500;   // after each step, before waiting for the camera: a move starts, a timer fires
const REAL_MS = 20;

/** Each view: the steps from a freshly opened page, then RUN_MS of motion. */
const VIEWS = [
  // the site after a visit inside: the motion it first showed started before the fake clock's pause held
  { name: "01-demo-site-motion", steps: [["find", "S1"], ["pick"], ["down"], ["site"]] },
  // no inner floor of the demo has both: one with rails (dags, its trains running), one with drones (billing)
  { name: "02-demo-dags-floor-trains", steps: [["find", "S7·P1"], ["pick"], ["down"]] },
  { name: "03-demo-billing-floor-drones", steps: [["find", "S2·P1"], ["pick"], ["down"]] },
];

/** Runs the paused fake clock one frame, then lets real time pass, so work the frame started that waits on no timer
 *  (an image decoded, a texture uploaded) is done before the next frame, not at a moment that varies by run. */
async function frame(page) {
  await page.clock.runFor(FRAME);
  await page.waitForTimeout(REAL_MS);
}

/** Runs frames until `ready` holds in the page. */
async function runUntil(page, ready, what) {
  for (let ms = 0; ms < 60_000; ms += FRAME) {
    if (await page.evaluate(ready)) return;
    await frame(page);
  }
  throw new Error(`${what}: not reached in 60 s of page time`);
}

const still = () => {
  const c = document.querySelector("canvas");
  return !!c?.dataset.plans && c.dataset.camera !== "moving" && !document.body.innerText.includes("Moving…")
    && !document.querySelector(".floors button[aria-current=page]")?.disabled;   // disabled while a floor change runs
};

async function render(out) {
  mkdirSync(out, { recursive: true });
  const browser = await launch();
  const errors = [];
  try {
    for (const v of VIEWS) {
      const context = await browser.newContext({ viewport: { width: W, height: H }, reducedMotion: "no-preference" });
      await context.clock.install({ time: 0 });
      // the fake performance.now() and animation frames count from when the document started, a moment that varies by
      // a few real milliseconds before the pause below holds: count from the fake Date's zero instead
      await context.addInitScript(() => {
        performance.now = () => Date.now();
        // animation frames on a fixed 16 ms grid of the fake clock (its own frames start where the page's first asked)
        window.requestAnimationFrame = (cb) => {
          const t = (Math.floor(Date.now() / 16) + 1) * 16;
          return setTimeout(() => cb(t), t - Date.now());
        };
        window.cancelAnimationFrame = (h) => clearTimeout(h);
      });
      const page = await context.newPage();
      page.on("pageerror", (e) => errors.push(`${v.name}: ${e.message}`));
      await page.clock.pauseAt(1000);   // installed, the fake clock still follows real time; paused, only runFor moves it
      await page.goto(writePage(DEMO));
      // the first floor is built without the clock moving, so its motion starts at the same fake moment every time
      await page.waitForFunction(() => document.querySelector("canvas")?.dataset.plans, null, { timeout: 30_000 });
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(1000);   // and whatever it started that waits on no timer is done
      await runUntil(page, still, `${v.name}: first floor`);
      for (const [verb, arg] of v.steps) {
        if (verb === "find") await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(arg);
        if (verb === "pick") await page.locator("#rail-find button.item").first().click();
        if (verb === "down") await page.locator(".floors button.down").click();
        if (verb === "site") await page.locator(".floors button", { hasText: "F0" }).click();
        for (let t = 0; t < STEP_MS; t += FRAME) await frame(page);
        await runUntil(page, still, `${v.name}: ${verb}`);
      }
      await page.mouse.move(W - 1, H - 1);   // no hover over the floor
      for (let t = 0; t < RUN_MS; t += FRAME) await frame(page);
      await page.screenshot({ path: join(out, `${v.name}.png`) });
      await context.close();
    }
  } finally {
    await browser.close();
  }
  if (errors.length) { console.error(errors.join("\n")); process.exitCode = 1; }
  return errors;
}

function differing(a, b) {
  const p = pixels(a), q = pixels(b);
  if (p.w !== q.w || p.h !== q.h) return Infinity;
  let n = 0;
  for (let i = 0; i < p.out.length; i += 4) if (p.out.readUInt32BE(i) !== q.out.readUInt32BE(i)) n++;
  return n;
}

const args = process.argv.slice(2);
if (args[0] === "--compare") {
  const base = args[1];
  if (!base) { console.error("usage: motion-shots.mjs --compare <baseline-dir> [out-dir]"); process.exit(2); }
  const out = args[2] ?? mkdtempSync(join(tmpdir(), "motion-shots-"));
  let bad = (await render(out)).length;
  const want = readdirSync(base).filter((f) => f.endsWith(".png"));
  for (const f of VIEWS.map((v) => `${v.name}.png`)) {
    if (!want.includes(f)) { console.log(`MISSING in baseline  ${f}`); bad++; continue; }
    const a = readFileSync(join(base, f)), b = readFileSync(join(out, f));
    const n = a.equals(b) ? 0 : differing(a, b);
    console.log(`${n === 0 ? "same" : "DIFF"}  ${f}${n ? `  (${n === Infinity ? "size differs" : `${n} px`})` : ""}`);
    if (n) bad++;
  }
  console.log(`${VIEWS.length} views, ${bad} difference(s); this render: ${out}`);
  process.exit(bad ? 1 : 0);
} else {
  if (!args[0]) { console.error("usage: motion-shots.mjs <out-dir> | --compare <baseline-dir> [out-dir]"); process.exit(2); }
  const errors = await render(args[0]);
  console.log(`${VIEWS.length} views in ${args[0]}${errors.length ? `; ${errors.length} page error(s)` : ", no page errors"}`);
}
