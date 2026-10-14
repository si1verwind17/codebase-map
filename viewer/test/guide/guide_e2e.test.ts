// The field guide in a browser: 18 pages turned with ← and →, Back and Next in the same place on every page, every
// picture and clip loaded, nothing wider than a 375 px phone. Needs `npm run guide` first and a Chromium:
// VIZ_CHROMIUM=/usr/bin/chromium npx vitest run test/guide_e2e.test.ts
import { existsSync } from "node:fs";
import { chromium, type Page } from "playwright-core";
import { describe, expect, it } from "vitest";

const CHROMIUM = process.env.VIZ_CHROMIUM ?? "";
const GUIDE = new URL("../../../docs/field-guide.html", import.meta.url);
const PAGES = 18;

/** Every picture and clip on the current page has loaded. */
const loaded = (page: Page) => page.waitForFunction(() =>
  [...document.querySelectorAll("#page img")].every((i) => (i as HTMLImageElement).complete && (i as HTMLImageElement).naturalWidth > 0) &&
  [...document.querySelectorAll("#page video")].every((v) => (v as HTMLVideoElement).readyState >= 2 && (v as HTMLVideoElement).videoWidth > 0),
  null, { timeout: 15_000 });

/** Where Back and Next are on screen. */
const place = async (page: Page) => JSON.stringify([await page.locator("#prev").boundingBox(), await page.locator("#next").boundingBox()]);

describe.runIf(CHROMIUM && existsSync(CHROMIUM))("the field guide in a browser", () => {
  it("turns 18 pages with ← and →, keeps Back and Next in place, and loads every picture and clip", async () => {
    const browser = await chromium.launch({ executablePath: CHROMIUM });
    const errors: string[] = [];
    try {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
      page.on("pageerror", (e) => errors.push(e.message));
      await page.goto(GUIDE.href);
      await expect(page.locator("#toc button").count()).resolves.toBe(PAGES);
      const first = await place(page);
      const titles: string[] = [];
      for (let n = 1; n <= PAGES; n++) {
        await expect(page.locator("#count").textContent()).resolves.toBe(`${n} / ${PAGES}`);
        titles.push((await page.locator("#page h2").textContent())!);
        await loaded(page);
        const pics = await page.locator("#page img, #page video").count();
        expect(pics > 0, `page ${n} has a picture`).toBe(n < PAGES);
        expect(await place(page), `Back and Next on page ${n}`).toBe(first);
        await page.keyboard.press("ArrowRight");
      }
      await expect(page.locator("#count").textContent()).resolves.toBe(`${PAGES} / ${PAGES}`);   // → on the last page stays
      expect(new Set(titles).size).toBe(PAGES);
      for (let n = PAGES - 1; n >= 1; n--) {
        await page.keyboard.press("ArrowLeft");
        await expect(page.locator("#count").textContent()).resolves.toBe(`${n} / ${PAGES}`);
        await expect(page.locator("#page h2").textContent()).resolves.toBe(titles[n - 1]);
      }
      await page.keyboard.press("ArrowLeft");
      await expect(page.locator("#count").textContent()).resolves.toBe(`1 / ${PAGES}`);
      expect(await page.locator("#prev").isDisabled()).toBe(true);
    } finally {
      await browser.close();
    }
    expect(errors).toEqual([]);
  }, 120_000);

  it("fits a 375 px phone on every page: nothing overflows sideways, and Back and Next stay in place", async () => {
    const browser = await chromium.launch({ executablePath: CHROMIUM });
    try {
      const page = await browser.newPage({ viewport: { width: 375, height: 740 } });
      await page.goto(GUIDE.href);
      const first = await place(page);
      for (let n = 1; n <= PAGES; n++) {
        await loaded(page);
        expect(await place(page), `Back and Next on page ${n} at 375 px`).toBe(first);
        const over = await page.evaluate(() => {
          const w = document.documentElement.clientWidth, bad: string[] = [];
          if (document.documentElement.scrollWidth > w) bad.push(`page scrolls sideways (${document.documentElement.scrollWidth} > ${w})`);
          for (const el of document.querySelectorAll<HTMLElement>("main, main *")) {
            const r = el.getBoundingClientRect();
            if (r.width && (r.right > w + 0.5 || r.left < -0.5)) bad.push(`${el.tagName.toLowerCase()}.${el.className} spans ${Math.round(r.left)}–${Math.round(r.right)}`);
          }
          const sheet = document.querySelector<HTMLElement>(".sheet")!;
          if (sheet.scrollWidth > sheet.clientWidth) bad.push(`the sheet scrolls sideways (${sheet.scrollWidth} > ${sheet.clientWidth})`);
          return bad;
        });
        expect(over, `page ${n} at 375 px`).toEqual([]);
        await page.keyboard.press("ArrowRight");
      }
    } finally {
      await browser.close();
    }
  }, 120_000);
});
