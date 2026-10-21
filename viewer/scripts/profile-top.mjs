// Where the time went in a .cpuprofile (from `npm run profile -- --cpuprofile DIR`): the functions with the most self
// time and the most total time.
//   node scripts/profile-top.mjs <file.cpuprofile> [--top 25] [--viewer P]
// --viewer: the viewer page the profile was taken on, built with source maps, so each function is named by its source
// file and line instead of a place in the one-line bundle:
//   npx vite build --sourcemap --minify false --outDir /tmp/viewer-debug
//   npm run profile -- --viewer /tmp/viewer-debug/index.html --cpuprofile /tmp/prof
//   node scripts/profile-top.mjs /tmp/prof/run1-coldEntry.cpuprofile --viewer /tmp/viewer-debug/index.html
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";

const args = process.argv.slice(2);
const opt = (name, fallback) => { const i = args.indexOf(name); return i < 0 ? fallback : args.splice(i, 2)[1]; };
const TOP = Number(opt("--top", 25));
const viewer = opt("--viewer", null);
const file = args[0];
if (!file) { console.error("usage: profile-top.mjs <file.cpuprofile> [--top N] [--viewer P]"); process.exit(2); }

/** Maps a page position to its source, when the page's source map is at hand. The page inlines the bundle in its
 *  module script (in <head>, before the map's own script, so the map does not shift its lines). */
async function sourcePlaces(viewer) {
  if (!viewer) return null;
  const { SourceMapConsumer } = await import("source-map-js");   // vite's own dependency
  const files = (d) => readdirSync(d, { recursive: true }).map((f) => join(d, f));
  const mapFile = files(dirname(viewer)).find((f) => f.endsWith(".js.map"));
  if (!mapFile) throw new Error(`no .js.map beside ${viewer}: build it with --sourcemap`);
  const smc = new SourceMapConsumer(JSON.parse(readFileSync(mapFile, "utf8")));
  const html = readFileSync(viewer, "utf8").split("\n");
  const line0 = html.findIndex((l) => l.includes('<script type="module"'));
  const col0 = html[line0].indexOf(">", html[line0].indexOf('<script type="module"')) + 1;
  return (cf) => {
    const line = cf.lineNumber - line0, col = line === 0 ? cf.columnNumber - col0 : cf.columnNumber;
    if (line < 0) return "page";
    const o = smc.originalPositionFor({ line: line + 1, column: col });
    if (!o.source) return `bundle:${line + 1}`;
    return `${o.source.replace(/^.*?(viewer\/src\/|node_modules\/)/, (_, g) => (g === "node_modules/" ? "npm:" : ""))}:${o.line}`;
  };
}

const place = await sourcePlaces(viewer);
const where = (cf) => {
  if (!cf.url) return "(native)";
  if (place && cf.url.endsWith(".html")) return place(cf);
  return `${cf.url.split("/").pop()}:${cf.lineNumber + 1}`;
};

const prof = JSON.parse(readFileSync(file, "utf8"));
const byId = new Map(prof.nodes.map((n) => [n.id, n]));
const parent = new Map();
for (const n of prof.nodes) for (const c of n.children ?? []) parent.set(c, n.id);
const keyOf = (n) => `${n.callFrame.functionName || "(anon)"} @ ${where(n.callFrame)}`;

const self = new Map(), total = new Map();
let span = 0, idle = 0;
for (let i = 0; i < prof.samples.length; i++) {
  const ms = (prof.timeDeltas[i + 1] ?? 0) / 1000;   // a sample lasts until the next one
  let id = prof.samples[i];
  const leaf = byId.get(id);
  span += ms;
  if (leaf.callFrame.functionName === "(idle)") idle += ms;
  self.set(keyOf(leaf), (self.get(keyOf(leaf)) ?? 0) + ms);
  const seen = new Set();   // a recursive function counts once per sample
  for (; id !== undefined; id = parent.get(id)) {
    const k = keyOf(byId.get(id));
    if (!seen.has(k)) { seen.add(k); total.set(k, (total.get(k) ?? 0) + ms); }
  }
}
const of = (name) => self.get(`${name} @ (native)`) ?? 0;
const top = (m) => [...m.entries()].filter(([k]) => !/^\((idle|root|program|garbage collector)\)/.test(k))
  .sort((a, b) => b[1] - a[1]).slice(0, TOP).map(([k, v]) => `${v.toFixed(1).padStart(8)} ms  ${k}`).join("\n");
console.log(`# ${file.split("/").pop()}: span ${span.toFixed(0)} ms, idle ${idle.toFixed(0)} ms, busy ${(span - idle).toFixed(0)} ms, gc ${of("(garbage collector)").toFixed(0)} ms, program ${of("(program)").toFixed(0)} ms`);
console.log(`## self\n${top(self)}`);
console.log(`## total\n${top(total)}`);
