// Traces: one mark, any box traces (spec 2026-10-13-traces-any-box): one blue ring on the floor, any box or line clicked
// while the pane is open re-targets the trace, the trace's own box keeps it, no dimmed pane. Needs `npm run build` first
// and a Chromium: VIZ_CHROMIUM=/usr/bin/chromium npx vitest run test/trace_anybox_e2e.test.ts
import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { TraceGraph } from "../../src/trace/graph";
import { layoutTrace } from "../../src/trace/layout";
import { initialState } from "../../src/trace/reach";
import { entryPoints, lineStart, seedsFor } from "../../src/trace/entries";
import { CHROMIUM, FOCUS, browserOf, clickLine, clickMachine, demoText, machineOnScreen, marked, openViewer, rowName, settled, titleEnds, toSite, traceFromInspector } from "./trace_page";

const PICKED = "rgb(0, 85, 191)", PICKED_WASH = "rgb(212, 227, 247)";
const demo = () => new Model(JSON.parse(demoText()) as CodeMap);
const look = (page: import("playwright-core").Page, sel: string) =>
  page.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); return { bg: c.backgroundColor, ring: c.boxShadow }; });

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("traces: one mark, any box", () => {
  it("one blue mark (row 62): a pointed row takes the floor ring and the keyline from the focus; closing the detail, or pointing the focus row, gives them back", async () => {
    const m = demo();
    const rows = [...layoutTrace(m, new TraceGraph(m), initialState(FOCUS)).rows.values()];
    const here = rows.find((r) => r.kind === "node" && !r.focus && m.floorOf(r.node) === SITE && m.liftTo(SITE, r.node) !== m.liftTo(SITE, FOCUS))!;
    expect(here, "a row on F0 that is not the focus's box").toBeTruthy();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await toSite(page);
      const focusItem = m.liftTo(SITE, FOCUS)!;
      await expect.poll(() => marked(page)).toBe(focusItem);
      // a row pointed: the floor rings its item alone; the pane's keyline moves to it, the focus keeps its wash
      await rowName(page, here).click();
      await expect.poll(() => marked(page)).toBe(m.liftTo(SITE, here.node)!);
      const f = await look(page, ".trace .row.focus");
      expect(f.bg).toBe(PICKED_WASH);
      expect(f.ring).toBe("none");
      expect((await look(page, ".trace .row.pointed")).ring).toContain(PICKED);
      // the detail closed: the ring and the keyline go back to the focus
      await page.locator(".trace .detail .x").click();
      await expect.poll(() => marked(page)).toBe(focusItem);
      expect((await look(page, ".trace .row.focus")).ring).toContain(PICKED);
      // the focus row pointed: it is the one mark, in both panes
      await page.locator(".trace .row.focus .rname").first().click();
      await expect.poll(() => marked(page)).toBe(focusItem);
      await expect(page.locator(".trace .row.focus.pointed").count()).resolves.toBe(1);
      expect((await look(page, ".trace .row.focus.pointed")).ring).toContain(PICKED);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("a service traces from its entry points: the header names it, its kind and the count; above five they fold; the pin offers its name and plays back the same trace", async () => {
    const m = demo();
    const browser = await browserOf();
    const errors: string[] = [];
    const h2 = (page: import("playwright-core").Page) => page.locator(".trace > header h2").textContent();
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, "svc:feature-store");
      await expect(h2(page)).resolves.toMatch(/feature-store · service · 1 entry point$/);
      await expect(page.locator(".trace .row.focus").count()).resolves.toBe(1);
      await page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).click();
      await expect(page.locator("#pin-title").inputValue()).resolves.toBe("feature-store");
      await page.locator(".naming button", { hasText: /^Pin$/ }).click();
      await page.locator(".trace > header .tools button", { hasText: /^Close$/ }).click();
      await page.locator(".rail .pins .pin-start", { hasText: "feature-store" }).first().click();
      await expect(h2(page)).resolves.toMatch(/feature-store · service · 1 entry point$/);
      await page.locator(".trace > header .tools button", { hasText: /^Close$/ }).click();
      // ten entry points: five shown, the total in the header, show all brings the rest
      await traceFromInspector(page, m, "svc:nightly-jobs");
      await expect(h2(page)).resolves.toMatch(/nightly-jobs · service · 10 entry points$/);
      await expect(page.locator(".trace .row.focus").count()).resolves.toBe(5);
      await page.locator(".trace > header .chip.seeds", { hasText: /^show all 10$/ }).click();
      await expect.poll(() => page.locator(".trace .row.focus").count()).toBe(10);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("any box re-targets the trace (row 63): a service clicked traces from its entry points, the first service clicked again traces it again; nothing dims", async () => {
    const m = demo();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, "svc:notifier");
      await titleEnds(page, "svc:notifier");
      await clickMachine(page, m, SITE, "svc:feature-store");
      await titleEnds(page, "svc:feature-store");
      await expect(page.locator(".trace > header h2").textContent()).resolves.toMatch(/feature-store · service · 1 entry point$/);
      await expect(page.locator(".trace .dim-note").count()).resolves.toBe(0);
      await expect(page.locator(".trace .body[inert]").count()).resolves.toBe(0);
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe("feature-store");   // the trace's subject (row 64)
      await expect(page.locator(".rail .item.sel").count(), "nothing selected").resolves.toBe(0);
      await expect.poll(() => marked(page)).toBe("svc:feature-store");
      await clickMachine(page, m, SITE, "svc:notifier");
      await titleEnds(page, "svc:notifier");
      await page.locator(".trace .row .rname").first().click();   // the pane is usable
      await expect(page.locator(".trace .detail").count()).resolves.toBe(1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("the trace's own box keeps the trace as it is: a method's service on F0, an outside service itself", async () => {
    const m = demo();
    const EXT = "3p:stripe";
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await page.getByRole("radio", { name: "Downstream" }).click();
      const more = page.locator(".trace .chip.more").first();
      if (await more.count()) await more.click();   // a deeper trace: the depth must survive the click
      await toSite(page);
      const rows = await page.locator(".trace .row").count();
      await clickMachine(page, m, SITE, m.liftTo(SITE, FOCUS)!);
      await page.waitForTimeout(500);
      await settled(page);
      await titleEnds(page, FOCUS);
      await expect(page.getByRole("radio", { name: "Downstream" }).getAttribute("aria-checked")).resolves.toBe("true");
      await expect(page.locator(".trace .row").count()).resolves.toBe(rows);
      await expect(page.locator(".trace .dim-note").count()).resolves.toBe(0);
      await expect.poll(() => marked(page)).toBe(m.liftTo(SITE, FOCUS)!);
      await page.locator(".trace > header .tools button", { hasText: /^Close$/ }).click();
      await traceFromInspector(page, m, EXT);
      await page.getByRole("radio", { name: "Upstream" }).click();
      const extRows = await page.locator(".trace .row").count();
      await clickMachine(page, m, SITE, EXT);
      await page.waitForTimeout(500);
      await titleEnds(page, EXT);
      await expect(page.getByRole("radio", { name: "Upstream" }).getAttribute("aria-checked")).resolves.toBe("true");
      await expect(page.locator(".trace .row").count()).resolves.toBe(extRows);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("a line clicked while tracing traces from both of its ends, keeps it on a direction change, and offers no Pin", async () => {
    const m = demo();
    const KEY = "3p:smtp|svc:notifier";
    const bundle = m.bundles(SITE).bundles.find((b) => b.key === KEY)!;
    expect(bundle, "the demo's smtp line on F0").toBeTruthy();
    const line = lineStart(m, KEY, bundle.relations, "smtp ↔ notifier")!;
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await toSite(page);
      await clickLine(page, m, KEY);
      await titleEnds(page, `line:${KEY}`);
      const n = line.ends.length;
      await expect(page.locator(".trace > header h2").textContent()).resolves.toMatch(new RegExp(`smtp ↔ notifier · line · ${n} ends?$`));
      await expect(page.locator(".trace .row.focus").count()).resolves.toBe(n);
      await expect(page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).count()).resolves.toBe(0);
      await expect(page.locator(".trace > header h2 .code").count(), "a line has no code: no empty chip").resolves.toBe(0);
      await expect(page.locator(".insp h2").first().textContent(), "the inspector shows the traced line (row 64)").resolves.toBe("smtp ↔ notifier");
      await page.getByRole("radio", { name: "Upstream" }).click();
      await titleEnds(page, `line:${KEY}`);
      await expect(page.locator(".trace .row.focus").count()).resolves.toBe(n);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("Find while the pane is open re-targets for a method and for a service alike", async () => {
    const m = demo();
    const REFUND = "billing::city.parking.billing.BillingService.Live#refund/1";
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      const search = page.getByRole("searchbox", { name: "Find a node by name or code" });
      await search.fill(m.codes.get(REFUND)!);
      await page.locator(".rail .list button").first().click();
      await titleEnds(page, REFUND);
      await search.fill(m.codes.get("svc:billing")!);
      await page.locator(".rail .list button").filter({ has: page.locator(".code", { hasText: new RegExp(`^${m.codes.get("svc:billing")}$`) }) }).first().click();
      await titleEnds(page, "svc:billing");
      const n = entryPoints(m, "svc:billing").length;
      await expect(page.locator(".trace > header h2").textContent()).resolves.toMatch(new RegExp(`billing · service · ${n} entry points?$`));
      await expect(page.locator(".trace .dim-note").count()).resolves.toBe(0);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("Esc closes one thing per press: the detail, then the pane, then a selection (no dim state between)", async () => {
    const m = demo();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, FOCUS);
      await page.locator(".trace .row:not(.focus) .rname").first().click();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace .detail").count()).resolves.toBe(0);
      await expect(page.locator(".trace").count()).resolves.toBe(1);
      await page.keyboard.press("Escape");
      await expect(page.locator(".trace").count()).resolves.toBe(0);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get("svc:billing")!);
      await page.locator(".rail .list button").filter({ has: page.locator(".code", { hasText: new RegExp(`^${m.codes.get("svc:billing")}$`) }) }).first().click();
      await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent?.trim() === "billing", null, { timeout: 10_000 });
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await expect(page.locator(".insp h2").first().textContent()).resolves.toBe("Whole system");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("Trace from here shows on a seed row of a container's trace and narrows the trace to that entry point (ruling R11)", async () => {
    const m = demo();
    const seeds = seedsFor(m, "svc:feature-store").ids;
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, "svc:feature-store");
      const seedRow = page.locator(".trace .row.focus .rname").first();
      const node = ((await seedRow.getAttribute("title")) ?? "").split(" — ")[1]?.split(" · ")[0] ?? "";
      expect(seeds).toContain(node);
      await seedRow.click();
      await page.locator(".trace .detail button", { hasText: /^Trace from here$/ }).click();
      await titleEnds(page, node);
      await expect(page.locator(".trace .row.focus").count()).resolves.toBe(1);
      await expect(page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).count()).resolves.toBe(1);   // a map node: pinnable
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("a floor group's inspector Trace opens the pane on the entry points inside its members (ruling R6), with no Pin", async () => {
    const PKG = "billing::city.parking.billing/", GROUP = "group:billing-code";
    const map = JSON.parse(demoText()) as CodeMap;
    const floor = map.layout.containers["svc:billing"];
    const at = floor.items[PKG];
    floor.items = { [GROUP]: at };
    floor.groups = [{ id: GROUP, label: "billing-code", members: [PKG], kind: "family" }];
    map.layout.containers[GROUP] = { ...structuredClone(floor), items: { [PKG]: at }, groups: [] };
    const text = JSON.stringify(map);
    const m = new Model(map);
    const n = seedsFor(m, GROUP).ids.length;
    expect(n, "billing's entry points sit inside the group").toBeGreaterThan(0);
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, text, errors);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get("svc:billing")!);
      await page.locator(".rail .list button").filter({ has: page.locator(".code", { hasText: new RegExp(`^${m.codes.get("svc:billing")}$`) }) }).first().click();
      await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent?.trim() === "billing", null, { timeout: 10_000 });
      await settled(page);
      await page.locator(".insp header button", { hasText: /^Open sub-assembly$/ }).click();
      await page.waitForFunction(() => document.querySelector("canvas")?.dataset.floor === "svc:billing", null, { timeout: 15_000 });
      await settled(page);
      await page.locator(".rail button.item", { hasText: "billing-code" }).click();   // On this floor: the group selected
      await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent?.trim() === "billing-code", null, { timeout: 10_000 });
      await page.locator(".insp header button", { hasText: /^Trace$/ }).click();
      await page.waitForSelector(".trace .row", { timeout: 10_000 });
      await titleEnds(page, GROUP);
      await expect(page.locator(".trace > header h2").textContent()).resolves.toMatch(new RegExp(`billing-code · group · ${n} entry points?$`));
      await expect(page.locator(".trace > header .tools button", { hasText: /^Pin$/ }).count()).resolves.toBe(0);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("the inspector shows the item the blue mark is on (row 64): the focus, a pointed row's item, the focus again; the floor once the pane closes; a comment attaches to the shown item", async () => {
    const m = demo();
    const SVC = "svc:feature-store";
    const rows = [...layoutTrace(m, new TraceGraph(m), initialState(SVC)).rows.values()];
    const other = rows.find((r) => r.kind === "node" && !r.focus && r.node !== SVC && m.nodes.has(r.node))!;
    expect(other, "a row of feature-store's trace that is not a seed").toBeTruthy();
    const h2 = (page: import("playwright-core").Page) => page.locator(".insp h2").first().textContent();
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await traceFromInspector(page, m, SVC);
      await toSite(page);
      await expect(h2(page)).resolves.toBe("feature-store");
      await expect(page.locator(".insp .starts .tab").textContent()).resolves.toBe(`Entry points (${entryPoints(m, SVC).length})`);
      await expect(page.locator(".insp .starts .go-trace").count()).resolves.toBe(entryPoints(m, SVC).length);
      await expect(page.locator(".rail .item.sel").count(), "no selection is made (S1)").resolves.toBe(0);
      // its own Trace button would only restart the trace: disabled; an entry point's still narrows it
      const own = page.locator(".insp header button", { hasText: /^Trace$/ });
      await expect(own.isDisabled()).resolves.toBe(true);
      await expect(own.getAttribute("title")).resolves.toBe("Already traced");
      await expect(page.locator(".insp .starts .go-trace:disabled").count()).resolves.toBe(0);
      // a row pointed: its item; the detail closed: the focus again
      await rowName(page, other).click();
      await expect.poll(() => h2(page)).toBe(m.itemName(other.node));
      await page.locator(".trace .detail .x").click();
      await expect.poll(() => h2(page)).toBe("feature-store");
      // a comment added now attaches to feature-store, not to the floor
      await page.locator("#draft").fill("row 64 note");
      await page.locator(".insp .add").click();
      await expect(page.locator(".insp .note").textContent()).resolves.toBe("row 64 note");
      // the pane closed: the inspector is back on the floor, which has no such note
      await page.locator(".trace > header .tools button", { hasText: /^Close$/ }).click();
      await expect.poll(() => h2(page)).toBe("Whole system");
      await expect(page.locator(".insp .note").count()).resolves.toBe(0);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(m.codes.get(SVC)!);
      await page.locator(".rail .list button").first().click();
      await expect.poll(() => h2(page)).toBe("feature-store");
      await expect(page.locator(".insp .note").textContent()).resolves.toBe("row 64 note");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("hiding and showing the inspector keeps the floor's zoom and the point at the canvas centre (row 65)", async () => {
    const m = demo();
    const SVC = "svc:feature-store";
    const browser = await browserOf();
    const errors: string[] = [];
    try {
      const page = await openViewer(browser, demoText(), errors);
      await settled(page);
      const fitted = await page.locator("canvas").getAttribute("data-zoom");
      const box = (await page.locator("canvas").boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      // a fresh floor ignores the wheel for a moment (camera.ts depthQuietUntil): wheel until the canvas reports a new zoom
      for (let i = 0; ; i++) {
        await page.mouse.wheel(0, -400);
        const zoomed = await page.waitForFunction((z) => document.querySelector("canvas")?.dataset.zoom !== z, fitted, { timeout: 400 }).then(() => true, () => false);
        if (zoomed) break;
        if (i === 10) throw new Error("the wheel never zoomed the floor");
      }
      await settled(page);
      const offset = async () => {
        const at = await machineOnScreen(page, m, SITE, SVC);
        const c = await page.evaluate(() => { const d = document.querySelector("canvas")!; return { w: d.clientWidth, h: d.clientHeight }; });
        return { zoom: at.zoom, dx: at.rect.x + at.rect.w / 2 - c.w / 2, dy: at.rect.y + at.rect.h / 2 - c.h / 2, w: c.w };
      };
      const before = await offset();
      expect(before.zoom, "the wheel zoomed in").not.toBe(fitted);
      for (const step of ["hide", "show"]) {
        const w = (await offset()).w;
        await page.locator(".side .collapse").click();
        await page.waitForFunction((x) => document.querySelector("canvas")!.clientWidth !== x, w, { timeout: 5_000 });
        await page.waitForTimeout(300);
        await settled(page);
        const now = await offset();
        expect(now.zoom, `${step}: the zoom is kept`).toBe(before.zoom);
        expect(Math.abs(now.dx - before.dx), `${step}: the centre point is kept (x)`).toBeLessThan(3);
        expect(Math.abs(now.dy - before.dy), `${step}: the centre point is kept (y)`).toBeLessThan(3);
      }
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);
});
