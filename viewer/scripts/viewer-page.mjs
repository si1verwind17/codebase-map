// Shared by scripts/shotset.mjs and scripts/guide.mjs: open the built viewer on a map in Chromium (1440×900, Still motion,
// unless the caller asks otherwise) and walk it to a view with a list of steps. Needs `npm run build` first.
import { readFileSync, writeFileSync } from "node:fs";
import { inflateSync } from "node:zlib";
import { chromium } from "playwright-core";

export const W = 1440, H = 900;
const BUILT = new URL("../../skills/visualizing-codebases/viewer/dist/viewer.html", import.meta.url);
const PAGE = new URL("../.shot-page.html", import.meta.url);   // gitignored, overwritten for each view

export function launch() {
  return chromium.launch({ executablePath: process.env.VIZ_CHROMIUM ?? "/usr/bin/chromium", args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
}

/** Writes the built viewer with `map` (a path or file URL) inlined to the shot page; returns the page's URL. */
export function writePage(map) {
  const built = readFileSync(BUILT, "utf8");
  writeFileSync(PAGE, built.replace("/*CODE_MAP*/", readFileSync(map, "utf8").replaceAll("<", "\\u003c")));
  return PAGE.href;
}

/** Opens `map` in a new page of `target`, collects page errors into `errors` tagged with `name`, and waits until the
 *  first floor is drawn and past its wheel-quiet time. From a browser the page is W×H (or `viewport` [w, h]) at device
 *  scale `scale` (1 unless asked), in Still motion (reduced motion). From a context the context's own settings hold:
 *  the guide's clips use one with motion on, so floor changes and travel are animated. */
export async function openView(target, map, name, errors, { scale = 1, viewport = [W, H] } = {}) {
  const href = writePage(map);
  const page = "newContext" in target
    ? await target.newPage({ viewport: { width: viewport[0], height: viewport[1] }, deviceScaleFactor: scale, reducedMotion: "reduce" })
    : await target.newPage();
  page.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`${name} console: ${m.text()}`);
  });
  await page.goto(href);
  // pictures and clips show the floor as it was before the guide went online: no guide link in the legend, no notice
  await page.addStyleTag({ content: ".legend .guide-link, .guide-note { display: none !important; }" });
  await page.waitForSelector("canvas");
  await idle(page);
  await page.waitForTimeout(800);   // past the fresh floor's wheel-quiet time
  return page;
}

/** Runs each step, waiting for the camera to settle after each:
 *  ["find", text] fills Find · ["pick"] clicks the first result · ["down"] opens the floor below ·
 *  ["floor", /re/ or "re"] waits until the current floor's button matches · ["tap", x, y] clicks the canvas ·
 *  ["layer", name] shows an extra layer · ["wheel", x, y, dy, n, gap?] zooms about (x, y) ·
 *  ["key", key] presses a key · ["fit"] presses Fit · ["panel"] closes the inspector · ["legend"] collapses the legend when it is open ·
 *  ["pinned", text] starts the pinned trace whose title has text · ["trace"] presses the inspector's Trace · ["row", text] opens a trace row's detail. */
export async function runSteps(page, steps) {
  for (const [verb, ...a] of steps) {
    if (verb === "find") await page.getByRole("searchbox", { name: "Find a node by name or code" }).fill(a[0]);
    if (verb === "pick") await page.locator(".rail .list button").first().waitFor();
    if (verb === "pick") await page.locator(".rail .list button").first().click();
    if (verb === "down") await page.locator(".floors button.down").click();
    if (verb === "floor") await page.waitForFunction((re) => new RegExp(re).test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), a[0].source ?? a[0], { timeout: 15_000 });
    if (verb === "tap") await page.mouse.click(a[0], a[1]);
    if (verb === "key") await page.keyboard.press(a[0]);
    if (verb === "fit") await page.locator(".floor-tools button", { hasText: /^Fit$/ }).click();
    if (verb === "panel") await page.locator("button.collapse[aria-expanded=true]").click();
    if (verb === "legend") { const t = page.locator(".legend .toggle[aria-expanded=true]"); if (await t.count()) await t.click(); }
    if (verb === "pinned") await page.locator(".rail .pins .pin-start", { hasText: a[0] }).first().click();   // start a pinned trace
    if (verb === "trace") await page.locator(".insp header button", { hasText: /^Trace$/ }).click();          // the inspector's Trace
    if (verb === "row") await page.locator(".trace .row .rname", { hasText: a[0] }).first().click();          // open a row's detail
    if (verb === "layer") {   // show an extra layer from the layers button's list
      await page.getByRole("button", { name: /^Layers:/ }).click();
      await page.getByRole("radio", { name: new RegExp(`^${a[0]} · `) }).click();
    }
    if (verb === "wheel") {   // zoom about (x, y): n wheel steps of dy each (negative dy zooms in), `gap` ms apart
      const [x, y, dy, n, gap = 80] = a;
      await page.waitForTimeout(900);   // a freshly shown floor ignores the wheel for 600 ms (scene depthQuietUntil)
      await page.mouse.move(x, y);
      for (let i = 0; i < n; i++) { await page.mouse.wheel(0, dy); await page.waitForTimeout(gap); }
    }
    await idle(page);
  }
}

/** Ends the view: no hover left over the canvas unless a tap put it there on purpose, then the camera settles. */
export async function settle(page, steps) {
  const v = page.viewportSize() ?? { width: W, height: H };
  await page.mouse.move(v.width - 1, v.height - 1);
  if (steps.some(([s]) => s === "tap")) await page.mouse.move(...steps.find(([s]) => s === "tap").slice(1));
  await page.waitForTimeout(600);
  await idle(page);
}

/** The camera is still and no floor change is under way. */
export async function idle(page) {
  await page.waitForFunction(() => {
    const c = document.querySelector("canvas");
    return c && c.dataset.camera !== "moving" && !document.body.innerText.includes("Moving…");
  }, null, { timeout: 15_000 });
}

/** RGBA pixels of a PNG as Chromium writes it (8-bit, non-interlaced, colour type 2 or 6). */
export function pixels(buf) {
  let p = 8, w = 0, h = 0, type = 6;
  const idat = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p), kind = buf.toString("ascii", p + 4, p + 8), data = buf.subarray(p + 8, p + 8 + len);
    if (kind === "IHDR") { w = data.readUInt32BE(0); h = data.readUInt32BE(4); type = data[9]; }
    if (kind === "IDAT") idat.push(data);
    p += 12 + len;
  }
  const bpp = type === 6 ? 4 : 3, raw = inflateSync(Buffer.concat(idat)), stride = w * bpp;
  const out = Buffer.alloc(w * h * 4), prev = Buffer.alloc(stride), cur = Buffer.alloc(stride);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)], row = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? cur[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c);
      const pred = f === 0 ? 0 : f === 1 ? a : f === 2 ? b : f === 3 ? (a + b) >> 1 : pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
      cur[i] = (row[i] + pred) & 255;
    }
    for (let x = 0; x < w; x++) for (let k = 0; k < 4; k++) out[(y * w + x) * 4 + k] = k < bpp ? cur[x * bpp + k] : 255;
    cur.copy(prev);
  }
  return { w, h, out };
}
