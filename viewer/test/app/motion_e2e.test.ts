// The hidden-tab pause in the built viewer (visibility.ts): with motion on, the drone clock stands still while the page
// is hidden and runs again when it shows, with no catch-up jump. Needs `npm run build` first and a Chromium:
// VIZ_CHROMIUM=/usr/bin/chromium.
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
import { describe, expect, it } from "vitest";
import { GL_ARGS } from "../gl";

const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
const BUILT = new URL("../../../skills/visualizing-codebases/viewer/dist/viewer.html", import.meta.url);

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("motion while the tab is hidden", () => {
  it("the drone clock stands still while the page is hidden, and runs on with a first step of at most 1.2 s when it shows", async () => {
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
      await page.waitForFunction(() => Number(document.querySelector("canvas")?.getAttribute("data-drones")) > 0, null, { timeout: 15_000 });
      const c00 = await clock();
      await page.waitForTimeout(1200);   // the canvas shows the clock about once a second
      expect(await clock(), "the drone clock runs").toBeGreaterThan(c00);
      // a headless page never hides: the test tells it so, as the browser would when the reader switches tabs
      const visibility = (s: DocumentVisibilityState) => page.evaluate((v) => {
        Object.defineProperty(document, "visibilityState", { configurable: true, get: () => v });
        document.dispatchEvent(new Event("visibilitychange"));
      }, s);
      await visibility("hidden");
      const c0 = await clock();
      await page.waitForTimeout(1500);
      expect(await clock(), "nothing advances while hidden").toBe(c0);
      await visibility("visible");
      await page.waitForFunction((c) => Number(document.querySelector("canvas")?.getAttribute("data-drone-clock")) > c, c0, { timeout: 5_000 });
      const c1 = await clock();
      expect(c1 - c0, "no catch-up jump on return").toBeLessThanOrEqual(1.2);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 60_000);
});
