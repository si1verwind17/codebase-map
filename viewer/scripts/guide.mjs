// The field guide: renders each picture named in guide/pages.html from its tiny example map with the built viewer
// (1440×900 unless the picture asks for another viewport, Still motion, like scripts/shotset.mjs; device scale 2 so the
// labels stay sharp when the page shows the picture smaller), crops stills to the drawn floor, records the two clips
// (1200×750, motion on) with a visible pointer, inlines everything and writes docs/field-guide.html. Needs `npm run build`.
//   VIZ_CHROMIUM=/usr/bin/chromium npm run guide [-- --clips] [-- --keep <dir>]
//     --keep   also saves each still and clip there
//     --clips  records the clips again even when the guide is fresh. Without it, when docs/field-guide.html is stamped
//              with the current inputs digest (scripts/guide-inputs.mjs), its clips are reused as they are: a recording
//              differs from run to run, so a re-render with unchanged inputs keeps the committed file stable.
// Clips are transcoded by ffmpeg (VIZ_FFMPEG, default `ffmpeg` on the PATH): 960 px wide, 15 fps, VP9, no audio.
// Playwright's recordVideo also needs its own ffmpeg build (~/.cache/ms-playwright/ffmpeg-*/ffmpeg-linux; get it with
// `npx playwright install ffmpeg`): recording checks for it first and stops before the ~90 s of stills if it is missing.
// After any viewer change: npm run build, then this guide (VIZ_CHROMIUM=... npm run guide), then npx vitest run and
// npm run check, then the shots (scripts/shotset.mjs), and rebuild the demo page (scripts/view.py demo/parking-city).
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { guideDigest } from "./guide-inputs.mjs";
import { idle, launch, openView, pixels, runSteps, settle } from "./viewer-page.mjs";

const ROOT = new URL("../", import.meta.url);
const TEMPLATE = new URL("guide/pages.html", ROOT);
const OUT = new URL("../docs/field-guide.html", ROOT);
const FONT = new URL("node_modules/@fontsource-variable/archivo/files/archivo-latin-wdth-normal.woff2", ROOT);
const DEMO = new URL("../demo/parking-city/docs/viz-code/code-map.json", ROOT);
const mapOf = (name) => (name === "@demo" ? DEMO : new URL(`guide/maps/${name}.code-map.json`, ROOT));
const PICTURES = /(<script type="application\/json" id="pictures">)([\s\S]*?)(<\/script>)/;
const HIDE = ".legend, .floor-tools, .layers-panel, .guide-note { visibility: hidden !important; }";   // pictures show the floor alone
/** A picture with "layersButton": true keeps the layers button (the other floor tools stay hidden), so it shows where the map has it. */
const HIDE_BUT_LAYERS_BUTTON = ".legend, .layers-panel, .guide-note, .floor-tools button:not(.layers-btn) { visibility: hidden !important; }";

const keepAt = process.argv.includes("--keep") ? process.argv[process.argv.indexOf("--keep") + 1] : null;
if (keepAt) mkdirSync(keepAt, { recursive: true });
const keep = (name, buf) => { if (keepAt) writeFileSync(join(keepAt, name), buf); };

/** One still: the view after `steps`, cropped to the floor drawn in the canvas (the canvas less its empty margin), or
 *  the trace pane (`pane`) or the inspector (`inspector`) alone. */
async function still(browser, shot, name, errors) {
  const scale = shot.scale ?? 2;
  const page = await openView(browser, mapOf(shot.map), name, errors, { scale, ...(shot.viewport ? { viewport: shot.viewport } : {}) });
  await runSteps(page, shot.steps);
  await settle(page, shot.steps);
  await page.addStyleTag({ content: shot.layersButton ? HIDE_BUT_LAYERS_BUTTON : HIDE });
  await page.waitForTimeout(200);
  const done = async (clip) => {
    const png = await page.screenshot({ clip });
    await page.close();
    keep(`${name}.png`, png);
    return { src: `data:image/png;base64,${png.toString("base64")}`, density: scale / (shot.show ?? 1) };
  };
  if (shot.pane) return done(await page.locator(".pane").boundingBox());   // the trace pane, whole: no floor crop
  if (shot.inspector) {   // the inspector down to the end of what it holds: no floor crop
    const box = await page.locator(".insp").boundingBox();
    const end = await page.locator(".insp > :last-child").evaluate((e) => e.getBoundingClientRect().bottom);
    return done({ ...box, height: Math.min(box.height, end - box.y) });
  }
  const box = await page.locator(".canvas").boundingBox();
  const whole = { x: Math.round(box.x), y: Math.round(box.y), width: Math.round(box.width), height: Math.round(box.height) };
  const { w, h, out } = pixels(await page.screenshot({ clip: whole }));
  const bg = out.readUInt32BE(0);   // the canvas's top-left corner is empty floor background
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    if (out.readUInt32BE(i) === bg) continue;
    const d = Math.max(...[0, 1, 2].map((k) => Math.abs(out[i + k] - ((bg >>> (24 - 8 * k)) & 255))));
    if (d < 6) continue;
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
  }
  if (x1 < 0) throw new Error(`${name}: nothing drawn in the canvas`);
  const pad = 10 * scale;
  const [cx0, cy0] = [Math.max(0, x0 - pad), Math.max(0, y0 - pad)];
  const [cx1, cy1] = [Math.min(w - 1, x1 + pad), Math.min(h - 1, y1 + pad)];
  return done({ x: whole.x + cx0 / scale, y: whole.y + cy0 / scale, width: (cx1 - cx0 + 1) / scale, height: (cy1 - cy0 + 1) / scale });
}

/** A pointer drawn into the page, so a clip shows where the mouse is and when it clicks. */
function pointer() {
  addEventListener("DOMContentLoaded", () => {
    const c = document.createElement("div");
    c.style.cssText = "position:fixed;z-index:99999;left:-40px;top:-40px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;border:3px solid #d01012;background:rgba(245,205,47,.55);pointer-events:none;transition:transform .15s";
    document.body.appendChild(c);
    addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    addEventListener("mousedown", () => (c.style.transform = "scale(.6)"), true);
    addEventListener("mouseup", () => (c.style.transform = ""), true);
  });
}

const glide = (page, x, y) => page.mouse.move(x, y, { steps: 25 });
const floorIs = (page, re) => page.waitForFunction((s) => new RegExp(s).test(document.querySelector(".floors button[aria-current=page]")?.textContent ?? ""), re, { timeout: 15_000 });
const current = (page) => page.evaluate(() => document.querySelector(".floors button[aria-current=page]")?.textContent ?? "");

/** Wheel steps of `dy` over (x, y) until the current floor's button matches `re` (at most `n` steps). */
async function wheelUntil(page, x, y, dy, re, n = 30) {
  await page.mouse.move(x, y);
  for (let i = 0; i < n && !new RegExp(re).test(await current(page)); i++) { await page.mouse.wheel(0, dy); await page.waitForTimeout(110); }
  await floorIs(page, re);
}

/** Where the factory `name` is drawn on the fitted floor: picked from the "On this floor" list, the floor fitted again,
 *  then the centre of its blue selection frame. The selection is cleared again with a click on empty stage. Runs before
 *  the clip's first frame. */
async function factoryAt(page, name) {
  await page.locator(".rail button.item").filter({ has: page.locator(".name", { hasText: new RegExp(`^${name}$`) }) }).first().click();
  await idle(page);
  await runSteps(page, [["fit"]]);
  await page.waitForTimeout(600);
  const box = await page.locator(".canvas").boundingBox();
  const { w, h, out } = pixels(await page.screenshot({ clip: box }));
  // the frame's #0055bf: its edges are the columns and rows with a long run of blue (small blue marks elsewhere are not)
  const cols = new Array(w).fill(0), rows = new Array(h).fill(0);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    if (out[i] < 40 && out[i + 1] > 60 && out[i + 1] < 120 && out[i + 2] > 160 && out[i + 2] < 220) { cols[x]++; rows[y]++; }
  }
  const edges = (n) => n.flatMap((c, k) => (c > 40 ? [k] : []));
  const [xs, ys] = [edges(cols), edges(rows)];
  if (xs.length < 2 || ys.length < 2) throw new Error(`no selection frame for ${name}: the clip cannot find the factory`);
  const [x0, x1, y0, y1] = [xs[0], xs.at(-1), ys[0], ys.at(-1)];
  const empty = { x: box.x + 30, y: box.y + box.height - 30 };
  await page.mouse.click(empty.x, empty.y);
  await idle(page);
  return { at: { x: box.x + (x0 + x1) / 2, y: box.y + (y0 + y1) / 2 }, empty };
}

/** The inspector's heading reads `title`; fails loudly when it does not. */
const inspectorIs = (page, title) => page.waitForFunction((t) => document.querySelector(".insp h2")?.textContent?.trim() === t, title, { timeout: 10_000 })
  .catch(() => { throw new Error(`the inspector does not show ${title}`); });

/** The clips: each starts on a settled floor with the pointer in view, then runs its moves. */
const CLIPS = {
  /** click a factory, clear the selection, scroll in on it to go inside, scroll out to come back up. The selection is
   *  cleared with a click on empty floor (Esc clears it too, but a key press does not show in the clip). */
  async select(page, spec, { at, empty }) {
    await glide(page, at.x, at.y); await page.waitForTimeout(500);
    await page.mouse.click(at.x, at.y);
    await inspectorIs(page, spec.factory); await page.waitForTimeout(2500);
    await glide(page, empty.x, empty.y); await page.waitForTimeout(300);
    await page.mouse.click(empty.x, empty.y);
    await inspectorIs(page, "Whole system"); await page.waitForTimeout(1200);
    await glide(page, at.x, at.y); await page.waitForTimeout(300);
    await wheelUntil(page, at.x, at.y, -120, spec.factory);
    await idle(page); await page.waitForTimeout(2500);
    await wheelUntil(page, at.x, at.y, 120, "Whole system");
    await idle(page); await page.waitForTimeout(2500);
  },
};

const CW = 1200, CH = 750;   // the clips' viewport: the page's text is shown larger than from 1440×900

async function clip(browser, spec, name, errors, work) {
  const ctx = await browser.newContext({ viewport: { width: CW, height: CH }, deviceScaleFactor: 1, recordVideo: { dir: work, size: { width: CW, height: CH } } });
  await ctx.addInitScript(pointer);
  const t0 = Date.now();
  const page = await openView(ctx, mapOf(spec.map), name, errors);
  await runSteps(page, [["legend"]]);
  const where = spec.factory ? await factoryAt(page, spec.factory) : null;
  await page.mouse.move(CW - 230, CH - 140);
  await idle(page); await page.waitForTimeout(400);
  const start = (Date.now() - t0) / 1000;   // the clip opens here, on the settled floor (the recording began at t0 or a little later)
  await page.waitForTimeout(1200);
  await CLIPS[spec.clip](page, spec, where);
  const video = page.video();
  await ctx.close();
  const raw = await video.path();
  const out = join(work, `${name}.webm`);
  execFileSync(process.env.VIZ_FFMPEG ?? "ffmpeg", ["-y", "-loglevel", "error", "-ss", start.toFixed(2), "-i", raw,
    "-vf", "scale=960:-2,fps=15", "-an", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "42", "-row-mt", "1", "-deadline", "good", "-cpu-used", "2", out]);
  const webm = readFileSync(out);
  keep(`${name}.webm`, webm);
  return `data:video/webm;base64,${webm.toString("base64")}`;
}

const template = readFileSync(TEMPLATE, "utf8");
const specs = JSON.parse(template.match(PICTURES)[2]);
const digest = guideDigest();
/** The committed guide's clips, when it is fresh and --clips was not passed. */
const kept = (() => {
  if (process.argv.includes("--clips") || !existsSync(OUT)) return {};
  const old = readFileSync(OUT, "utf8");
  if (old.match(/<meta name="guide-inputs" content="([0-9a-f]*)">/)?.[1] !== digest) return {};
  return Object.fromEntries(Object.entries(JSON.parse(old.match(PICTURES)[2])).filter(([, p]) => p.clip));
})();
if (Object.entries(specs).some(([name, spec]) => spec.clip && !kept[name])) {   // fail fast, before the stills
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH ?? join(homedir(), ".cache", "ms-playwright");
  const found = existsSync(base) && readdirSync(base).some((d) => d.startsWith("ffmpeg-"));
  if (!found) { console.error(`Recording clips needs Playwright's own ffmpeg under ${base}/ffmpeg-*: run \`npx playwright install ffmpeg\``); process.exit(1); }
}
const work = mkdtempSync(join(tmpdir(), "guide-"));
const browser = await launch();
const errors = [], rendered = {};
try {
  for (const [name, spec] of Object.entries(specs)) {
    if (spec.clip && kept[name]) { rendered[name] = kept[name]; console.log(`kept ${name} (fresh guide; --clips records it again)`); continue; }
    if (spec.clip) rendered[name] = { clip: await clip(browser, spec, name, errors, work) };
    else {
      const shots = spec.shots ?? [spec];
      rendered[name] = { stills: [], ...(spec.stack ? { stack: true } : {}) };
      for (const [k, shot] of shots.entries()) rendered[name].stills.push(await still(browser, shot, shots.length > 1 ? `${name}-${k + 1}` : name, errors));
    }
    console.log(`rendered ${name}`);
  }
} finally {
  await browser.close();
  rmSync(work, { recursive: true, force: true });   // the raw recordings
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }

const font = `data:font/woff2;base64,${readFileSync(FONT).toString("base64")}`;
const html = template
  .replace(PICTURES, (_, a, __, c) => `${a}${JSON.stringify(rendered).replaceAll("<", "\\u003c")}${c}`)
  .replace('/*FONT*/', font)
  .replace('<meta name="guide-inputs" content="">', `<meta name="guide-inputs" content="${digest}">`);
writeFileSync(OUT, html);
console.log(`wrote docs/field-guide.html: ${(Buffer.byteLength(html) / 1024 / 1024).toFixed(2)} MB, ${Object.keys(rendered).length} pictures`);
