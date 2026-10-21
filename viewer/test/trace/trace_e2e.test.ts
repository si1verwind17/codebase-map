// The trace pane in a browser: started from the inspector or a pinned trace, the split with its divider and
// maximize (remembered, and working with storage blocked), the floor following the trace, Esc, pins and their export,
// and the big map's responsiveness. Needs `npm run build` first and a Chromium:
// VIZ_CHROMIUM=/usr/bin/chromium npx vitest run test/trace_e2e.test.ts   (add VIZ_BIG_MAP=<map> for the big-map case)
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium, type Browser, type Page } from "playwright-core";
import { describe, expect, it } from "vitest";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { TraceGraph } from "../../src/trace/graph";
import { initialState } from "../../src/trace/reach";
import { layoutTrace, traceTitle } from "../../src/trace/layout";
import { EXAMPLE_LABEL } from "../../src/trace/examples";
import { GL_ARGS } from "../gl";

const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
const BIG = process.env.VIZ_BIG_MAP ?? "";
const BUILT = new URL("../../../skills/visualizing-codebases/viewer/dist/viewer.html", import.meta.url);
const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const W = 1440, H = 900;
/** A method of the demo with callers and callees: its trace has boxes on both sides. */
const FOCUS = "billing::city.parking.billing.BillingService.Live#charge/1";

const demoText = () => readFileSync(DEMO, "utf8");
const BLOCK_STORAGE = () => {
  Object.defineProperty(window, "localStorage", { get() { throw new DOMException("blocked", "SecurityError"); } });
};
const NO_PICKER = () => { delete (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker; };

async function openViewer(browser: Browser, mapText: string, errors: string[], init: (() => void)[] = []): Promise<Page> {
  const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", mapText.replaceAll("<", "\\u003c"));
  const file = join(mkdtempSync(join(tmpdir(), "viz-trace-")), "index.html");
  writeFileSync(file, html);
  const page = await browser.newPage({ viewport: { width: W, height: H } });
  page.on("pageerror", (e) => errors.push(e.message));
  for (const f of init) await page.addInitScript(f);
  await page.goto("file://" + file);
  await page.waitForSelector("canvas");
  return page;
}

const settled = (page: Page) => page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera !== "moving" && !document.body.innerText.includes("Moving…"), null, { timeout: 15_000 });

/** Find `id` by its code, select it, press the inspector's Trace button; the pane's rows are drawn. `selected` runs
 *  once the selection has settled, before the press. */
async function traceFromInspector(page: Page, m: Model, id: string, selected?: () => Promise<void>) {
  await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get(id)!);
  await page.locator(".rail .list button").first().click();
  await page.waitForFunction((name) => document.querySelector(".insp h2")?.textContent?.trim() === name, m.itemName(id), { timeout: 10_000 });
  await settled(page);
  await selected?.();
  await page.locator(".insp header button", { hasText: /^Trace$/ }).click();
  await page.waitForSelector(".trace .row");
}

/** The floor camera's zoom (the canvas's `data-zoom`, set by floor/camera.ts). */
const zoom = (page: Page) => page.locator("canvas").getAttribute("data-zoom");
const paneHeight = async (page: Page) => (await page.locator(".pane").boundingBox())!.height;
const browserOf = () => chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("the trace pane in a browser", () => {
  it("starts from the inspector, splits the screen, follows the floor, changes direction and depth, and closes with Esc", async () => {
    const m = new Model(JSON.parse(demoText()) as CodeMap);
    const g = new TraceGraph(m);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      const floorBefore = (await page.locator(".canvas").boundingBox())!.height;
      let zoomBefore: string | null = null;
      await traceFromInspector(page, m, FOCUS, async () => { zoomBefore = await zoom(page); });
      // the split: the floor is shorter, the pane below it at the default 45 % of the window
      expect((await page.locator(".canvas").boundingBox())!.height).toBeLessThan(floorBefore - 200);
      expect(Math.abs(await paneHeight(page) - 0.45 * H)).toBeLessThanOrEqual(2);
      expect(zoomBefore).toBeTruthy();
      await expect(zoom(page)).resolves.toBe(zoomBefore);   // the floor keeps its zoom
      // the rows are the layout's; the focus row's label is whole, its title the pane's (with the node id on hover)
      const both = layoutTrace(m, g, initialState(FOCUS));
      const focusRow = [...both.rows.values()].find((r) => r.focus)!;
      await expect(page.locator(".trace .row").count()).resolves.toBe(both.rows.size);
      await expect(page.locator(".trace .row.focus .rname").textContent()).resolves.toContain("charge");
      expect(await page.locator(".trace .row.focus .rname").evaluate((e) => e.scrollWidth <= e.clientWidth)).toBe(true);
      await expect(page.locator(".trace > header h2").textContent()).resolves.toContain(focusRow.label);
      await expect(page.locator(".trace > header h2").getAttribute("title")).resolves.toBe(`${focusRow.label} — ${FOCUS}`);
      // Pin offers the focus row's label as the title (the rail shows the direction), the field taking the keys at once (typing
      // replaces the offered words); Esc there closes the form only
      await page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).click();
      await expect(page.locator("#pin-title").inputValue()).resolves.toBe(focusRow.label);
      await page.keyboard.type("Charge path");
      await expect(page.locator("#pin-title").inputValue()).resolves.toBe("Charge path");
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace .naming").count()).resolves.toBe(0);
      await expect(page.locator(".trace").count()).resolves.toBe(1);
      // an arrow inside a box is drawn above the box, and its elbow into the row is its own: the elbow's middle picks it
      const inBox = both.arrows.filter((a) => both.boxes.some((b) => b.rows.some((r) => r.id === a.from) && b.rows.some((r) => r.id === a.to)));
      expect(inBox.length, "the trace has an arrow inside a box").toBeGreaterThan(0);
      const hits = await page.evaluate((ids) => ids.map((id) => {
        const gEl = document.querySelector(`.trace g.arrow[data-id="${CSS.escape(id)}"]`) as SVGGElement | null;
        const path = gEl?.querySelector("path.hit") as SVGPathElement | null;
        if (!gEl || !path) return `missing ${id}`;
        path.scrollIntoView({ block: "center", inline: "center" });
        const p = path.getPointAtLength(path.getTotalLength() / 2), ctm = path.getScreenCTM()!;
        const x = p.x * ctm.a + p.y * ctm.c + ctm.e, y = p.x * ctm.b + p.y * ctm.d + ctm.f;
        const el = document.elementFromPoint(x, y), hit = el?.closest(".trace g.arrow") as SVGGElement | null;
        return hit?.dataset.id === id ? "arrow" : `${id}: ${el?.tagName} ${hit?.dataset.id ?? el?.getAttribute("class")}`;
      }), inBox.map((a) => a.id));
      expect(hits).toEqual(inBox.map(() => "arrow"));
      // a row's detail closes when a direction change drops the row
      const upOnly = [...both.rows.values()].find((r) => r.kind === "node" && !r.focus && r.side !== 0
        && !layoutTrace(m, g, initialState(FOCUS, "downstream")).rows.has(r.id))!;
      expect(upOnly, "the trace has an upstream-only row").toBeTruthy();
      await page.locator(`.trace .rname[title="${upOnly.label} — ${upOnly.node}"]`).click();
      await expect(page.locator(".trace .detail h3").textContent()).resolves.toBe(upOnly.label);
      // the floor: the traced items stay lit; hovering the focus row rings its box
      expect(Number(await page.locator("canvas").getAttribute("data-traced"))).toBeGreaterThan(0);
      await page.locator(".trace .row.focus").hover();
      await page.waitForFunction(() => !!document.querySelector("canvas")?.dataset.traceHover, null, { timeout: 5_000 });
      await page.mouse.move(5, H - 5);
      await page.waitForFunction(() => !document.querySelector("canvas")?.dataset.traceHover, null, { timeout: 5_000 });
      // direction
      await page.getByRole("radio", { name: "Downstream" }).click();
      const down = layoutTrace(m, g, initialState(FOCUS, "downstream"));
      await expect(page.locator(".trace .row").count()).resolves.toBe(down.rows.size);
      await expect(page.locator(".trace .detail").count()).resolves.toBe(0);
      // a `+` adds one hop beyond its row
      const frontier = [...down.rows.values()].find((r) => r.more > 0);
      if (frontier) {
        await page.getByRole("button", { name: `Show ${frontier.more} more beyond ${frontier.label}` }).first().click();
        const more = layoutTrace(m, g, { ...initialState(FOCUS, "downstream"), expanded: new Set([frontier.id]) });
        await expect(page.locator(".trace .row").count()).resolves.toBe(more.rows.size);
      }
      // the arrows come after the boxes in the page: Tab reaches the rows in reading order first
      await expect(page.evaluate(() => document.querySelector(".trace .sheet")?.lastElementChild?.tagName.toLowerCase())).resolves.toBe("svg");
      // Esc, one thing per press (focus outside the title field): the pin form, then the detail panel, then the pane
      await page.locator(".trace .row.focus .rname").click();
      await page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).click();
      await expect(page.locator(".trace .detail").count()).resolves.toBe(1);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace .naming").count()).resolves.toBe(0);
      await expect(page.locator(".trace .detail").count()).resolves.toBe(1);
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace .detail").count()).resolves.toBe(0);
      await expect(page.locator(".trace").count()).resolves.toBe(1);
      // then the pane; closing with a row hovered drops its ring too. The trace cleared the selection when it started
      // (spec S1): the inspector is on the floor, and a further Esc changes nothing
      await page.locator(".trace .row.focus").hover();
      await page.waitForFunction(() => !!document.querySelector("canvas")?.dataset.traceHover, null, { timeout: 5_000 });
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace").count()).resolves.toBe(0);
      await expect(page.locator("canvas").getAttribute("data-traced")).resolves.toBeNull();
      await expect(page.locator("canvas").getAttribute("data-trace-hover")).resolves.toBeNull();
      await expect(page.locator("canvas").getAttribute("data-trace-marked")).resolves.toBeNull();
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.label(m.floorOf(FOCUS)!));
      expect((await page.locator(".canvas").boundingBox())!.height).toBeGreaterThan(floorBefore - 2);
      await page.keyboard.press("Escape");
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.label(m.floorOf(FOCUS)!));
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("a service lists its entry points with a Trace button each; a click on a row shows its examples, labelled", async () => {
    const map = JSON.parse(demoText()) as CodeMap;
    const m = new Model(map);
    const entry = map.examples?.entries?.[0];
    expect(entry, "the demo map has entry examples").toBeTruthy();
    const svc = m.path(m.floorOf(entry!.node)!)[1];
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get(svc)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((name) => document.querySelector(".insp h2")?.textContent?.trim() === name, m.itemName(svc), { timeout: 10_000 });
      await expect(page.locator(".insp .starts .tab").textContent()).resolves.toMatch(/^Entry points \(\d+\)$/);
      await page.getByRole("button", { name: `Trace ${m.itemName(entry!.node)}`, exact: true }).first().click();
      await page.waitForSelector(".trace .row.focus");
      await page.locator(".trace .row.focus .rname").click();
      await expect(page.locator(".trace .detail").textContent()).resolves.toContain(EXAMPLE_LABEL);
      await expect(page.locator(".trace .detail h4").first().textContent()).resolves.toBe(entry!.key);
      // a datastore's trace starts at its tables, and is titled (and pinned by default) after the datastore itself
      const ds = m.map.nodes.find((n) => n.kind === "datastore" && m.map.nodes.some((t) => t.kind === "table" && t.parent === n.id))!;
      const dsTitle = traceTitle(m, layoutTrace(m, new TraceGraph(m), initialState(ds.id)));
      expect(dsTitle).toBe(m.label(ds.id));
      await page.locator(".trace > header .tools button", { hasText: /^Close$/ }).click();
      await traceFromInspector(page, m, ds.id);
      await expect(page.locator(".trace > header h2").textContent()).resolves.toContain(dsTitle);
      await page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).click();
      await expect(page.locator("#pin-title").inputValue()).resolves.toBe(dsTitle);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("maximize fills the screen and restores the split; the divider's place is remembered, and with storage blocked works for the visit", async () => {
    const m = new Model(JSON.parse(demoText()) as CodeMap);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      for (const blocked of [false, true]) {
        const page = await openViewer(browser, demoText(), errors, blocked ? [BLOCK_STORAGE] : []);
        let zoomBefore: string | null = null;
        await traceFromInspector(page, m, FOCUS, async () => { zoomBefore = await zoom(page); });
        const divider = (await page.getByRole("separator", { name: "Resize the trace pane" }).boundingBox())!;
        await page.mouse.move(divider.x + 200, divider.y + 4);
        await page.mouse.down();
        await page.mouse.move(divider.x + 200, divider.y - 96, { steps: 6 });
        await page.mouse.up();
        const dragged = await paneHeight(page);
        expect(dragged).toBeGreaterThan(0.45 * H + 80);
        await expect(zoom(page)).resolves.toBe(zoomBefore);   // the floor keeps its zoom through the divider's move
        await page.getByRole("button", { name: "Maximize" }).click();
        expect(await page.locator(".pane").boundingBox()).toEqual({ x: 0, y: 0, width: W, height: H });
        await page.getByRole("button", { name: "Restore" }).click();
        expect(Math.abs(await paneHeight(page) - dragged)).toBeLessThanOrEqual(1);
        await expect(zoom(page)).resolves.toBe(zoomBefore);   // and through maximize and restore
        await page.getByRole("separator", { name: "Resize the trace pane" }).focus();
        await page.keyboard.press("ArrowUp");
        expect(Math.abs(await paneHeight(page) - (dragged + 0.05 * H))).toBeLessThanOrEqual(2);
        const kept = await paneHeight(page);
        await page.reload();
        await page.waitForSelector("canvas");
        await traceFromInspector(page, m, FOCUS);
        expect(Math.abs(await paneHeight(page) - (blocked ? 0.45 * H : kept))).toBeLessThanOrEqual(2);
        // a cancelled drag (a touch turned into a scroll) ends where it is: later moves do not resize
        const at = (await page.getByRole("separator", { name: "Resize the trace pane" }).boundingBox())!;
        await page.mouse.move(at.x + 200, at.y + 4);
        await page.mouse.down();
        await page.mouse.move(at.x + 200, at.y + 44, { steps: 4 });
        const cancelled = await paneHeight(page);
        await page.getByRole("separator", { name: "Resize the trace pane" }).dispatchEvent("pointercancel");
        await page.mouse.move(at.x + 200, at.y + 124, { steps: 4 });
        await page.mouse.up();
        expect(cancelled).toBeLessThan(kept - 20);
        expect(Math.abs(await paneHeight(page) - cancelled)).toBeLessThanOrEqual(1);
        await page.close();
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("pins: a pinned trace starts from the panel; pin and unpin act at once, survive a reload and go out under ## Pins", async () => {
    const map = JSON.parse(demoText()) as CodeMap;
    const m = new Model(map);
    const first = map.pins?.[0];
    expect(first, "the demo map has pins").toBeTruthy();
    const withMissing = JSON.stringify({ ...map, pins: [...map.pins!, { id: "gone", title: "a renamed start", start: "nope#x/0", direction: "both", by: "user" }] });
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, withMissing, errors, [NO_PICKER]);
      const panel = page.locator(".rail .pins");
      await expect(panel.locator(".pin").count()).resolves.toBe(map.pins!.length + 1);
      await expect(panel.locator(".pin.missing").textContent()).resolves.toContain("start not in this map");
      await expect(panel.locator(".pin.missing .pin-start").isDisabled()).resolves.toBe(true);
      // a pinned trace starts in its own direction, and the pane offers Unpin
      await panel.locator(".pin-start", { hasText: first!.title }).click();
      await page.waitForSelector(".trace .row.focus");
      await expect(page.getByRole("radio", { name: first!.direction[0].toUpperCase() + first!.direction.slice(1) }).getAttribute("aria-checked")).resolves.toBe("true");
      await page.locator(".trace header button", { hasText: /^Unpin$/ }).click();
      await expect(panel.locator(".pin-start", { hasText: first!.title }).count()).resolves.toBe(0);
      await expect(page.getByRole("button", { name: /^Save for the agent \(1\)$/ }).isEnabled()).resolves.toBe(true);
      // pin a new trace with a title holding a `|`
      await page.locator(".trace header button", { hasText: /^Close$/ }).click();
      await traceFromInspector(page, m, FOCUS);
      await page.getByRole("radio", { name: "Upstream" }).click();   // a direction no demo pin starts this method with
      await page.locator(".trace header button", { hasText: /^Pin$/ }).click();
      await page.getByLabel("Pin title").press("Escape");                  // Esc in the title cancels the pin, not the pane
      await expect(page.getByLabel("Pin title").count()).resolves.toBe(0);
      await expect(page.locator(".trace").count()).resolves.toBe(1);
      await page.locator(".trace header button", { hasText: /^Pin$/ }).click();
      await page.getByLabel("Pin title").fill("charge | settle");
      await page.getByLabel("Pin title").press("Enter");
      await expect(panel.locator(".pin-start", { hasText: "charge / settle" }).count()).resolves.toBe(1);
      await expect(page.locator(".trace header button", { hasText: /^Unpin$/ }).count()).resolves.toBe(1);
      // a reload keeps both changes
      await page.reload();
      await page.waitForSelector("canvas");
      await expect(panel.locator(".pin-start", { hasText: "charge / settle" }).count()).resolves.toBe(1);
      await expect(panel.locator(".pin-start", { hasText: first!.title }).count()).resolves.toBe(0);
      // the export: comments unchanged, then the pins section exactly
      const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /^Save for the agent \(2\)$/ }).click()]);
      const text = readFileSync((await download.path())!, "utf8");
      expect(text).toContain("_No comments._");
      expect(text.endsWith(`\n## Pins\n- pin: charge / settle | start: ${FOCUS} | direction: upstream\n- unpin: ${first!.id}\n`)).toBe(true);
      // every pin line fits the grammar the agent reads (SKILL.md, Review comments)
      for (const line of text.slice(text.indexOf("## Pins")).split("\n").slice(1).filter(Boolean)) {
        expect(line).toMatch(/^(- pin: [^|]+ \| start: \S+ \| direction: (downstream|upstream|both)|- unpin: \S+)$/);
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("a pin made here and a later map pin sharing an id are both listed", async () => {
    const map = JSON.parse(demoText()) as CodeMap;
    const first = map.pins![0];
    const key = `viz-code:pins:${map.meta.repo}`;
    const local = JSON.stringify({ added: [{ id: first.id, title: "made here first", start: first.start, direction: first.direction === "both" ? "upstream" : "both" }], removed: [] });
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: W, height: H } });
      await page.addInitScript(([k, v]) => { try { window.localStorage.setItem(k, v); } catch { /* blocked */ } }, [key, local]);
      page.on("pageerror", (e) => errors.push(e.message));
      const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", demoText().replaceAll("<", "\\u003c"));
      const file = join(mkdtempSync(join(tmpdir(), "viz-trace-")), "index.html");
      writeFileSync(file, html);
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const panel = page.locator(".rail .pins");
      await expect(panel.locator(".pin").count()).resolves.toBe(map.pins!.length + 1);
      await expect(panel.locator(".pin-start", { hasText: "made here first" }).count()).resolves.toBe(1);
      await expect(panel.locator(".pin-start", { hasText: first.title }).count()).resolves.toBe(1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it.runIf(BIG && existsSync(BIG))("the large real map (VIZ_BIG_MAP): the pane opens at depth 2 from its busiest method quickly, and a row's hover answers at once", async () => {
    const text = readFileSync(BIG, "utf8");
    const m = new Model(JSON.parse(text) as CodeMap);
    const g = new TraceGraph(m);
    const busiest = m.map.nodes.filter((n) => n.kind === "method").map((n) => n.id).sort((a, b) => g.degree(b) - g.degree(a) || a.localeCompare(b))[0];
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, text, errors);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get(busiest)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((name) => document.querySelector(".insp h2")?.textContent?.trim() === name, m.itemName(busiest), { timeout: 10_000 });
      await settled(page);
      // in the page: the click, Svelte's update, the floor's restyle and two frames; one warm-up open, then the median of 5
      const open = () => page.evaluate(async () => {
        const trace = () => [...document.querySelectorAll<HTMLButtonElement>(".insp header button")].find((b) => b.textContent?.trim() === "Trace");
        const t = performance.now();
        trace()!.click();
        await new Promise((r) => setTimeout(r, 0));
        for (let i = 0; i < 2; i++) await new Promise((r) => requestAnimationFrame(() => r(null)));
        return document.querySelectorAll(".trace .row").length ? performance.now() - t : -1;
      });
      const close = async () => { await page.keyboard.press("Escape"); await page.waitForFunction(() => !document.querySelector(".trace .row")); };
      // a trace clears the selection (spec S1): pick the method again from the Find list before the next open
      const reselect = async () => {
        await page.locator(".rail .list button").first().click();
        await page.waitForFunction((name) => document.querySelector(".insp h2")?.textContent?.trim() === name, m.itemName(busiest), { timeout: 10_000 });
        await settled(page);
      };
      const runs: number[] = [];
      for (let i = 0; i < 6; i++) {
        const ms = await open();
        expect(ms, "the pane is drawn").toBeGreaterThan(0);
        if (i > 0) runs.push(ms);
        if (i < 5) { await close(); await settled(page); await reselect(); }
      }
      const median = runs.sort((a, b) => a - b)[2];
      console.log(`big map: pane open median ${median.toFixed(0)} ms (runs ${runs.map((r) => r.toFixed(0)).join(", ")})`);
      expect(median, "the pane opens within 500 ms").toBeLessThan(500);
      const rows = page.locator(".trace .row");
      const n = Math.min(await rows.count(), 8);
      for (let i = 0; i < n; i++) {
        const hover = await rows.nth(i).evaluate((el) => { const t = performance.now(); el.dispatchEvent(new MouseEvent("mouseenter")); return performance.now() - t; });
        expect(hover, "a hover answers within 100 ms").toBeLessThan(100);
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);
});
