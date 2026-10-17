// Browser smoke test of the built viewer. Needs `npm run build` first and a Chromium:
// VIZ_CHROMIUM=/usr/bin/chromium npm run e2e
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { describe, expect, it } from "vitest";
import { Model } from "../../src/model/model";
import { floorLayers, listEntry } from "../../src/model/layers";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { codeLinkCount } from "../../src/factory/conduits";
import { doorWords } from "../../src/factory/boxname";
import { toGeometry } from "../../src/factory/layout";
import { trainPaths } from "../../src/factory/rail-place";
import { fitScale } from "../../src/floor/fitscale";
import { coveredKeys, flightPaths } from "../../src/factory/flights";
import { sharedTiles } from "../../src/factory/trunk-card";
import { CODE_BAND, NAME_MIN_PX } from "../../src/factory/machines";
import { textOverlaps, type Word } from "../text-overlaps";
import { GL_ARGS } from "../gl";

const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
const LEGEND_MAX_H = 4 * 12 + 3 * 3 + 12 + 2;   // the open legend at most: 4 dense 12 px rows, the 3 px gaps between, 6 px padding a side and the 1 px edge
const BUILT = new URL("../../../skills/visualizing-codebases/viewer/dist/viewer.html", import.meta.url);

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("built viewer in a browser", () => {
  it("opens the fixture map with no flow list, takes a comment, with no page errors", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await expect(page.getByRole("heading", { name: "demo" }).count()).resolves.toBe(1);
      await expect(page.getByText(/Shared utility/).count()).resolves.toBe(0);   // no utility in this map: no legend entry
      await expect(page.locator(".rail h2.tab", { hasText: /^Flows$/ }).count(), "no flow list").resolves.toBe(0);
      await expect(page.locator(".walk").count(), "no step-player panel").resolves.toBe(0);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /^S\d\s*worker/ }).first().click();
      await page.getByLabel(/Comment on/).fill("Rename run to run_job.");
      await page.getByRole("button", { name: "Add comment" }).click();
      await expect(page.getByRole("button", { name: /Save for the agent \(1\)/ }).isEnabled()).resolves.toBe(true);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("links the field guide on the project's site: one link, under the legend, and a first-visit notice once", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const withGuide = mkdtempSync(join(tmpdir(), "viz-guide-"));
    writeFileSync(join(withGuide, "index.html"), html);   // nothing beside it: the guide is on the web
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const open = async (dir: string) => {
        const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        page.on("pageerror", (e) => errors.push(e.message));
        await page.goto("file://" + join(dir, "index.html"));
        await page.waitForSelector("canvas");
        return page;
      };
      // with the guide: one link (under the legend), the notice
      const page = await open(withGuide);
      await page.waitForSelector(".guide-note", { timeout: 10_000 });
      const links = page.getByRole("link", { name: "Field guide", exact: true });
      await expect(links.count(), "exactly one Field guide link").resolves.toBe(1);
      await expect(page.locator(".floor-tools a").count(), "none in the floor tools").resolves.toBe(0);
      await expect(page.locator(".legend a", { hasText: "Field guide" }).getAttribute("href")).resolves.toBe("https://si1verwind17.github.io/codebase-map/");
      await expect(page.locator(".legend a", { hasText: "Field guide" }).getAttribute("target")).resolves.toBe("_blank");
      await expect(page.getByText("New here?").count()).resolves.toBe(1);
      await page.getByRole("button", { name: "Dismiss" }).click();
      await expect(page.locator(".guide-note").count()).resolves.toBe(0);
      await expect(links.count(), "the link stays").resolves.toBe(1);
      // shown once: it is marked seen as it appears, so a reload brings it back whether or not it was dismissed
      await page.reload();
      await page.waitForSelector("canvas");
      await page.waitForSelector(".legend a.guide-link");
      await expect(page.locator(".guide-note").count()).resolves.toBe(0);
      await page.close();
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("with the guide link the open legend keeps its height, and at 1024 px the notice clears the floor tools", async () => {
    const raw = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const dir = mkdtempSync(join(tmpdir(), "viz-guide-"));
    writeFileSync(join(dir, "index.html"), readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", raw.replaceAll("<", "\\u003c")));
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    try {
      for (const width of [1440, 1024]) {
        const ctx = await browser.newContext({ viewport: { width, height: 900 } });   // a fresh context: a first visit
        const page = await ctx.newPage();
        await page.goto("file://" + join(dir, "index.html"));
        await page.waitForSelector("canvas");
        await page.waitForSelector(".guide-note", { timeout: 10_000 });
        const legendH = await page.locator(".legend ul").evaluate((e) => e.getBoundingClientRect().height);
        if (width === 1440) expect(legendH, `open legend with the guide link: ${legendH} px`).toBeLessThanOrEqual(LEGEND_MAX_H);   // narrower floors wrap the list on their own
        await expect(page.locator(".legend a", { hasText: "Field guide" }).count()).resolves.toBe(1);
        const boxOf = async (sel: string) => (await page.locator(sel).boundingBox())!;
        const meet = (p: { x: number; y: number; width: number; height: number }, q: typeof p) =>
          p.x < q.x + q.width && q.x < p.x + p.width && p.y < q.y + q.height && q.y < p.y + p.height;
        const note = await boxOf(".guide-note");
        const tools = await boxOf(".floor-tools");
        expect(meet(note, tools), `notice ${JSON.stringify(note)} vs tools ${JSON.stringify(tools)} at ${width}px`).toBe(false);
        // the notice is under the legend, open or closed
        for (const open of [true, false]) {
          if (!open) await page.getByRole("button", { name: "Legend", exact: true }).click();
          const parts = open ? [".legend .head", ".legend ul"] : [".legend .head"];
          await expect(page.locator(".legend ul").count()).resolves.toBe(open ? 1 : 0);
          const n = await boxOf(".guide-note");
          for (const sel of parts) { const l = await boxOf(sel); expect(meet(n, l), `notice ${JSON.stringify(n)} vs ${sel} ${JSON.stringify(l)} at ${width}px, legend ${open ? "open" : "closed"}`).toBe(false); }
          expect(meet(n, await boxOf(".floor-tools")), `notice vs tools at ${width}px, legend ${open ? "open" : "closed"}`).toBe(false);
        }
        await ctx.close();
      }
    } finally {
      await browser.close();
    }
  }, 60_000);

  it("keeps navigating when Fit or a selection is pressed mid-move, and deletes a note", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const floorsDisabled = () => page.locator(".floors button").evaluateAll((bs) => bs.map((b) => (b as HTMLButtonElement).disabled));
      expect((await floorsDisabled()).some(Boolean), "floor buttons enabled before the move").toBe(false);
      await page.evaluate(() => {   // sample every frame whether all floor buttons are disabled at once
        const w = window as unknown as { __sawAllFloorsDisabled: boolean };
        w.__sawAllFloorsDisabled = false;
        const tick = () => {
          const bs = [...document.querySelectorAll<HTMLButtonElement>(".floors button")];
          if (bs.length && bs.every((b) => b.disabled)) w.__sawAllFloorsDisabled = true;
          requestAnimationFrame(tick);
        };
        tick();
      });
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("run");
      await page.locator(".rail .list button", { hasText: "method" }).first().click();   // a move down to the method's floor
      await page.locator(".rail .grow .list button").first().click();                    // a selection mid-move
      await page.getByRole("button", { name: "Fit" }).click();                            // a camera move mid-move
      await page.waitForFunction(() => /F3/.test(document.querySelector(".floors")?.textContent ?? ""), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((b) => !b.disabled), null, { timeout: 15_000 });
      expect(await page.evaluate(() => (window as unknown as { __sawAllFloorsDisabled: boolean }).__sawAllFloorsDisabled), "floor buttons were all disabled during the move").toBe(true);
      await page.getByLabel(/Comment on/).fill("Typo, drop me.");
      await page.getByRole("button", { name: "Add comment" }).click();
      await page.getByRole("button", { name: "Delete comment" }).click();
      await expect(page.getByRole("button", { name: /Save for the agent \(0\)/ }).count()).resolves.toBe(1);
      await page.locator(".floors button", { hasText: "Whole system" }).click();                         // a floor press after the move works
      await page.waitForFunction(() => /Whole system/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("opens in the factory, remembers the drone toggle and ignores a view stored by an old visit", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.evaluate((old) => localStorage.setItem("code-map.view", old), "schematic");   // an old stored value the viewer now ignores
      await page.reload();
      await page.waitForSelector("canvas");
      await expect(page.getByRole("button", { name: "Factory view" }).count()).resolves.toBe(0);   // no view switch
      await expect(page.getByRole("button", { name: "Drone paths" }).count()).resolves.toBe(1);
      await expect(page.getByText("Passes under").count()).resolves.toBe(1);   // the legend speaks factory
      await expect(page.getByText("Implementation (dotted)", { exact: true }).count()).resolves.toBe(0);   // no implements in this map
      const drones = page.getByRole("button", { name: "Drone paths" });        // on by default
      await expect(drones.getAttribute("aria-pressed")).resolves.toBe("true");
      await drones.click();
      await expect(drones.getAttribute("aria-pressed")).resolves.toBe("false");
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /^S\d\s*worker/ }).first().click();
      await page.reload();
      await page.waitForSelector("canvas");
      await expect(page.getByRole("button", { name: "Drone paths" }).getAttribute("aria-pressed")).resolves.toBe("false");   // remembered
      await page.getByRole("button", { name: "Drone paths" }).click();
      await expect(page.getByRole("button", { name: "Drone paths" }).getAttribute("aria-pressed")).resolves.toBe("true");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("keeps the selection when the floor is dragged and clears it on a click on empty floor", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /^S\d\s*worker/ }).first().click();
      const shown = () => page.locator(".insp h2", { hasText: /^worker$/ }).count();   // the selected node, not the floor
      await expect(shown()).resolves.toBe(1);
      const box = (await page.locator("canvas").boundingBox())!;
      const [x, y] = [box.x + 6, box.y + box.height - 6];            // a corner of empty floor
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x + 40, y - 30, { steps: 5 });
      await page.mouse.up();
      await expect(shown()).resolves.toBe(1);                         // a drag keeps the selection
      await page.mouse.move(x + 41, y - 30);
      await page.mouse.down();
      await page.mouse.up();
      await page.waitForTimeout(100);
      await expect(shown()).resolves.toBe(0);                         // a click on empty floor clears it
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("Esc clears a selection as a click on empty floor does", async () => {
    const map = readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const heading = () => page.locator(".insp h2").first().textContent();
      const floorHeading = await heading();                           // nothing selected: the inspector shows the floor
      const pickWorker = async () => {
        await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("worker");
        await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /^S\d\s*worker/ }).first().click();
        await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent?.trim() === "worker", null, { timeout: 10_000 });
      };
      await pickWorker();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());   // keys from the page, not the search box
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent?.trim() !== "worker", null, { timeout: 5_000 })
        .catch(() => { throw new Error("Esc left the selection as it was"); });
      await expect(heading(), "the inspector is back on the floor").resolves.toBe(floorHeading);
      await expect(page.locator("canvas").getAttribute("data-machines-dim"), "nothing dimmed").resolves.toBe("0");
      await page.keyboard.press("Escape");                            // nothing selected: a no-op
      await expect(heading()).resolves.toBe(floorHeading);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("factory view at Fit shows machine codes; zooming in with the wheel brings the names back, which hold down to about 6 px", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const mode = () => page.locator("canvas").getAttribute("data-labels");
      // the legend's rows: 12 px text on a 12 px line, which hold as entries are added
      const row = await page.locator(".legend li").first().evaluate((e) => { const c = getComputedStyle(e); return [c.fontSize, c.lineHeight, e.getBoundingClientRect().height]; });
      expect(row).toEqual(["12px", "12px", 12]);
      // the site has every kind of messaging: each legend entry is a plain name, with no map example
      for (const n of ["Implementation (dotted)", "Queue (waiting stack)", "Push dock", "Pull", "Dead letters"]) await expect(page.locator(".legend li", { hasText: new RegExp(`^${n.replace(/[()]/g, "\\$&")}$`) }).count(), n).resolves.toBe(1);
      // ...and the open legend is no taller than 4 dense rows (12 px, 3 px between, 6 px padding and a 1 px edge a side),
      // so it hides no more of the floor at Fit
      const legendH = await page.locator(".legend ul").evaluate((e) => e.getBoundingClientRect().height);
      expect(legendH, `open legend ${legendH} px`).toBeLessThanOrEqual(LEGEND_MAX_H);
      for (const n of ["Rail yard", "Station", "Schedule sign", "Train"]) await expect(page.locator(".legend li", { hasText: new RegExp(`^${n}$`) }).count(), n).resolves.toBe(1);
      for (const n of ["Cache", "Bucket", "Receiving dock"]) await expect(page.locator(".legend li", { hasText: new RegExp(`^${n}$`) }).count(), n).resolves.toBe(1);
      await expect(page.locator(".legend li").count()).resolves.toBe(22);   // all of them shown: 10 kinds, implements, 4 messaging (replicas only on inner floors), the webhook's receiving dock, 4 rail and 2 store (cache, bucket)
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1500);
      await expect(mode()).resolves.toBe("codes");
      const zones = ((await page.locator("canvas").getAttribute("data-zones")) ?? "").split("|").filter(Boolean);
      expect(zones.length, `zone names shown at Fit: ${zones}`).toBeGreaterThanOrEqual(6);   // they grow into clear room (7 of 8 on the demo)
      const box = (await page.locator("canvas").boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      for (let i = 0; i < 4 && (await mode()) !== "names"; i++) { await page.mouse.wheel(0, -300); await page.waitForTimeout(150); }
      await expect(mode()).resolves.toBe("names");
      // names hold two wheel notches (x e^-0.2 each) past the old 9 px switch: zooming out a notch at a time, the smallest
      // name still shows under 9 px, and the floor turns to codes only once it would render under about 6 px (9·e^-0.4)
      const namePx = async () => Number(await page.locator("canvas").getAttribute("data-name-px"));
      let last = await namePx(), held = 0;
      for (let i = 0; i < 20 && (await mode()) === "names"; i++) {
        last = await namePx();
        if (last < 9) held++;
        await page.mouse.wheel(0, 100); await page.waitForTimeout(120);
      }
      await expect(mode()).resolves.toBe("codes");
      expect(held, `notches with names under 9 px (last ${last} px)`).toBeGreaterThanOrEqual(2);   // the owner: two wheel notches
      expect(await namePx(), "codes take over only under about 6 px").toBeLessThan(9 * Math.exp(-0.4));
      expect(last, "names never shown under about 6 px (less the band)").toBeGreaterThanOrEqual(9 * Math.exp(-0.4) - 14 * 0.04 - 0.1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("factory view: a trait lists its implementation in the inspector, which leads to it", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const trait = "billing::city.parking.billing.DeadLetters", impl = "billing::city.parking.billing.DeadLetters.live$impl";
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await expect(page.getByText("Implementation (dotted)", { exact: true }).count()).resolves.toBe(1);   // the legend names the dotted link plainly
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get(trait)!);
      await page.locator(".rail .list button").first().click();                        // the trait, on its package floor (trait and $impl both items)
      await page.waitForFunction(() => document.querySelector(".insp")?.textContent?.includes("Implemented by"), null, { timeout: 10_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });   // the move to the floor has ended
      const by = page.locator(".insp .impl button");
      await expect(by.count()).resolves.toBe(1);
      await expect(by.textContent()).resolves.toContain(model.codes.get(impl)!);
      await by.click();                                                                  // reveal: on to the implementation
      await page.waitForFunction(() => document.querySelector(".insp")?.textContent?.includes("Implements"), null, { timeout: 15_000 });
      await expect(page.locator(".insp .impl button").textContent()).resolves.toContain(model.codes.get(trait)!);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("factory view: drones fly a selected worker's flights, and Still motion stops them", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("enforcement-worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /enforcement-worker/ }).first().click();
      const clock = async () => Number(await page.locator("canvas").getAttribute("data-drone-clock"));
      // its take, failure (and the queue's enqueue) are lit: drones fly within a cycle
      await page.waitForFunction(() => Number(document.querySelector("canvas")?.getAttribute("data-drones")) > 0, null, { timeout: 15_000 });
      const c0 = await clock();
      await page.waitForTimeout(1200);   // the canvas shows the clock about once a second
      expect(await clock(), "the drone clock runs").toBeGreaterThan(c0);
      const still = page.getByLabel("Still motion");
      await still.check();
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-drones") === "0", null, { timeout: 5_000 });
      const c1 = await clock();
      await page.waitForTimeout(700);
      expect(await clock(), "nothing advances under Still motion").toBe(c1);
      await expect(page.locator("canvas").getAttribute("data-drones")).resolves.toBe("0");
      await still.uncheck();
      await page.waitForTimeout(1200);
      expect(await clock(), "and moves again without it").toBeGreaterThan(c1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("factory view: with nothing selected every line on the floor is lit and drones fly, on the overview and after a visit to an inner floor; a selection narrows it", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const clock = async () => Number(await page.locator("canvas").getAttribute("data-drone-clock"));
      const flying = () => page.waitForFunction(() => Number(document.querySelector("canvas")?.getAttribute("data-drones")) > 0, null, { timeout: 15_000 });
      const runs = async (what: string) => {
        await flying();
        const c0 = await clock();
        await page.waitForTimeout(1200);   // the canvas shows the clock about once a second
        expect(await clock(), `${what}: the drone clock runs`).toBeGreaterThan(c0);
      };
      const lit = async () => Number(await page.locator("canvas").getAttribute("data-lit"));
      const allF0 = new Model(JSON.parse(map) as CodeMap).bundles("site").bundles.length;
      // F0 on open, nothing selected: every line on the floor is lit and the drones fly, with no selection needed
      await expect(page.locator(".floors button[aria-current=page]").textContent()).resolves.toContain("Whole system");
      expect(await lit(), "F0 on open: every line lit").toBe(allF0);
      await runs("F0 on open");
      // into an inner floor by a selection there (which lights that floor's lines), then back up with nothing selected
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("main.py");
      await page.locator(".rail .list button", { hasText: "main.py" }).first().click();
      await page.waitForFunction(() => !/Whole system/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? "Whole system"), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      await page.locator(".floors button", { hasText: "Whole system" }).click();
      await page.waitForFunction(() => /Whole system/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      expect(await lit(), "F0 after an inner floor: every line lit again").toBe(allF0);
      await runs("F0 after an inner floor");
      // a selection narrows motion to its own lines
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("enforcement-worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /enforcement-worker/ }).first().click();
      await page.waitForFunction((all) => { const n = Number(document.querySelector("canvas")?.getAttribute("data-lit")); return n > 0 && n < all; }, allF0, { timeout: 15_000 });
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("factory view: demand-forecast's floor opens with its stand-in rail (a reference task to a door) and no page error", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      // forecast/ is an item of demand-forecast's own floor: selecting it moves there
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get("forecast::forecast/")!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction(() => /demand-forecast/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      await page.waitForTimeout(500);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);

  it("factory view: on every demo floor no word is turned, no rail part carries a caption naming its kind, and, at Fit and closer in with names shown, no word sits on a line or on another word", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    // every floor, reached by selecting a node on it (Still motion: each move lands at once)
    const floors = Object.keys(model.map.layout.containers).filter((c) => model.floor(c));
    const via = new Map<string, string>();
    for (const n of model.map.nodes) { const c = model.floorOf(n.id) ?? "site"; if (!via.has(c)) via.set(c, n.id); }
    const turned: string[] = [], captions: string[] = [], found: string[] = [];
    let seen = 0, ownNear = 0, layersSeen = 0, pathsSeen = 0, codeLinksSeen = 0;
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.addInitScript(() => { (globalThis as { vizMeasureTexts?: boolean }).vizMeasureTexts = true; });   // the word measure (labels.ts)
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByLabel("Still motion").check();
      const attr = (n: string) => page.locator("canvas").getAttribute(n);
      const frames = () => page.evaluate(() => new Promise<void>((r) => { let k = 3; const f = () => (--k ? requestAnimationFrame(f) : r()); requestAnimationFrame(f); }));
      /** The words as measured at the zoom now on floor `c` (two frames: the labels sync, then the measure), checked. */
      const check = async (c: string, at: string) => {
        await frames();
        await page.waitForFunction((c) => { const d = document.querySelector("canvas")!.dataset; return d.textsFloor === c && d.textsZoom === d.zoom; }, c, { timeout: 10_000 });
        const z = Number(await attr("data-texts-zoom"));
        const paths = JSON.parse((await attr("data-line-paths"))!) as Record<string, number[][]>;
        const r = textOverlaps(JSON.parse((await attr("data-texts"))!) as Word[], JSON.parse((await attr("data-line-tiles"))!) as Record<string, string[]>, 1 / z, paths);
        pathsSeen += Object.keys(paths).length;
        // nothing is exempt: a `used by N` badge stays off every line, its own layer's included (clear.ts placeBadges)
        found.push(...r.found.map((f) => `${c} ${at}: ${f}`));
        ownNear += r.ownNear;
        return z;
      };
      const search = page.getByRole("searchbox", { name: "Find a node by name or code" });
      for (const c of floors) {
        if (c !== "site") {
          const id = via.get(c);
          if (!id) continue;
          await search.fill(model.codes.get(id)!);
          await page.locator(".rail .list button").first().click();
        }
        await page.waitForFunction((c) => document.querySelector("canvas")?.getAttribute("data-floor") === c, c, { timeout: 15_000 });
        const n = Number(await attr("data-turned-text"));
        if (n) turned.push(`${c}: ${n}`);
        const words = ((await attr("data-words")) ?? "").split("|");
        for (const w of words) if (/^(rail ?yard|yard|station|platform|train|schedule sign)$/i.test(w.trim())) captions.push(`${c}: ${w}`);
        // arriving by a node whose lines all sit in a layer opens that layer: measure the base first, the layers after
        if (await attr("data-layer")) { await page.keyboard.press("Escape"); await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-layer") === null, null, { timeout: 5_000 }); }
        await page.getByRole("button", { name: "Fit" }).click();
        const fit = await check(c, "fit");
        // closer in: one wheel event over the floor's middle, sized to just past the names switch (or one notch, x e^0.2,
        // when names already show); a fresh floor ignores the wheel for 600 ms, so it is sent until the zoom moves
        const minName = Number(await attr("data-name-px")) / fit;
        const want = (await attr("data-labels")) === "names" ? fit * Math.exp(0.2) : (NAME_MIN_PX / minName + CODE_BAND) * 1.03;
        const box = (await page.locator("canvas").boundingBox())!;
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        for (let i = 0; i < 10 && Number(await attr("data-zoom")) === fit; i++) { await page.mouse.wheel(0, -500 * Math.log(want / fit)); await frames(); if (Number(await attr("data-zoom")) === fit) await page.waitForTimeout(100); }
        expect(await attr("data-floor"), `${c}: still on the floor closer in`).toBe(c);
        expect(await attr("data-labels"), `${c}: names closer in`).toBe("names");
        expect(await check(c, "near"), `${c}: measured closer in`).toBeGreaterThan(fit);
        // each extra layer of the floor, shown once (closer in): its lines count as on top, the base at 12% does not
        for (const l of floorLayers(model, c)) {
          await page.getByRole("button", { name: /^Layers:/ }).click();
          await page.getByRole("radio", { name: listEntry(l) }).click();
          await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, l.id, { timeout: 5_000 });
          await check(c, `layer ${l.id}`);
          await page.keyboard.press("Escape");
          await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-layer") === null, null, { timeout: 5_000 });
          layersSeen++;
        }
        // F0's Code links toggle, on once (closer in): its conduits count as paths on top; then off again
        if (c === "site" && codeLinkCount(model)) {
          await page.getByRole("button", { name: "Code links" }).click();
          await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-conduits") !== null, null, { timeout: 5_000 });
          await check(c, "code links");
          await page.getByRole("button", { name: "Code links" }).click();
          await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-conduits") === null, null, { timeout: 5_000 });
          codeLinksSeen++;
        }
        seen++;
      }
    } finally {
      await browser.close();
    }
    expect(seen, "every floor visited").toBe(floors.length);
    expect(pathsSeen, "dotted flight, drone and conduit paths were measured").toBeGreaterThan(0);
    console.log(`text checks: ${pathsSeen} paths, ${layersSeen} layer views`);
    expect(layersSeen, "the dags floor's layer measured").toBeGreaterThanOrEqual(1);
    expect(codeLinksSeen, "F0's Code links conduits measured").toBe(1);
    expect({ turned, captions }, "turned words; rail parts captioned with their kind").toEqual({ turned: [], captions: [] });
    // words and tiles share coordinates: a line's own words (station and platform codes) are found beside its tiles
    expect(ownNear, "a line's own words within a tile of it").toBeGreaterThan(0);
    // the ratchet: an overlap with no local fix is listed here (`<floor> <fit|near>: "<word>" over …`); the list never grows,
    // and an entry no longer found is taken off it. Empty: every overlap found so far was fixed where it was drawn.
    const KNOWN: string[] = [];
    expect({ added: found.filter((f) => !KNOWN.includes(f)), gone: KNOWN.filter((k) => !found.includes(k)) }, "words over a line or another word").toEqual({ added: [], gone: [] });
    expect(errors).toEqual([]);
  }, 300_000);

  it("factory view: the nearby floors are planned while idle, so descending finds the plan cached", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const kids = Object.keys(model.floor("site")!.items).filter((id) => model.floor(id));
    const inside = model.map.nodes.find((n) => model.floorOf(n.id) === kids[0])!;
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByLabel("Still motion").check();
      const attr = (n: string) => page.locator("canvas").getAttribute(n);
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-plans-queued") === "0", null, { timeout: 60_000 });
      expect(Number(await attr("data-plans")), "F0 and the floors its machines open").toBe(1 + kids.length);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get(inside.id)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((c) => document.querySelector("canvas")?.getAttribute("data-floor") === c, kids[0], { timeout: 15_000 });
      expect(await attr("data-plan-hit"), "the floor's plan was already cached").toBe("true");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("factory view: hovering a schedule sign lists its jobs; a stand-in rail is selected and named in the inspector", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    // where a floor tile's centre lands on the canvas at Fit (the scene's fit(): the floor centred at fitScale)
    const atFit = async (page: import("playwright-core").Page, c: string, tx: number, ty: number) => {
      const { bundles, doors } = model.bundles(c);
      const tf = planFloor(model, c, doors, bundles).tf, { w, h } = toGeometry(tf).bounds;
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, c === "site")));
      return { x: box.x + (box.width - w * s) / 2 + (tx * 24 + 12) * s, y: box.y + (box.height - h * s) / 2 + 14 * s + (ty * 24 + 12) * s, tf };
    };
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      // nightly-jobs' sign on F0: its hover lists all ten jobs with their schedules
      const { bundles, doors } = model.bundles("site");
      const sign = planFloor(model, "site", doors, bundles).tf.rails!.yards.find((y) => y.source === "svc:nightly-jobs")!.sign!;
      const at = await atFit(page, "site", sign.x, sign.y);
      await page.mouse.move(at.x, at.y);
      await page.waitForFunction(() => !!document.querySelector("canvas")?.getAttribute("data-rail-tip"), null, { timeout: 5_000 });
      const tip = (await page.locator("canvas").getAttribute("data-rail-tip"))!;
      expect(tip).toContain("bq_revenue_export — daily 03:45 (1×/day)");
      expect(tip.split("\n")).toHaveLength(11);
      await page.mouse.click(at.x, at.y);         // a tap selects the yard: the inspector lists its jobs and schedules (the keyboard route)
      await page.waitForFunction(() => /Rail yard/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      await expect(page.locator(".insp .jobs li").count()).resolves.toBe(10);
      await expect(page.locator(".insp .jobs").textContent()).resolves.toContain("bq_revenue_export — daily 03:45 (1×/day)");
      await page.mouse.move(at.x, at.y - 200);   // off the sign: the list goes
      await page.waitForFunction(() => !document.querySelector("canvas")?.getAttribute("data-rail-tip"), null, { timeout: 5_000 });
      // demand-forecast's floor: a tap on its stand-in rail (the reference task to feature-store's door) selects it
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get("forecast::forecast/")!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction(() => /demand-forecast/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      const df = await atFit(page, "svc:demand-forecast", 0, 0), shell = df.tf.rails!.shells[0];
      const { routes } = (() => { const q = model.bundles("svc:demand-forecast"); return planFloor(model, "svc:demand-forecast", q.doors, q.bundles); })();
      const own = routes.find((r) => r.key === shell.key)!.pieces.filter((q) => !q.under && !routes.some((o) => o.key !== shell.key && o.pieces.some((z) => z.x === q.x && z.y === q.y)));
      const t = own[Math.floor(own.length / 2)];
      const p = await atFit(page, "svc:demand-forecast", t.x, t.y);
      await page.mouse.click(p.x, p.y);
      await page.waitForFunction(() => /feature-store/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      await expect(page.locator(".insp .sub").first().textContent()).resolves.toMatch(/batch rail · 1 job/);
      await expect(page.locator(".insp .rels li").count()).resolves.toBe(1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("factory view: a door's double-click goes in to the door back on the far side, and that door leads back", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    const FEATURES = "features::features.workflows", FORECAST = "svc:demand-forecast";
    // the centre of door `door` on floor `c` at Fit (the scene's fit(): the floor centred at fitScale)
    const doorAt = async (page: import("playwright-core").Page, c: string, door: string) => {
      const { bundles, doors } = model.bundles(c);
      const tf = planFloor(model, c, doors, bundles).tf, { w, h } = toGeometry(tf).bounds, r = tf.boxes.get(door)!;
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, c === "site")));
      return { x: box.x + (box.width - w * s) / 2 + (r.x + r.w / 2) * 24 * s, y: box.y + (box.height - h * s) / 2 + 14 * s + (r.y + r.h / 2) * 24 * s };
    };
    const onFloor = (page: import("playwright-core").Page, name: string) =>
      page.waitForFunction((n) => (document.querySelector(".floors button[aria-current=page]")?.textContent ?? "").includes(n)
        && [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), name, { timeout: 30_000 });
    const fit = async (page: import("playwright-core").Page) => {
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera === "idle", null, { timeout: 5_000 });
    };
    try {
      expect(model.doorLanding(FEATURES, FORECAST)).toEqual({ floor: FORECAST, door: "door:svc:feature-store" });
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      // features' workflows.py: its door to demand-forecast carries the reference task forecast runs there
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get("features::features.workflows#compute_zone_features/1")!);
      await page.locator(".rail .list button").first().click();
      await onFloor(page, "workflows.py");
      await fit(page);
      const out = await doorAt(page, FEATURES, "door:svc:demand-forecast");
      await page.mouse.dblclick(out.x, out.y);
      // not F0: in to demand-forecast's own floor, where the stand-in rail meets the door back to feature-store
      await onFloor(page, "demand-forecast");
      await page.waitForFunction(() => /feature-store/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      await fit(page);
      const back = await doorAt(page, FORECAST, "door:svc:feature-store");
      await page.mouse.dblclick(back.x, back.y);
      await onFloor(page, "workflows.py");
      await page.waitForFunction(() => /demand-forecast/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      // a door deeper in is named after the building it opens: reservations' quote calls pricing's QuoteEndpoint
      const quote = "reservations::city.parking.reservations.PricingClient.Live", PRICING = "svc:pricing";
      const words = doorWords(model, quote, PRICING), lands = model.doorLanding(quote, PRICING)!;
      expect(words).toBe(`${model.codes.get(lands.floor)} QuoteEndpoint`);
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get(quote + "#quote/2")!);
      await page.locator(".rail .list button").first().click();
      await onFloor(page, "Live");
      await fit(page);
      const to = await doorAt(page, quote, "door:" + PRICING);
      await page.mouse.dblclick(to.x, to.y);
      await onFloor(page, "QuoteEndpoint");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("factory view: a train runs each rail with nothing selected; a selected station runs its own; Still motion parks them", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c"));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    const trainsOf = (c: string) => { const q = model.bundles(c), p = planFloor(model, c, q.doors, q.bundles); return { p, n: trainPaths(p.tf, p.routes).length }; };
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const trains = (n: number) => page.waitForFunction((n) => document.querySelector("canvas")?.getAttribute("data-trains") === String(n), n, { timeout: 15_000 });
      const clock = async () => Number(await page.locator("canvas").getAttribute("data-drone-clock"));
      const settled = () => page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      // F0, nothing selected: demand-forecast's yard → feature-store's station runs its train (self-only yards have none)
      const f0 = trainsOf("site").n;
      expect(f0).toBeGreaterThan(0);
      await trains(f0);
      // Still motion: every train parks at its yard (or door) end and nothing advances
      const still = page.getByLabel("Still motion");
      await still.check();
      await trains(0);
      const c1 = await clock();
      await page.waitForTimeout(700);
      expect(await clock(), "nothing advances under Still motion").toBe(c1);
      await still.uncheck();
      await trains(f0);
      // nightly-jobs' dags/ floor, opened with nothing selected: ten trains, one per DAG rail
      const search = page.getByRole("searchbox", { name: "Find a node by name or code" });
      await search.fill(model.codes.get("jobs/dags::dags/")!);
      await page.locator(".rail .list button").first().click();
      await settled();
      await page.locator(".floors button.down").click();
      await page.waitForFunction(() => /dags/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await settled();
      const dags = trainsOf("jobs/dags::dags/");
      expect(dags.n).toBe(10);
      await trains(10);
      // a tap on one station selects its rail: only that rail's train runs
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      const st = dags.p.tf.rails!.stations[0], { w, h } = toGeometry(dags.p.tf).bounds;
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, false)));
      const tx = st.x + Math.floor(st.w / 2), ty = st.y + Math.floor(st.h / 2);
      await page.mouse.click(box.x + (box.width - w * s) / 2 + (tx * 24 + 12) * s, box.y + (box.height - h * s) / 2 + 14 * s + (ty * 24 + 12) * s);
      await trains(1);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("refuses a version-1 map with a rescan message", async () => {
    const html = readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", JSON.stringify({ meta: { schema_version: 1, repo: "x", commit: "y" } }));
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, html);
    const browser = await chromium.launch({ executablePath: CHROMIUM });
    try {
      const page = await browser.newPage();
      await page.goto("file://" + file);
      await expect(page.getByRole("alert").textContent()).resolves.toMatch(/format version 1; rescan/);
    } finally {
      await browser.close();
    }
  }, 30_000);

  it("factory view: the webhook dock lights and fades with payments-webhook and the Stripe belt; its hover lists the routes", async () => {
    const demoMap = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    // the fixture with two inbound webhooks into worker: its dock is upright, so its routes show on hover only
    const two = JSON.parse(readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8")) as CodeMap;
    const to = "worker::worker.main#health/0";
    for (const [id, col, row, key] of [["3p:pay", 3, 0, "POST /hooks/pay"], ["3p:mail", 0, 1, "POST /hooks/mail"]] as const) {
      two.nodes.push({ id, kind: "external", name: id.slice(3) } as CodeMap["nodes"][number]);
      two.layout.containers.site.items[id] = { region: "line", col, row };
      two.relations.push({ kind: "request", from: id, to, id: `r:request:${id}->${to}`, key, confidence: "inferred", evidence: [] } as unknown as CodeMap["relations"][number]);
    }
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    const open = async (map: string) => {
      const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
      writeFileSync(file, readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c")));
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      return page;
    };
    // where a site tile's centre lands on the canvas at Fit (the scene's fit(): the floor centred at fitScale)
    const atFit = async (page: import("playwright-core").Page, model: Model, tx: number, ty: number) => {
      const { bundles, doors } = model.bundles("site");
      const p = planFloor(model, "site", doors, bundles), { w, h } = toGeometry(p.tf).bounds;
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, true)));
      return { x: box.x + (box.width - w * s) / 2 + (tx * 24 + 12) * s, y: box.y + (box.height - h * s) / 2 + 14 * s + (ty * 24 + 12) * s, p };
    };
    const docks = (page: import("playwright-core").Page) => page.locator("canvas").getAttribute("data-docks");
    const docksAre = (page: import("playwright-core").Page, want: string) =>
      page.waitForFunction((w) => document.querySelector("canvas")?.getAttribute("data-docks") === w, want, { timeout: 5_000 });
    try {
      const demo = new Model(JSON.parse(demoMap) as CodeMap);
      const page = await open(demoMap);
      await expect(docks(page), "nothing selected: lit").resolves.toBe("svc:payments-webhook:lit");
      const { p } = await atFit(page, demo, 0, 0), d = p.tf.webhooks![0], m = p.tf.boxes.get("svc:payments-webhook")!;
      // the dock's face says `POST`: hovering it lists the whole route
      const dock = await atFit(page, demo, d.x + d.w - 1, d.y);
      await page.mouse.move(dock.x, dock.y);
      await page.waitForFunction(() => !!document.querySelector("canvas")?.getAttribute("data-dock-tip"), null, { timeout: 5_000 });
      await expect(page.locator("canvas").getAttribute("data-dock-tip")).resolves.toBe("POST /webhooks/stripe");
      await page.mouse.move(dock.x, dock.y - 300);
      await page.waitForFunction(() => !document.querySelector("canvas")?.getAttribute("data-dock-tip"), null, { timeout: 5_000 });
      // back on, then a wheel: the camera moved, the card goes (as the trunk card does)
      await page.mouse.move(dock.x, dock.y);
      await page.waitForFunction(() => !!document.querySelector("canvas")?.getAttribute("data-dock-tip"), null, { timeout: 5_000 });
      await page.mouse.wheel(0, -40);
      await page.waitForFunction(() => !document.querySelector("canvas")?.getAttribute("data-dock-tip"), null, { timeout: 5_000 });
      await page.mouse.move(dock.x, dock.y - 300);
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      // payments-webhook selected: lit; an unrelated machine selected: faded
      const at = await atFit(page, demo, m.x + Math.floor(m.w / 2), m.y + 1);
      await page.mouse.click(at.x, at.y);
      await page.waitForFunction(() => /payments-webhook/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      await docksAre(page, "svc:payments-webhook:lit");
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("enforcement-worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /enforcement-worker/ }).first().click();
      await docksAre(page, "svc:payments-webhook:faded");
      // the Stripe belt selected (a tile of its own): lit again
      const key = "3p:stripe|svc:payments-webhook", own = p.routes.find((r) => r.key === key)!.pieces
        .filter((q) => !q.under && !q.join && !p.routes.some((o) => o.key !== key && o.pieces.some((z) => z.x === q.x && z.y === q.y)));
      expect(own.length, "the Stripe belt has tiles of its own").toBeGreaterThan(0);
      await page.getByRole("button", { name: "Fit" }).click();   // the find moved the camera to its pick
      await page.waitForTimeout(1200);
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      const t = own[Math.floor(own.length / 2)], belt = await atFit(page, demo, t.x, t.y);
      await page.mouse.click(belt.x, belt.y);
      await page.waitForFunction(() => /stripe/.test(document.querySelector(".insp")?.textContent ?? "") && /payments-webhook/.test(document.querySelector(".insp")?.textContent ?? ""), null, { timeout: 5_000 });
      await docksAre(page, "svc:payments-webhook:lit");
      // two routes into worker: the upright dock's hover lists both
      const model2 = new Model(two), page2 = await open(JSON.stringify(two));
      const { p: p2 } = await atFit(page2, model2, 0, 0), d2 = p2.tf.webhooks![0];
      const at2 = await atFit(page2, model2, d2.x, d2.y + 1);
      await page2.mouse.move(at2.x, at2.y);
      await page2.waitForFunction(() => !!document.querySelector("canvas")?.getAttribute("data-dock-tip"), null, { timeout: 5_000 });
      await expect(page2.locator("canvas").getAttribute("data-dock-tip")).resolves.toBe("POST /hooks/mail\nPOST /hooks/pay");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("factory view: hovering a trunk tile shows its lines on a card; moving off, a selection, a camera move and a floor change hide it; a click on a trunk tile or a junction plate selects a line", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(map) as CodeMap);
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c")));
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    const tipOf = (page: import("playwright-core").Page) => page.locator("canvas").getAttribute("data-trunk-tip");
    const tipShown = (page: import("playwright-core").Page, on: boolean) =>
      page.waitForFunction((o) => !!document.querySelector("canvas")?.getAttribute("data-trunk-tip") === o, on, { timeout: 5_000 });
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      // the ext-call trunk out of the notifier: three lines on one run, splitting to smtp, twilio and accounts-api
      const { bundles, doors } = model.bundles("site");
      const { tf, routes } = planFloor(model, "site", doors, bundles), { w, h } = toGeometry(tf).bounds;
      const covered = coveredKeys(flightPaths(tf), bundles);
      const trunk = [...sharedTiles(routes, (r) => covered.has(r.key)).values()]
        .filter((t) => t.ris.length === 3 && t.ris.every((i) => routes[i].kind === "belt")).sort((p, q) => p.y - q.y || p.x - q.x)[0];
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, true)));
      // where a site tile's centre lands on the canvas at Fit, and a tile only this line holds
      const at = (t: { x: number; y: number }) => ({ x: box.x + (box.width - w * s) / 2 + (t.x * 24 + 12) * s, y: box.y + (box.height - h * s) / 2 + 14 * s + (t.y * 24 + 12) * s });
      const own = (key: string) => { const r = routes.find((q) => q.key === key)!; return r.pieces.find((p) => !p.under && !p.join && !routes.some((o) => o !== r && o.pieces.some((z) => z.x === p.x && z.y === p.y)))!; };
      const on = at(trunk);
      await page.mouse.move(on.x, on.y);
      await tipShown(page, true);
      const tip = (await tipOf(page))!.split("\n");
      expect(tip[0]).toBe("3 lines · ext-call ×3");
      expect(tip.slice(1).map((r) => r.replace(/^→ X\d+ /, "")), "one row per branch, by code").toEqual(["smtp · ext-call", "twilio · ext-call", "accounts-api · ext-call"]);
      await page.mouse.move(on.x, on.y - 300);   // off the trunk: the card goes
      await tipShown(page, false);
      // back on, then a click: the card takes no pointer events, the click selects one of the trunk's lines (nothing was
      // selected), and that selection change hides the card
      const trunkLine = /^(smtp|twilio|accounts-api) ↔ notifier$/, h2 = () => page.locator(".insp h2").first().textContent();
      await expect(h2()).resolves.toBe("Whole system");
      await page.mouse.move(on.x, on.y);
      await tipShown(page, true);
      await page.mouse.click(on.x, on.y);
      await page.waitForFunction((re) => new RegExp(re).test(document.querySelector(".insp h2")?.textContent ?? ""), trunkLine.source, { timeout: 5_000 });
      await tipShown(page, false);
      // a junction plate of the trunk selects a line too: cleared first (a press on empty floor), then the plate
      const plate = trunk.ris.flatMap((i) => routes[i].pieces).find((p) => p.join && !p.under && (p.x !== trunk.x || p.y !== trunk.y))!, pl = at(plate);
      await page.mouse.click(box.x + 6, box.y + box.height - 6);
      await page.waitForFunction(() => document.querySelector(".insp h2")?.textContent === "Whole system", null, { timeout: 5_000 });
      await page.mouse.click(pl.x, pl.y);
      await page.waitForFunction((re) => new RegExp(re).test(document.querySelector(".insp h2")?.textContent ?? ""), trunkLine.source, { timeout: 5_000 });
      // back on, then a wheel: the camera moved, the card goes
      await page.mouse.move(on.x + 1, on.y);
      await page.mouse.move(on.x, on.y);
      await tipShown(page, true);
      await page.mouse.wheel(0, -40);
      await tipShown(page, false);
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForTimeout(1200);
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      // the trunk's lines still select from their own tiles
      const smtp = at(own("3p:smtp|svc:notifier"));
      await page.mouse.click(smtp.x, smtp.y);
      await page.waitForFunction(() => /smtp ↔ notifier/.test(document.querySelector(".insp h2")?.textContent ?? ""), null, { timeout: 5_000 });
      // a single-line belt shows no card
      const lone = at(own("3p:twilio|svc:notifier"));
      await page.mouse.move(lone.x, lone.y);
      await page.waitForTimeout(300);
      await expect(tipOf(page)).resolves.toBeNull();
      // a floor change hides the card: shown, then demand-forecast opened from the find list by keyboard (the pointer
      // stays on the trunk tile)
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get("forecast::forecast/")!);
      await page.mouse.move(on.x + 1, on.y);
      await page.mouse.move(on.x, on.y);
      await tipShown(page, true);
      await page.locator(".rail .list button").first().focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction(() => /demand-forecast/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await expect(tipOf(page)).resolves.toBeNull();
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);
  it("factory view: the Code links toggle shows and hides F0's code conduits, fades them with a selection, survives a reload and is hidden on an inner floor", async () => {
    const map = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", map.replaceAll("<", "\\u003c")));
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const links = page.getByRole("button", { name: "Code links" });
      const conduits = () => page.locator("canvas").getAttribute("data-conduits");
      const legend = page.locator(".legend li", { hasText: "Code dependency" });
      const whole = () => page.waitForFunction(() => /Whole system/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await expect(links.getAttribute("aria-pressed"), "off by default").resolves.toBe("false");
      await expect(conduits()).resolves.toBeNull();
      await expect(legend.count()).resolves.toBe(0);
      await links.click();
      await expect(links.getAttribute("aria-pressed")).resolves.toBe("true");
      await expect(conduits(), "on: one conduit per uses-code pair").resolves.toBe("12");
      await expect(legend.count()).resolves.toBe(1);
      // the open legend stays within the bound the Fit test holds it to
      const legendH = await page.locator(".legend ul").evaluate((e) => e.getBoundingClientRect().height);
      expect(legendH, `open legend with Code links ${legendH} px`).toBeLessThanOrEqual(LEGEND_MAX_H);
      await expect(page.locator("canvas").getAttribute("data-conduits-lit"), "nothing selected: all at full strength").resolves.toBe("12");
      // a selected service keeps its own conduit; the rest fade
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("enforcement-worker");
      await page.locator(".rail .list button", { hasText: "service" }).filter({ hasText: /enforcement-worker/ }).first().click();
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-conduits-lit") === "1", null, { timeout: 5_000 });
      // remembered across a reload
      await page.reload();
      await page.waitForSelector("canvas");
      await whole();
      await expect(links.getAttribute("aria-pressed")).resolves.toBe("true");
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-conduits") === "12", null, { timeout: 15_000 });
      // an inner floor: no toggle, no legend entry, no conduits leaked onto it
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill("main.py");
      await page.locator(".rail .list button", { hasText: "main.py" }).first().click();
      await page.waitForFunction(() => !/Whole system/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? "Whole system"), null, { timeout: 15_000 });
      await page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      await expect(links.count()).resolves.toBe(0);
      await expect(conduits()).resolves.toBeNull();
      await expect(legend.count()).resolves.toBe(0);
      // back on F0 they return; off hides them and the legend entry
      await page.locator(".floors button", { hasText: "Whole system" }).click();
      await whole();
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-conduits") === "12", null, { timeout: 15_000 });
      await links.click();
      await expect(links.getAttribute("aria-pressed")).resolves.toBe("false");
      await expect(conduits()).resolves.toBeNull();
      await expect(legend.count()).resolves.toBe(0);
      // a map with no uses-code pair (the fixture without its two, with one implements link inside shop, none on F0), the
      // toggle remembered on: no button, no conduit, and the legend as with the toggle off (its implements key kept, no
      // code-dependency key)
      const bare = JSON.parse(readFileSync(new URL("../fixtures/shop.code-map.json", import.meta.url), "utf8")) as CodeMap;
      bare.relations = bare.relations.filter((r) => r.kind !== "uses-code");
      Object.assign(bare.nodes.find((n) => n.id === "shop::io.demo.shop.repo.PgOrderRepo")!, { implements: ["shop::io.demo.shop.repo.OrderRepo"] });
      const bareFile = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
      writeFileSync(bareFile, readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", JSON.stringify(bare).replaceAll("<", "\\u003c")));
      const legendOf = async (on: boolean) => {
        const p = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        p.on("pageerror", (e) => errors.push(e.message));
        await p.goto("file://" + bareFile);
        await p.evaluate((v) => { localStorage.setItem("code-map.code-links", v); }, on ? "on" : "off");
        await p.reload();
        await p.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
        await expect(p.getByRole("button", { name: "Code links" }).count(), "no uses-code: no toggle").resolves.toBe(0);
        await expect(p.locator("canvas").getAttribute("data-conduits"), "on: none drawn; off: no count").resolves.toBe(on ? "0" : null);
        return p.locator(".legend li").allTextContents();
      };
      const shown = await legendOf(true);
      expect(shown).not.toContain("Code dependency");
      expect(shown).toContain("Implementation (dotted)");
      expect(shown, "the legend is as with Code links off").toEqual(await legendOf(false));
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);

  it("factory view: the dags floor's layers button and `used by 10` badge show _common.py's layer, named by its code, over a faint base; a selection lights all its lines; Esc, an empty-floor click and a floor change return to the base", async () => {
    const DAGS = "jobs/dags::dags/", COMMON = "jobs/dags::dags._common";
    const raw = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
    const model = new Model(JSON.parse(raw) as CodeMap);
    const code = model.codes.get(COMMON)!;   // the layer's name: _common.py's map code, as its machine shows it
    const file = join(mkdtempSync(join(tmpdir(), "viz-")), "index.html");
    writeFileSync(file, readFileSync(BUILT, "utf8").replace("/*CODE_MAP*/", raw.replaceAll("<", "\\u003c")));
    const browser = await chromium.launch({ executablePath: CHROMIUM, args: GL_ARGS });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto("file://" + file);
      await page.waitForSelector("canvas");
      const button = page.getByRole("button", { name: /^Layers:/ });
      const canvas = (k: string) => page.locator("canvas").getAttribute(`data-${k}`);
      const settled = () => page.waitForFunction(() => [...document.querySelectorAll<HTMLButtonElement>(".floors button")].every((x) => !x.disabled), null, { timeout: 15_000 });
      const name = () => button.locator(".layer-name").textContent();
      await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(model.codes.get("jobs/dags::dags/")!);
      await page.locator(".rail .list button").first().click();
      await settled();
      // nightly-jobs: no extra layer, no button
      await expect(button.count()).resolves.toBe(0);
      await expect(canvas("layers")).resolves.toBe("");
      await page.locator(".floors button.down").click();
      await page.waitForFunction(() => /dags/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await settled();
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      await expect(name()).resolves.toBe("Base");
      await expect(button.getAttribute("title"), "on the base the hover is the list's title").resolves.toBe("Layers");
      await expect(button.locator(".badge").textContent()).resolves.toBe("1");
      await expect(canvas("layers")).resolves.toBe(`${COMMON}:10`);
      await expect(canvas("used-by"), "_common.py is used by 10").resolves.toBe("jobs/dags::dags._common:10");
      expect((await canvas("words"))!.split("|")).toContain("used by 10");
      await expect(canvas("base-alpha")).resolves.toBe("1");
      // the list: Base and the layer with its count; choosing it lights its 10 lines over a 12% base, buildings as they were
      await button.click();
      await expect(page.locator(".layers-panel").getByRole("radio").count(), "the list: Base and the one layer").resolves.toBe(2);
      await expect(page.getByRole("radio", { name: "Base", exact: true }).isChecked()).resolves.toBe(true);
      await expect(page.getByRole("radio", { name: `${code} · 10`, exact: true }).count()).resolves.toBe(1);
      await expect(page.locator(".layers-panel label", { hasText: `${code} · 10` }).getAttribute("title"), "the full name on hover").resolves.toBe("_common.py");
      await page.getByRole("radio", { name: `${code} · 10` }).click();
      await expect(page.locator(".layers-panel").count(), "the list closes").resolves.toBe(0);
      await expect(name()).resolves.toBe(code);
      await expect(button.getAttribute("title"), "the full name on hover").resolves.toBe("_common.py");
      await expect(canvas("layer")).resolves.toBe(COMMON);
      await expect(canvas("layer-lit")).resolves.toBe("10");
      await expect(canvas("base-alpha")).resolves.toBe("0.12");
      await expect(canvas("machines-dim")).resolves.toBe("0");
      await expect(canvas("lit"), "moving parts run on the layer's 10 lines").resolves.toBe("10");
      await expect(canvas("trains"), "the base's trains stop with the fade").resolves.toBe("0");
      // the legend's line rows follow the layer: belts, no rails
      await page.locator(".legend .toggle").click();
      const rows = await page.locator(".legend li").allTextContents();
      expect(rows).toContain("Request (belt)");
      expect(rows).not.toContain("Batch job (rail)");
      // Esc returns to the base
      await page.keyboard.press("Escape");
      await expect(canvas("layer")).resolves.toBeNull();
      await expect(name()).resolves.toBe("Base");
      await expect(canvas("base-alpha")).resolves.toBe("1");
      expect(await page.locator(".legend li").allTextContents()).toContain("Batch job (rail)");
      // the `used by 10` badge, reached by keyboard (Tab turns on the canvas's accessible buttons), opens the layer
      await page.keyboard.press("Tab");
      const badge = page.locator(`button[aria-label="used by 10: show ${code}"]`);
      await badge.waitFor({ state: "attached", timeout: 5_000 });
      await badge.press("Enter");
      await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, COMMON, { timeout: 5_000 });
      await expect(name()).resolves.toBe(code);
      // a floor change resets to the base: up to nightly-jobs (no button), back down to dags (on the base)
      await page.locator(".floors button", { hasText: "nightly-jobs" }).click();
      await page.waitForFunction(() => /nightly-jobs/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await settled();
      await expect(canvas("layer")).resolves.toBeNull();
      await expect(button.count()).resolves.toBe(0);
      await page.locator(".rail .list button").first().click();
      await settled();
      await page.locator(".floors button.down").click();
      await page.waitForFunction(() => /dags/.test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), null, { timeout: 15_000 });
      await settled();
      await expect(canvas("layer")).resolves.toBeNull();
      await expect(name()).resolves.toBe("Base");
      // at Fit the badge's text reads: at least 10 px on screen
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      expect(Number(await canvas("badge-px")), "the badge's text px at Fit").toBeGreaterThanOrEqual(10);
      // trunk cards hide when the camera moves: a base trunk tile's on the base, a layer trunk tile's with the layer shown
      const b = model.bundles(DAGS), plan = planFloor(model, DAGS, b.doors, b.bundles, b.layered), { w, h } = toGeometry(plan.tf).bounds;
      const box = (await page.locator("canvas").boundingBox())!;
      const s = Math.max(0.12, Math.min(1.4, fitScale(w, h, box.width, box.height, false)));
      const at = (t: { x: number; y: number }) => ({ x: box.x + (box.width - w * s) / 2 + (t.x * 24 + 12) * s, y: box.y + (box.height - h * s) / 2 + 14 * s + (t.y * 24 + 12) * s });
      const tipShown = (on: boolean) => page.waitForFunction((o) => !!document.querySelector("canvas")?.getAttribute("data-trunk-tip") === o, on, { timeout: 5_000 });
      const cardHidesOnZoom = async (routes: typeof plan.routes) => {
        // a shared tile well away from _common.py's box (its badge stands beside it, over the floor)
        const hub = plan.tf.boxes.get(COMMON)!, far = (t: { x: number; y: number }) => Math.max(hub.x - t.x, t.x - (hub.x + hub.w), hub.y - t.y, t.y - (hub.y + hub.h)) > 8;
        const t = [...sharedTiles(routes, () => false).values()].filter(far).sort((p, q) => p.y - q.y || p.x - q.x)[0], on = at(t);
        await page.mouse.move(on.x + 1, on.y);
        await page.mouse.move(on.x, on.y);
        await tipShown(true);
        await page.mouse.wheel(0, -40);
        await tipShown(false);
        await page.getByRole("button", { name: "Fit" }).click();
        await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      };
      await cardHidesOnZoom(plan.routes);
      await button.click();
      await page.getByRole("radio", { name: `${code} · 10`, exact: true }).click();
      await cardHidesOnZoom(plan.layers![COMMON]!.routes);
      await page.keyboard.press("Escape");
      await expect(canvas("layer")).resolves.toBeNull();
      // picking a node whose lines are all in a layer opens it; Esc then returns to the base and, since its lines are
      // all in the layer, clears the selection with it (no lone selected box over a faded floor)
      const search = page.getByRole("searchbox", { name: "Find a node by name or code" });
      await search.fill(model.codes.get(COMMON)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, COMMON, { timeout: 5_000 });
      await expect(name()).resolves.toBe(code);
      await page.keyboard.press("Escape");
      await expect(canvas("layer")).resolves.toBeNull();
      await expect(page.locator(".insp h2").first().textContent(), "Esc closed the layer and its layer-only selection").resolves.not.toMatch(/_common/);
      await expect(canvas("machines-dim"), "no dimmed buildings").resolves.toBe("0");
      await expect(page.locator(".insp .sub").first().textContent(), "the floor's line count includes the layer, named by its code").resolves.toContain(`(10 in ${code})`);
      // a node with base lines leaves the base as it is
      const other = b.bundles.flatMap((x) => [x.a, x.b]).find((id) => id !== COMMON && model.nodes.get(id)?.kind === "file" && model.floorOf(id) === DAGS)!;
      await search.fill(model.codes.get(other)!);
      await page.locator(".rail .list button").first().click();
      await page.waitForFunction((n) => (document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(other), { timeout: 5_000 });
      await expect(canvas("layer")).resolves.toBeNull();
      // a box selected while a layer shows lights all its lines, layer and base: bq_tariff_snapshot.py's layer belt from
      // _common.py and its base rail (with its station and platform) and DB read/write taps, at full strength; moving
      // parts run on them, the train among them. A click on empty floor then returns to the base with nothing selected
      const TARIFF = "jobs/dags::dags.bq_tariff_snapshot";
      const own = b.bundles.filter((x) => x.a === TARIFF || x.b === TARIFF).map((x) => x.key).sort();
      expect(own, "its base lines: the rail and the two taps").toEqual(["db:bigquery:BQ_PROJECT|" + TARIFF, "db:postgres:DB_HOST|" + TARIFF, "door:svc:nightly-jobs|" + TARIFF]);
      await page.getByRole("button", { name: "Fit" }).click();
      await page.waitForSelector("canvas[data-camera=idle]", { timeout: 15_000 });
      const empty = () => page.mouse.click(box.x + box.width - 4, box.y + box.height / 2);
      await empty();   // on the base: clears the selection, as before
      await page.waitForFunction((n) => !(document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(other), { timeout: 5_000 });
      await button.click();
      await page.getByRole("radio", { name: `${code} · 10`, exact: true }).click();
      await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, COMMON, { timeout: 5_000 });
      await expect(canvas("base-lit"), "no base line at full strength with nothing selected").resolves.toBe("");
      const tb = plan.tf.boxes.get(TARIFF)!, mid = at({ x: tb.x + (tb.w - 1) / 2, y: tb.y + (tb.h - 1) / 2 });
      await page.mouse.click(mid.x, mid.y);
      await page.waitForFunction((n) => (document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(TARIFF), { timeout: 5_000 });
      await expect(canvas("layer"), "the layer stays").resolves.toBe(COMMON);
      // the yard's views are also its rail's (lineViews joins each yard part under every rail of the yard and its own key)
      await expect(canvas("base-lit"), "its rail (with the yard it leaves) and DB read/write taps at full strength").resolves.toBe([...own, "yard:" + DAGS].join(" "));
      await expect(canvas("layer-lit"), "its layer belt at full strength").resolves.toBe("1");
      await expect(canvas("lit"), "moving parts on its four lines").resolves.toBe("4");
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-trains") === "1", null, { timeout: 5_000 });   // its rail runs its train (counted as it runs)
      await empty();
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-layer") === null, null, { timeout: 5_000 });
      await expect(name()).resolves.toBe("Base");
      await expect(page.locator(".insp h2").first().textContent(), "nothing selected").resolves.not.toMatch(/tariff/);
      await expect(canvas("base-alpha")).resolves.toBe("1");
      await expect(canvas("machines-dim"), "no dimmed buildings").resolves.toBe("0");
      // with a layer shown and a box with base lines selected, the first Esc returns to the base and keeps the
      // selection; the second clears it
      await button.click();
      await page.getByRole("radio", { name: `${code} · 10`, exact: true }).click();
      await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, COMMON, { timeout: 5_000 });
      await page.mouse.click(mid.x, mid.y);
      await page.waitForFunction((n) => (document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(TARIFF), { timeout: 5_000 });
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-layer") === null, null, { timeout: 5_000 });
      await expect(page.locator(".insp h2").first().textContent(), "the first Esc keeps the selection").resolves.toContain(model.itemName(TARIFF));
      await page.keyboard.press("Escape");
      await page.waitForFunction((n) => !(document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(TARIFF), { timeout: 5_000 })
        .catch(() => { throw new Error("the second Esc left the selection as it was"); });
      await expect(canvas("machines-dim"), "no dimmed buildings").resolves.toBe("0");
      // a box with base lines selected on the base peeks its layer lines over it, without switching layer, and the
      // inspector names the layer each such connection lives in; Esc, or showing the layer, ends the peek
      const peeked = new Set(b.layered.filter((x) => x.a === TARIFF || x.b === TARIFF).map((x) => x.key)).size;
      expect(peeked, "bq_tariff_snapshot.py has a layer belt").toBeGreaterThanOrEqual(1);
      await expect(canvas("peek"), "nothing selected: no peek").resolves.toBeNull();
      const pick = async () => {
        await search.fill(model.codes.get(TARIFF)!);
        await page.locator(".rail .list button").first().click();
        await page.waitForFunction((n) => (document.querySelector(".insp h2")?.textContent ?? "").includes(n), model.itemName(TARIFF), { timeout: 5_000 });
      };
      await pick();
      await expect(canvas("layer"), "the base stays").resolves.toBeNull();
      await expect(canvas("peek"), "its layer line keys").resolves.toBe(String(peeked));
      // the far box of a peeked line (_common.py) is lit, as a base line's far box is: only buildings it has no line to dim
      const dimmed = ((await canvas("dimmed")) ?? "").split(" ").filter(Boolean);
      expect(dimmed, "the box it has a layer line to is lit").not.toContain(COMMON);
      expect(dimmed, "the buildings it has no line to dim").not.toHaveLength(0);
      const toCommon = page.locator(".insp .rels li", { hasText: code }).filter({ hasText: "in layer" });
      await expect(toCommon.first().locator(".meta").textContent(), "the connection to _common.py names its layer").resolves.toContain(` · in layer ${code}`);
      await expect(page.locator(".insp .rels li", { hasText: "in layer" }).count(), "the layer connections are named").resolves.toBeGreaterThanOrEqual(peeked);
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelector("canvas")?.getAttribute("data-peek") === null, null, { timeout: 5_000 });
      await pick();
      await expect(canvas("peek")).resolves.toBe(String(peeked));
      await button.click();
      await page.getByRole("radio", { name: `${code} · 10`, exact: true }).click();
      await page.waitForFunction((id) => document.querySelector("canvas")?.getAttribute("data-layer") === id, COMMON, { timeout: 5_000 });
      await expect(canvas("peek"), "a shown layer peeks nothing").resolves.toBeNull();
      await expect(canvas("layer-lit"), "its layer belt at full strength").resolves.toBe("1");
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 90_000);
});
