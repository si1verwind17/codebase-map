// The layout worker in the built viewer, opened from file:// as a reader opens it: it starts, a floor not planned ahead
// waits for its plan and then shows (the camera rests only on the new floor), and that floor's lines are where node's
// planFloor puts them. Needs `npm run build` first and a Chromium: VIZ_CHROMIUM=/usr/bin/chromium.
import { existsSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { coveredKeys, flightPaths } from "../../src/factory/flights";
import { MAX_NEARBY, nextFloors } from "../../src/floor/precompute";
import { GL_ARGS } from "../gl";

const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
const DIST = new URL("../../../skills/visualizing-codebases/viewer/dist/", import.meta.url);
const BUILT = new URL("viewer.html", DIST);

describe("the built viewer's dist", () => {
  it("holds the page and the audit only: the worker is inlined, never a file beside them", () => {
    expect(readdirSync(DIST).sort()).toEqual(["audit.mjs", "viewer.html"]);
    expect(readFileSync(BUILT, "utf8")).not.toMatch(/assets\//);
    expect(readFileSync(new URL("audit.mjs", DIST), "utf8"), "the audit plans without a worker").not.toMatch(/new Worker\(/);
  });
});

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("the layout worker in a browser", () => {
  it("starts from file://, and a floor not planned ahead waits for its plan, then shows with node's lines", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    // a floor one step from F0 that idle planning leaves alone (past MAX_NEARBY), reached through a node on it
    const ahead = new Set(nextFloors(model, SITE));
    const cold = nextFloors(model, SITE, undefined, Infinity).slice(MAX_NEARBY).find((c) => !ahead.has(c) && model.map.nodes.some((n) => model.floorOf(n.id) === c))!;
    expect(cold, "the demo's F0 opens more floors than are planned ahead").toBeDefined();
    const inside = model.map.nodes.find((n) => model.floorOf(n.id) === cold)!;
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.addInitScript(() => { (globalThis as { vizMeasureTexts?: boolean }).vizMeasureTexts = true; });   // data-line-tiles (labels.ts)
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const attr = (n: string) => page.locator("canvas").getAttribute(n);
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-plans-queued") === "0", null, { timeout: 60_000 });
      expect(await attr("data-planner"), "the worker started").toBe("worker");
      // every time the camera comes to rest, the floor it rests on
      await page.evaluate(() => {
        const c = document.querySelector("canvas")!, w = window as unknown as { rests: string[] };
        w.rests = [];
        new MutationObserver(() => { if (c.dataset.camera === "idle") w.rests.push(c.dataset.floor ?? ""); })
          .observe(c, { attributes: true, attributeFilter: ["data-camera"] });
      });
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get(inside.id)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((c) => document.querySelector("canvas")?.getAttribute("data-floor") === c, cold, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      expect(await attr("data-plan-hit"), "the floor was not planned ahead").toBe("false");
      expect(await attr("data-planner"), "still the worker after the press: no silent fallback").toBe("worker");
      const rests = await page.evaluate(() => (window as unknown as { rests: string[] }).rests);
      expect(rests[0], "the camera first rests on the new floor").toBe(cold);
      // its lines where node's planFloor puts them: each line's tiles on top, as the scene measures them
      const { doors, bundles, layered } = model.bundles(cold);
      const plan = planFloor(model, cold, doors, bundles, layered);
      const covered = coveredKeys(flightPaths(plan.tf), bundles);
      const want: Record<string, string[]> = {};
      for (const r of plan.routes) {
        if (r.kind === "drone" || covered.has(r.key)) continue;
        for (const p of r.pieces) if (!p.under) (want[r.key] ??= []).push(`${p.x},${p.y}`);
      }
      const got = JSON.parse((await attr("data-line-tiles"))!) as Record<string, string[]>;
      expect(Object.keys(want).length, "the floor has lines").toBeGreaterThan(0);
      for (const [k, ts] of Object.entries(want)) expect(got[k]?.slice(0, ts.length), k).toEqual(ts);   // a rail's yard link and siding follow its own tiles
      expect(Object.keys(got).filter((k) => !(k in want)), "no line node does not route").toEqual([]);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("while a floor change waits on its plan, the camera reads moving and presses are ignored", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const cold = nextFloors(model, SITE, undefined, Infinity).slice(MAX_NEARBY).find((c) => model.map.nodes.some((n) => model.floorOf(n.id) === c))!;
    const inside = model.map.nodes.find((n) => model.floorOf(n.id) === cold)!;
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      // the worker's answers held while `planHold` is set, released by `releasePlans()`
      await page.addInitScript(() => {
        const w = window as unknown as { planHold: boolean; releasePlans: () => void; Worker: typeof Worker };
        const held: (() => void)[] = [];
        w.planHold = false;
        w.releasePlans = () => { w.planHold = false; held.splice(0).forEach((f) => f()); };
        const Base = w.Worker;
        w.Worker = class extends Base {
          addEventListener(type: string, fn: EventListenerOrEventListenerObject, opts?: boolean | AddEventListenerOptions) {
            if (type !== "message" || typeof fn !== "function") return super.addEventListener(type, fn, opts);
            return super.addEventListener(type, (e: Event) => { if (w.planHold) held.push(() => fn.call(this, e)); else fn.call(this, e); }, opts);
          }
        };
      });
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const attr = (n: string) => page.locator("canvas").getAttribute(n);
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-plans-queued") === "0", null, { timeout: 60_000 });
      expect(await attr("data-planner")).toBe("worker");
      await page.evaluate(() => { (window as unknown as { planHold: boolean }).planHold = true; });
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get(inside.id)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-plan-jobs") === "1", null, { timeout: 10_000 });
      await page.waitForTimeout(1000);   // past any camera ease the selection started
      expect(await attr("data-camera"), "moving while the plan is awaited").toBe("moving");
      expect(await attr("data-floor"), "the old floor still shown").toBe(SITE);
      expect(await page.locator(".floors button").evaluateAll((bs) => bs.every((b) => (b as HTMLButtonElement).disabled)), "the floor list ignores presses").toBe(true);
      const box = (await page.locator("canvas").boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      for (let i = 0; i < 12; i++) { await page.mouse.wheel(0, -400); await page.waitForTimeout(40); }   // a zoom deep enough to go inside, ignored
      await page.waitForTimeout(500);
      expect(await attr("data-floor")).toBe(SITE);
      await page.evaluate(() => (window as unknown as { releasePlans: () => void }).releasePlans());
      await page.waitForFunction((c) => document.querySelector("canvas")?.getAttribute("data-floor") === c, cold, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      await page.waitForTimeout(1500);
      expect(await attr("data-floor"), "the waited-for floor, and no other move after it").toBe(cold);
      expect(await attr("data-planner")).toBe("worker");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);
});
