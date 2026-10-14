// Screenshot the built viewer with a map inlined (visual checks; not part of the test suite):
//   [REDUCED=1] VIZ_CHROMIUM=/usr/bin/chromium node scripts/shot.mjs <code-map.json> <out-prefix> [click=Text | dbl=x,y | hover=x,y | key=ArrowRight | find=text | wheel=x,y,dy[,n] | wait=ms ...]
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";
const [mapPath, prefix, ...actions] = process.argv.slice(2);
const html = readFileSync(new URL("../dist/viewer.html", import.meta.url), "utf8").replace("/*CODE_MAP*/", readFileSync(mapPath, "utf8").replaceAll("<", "\\u003c"));
const pagePath = new URL(`../.shot-page.html`, import.meta.url);
writeFileSync(pagePath, html);
const browser = await chromium.launch({ executablePath: process.env.VIZ_CHROMIUM ?? "/usr/bin/chromium", args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"] });
const errors = [];
const sizes = (process.env.SIZES ?? "1440x900:desktop").split(",").map((s) => { const [wh, tag] = s.split(":"); const [w, h] = wh.split("x").map(Number); return [w, h, tag]; });
for (const [w, h, tag] of sizes) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1, reducedMotion: process.env.REDUCED ? "reduce" : "no-preference" });
  page.on("pageerror", (e) => errors.push(`${tag}: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${tag} console: ${m.text()}`); });
  await page.goto(pagePath.href);
  await page.waitForTimeout(1500);
  for (const a of actions) {
    const [verb, ...rest] = a.split("=");
    const arg = rest.join("=");
    if (verb === "click") await page.getByText(arg, { exact: false }).first().click();
    if (verb === "role") { const [role, name] = arg.split(":"); await page.getByRole(role, { name }).first().click(); }
    if (verb === "dbl") { const [x, y] = arg.split(",").map(Number); await page.mouse.dblclick(x, y); }
    if (verb === "hover") { const [x, y] = arg.split(",").map(Number); await page.mouse.move(x, y); }
    if (verb === "tap") { const [x, y] = arg.split(",").map(Number); await page.mouse.click(x, y); }
    if (verb === "key") await page.keyboard.press(arg);
    if (verb === "find") await page.getByRole("searchbox").fill(arg);
    if (verb === "wait") await page.waitForTimeout(Number(arg));
    if (verb === "wheel") {   // zoom about (x, y): n wheel steps of dy each (negative dy zooms in)
      const [x, y, dy, n = 1] = arg.split(",").map(Number);
      await page.mouse.move(x, y);
      for (let i = 0; i < n; i++) { await page.mouse.wheel(0, dy); await page.waitForTimeout(60); }
    }
  }
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${prefix}-${tag}.png`, fullPage: tag === "mobile" });
  await page.close();
}
await browser.close();
console.log(errors.length ? errors.join("\n") : "no page errors");
