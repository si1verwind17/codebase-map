// Profiles the built viewer on a big map in Chromium: load, entering the busiest service, entering its busiest floor
// cold, frame cost and heap. Prints the median of each metric over the runs. Needs `npm run build` first.
//   VIZ_CHROMIUM=/usr/bin/chromium npm run profile -- [--map P] [--viewer P] [--runs 3] [--throttle 4] [--swiftshader]
//                                                     [--picker] [--json OUT] [--cpuprofile DIR]
// Without --map it profiles the synthetic map scripts/big_map.py writes to .profile/big.code-map.json (built when
// missing; VIZ_PYTHON picks the Python, default ../.venv/bin/python). The page is what view.py writes, with the map
// built in whatever its size (--picker opens it through the page's file input instead). GPU drawing by default, as
// VIZ_GPU=1 does for the browser tests; --swiftshader draws on the CPU. --throttle slows the CPU N times (CDP).
// --cpuprofile writes a .cpuprofile per step; scripts/profile-top.mjs lists where the time went.
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

const HERE = dirname(fileURLToPath(import.meta.url));
const VIEWER = resolve(HERE, "../../skills/visualizing-codebases/viewer/dist/viewer.html");
const SCRIPTS = resolve(HERE, "../../skills/visualizing-codebases/scripts");
const PROFILE_DIR = resolve(HERE, "../.profile");   // gitignored: the synthetic map and the page built from it
const BIG = resolve(PROFILE_DIR, "big.code-map.json");
const GPU_ARGS = ["--use-angle=vulkan", "--enable-features=Vulkan", "--ignore-gpu-blocklist"];   // as test/gl.ts
const CPU_ARGS = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"];
const WAIT = 600_000;   // a throttled settle on a big map takes tens of seconds

/** The metric keys, in the order the table prints them. */
export const KEYS = ["firstFrameMs", "parseMs", "enterService.longTaskSumMs", "enterService.longTaskMaxMs",
  "enterService.settleMs", "coldEntry.floorMs", "coldEntry.longestTaskMs", "frameJsMs.idle", "frameJsMs.pan",
  "heapMB.load", "heapMB.session", "heapMB.worker"];

/** Relations per floor with an end on it (the floor's container, or under it through parents or group members), as
 *  big_map.relations_inside counts them. */
export function relationsInside(map) {
  const parent = new Map(map.nodes.map((n) => [n.id, n.parent]));
  const groups = new Map();   // member -> the groups holding it
  for (const floor of Object.values(map.layout.containers))
    for (const g of floor.groups ?? []) for (const m of g.members) groups.set(m, [...(groups.get(m) ?? []), g.id]);
  const memo = new Map();
  const above = (x) => {
    if (!memo.has(x)) {
      const out = new Set([x, ...(groups.get(x) ?? [])]);
      for (const g of groups.get(x) ?? []) for (const y of above(g)) out.add(y);
      if (parent.get(x)) for (const y of above(parent.get(x))) out.add(y);
      memo.set(x, out);
    }
    return memo.get(x);
  };
  const counts = new Map(Object.keys(map.layout.containers).map((c) => [c, 0]));
  for (const r of map.relations)
    for (const c of new Set([...above(r.from), ...above(r.to)])) if (counts.has(c)) counts.set(c, counts.get(c) + 1);
  return counts;
}

/** What to enter: the site's busiest item, then its busiest floor (where a cold entry costs the most), each with the
 *  name the Find list shows for it. */
export function pickTargets(map) {
  const floors = map.layout.containers, inside = relationsInside(map);
  const busiest = (ids) => ids.filter((i) => floors[i]).sort((a, b) => inside.get(b) - inside.get(a) || (a < b ? 1 : -1))[0];
  const names = new Map(map.nodes.map((n) => [n.id, n.name]));
  for (const f of Object.values(floors)) for (const g of f.groups ?? []) names.set(g.id, g.label);
  const service = busiest(Object.keys(floors.site.items));
  const cold = busiest(Object.keys(floors[service].items));
  return { service, serviceLabel: names.get(service), cold, coldLabel: names.get(cold) };
}

/** Writes the page view.py would write for `map` (built in at any size, or none with `picker`); returns its path. */
function writePage(map, viewer, picker) {
  const out = resolve(PROFILE_DIR, "page.html");
  mkdirSync(PROFILE_DIR, { recursive: true });
  const py = `import sys; sys.path.insert(0, sys.argv[1]); import view
view.INLINE_LIMIT = -1 if sys.argv[5] == "picker" else float("inf")
page, _ = view.render(open(sys.argv[2], encoding="utf-8").read(), open(sys.argv[3], encoding="utf-8").read())
open(sys.argv[4], "w", encoding="utf-8").write(page)`;
  execFileSync(python(), ["-c", py, SCRIPTS, map, viewer, out, picker ? "picker" : "inline"], { stdio: "inherit" });
  return out;
}

function python() {
  return process.env.VIZ_PYTHON ?? resolve(HERE, "../../.venv/bin/python");
}

/** Installed before the page's own scripts: long tasks, the map's JSON.parse, the first drawn frame, frame counting. */
function instrument() {
  const P = { lt: [], marks: {} };
  window.__perf = P;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) P.lt.push([e.startTime, e.duration]); })
    .observe({ type: "longtask", buffered: true });
  const parse = JSON.parse;
  JSON.parse = function (s, ...r) {
    if (typeof s !== "string" || s.length < 1e5 || P.marks.parse) return parse.call(this, s, ...r);
    const t = performance.now(), v = parse.call(this, s, ...r);
    P.marks.parse = performance.now() - t;
    return v;
  };
  const mo = new MutationObserver(() => {
    const c = document.querySelector("canvas");
    if (c?.dataset.plans && !P.marks.shown) {
      P.marks.shown = performance.now();
      requestAnimationFrame(() => requestAnimationFrame(() => { P.marks.firstFrame = performance.now(); }));
      mo.disconnect();
    }
  });
  mo.observe(document, { subtree: true, childList: true, attributes: true });
  P.raf2 = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  P.longest = (t0, t1 = Infinity) => P.lt.filter(([s, d]) => s + d >= t0 && s <= t1).map(([, d]) => d);
  P.count = () => { const f = { n: 0, on: true }; const loop = () => { if (!f.on) return; f.n++; requestAnimationFrame(loop); }; requestAnimationFrame(loop); return f; };
}

const mid = (xs) => {
  const s = xs.filter((x) => x !== null && x !== undefined).sort((a, b) => a - b);
  if (!s.length) return null;
  return s.length % 2 ? s[s.length >> 1] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};
const T0 = Date.now();
const say = (what) => process.stderr.write(`  ${((Date.now() - T0) / 1000).toFixed(0).padStart(4)} s  ${what}\n`);   // progress: a run takes minutes
const round = (x, d = 1) => (x === null || x === undefined ? null : +x.toFixed(d));

/** Opens a fresh page on the map and waits until the first floor is drawn and its nearby floors are planned. */
async function open(browser, opts, path) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.addInitScript(instrument);
  const cdp = await context.newCDPSession(page);
  if (opts.throttle > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: opts.throttle });
  await cdp.send("Performance.enable");
  await cdp.send("HeapProfiler.enable");
  const workers = await watchWorkers(cdp);
  await page.goto(pathToFileURL(path).href);
  if (opts.picker) {
    await page.evaluate(() => { window.__perf.marks.start = performance.now(); });
    await page.setInputFiles('input[type="file"]', opts.map);
  }
  await page.waitForFunction(() => window.__perf.marks.firstFrame, null, { timeout: WAIT, polling: 50 });
  await settled(page);
  return { context, page, cdp, errors, workers };
}

/** Until no nearby floor waits to be planned. */
async function settled(page) {
  await page.waitForFunction(() => document.querySelector("canvas")?.dataset.plansQueued === "0", null, { timeout: WAIT, polling: 50 });
}

/** The camera is still and no floor change is under way (the viewer ignores presses during one; it disables the
 *  floor buttons meanwhile). */
async function idle(page) {
  await page.waitForFunction(() => document.querySelector("canvas")?.dataset.camera !== "moving"
    && !document.querySelector(".floors button[aria-current=page]")?.disabled, null, { timeout: WAIT, polling: 50 });
}

/** Selects the item named `label` on the current floor from the rail's floor list and at once presses the
 *  inspector's Open sub-assembly, as a double-click on it would (no idle moment between: a selected item's floor is
 *  the first the idle planner plans). Returns, from the press: when the canvas showed another floor, when the camera
 *  came to rest, and whether that floor's plan was ready (data-plan-hit). */
async function enter(page, label) {
  await idle(page);   // a floor change still under way would ignore the press, and clear the selection when it ends
  return page.evaluate(async ([label, wait]) => {
    // the list drops the prefix every item on the floor shares: the item's name, or the longest end of it, is shown
    const name = (b) => b.querySelector(".name")?.textContent.replace(/\u200b/g, "").trim() ?? "";
    const named = [...document.querySelectorAll("#rail-floor button.item")].filter((b) => name(b) && label.endsWith(name(b)));
    if (!named.length) throw new Error(`no item named ${label} on this floor`);
    named.sort((x, y) => name(y).length - name(x).length)[0].click();
    const open = () => [...document.querySelectorAll("button.open")].find((b) => b.textContent.includes("Open sub-assembly"));
    for (let i = 0; i < 50 && !open(); i++) await Promise.resolve();   // the inspector updates in a microtask
    const btn = open();
    if (!btn) throw new Error("no Open sub-assembly button");
    const c = document.querySelector("canvas"), from = c.dataset.floor;
    let floor = null, still = null;
    const t0 = performance.now();
    const done = new Promise((res, rej) => {
      const mo = new MutationObserver(() => {
        if (floor === null && c.dataset.floor !== from) floor = performance.now();
        if (floor !== null && c.dataset.camera === "idle") { still = performance.now(); mo.disconnect(); res(); }
      });
      mo.observe(c, { attributes: true });
      setTimeout(() => rej(new Error(`the floor did not change from ${from}`)), wait);
    });
    btn.click();
    await done;
    return { t0, floorMs: floor - t0, stillAt: still, planHit: c.dataset.planHit === "true", floor: c.dataset.floor };
  }, [label, WAIT]);
}

/** Script time per frame over `ms` of `act` (CDP ScriptDuration delta over the frames drawn). */
async function frameJs(page, cdp, ms, act) {
  const script = async () => (await cdp.send("Performance.getMetrics")).metrics.find((m) => m.name === "ScriptDuration").value;
  await page.evaluate(() => { window.__frames = window.__perf.count(); });
  const s0 = await script();
  await act(ms);
  const s1 = await script();
  const n = await page.evaluate(() => { window.__frames.on = false; return window.__frames.n; });
  return n ? ((s1 - s0) * 1000) / n : null;
}

async function heapMB(cdp) {
  await cdp.send("HeapProfiler.collectGarbage");
  return (await cdp.send("Runtime.getHeapUsage")).usedSize / 1e6;
}

/** Dedicated workers the page starts, attached through CDP (auto-attach) so their heap can be read. */
async function watchWorkers(cdp) {
  const sessions = [], pending = new Map();
  let next = 1;
  cdp.on("Target.attachedToTarget", (e) => { if (/worker/.test(e.targetInfo.type)) sessions.push(e.sessionId); });
  cdp.on("Target.detachedFromTarget", (e) => {   // a terminated worker: no heap to read, nor two timeouts to wait out
    const i = sessions.indexOf(e.sessionId);
    if (i >= 0) sessions.splice(i, 1);
  });
  cdp.on("Target.receivedMessageFromTarget", (e) => {
    const m = JSON.parse(e.message);
    pending.get(m.id)?.(m);
    pending.delete(m.id);
  });
  try {
    await cdp.send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: false });
  } catch {
    return { heapMB: async () => null };
  }
  const call = (sessionId, method) => new Promise((res) => {
    const id = next++;
    pending.set(id, res);
    setTimeout(() => { pending.delete(id); res(null); }, 5000);
    cdp.send("Target.sendMessageToTarget", { sessionId, message: JSON.stringify({ id, method }) }).catch(() => res(null));
  });
  return {
    async heapMB() {   // best effort: null without a worker or when it does not answer
      let sum = null;
      for (const s of sessions) {
        await call(s, "HeapProfiler.collectGarbage");
        const r = await call(s, "Runtime.getHeapUsage");
        if (r?.result?.usedSize !== undefined) sum = (sum ?? 0) + r.result.usedSize / 1e6;
      }
      return sum;
    },
  };
}

async function profiled(cdp, opts, name, fn) {
  if (!opts.cpuprofile) return fn();
  await cdp.send("Profiler.enable");
  await cdp.send("Profiler.setSamplingInterval", { interval: 200 });
  await cdp.send("Profiler.start");
  try {
    return await fn();
  } finally {
    const { profile } = await cdp.send("Profiler.stop");
    mkdirSync(opts.cpuprofile, { recursive: true });
    writeFileSync(resolve(opts.cpuprofile, `run${opts.run}-${name}.cpuprofile`), JSON.stringify(profile));
  }
}

/** One run: two fresh pages in one browser. The first loads, enters the service and waits for its nearby floors,
 *  then measures frames and heap; the second enters the service and, as soon as the camera rests, its busiest floor
 *  (before the idle planner reaches it, so its layout is cold). */
export async function runOnce(opts) {
  const res = { info: {} };
  const browser = await chromium.launch({
    executablePath: process.env.VIZ_CHROMIUM ?? "/usr/bin/chromium",
    args: opts.swiftshader ? CPU_ARGS : GPU_ARGS,
  });
  try {
    {
      const { context, page, cdp, errors, workers } = await open(browser, opts, opts.page);
      say(`run ${opts.run}: loaded`);
      const marks = await page.evaluate(() => window.__perf.marks);
      res.firstFrameMs = marks.firstFrame - (marks.start ?? 0);
      res.parseMs = marks.parse ?? null;
      res["heapMB.load"] = await heapMB(cdp);
      const e = await profiled(cdp, opts, "enterService", async () => {
        const e = await enter(page, opts.targets.serviceLabel);
        await settled(page);
        e.settledAt = await page.evaluate(() => performance.now());
        return e;
      });
      const lt = await page.evaluate(([a, b]) => window.__perf.longest(a, b), [e.t0, e.settledAt]);
      res["enterService.longTaskSumMs"] = lt.reduce((a, b) => a + b, 0);
      res["enterService.longTaskMaxMs"] = lt.length ? Math.max(...lt) : 0;
      res["enterService.settleMs"] = e.settledAt - e.t0;
      say(`run ${opts.run}: entered the service; its nearby floors planned`);
      res.info.service = e.floor;
      res.info.plans = Number(await page.locator("canvas").getAttribute("data-plans"));
      const box = await page.locator("canvas").boundingBox();
      const empty = { x: box.x + 14, y: box.y + box.height - 14 };
      await page.mouse.move(empty.x, empty.y);
      await page.waitForTimeout(800);   // past the floor's wheel-quiet time
      res["frameJsMs.idle"] = await profiled(cdp, opts, "idle", () => frameJs(page, cdp, 2000, (ms) => page.waitForTimeout(ms)));
      res["frameJsMs.pan"] = await profiled(cdp, opts, "pan", () => frameJs(page, cdp, 3000, async (ms) => {
        await page.mouse.down();
        const t0 = Date.now();
        for (let i = 0; Date.now() - t0 < ms; i++) {
          await page.mouse.move(empty.x + 200 + 150 * Math.cos(i / 20), empty.y - 250 + 120 * Math.sin(i / 20));
          await page.waitForTimeout(16);
        }
        await page.mouse.up();
      }));
      say(`run ${opts.run}: frames measured`);
      res["heapMB.session"] = await heapMB(cdp);
      res["heapMB.worker"] = await workers.heapMB();
      res.info.errors = errors;
      await context.close();
    }
    {
      const { context, page, cdp, errors } = await open(browser, opts, opts.page);
      say(`run ${opts.run}: loaded again`);
      await enter(page, opts.targets.serviceLabel);
      const c = await profiled(cdp, opts, "coldEntry", () => enter(page, opts.targets.coldLabel));
      const lt = await page.evaluate(([a, b]) => window.__perf.longest(a, b), [c.t0, c.stillAt]);
      res["coldEntry.floorMs"] = c.floorMs;
      res["coldEntry.longestTaskMs"] = lt.length ? Math.max(...lt) : 0;
      res.info.cold = c.floor;
      say(`run ${opts.run}: entered the busiest floor`);
      res.info.coldWasPlanned = c.planHit;   // true: the idle planner got there first, so this entry was not cold
      res.info.errors.push(...errors);
      await context.close();
    }
  } finally {
    await browser.close();
  }
  return res;
}

/** The median of each metric over the runs (null when no run measured it). */
export function median(results) {
  const out = {};
  for (const k of KEYS) out[k] = round(mid(results.map((r) => r[k])));
  return out;
}

export function printTable(summary, results = []) {
  const w = Math.max(...KEYS.map((k) => k.length));
  console.log(`${"metric".padEnd(w)}  median${results.length > 1 ? "     runs" : ""}`);
  for (const k of KEYS) {
    const runs = results.length > 1 ? "  " + results.map((r) => (r[k] === null ? "—" : round(r[k]))).join(" / ") : "";
    console.log(`${k.padEnd(w)}  ${String(summary[k] ?? "—").padStart(6)}${runs}`);
  }
}

function parseArgs(argv) {
  const opts = { map: null, viewer: VIEWER, runs: 1, throttle: 1, swiftshader: false, picker: false, json: null, cpuprofile: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], v = () => argv[++i];
    if (a === "--map") opts.map = resolve(v());
    else if (a === "--viewer") opts.viewer = resolve(v());
    else if (a === "--runs") opts.runs = Number(v());
    else if (a === "--throttle") opts.throttle = Number(v());
    else if (a === "--swiftshader") opts.swiftshader = true;
    else if (a === "--picker") opts.picker = true;
    else if (a === "--json") opts.json = resolve(v());
    else if (a === "--cpuprofile") opts.cpuprofile = resolve(v());
    else throw new Error(`unknown argument ${a}`);
  }
  return opts;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.map) {
    opts.map = BIG;
    if (!existsSync(BIG)) execFileSync(python(), [resolve(HERE, "big_map.py"), "--out", BIG], { stdio: "inherit" });
  }
  const map = JSON.parse(readFileSync(opts.map, "utf8"));
  opts.targets = pickTargets(map);
  opts.page = writePage(opts.map, opts.viewer, opts.picker);
  console.log(`map ${opts.map}: ${map.nodes.length} nodes, ${map.relations.length} relations; service "${opts.targets.serviceLabel}", cold floor "${opts.targets.coldLabel}"`);
  console.log(`${opts.swiftshader ? "SwiftShader" : "GPU"}, CPU throttle ${opts.throttle}×, ${opts.picker ? "opened through the file input" : "map built in"}`);
  const results = [];
  for (let run = 1; run <= opts.runs; run++) {
    const r = await runOnce({ ...opts, run });
    if (r.info.coldWasPlanned) console.warn(`run ${run}: the cold floor was already planned; its entry was not cold`);
    if (r.info.errors.length) console.warn(`run ${run}: page errors:\n  ${r.info.errors.join("\n  ")}`);
    results.push(r);
  }
  const summary = median(results);
  printTable(summary, results);
  if (opts.json) {
    mkdirSync(dirname(opts.json), { recursive: true });
    writeFileSync(opts.json, JSON.stringify({ opts: { ...opts, targets: opts.targets }, summary, results }, null, 1));
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main();
