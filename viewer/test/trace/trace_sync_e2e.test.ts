// The floor and the trace pane as one subject (spec 2026-10-13-traces-sync): the picked blue, the selection cleared by
// a trace, floor clicks re-targeting the pane (any box: trace_anybox_e2e.test.ts), rows marked on the floor, pan and
// zoom, stepped Show on floor, and the rail. Needs `npm run build` first and a Chromium:
// VIZ_CHROMIUM=/usr/bin/chromium npx vitest run test/trace_sync_e2e.test.ts
import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { setStill } from "../still";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { fitZoom } from "../../src/trace/panzoom";
import { floorNote, traceMarks } from "../../src/trace/floor";
import { TraceGraph } from "../../src/trace/graph";
import { layoutTrace } from "../../src/trace/layout";
import { initialState } from "../../src/trace/reach";
import { traceable } from "../../src/trace/entries";
import { BLOCK_STORAGE, CHROMIUM, FOCUS, H, W, browserOf, clickMachine, demoText, machineOnScreen, marked, openViewer, recordFloors, rowName, settled, titleEnds, toSite, traceFromInspector } from "./trace_page";

const PICKED = "rgb(0, 85, 191)", PICKED_WASH = "rgb(212, 227, 247)", YELLOW = "rgb(245, 205, 47)";
const demo = () => new Model(JSON.parse(demoText()) as CodeMap);

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("the floor and the trace pane in sync", () => {
  it("the focus row and the row whose detail is open wear the picked blue, never yellow", async () => {
    const m = demo();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      const look = (sel: string) => page.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); return { bg: c.backgroundColor, ring: c.boxShadow }; });
      const focus = await look(".trace .row.focus");
      expect(focus.bg).toBe(PICKED_WASH);
      expect(focus.ring).toContain(PICKED);
      await page.locator(".trace .row:not(.focus) .rname").first().click();
      const pointed = await look(".trace .row.pointed");
      expect(pointed.ring).toContain(PICKED);
      for (const s of [focus, pointed]) { expect(s.bg).not.toBe(YELLOW); expect(s.ring).not.toContain(YELLOW); }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("starting a trace clears the selection; the floor marks the focus, then a clicked row's item instead, naming its floor when elsewhere", async () => {
    const m = demo();
    const view = layoutTrace(m, new TraceGraph(m), initialState(FOCUS));
    const rows = [...view.rows.values()];
    const here = rows.find((r) => r.kind === "node" && !r.focus && m.floorOf(r.node) === SITE && m.liftTo(SITE, r.node) !== m.liftTo(SITE, FOCUS))!;
    const away = rows.find((r) => r.kind === "node" && !r.focus && (m.floorOf(r.node) ?? SITE) !== SITE)!;
    expect(here && away, "the trace has a row on F0 and one deeper").toBeTruthy();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      // S1: the selection is gone; the floor marks the trace's focus
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.itemName(FOCUS));   // shown, not selected (row 64)
      await expect(page.locator(".rail .item.sel").count()).resolves.toBe(0);
      await expect(marked(page)).resolves.toBe(FOCUS);
      await toSite(page);
      const focusItem = m.liftTo(SITE, FOCUS)!;
      await expect(marked(page)).resolves.toBe(focusItem);
      // S3: a row on this floor is marked there, with no floor note
      await rowName(page, here).click();
      await expect(marked(page)).resolves.toBe(m.liftTo(SITE, here.node)!);
      await expect(page.locator(".trace .detail .floor-note").count()).resolves.toBe(0);
      // a row deeper down is marked where it lifts to, and the detail names its floor
      await rowName(page, away).click();
      await expect(marked(page)).resolves.toBe(m.liftTo(SITE, away.node)!);
      await expect(page.locator(".trace .detail .floor-note").textContent()).resolves.toBe(floorNote(m, SITE, away.node));
      // the detail closed: only the focus is marked
      await page.locator(".trace .detail .x").click();
      await expect(marked(page)).resolves.toBe(focusItem);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  const REFUND = "billing::city.parking.billing.BillingService.Live#refund/1";

  it("a click on a method on the floor re-targets the trace in its direction (downstream); the old pointed mark goes with it", async () => {
    const m = demo();
    const c = m.floorOf(FOCUS)!;
    const view = layoutTrace(m, new TraceGraph(m), initialState(FOCUS, "downstream"));
    const sameFloor = [...view.rows.values()].find((r) => r.kind === "node" && !r.focus && m.floorOf(r.node) === c);
    expect(m.floorOf(REFUND)).toBe(c);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await page.getByRole("radio", { name: "Downstream" }).click();
      expect(sameFloor, "a downstream row on the focus's floor").toBeTruthy();
      if (sameFloor) {   // a row on this floor pointed at: the row alone
        await rowName(page, sameFloor).click();
        await expect(marked(page)).resolves.toBe(sameFloor.node);
      }
      await clickMachine(page, m, c, REFUND);
      await titleEnds(page, REFUND);
      await expect(page.getByRole("radio", { name: "Downstream" }).getAttribute("aria-checked")).resolves.toBe("true");
      await expect(page.locator(".trace .detail").count()).resolves.toBe(0);
      await settled(page);   // review focus #2: once settled, the floor marks the new focus alone
      await expect(marked(page)).resolves.toBe(REFUND);
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.itemName(REFUND));   // the new focus, shown (row 64)
      await expect(page.locator(".rail .item.sel").count()).resolves.toBe(0);   // still nothing selected
      // the pane's own Trace from here re-targets the same way: no selection, the new focus marked alone
      const next = [...layoutTrace(m, new TraceGraph(m), initialState(REFUND, "downstream")).rows.values()]
        .find((r) => r.kind === "node" && !r.focus && traceable(m, r.node))!;
      expect(next, "a traceable downstream row of refund").toBeTruthy();
      await rowName(page, next).click();
      await page.locator(".trace .detail button", { hasText: /^Trace from here$/ }).click();
      await titleEnds(page, next.node);
      await settled(page);
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.itemName(next.node));
      await expect(marked(page)).resolves.toBe(traceMarks(m, c, next.node, null).join(" ") || null);   // off this floor: its door
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("the pane pans by dragging its background and zooms with Ctrl+wheel; a plain wheel scrolls; rows are never drags; Fit and the keys; a new focus starts at 100 %", async () => {
    const m = demo();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      const graph = page.locator(".trace .graph");
      const zoomOf = async () => Number(await graph.getAttribute("data-zoom"));
      const scroll = () => graph.evaluate((e) => ({ left: e.scrollLeft, top: e.scrollTop }));
      expect(await zoomOf()).toBe(1);
      const g = (await graph.boundingBox())!;
      // Ctrl+wheel about the top-left corner: three notches in, the page itself not zoomed
      await page.mouse.move(g.x + 8, g.y + 8);
      await page.keyboard.down("Control");
      for (let i = 0; i < 3; i++) await page.mouse.wheel(0, -100);
      await page.keyboard.up("Control");
      await expect.poll(zoomOf).toBeCloseTo(1.331, 2);
      expect(await page.evaluate(() => window.visualViewport?.scale ?? 1)).toBe(1);
      // a plain wheel scrolls and leaves the zoom
      const s0 = await scroll();
      await page.mouse.wheel(0, 120);
      await expect.poll(async () => (await scroll()).top).toBeGreaterThan(s0.top);
      expect(await zoomOf()).toBeCloseTo(1.331, 2);
      // a drag on the background pans
      await graph.evaluate((e) => { e.scrollLeft = 0; e.scrollTop = 0; });
      await page.mouse.move(g.x + 8, g.y + 8);
      await page.mouse.down();
      await page.mouse.move(g.x + 8 - 120, g.y + 8 - 80, { steps: 6 });
      await page.mouse.up();
      const dragged = await scroll();
      expect(dragged.left).toBeGreaterThan(100);
      expect(dragged.top).toBeGreaterThan(60);
      // a press on a row that moves is not a drag
      const row = (await page.locator(".trace .row.focus .rname").boundingBox())!;
      await page.mouse.move(row.x + 10, row.y + row.height / 2);
      await page.mouse.down();
      await page.mouse.move(row.x + 40, row.y + row.height / 2 + 20, { steps: 4 });
      await page.mouse.up();
      expect(await scroll()).toEqual(dragged);
      // Fit (detail closed): the whole sheet at the fit zoom, from the top-left; it reads "Fit trace" (the floor's own
      // reads "Fit")
      await expect(page.getByRole("button", { name: "Fit the trace" }).textContent()).resolves.toBe("Fit trace");
      await page.getByRole("button", { name: "Fit the trace" }).click();
      const size = await page.evaluate(() => {
        const el = document.querySelector(".trace .graph")!, sh = document.querySelector(".trace .sheet") as HTMLElement;
        return { cw: el.clientWidth, ch: el.clientHeight, w: sh.offsetWidth, h: sh.offsetHeight };
      });
      const want = fitZoom(size.w, size.h, size.cw, size.ch);
      await expect.poll(zoomOf).toBeCloseTo(want, 5);
      expect(await scroll()).toEqual({ left: 0, top: 0 });
      // keys with the graph focused: + zooms in one step, 0 fits again
      await graph.focus();
      await page.keyboard.press("+");
      await expect.poll(zoomOf).toBeCloseTo(Math.min(2, want * 1.1), 5);
      // modifier combos are the browser's: Ctrl+0 and Alt+Arrow are neither handled nor swallowed
      await page.evaluate(() => { (window as any).__prevented = []; document.addEventListener("keydown", (e) => { if (e.key === "0" || e.key === "ArrowLeft") (window as any).__prevented.push(e.defaultPrevented); }, false); });
      await page.keyboard.press("Control+0");
      await page.keyboard.press("Alt+ArrowLeft");
      expect(await page.evaluate(() => (window as any).__prevented)).toEqual([false, false]);
      expect(await zoomOf()).toBeCloseTo(Math.min(2, want * 1.1), 5);
      await page.keyboard.press("0");
      await expect.poll(zoomOf).toBeCloseTo(want, 5);
      // a no-move click on the background leaves an open detail open
      await page.locator(".trace .row:not(.focus):not(.gap):not(.fold) .rname").first().click();
      await expect(page.locator(".trace .detail").count()).resolves.toBe(1);
      await page.mouse.click(g.x + 3, g.y + 3);
      await expect(page.locator(".trace .detail").count()).resolves.toBe(1);
      // a new focus (Trace from here) starts at 100 %
      await page.locator(".trace .detail button", { hasText: /^Trace from here$/ }).click();
      await expect.poll(zoomOf).toBe(1);
      // ... with its focus row in view
      await page.waitForSelector(".trace .row.focus");
      const inView = await page.evaluate(() => {
        const g = document.querySelector(".trace .graph")!.getBoundingClientRect(), r = document.querySelector(".trace .row.focus")!.getBoundingClientRect();
        return r.left >= g.left - 1 && r.right <= g.right + 1 && r.top >= g.top - 1 && r.bottom <= g.bottom + 1;
      });
      expect(inView).toBe(true);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("the floor camera brings a newly marked item into view at the same zoom, never moves for one in view, and keeps the focus in view as the pane opens or the divider rises", async () => {
    const m = demo();
    const c = m.floorOf(FOCUS)!;
    const items = [...new Set([...layoutTrace(m, new TraceGraph(m), initialState(FOCUS)).rows.values()]
      .filter((r) => r.kind === "node" && !r.focus && m.floorOf(r.node) === c && m.liftTo(c, r.node) === r.node).map((r) => r.node))];
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      const on = (id: string) => machineOnScreen(page, m, c, id);
      await traceFromInspector(page, m, FOCUS);
      // the pane took the bottom of the screen: the focus, in view before, is in view still
      await expect.poll(async () => (await on(FOCUS)).inside, { timeout: 10_000 }).toBe(true);
      await settled(page);
      // the divider raised: the canvas shrinks under the focus, which is centred again at the same zoom
      const before = await on(FOCUS);
      const divider = page.getByRole("separator", { name: "Resize the trace pane" });
      await divider.focus();
      for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowUp");
      await expect.poll(async () => (await page.locator("canvas").boundingBox())!.height, { timeout: 5_000 }).toBeLessThan(before.rect.y + before.rect.h);
      await expect.poll(async () => (await on(FOCUS)).inside, { timeout: 5_000 }).toBe(true);
      expect((await on(FOCUS)).zoom).toBe(before.zoom);
      let off: string | undefined;
      for (const id of items) if (!(await on(id)).inside) { off = id; break; }
      expect(off, "a row of the trace whose machine is off screen on the focus's floor").toBeTruthy();
      const row = [...layoutTrace(m, new TraceGraph(m), initialState(FOCUS)).rows.values()].find((r) => r.kind === "node" && r.node === off)!;
      const zoom = (await on(FOCUS)).zoom;
      await rowName(page, row).click();
      await expect.poll(async () => (await on(off!)).inside, { timeout: 10_000 }).toBe(true);
      await settled(page);
      expect((await on(off!)).zoom).toBe(zoom);   // panned, not zoomed
      // marked again while in view: the camera stays where it is
      await page.locator(".trace .detail .x").click();
      await expect(marked(page)).resolves.toBe(FOCUS);
      const still = await on(off!);
      expect(still.inside).toBe(true);
      await rowName(page, row).click();
      await expect(marked(page)).resolves.toBe(off!);
      await page.waitForTimeout(700);
      const after = await on(off!);
      expect([after.zoom, after.pan]).toEqual([still.zoom, still.pan]);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("Restore brings the trace's focus back into the floor at the same zoom, even when it was out of view before", async () => {
    const m = demo();
    const c = m.floorOf(FOCUS)!;
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await settled(page);
      // the floor zoomed about its left edge so the focus is pushed off the canvas before maximizing
      const box = (await page.locator("canvas").boundingBox())!;
      await page.mouse.move(box.x + 5, box.y + box.height / 2);
      await page.mouse.wheel(0, -200);
      await settled(page);
      expect((await machineOnScreen(page, m, c, FOCUS)).inside).toBe(false);
      const zoom = (await machineOnScreen(page, m, c, FOCUS)).zoom;
      await page.getByRole("button", { name: "Maximize" }).click();
      await page.getByRole("button", { name: "Restore" }).click();
      await expect.poll(async () => (await machineOnScreen(page, m, c, FOCUS)).inside, { timeout: 10_000 }).toBe(true);
      await settled(page);
      const after = await machineOnScreen(page, m, c, FOCUS);
      expect(after.inside).toBe(true);
      expect(after.zoom).toBe(zoom);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("Show on floor passes through each floor on the way, once even when pressed twice; with Still motion it cuts straight there", async () => {
    const m = demo();
    const c = m.floorOf(FOCUS)!;
    const path = m.path(c);
    expect(path.length, "the focus is three floors down or more").toBeGreaterThanOrEqual(4);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      for (const still of [false, true]) {
        if (still) await setStill(page, true);
        await toSite(page);
        const floors = await recordFloors(page);
        await page.locator(".trace .row.focus .rname").click();
        await expect(page.locator(".trace .detail .floor-note").textContent()).resolves.toBe(floorNote(m, SITE, FOCUS));
        const show = page.locator(".trace .detail button", { hasText: /^Show on floor$/ });
        await show.click();
        if (!still) await show.click();   // a second press during the move is ignored
        await page.waitForFunction((want) => document.querySelector("canvas")?.dataset.floor === want, c, { timeout: 30_000 });
        await settled(page);
        expect(await floors()).toEqual(still ? [c] : path.slice(1));
        await expect(marked(page)).resolves.toBe(FOCUS);
        await expect(page.locator(".insp h2").first().textContent()).resolves.toBe(m.itemName(FOCUS));   // the pointed focus row, shown (row 64)
        await expect(page.locator(".rail .item.sel").count()).resolves.toBe(0);   // nothing selected
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("the rail: Find, On this floor, then Pinned traces; each folds to its heading with its count, remembered across a reload (for the visit with storage blocked)", async () => {
    const map = JSON.parse(demoText()) as CodeMap;
    const m = new Model(map);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      for (const blocked of [false, true]) {
        const page = await openViewer(browser, demoText(), errors, blocked ? [BLOCK_STORAGE] : []);
        const heads = (await page.locator(".rail section > h2").allTextContents()).map((t) => t.trim());
        expect(heads).toEqual(["Find", `On this floor (${Object.keys(m.floor(SITE)!.items).length})`, `Pinned traces (${map.pins!.length})`]);
        if (!blocked) {   // a heading under the pointer turns ink on paper: blue is for what is picked only
          await page.getByRole("button", { name: /^Find/ }).hover();
          const hover = await page.getByRole("button", { name: /^Find/ }).evaluate((e) => { const c = getComputedStyle(e); return { bg: c.backgroundColor, fg: c.color }; });
          expect(hover).toEqual({ bg: "rgb(255, 255, 255)", fg: "rgb(27, 29, 33)" });
          await page.mouse.move(W / 2, H / 2);
        }
        for (const name of [/^On this floor/, /^Pinned traces/]) {
          const b = page.getByRole("button", { name });
          await b.click();
          await expect(b.getAttribute("aria-expanded")).resolves.toBe("false");
        }
        await expect(page.locator("#rail-floor").isHidden()).resolves.toBe(true);
        await expect(page.locator("#rail-pins").isHidden()).resolves.toBe(true);
        await expect(page.locator("#rail-find").isVisible()).resolves.toBe(true);
        await page.reload();
        await page.waitForSelector("canvas");
        await expect(page.locator("#rail-floor").isHidden()).resolves.toBe(!blocked);
        await expect(page.locator("#rail-pins").isHidden()).resolves.toBe(!blocked);
        if (!blocked) {   // open again: the lists come back and stay open
          await page.getByRole("button", { name: /^On this floor/ }).click();
          await page.getByRole("button", { name: /^Pinned traces/ }).click();
          await expect(page.locator("#rail-floor").isVisible()).resolves.toBe(true);
          await expect(page.locator(".rail .pins .pin").count()).resolves.toBe(map.pins!.length);
        }
        await page.close();
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);
});
