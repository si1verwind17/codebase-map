// Shared by the trace pane's sync tests (trace_sync_e2e.test.ts): open the built viewer on a map in Chromium, start a
// trace from the inspector, wait for the floor to settle. Needs `npm run build` first.
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, type Browser, type Page } from "playwright-core";
import type { Model } from "../../src/model/model";
import { SITE } from "../../src/model/model";
import { planFloor } from "../../src/factory/plan";
import { toGeometry } from "../../src/factory/layout";
import { clampFit, fitScale } from "../../src/floor/fitscale";
import { GL_ARGS } from "../gl";

export const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
export const W = 1440, H = 900;
const BUILT = new URL("../../../skills/visualizing-codebases/viewer/dist/viewer.html", import.meta.url);
const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
/** A method of the demo four floors down (F4), with callers and callees: its trace has boxes on both sides. */
export const FOCUS = "billing::city.parking.billing.BillingService.Live#charge/1";

export const demoText = () => readFileSync(DEMO, "utf8");
export const BLOCK_STORAGE = () => {
  Object.defineProperty(window, "localStorage", { get() { throw new DOMException("blocked", "SecurityError"); } });
};
export const browserOf = () => chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });

export async function openViewer(browser: Browser, mapText: string, errors: string[], init: (() => void)[] = []): Promise<Page> {
  const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", mapText.replaceAll("<", "\\u003c"));
  const file = join(mkdtempSync(join(tmpdir(), "viz-sync-")), "index.html");
  writeFileSync(file, html);
  const page = await browser.newPage({ viewport: { width: W, height: H } });
  page.on("pageerror", (e) => errors.push(e.message));
  for (const f of init) await page.addInitScript(f);
  await page.goto("file://" + file);
  await page.waitForSelector("canvas");
  return page;
}

/** Waits until the floor is still: the camera not moving and no floor change under way (the Floors list's buttons are
 *  disabled for the whole of a move, App `travelling`; the canvas reports the new floor as soon as it is drawn, while
 *  its leave or enter animation still runs, and a press made then is ignored). */
export const settled = (page: Page) => page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera !== "moving"
  && !document.querySelector(".floors button:disabled"), null, { timeout: 15_000 });

/** Find `id` by its code, select it, press the inspector's Trace button; the pane's rows are drawn. */
export async function traceFromInspector(page: Page, m: Model, id: string, selected?: () => Promise<void>) {
  await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get(id)!);
  await page.locator(".rail .list button").first().click();
  await page.waitForFunction((name) => document.querySelector(".insp h2")?.textContent?.trim() === name, m.itemName(id), { timeout: 10_000 });
  await settled(page);
  await selected?.();
  await page.locator(".insp header button", { hasText: /^Trace$/ }).click();
  await page.waitForSelector(".trace .row");
}

/** Click machine `id` on floor `c` (the floor shown): the floor's Fit first, then the machine's centre as the scene's
 *  fit places it (floor/camera.ts `fit`: centred at the clamped fit zoom, 14 px × zoom down for the title). */
export async function clickMachine(page: Page, m: Model, c: string, id: string) {
  await page.locator(".floor-tools button", { hasText: /^Fit$/ }).click();
  await page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera === "idle", null, { timeout: 15_000 });
  const b = m.bundles(c);
  const geo = toGeometry(planFloor(m, c, b.doors, b.bundles, b.layered).tf);
  const r = geo.machines.get(id);
  if (!r) throw new Error(`${id} is not a machine on ${c}`);
  const { w, h } = geo.bounds;
  const box = (await page.locator("canvas").boundingBox())!;
  const s = clampFit(fitScale(w, h, box.width, box.height, c === SITE));
  const x0 = (box.width - w * s) / 2, y0 = (box.height - h * s) / 2 + 14 * s;
  await page.mouse.click(box.x + x0 + (r.x + r.w / 2) * s, box.y + y0 + (r.y + r.h / 2) * s);
}

/** Records the floors the canvas shows from now on (its `data-floor`, written on every floor drawn), each change once;
 *  the returned function reads them. */
export async function recordFloors(page: Page): Promise<() => Promise<string[]>> {
  await page.evaluate(() => {
    const c = document.querySelector("canvas")!;
    const w = window as unknown as { __floors: string[] };
    w.__floors = [];
    new MutationObserver(() => { const f = c.dataset.floor ?? ""; if (w.__floors.at(-1) !== f) w.__floors.push(f); })
      .observe(c, { attributes: true, attributeFilter: ["data-floor"] });
  });
  return () => page.evaluate(() => (window as unknown as { __floors: string[] }).__floors);
}

/** Machine `id` of floor `c` (the floor shown) on the canvas now, in canvas px, from the camera the canvas reports
 *  (`data-zoom`, `data-pan`: floor/camera.ts `markZoom`); `inside`: the whole box is within the canvas. */
export async function machineOnScreen(page: Page, m: Model, c: string, id: string) {
  const b = m.bundles(c);
  const r = toGeometry(planFloor(m, c, b.doors, b.bundles, b.layered).tf).machines.get(id);
  if (!r) throw new Error(`${id} is not a machine on ${c}`);
  const cam = await page.evaluate(() => { const d = document.querySelector("canvas")!; return { zoom: d.dataset.zoom ?? "", pan: d.dataset.pan ?? "", w: d.clientWidth, h: d.clientHeight }; });
  const s = Number(cam.zoom), [px, py] = cam.pan.split(" ").map(Number);
  const rect = { x: px + r.x * s, y: py + r.y * s, w: r.w * s, h: r.h * s };
  const inside = rect.x >= 0 && rect.y >= 0 && rect.x + rect.w <= cam.w && rect.y + rect.h <= cam.h;
  return { rect, inside, zoom: cam.zoom, pan: cam.pan };
}

/** The items the floor marks for the trace (the canvas's `data-trace-marked`: ids sorted, space-joined), null for none. */
export const marked = (page: Page) => page.locator("canvas").getAttribute("data-trace-marked");

/** Floor F0 from the Floors list; waits for it to be drawn and still. */
export async function toSite(page: Page) {
  await page.locator(".floors button", { hasText: /^F0/ }).click();
  await page.waitForFunction(() => document.querySelector("canvas")?.dataset.floor === "site", null, { timeout: 15_000 });
  await settled(page);
}

/** A row's name button, by its label and node (its title starts with both). */
export const rowName = (page: Page, r: { label: string; node: string }) => page.locator(`.trace .rname[title^="${r.label} — ${r.node}"]`).first();

/** Waits until the pane's heading names focus `id` (its title attribute ends "— id"). */
export const titleEnds = (page: Page, id: string) =>
  page.waitForFunction((x) => document.querySelector(".trace > header h2")?.getAttribute("title")?.endsWith(`— ${x}`), id, { timeout: 15_000 });

/** Click line `key` on F0 (the floor shown) on a tile only it holds, as the floor's Fit places it (see clickMachine). */
export async function clickLine(page: Page, m: Model, key: string) {
  await page.locator(".floor-tools button", { hasText: /^Fit$/ }).click();
  await page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera === "idle", null, { timeout: 15_000 });
  const b = m.bundles(SITE);
  const { tf, routes } = planFloor(m, SITE, b.doors, b.bundles, b.layered);
  const { w, h } = toGeometry(tf).bounds;
  const r = routes.find((q) => q.key === key);
  if (!r) throw new Error(`${key} is not a line on F0`);
  const p = r.pieces.find((x) => !x.under && !x.join && !routes.some((o) => o !== r && o.pieces.some((z) => z.x === x.x && z.y === x.y)));
  if (!p) throw new Error(`${key} has no tile of its own`);
  const box = (await page.locator("canvas").boundingBox())!;
  const s = clampFit(fitScale(w, h, box.width, box.height, true));
  const x0 = (box.width - w * s) / 2, y0 = (box.height - h * s) / 2 + 14 * s;
  await page.mouse.click(box.x + x0 + (p.x * 24 + 12) * s, box.y + y0 + (p.y * 24 + 12) * s);
}
