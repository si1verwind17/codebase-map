// The audit runner (`auditMap`) and its plain-Node build (dist/audit.mjs): every known map reports no map limit beyond
// the known ones, the budget skips the floors it does not reach (the same ones on every run), a floor whose plan
// throws is one `plan.crashed`, and the built file is fresh, free of Pixi and the DOM, and prints one line of JSON under plain `node`.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { auditMap, FLOOR_COST, type AuditReport } from "../../src/audit/run";
import type { CodeMap } from "../../src/model/types";
import { Model, SITE } from "../../src/model/model";
import { auditDigest } from "../../scripts/audit-inputs.mjs";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const SHOP = new URL("../fixtures/shop.code-map.json", import.meta.url);
const GUIDE = new URL("../../guide/maps/", import.meta.url);
const AUDIT = new URL("../../../skills/visualizing-codebases/viewer/dist/audit.mjs", import.meta.url);
const BIG = process.env.VIZ_BIG_MAP ?? "";
const BIG_KNOWN = `${BIG}.known.json`;
const read = (u: URL | string) => JSON.parse(readFileSync(u, "utf8")) as CodeMap;

/** Map limits already found on the known maps, all accepted by the owner (2026-10-11; the demo's are in its
 *  map-notes.md): check, floor code, and a piece of the detail. Every other failure fails the test. The large real
 *  map's list is local, like the map: `$VIZ_BIG_MAP.known.json`, a JSON array of the same entries (none when
 *  the file is missing). */
const KNOWN: Record<string, { check: string; code: string; detail: string }[]> = {
  demo: [],
};

// no `.known.json` next to the large map: no known limits, and the test still runs
if (BIG && existsSync(BIG)) KNOWN.big = existsSync(BIG_KNOWN) ? JSON.parse(readFileSync(BIG_KNOWN, "utf8")) : [];

/** Failed checks that are map limits: an advisory (`flights.hidden`, a known look) is not one. */
const failures = (r: AuditReport) => r.results.filter((x) => !x.ok && !x.advisory);
const unknown = (name: string, r: AuditReport) => failures(r)
  .filter((f) => !(KNOWN[name] ?? []).some((k) => k.check === f.check && k.code === f.code && f.detail.includes(k.detail)))
  .map((f) => `${f.check} @ ${f.code} (${f.floor}): ${f.detail}`);

/** KNOWN entries the report no longer shows: fixed, so drop them. */
const stale = (name: string, r: AuditReport) => KNOWN[name]
  .filter((k) => !failures(r).some((f) => f.check === k.check && f.code === k.code && f.detail.includes(k.detail)))
  .map((k) => `${k.check} @ ${k.code}: ${k.detail}`);

const known: [string, () => CodeMap][] = [["demo", () => read(DEMO)], ["shop", () => read(SHOP)],
  ...readdirSync(GUIDE).filter((f) => f.endsWith(".code-map.json")).sort()
    .map((f): [string, () => CodeMap] => [`guide ${f}`, () => read(new URL(f, GUIDE))])];

describe("auditMap on the known maps", () => {
  for (const [name, load] of known) it(`${name}: every check passes but the known map limits`, () => {
    const r = auditMap(load());
    expect(r.skipped).toEqual([]);
    expect(r.checked.length).toBeGreaterThan(0);
    expect(unknown(name, r)).toEqual([]);
  });

  it("the demo's known map limits are still there (drop an entry once it is fixed)", () => {
    expect(stale("demo", auditMap(read(DEMO)))).toEqual([]);
  });

  it.skipIf(!KNOWN.big)("the large real map (VIZ_BIG_MAP): every check passes but the known map limits", () => {
    const r = auditMap(read(BIG), Infinity);
    expect(r.skipped).toEqual([]);
    expect(unknown("big", r)).toEqual([]);
    expect(stale("big", r)).toEqual([]);
  }, 600_000);

  it("one result per check per floor, with the floor's code and audit row; `at` is a plain {x, y}", () => {
    const r = auditMap(read(DEMO));
    expect(r.checked[0]).toBe(SITE);
    const site = r.results.filter((x) => x.floor === SITE);
    expect(site.map((x) => x.check)).toEqual(["lines.failed", "lines.plugged", "lines.trunks", "lines.under",
      "lines.mid-side", "lines.plate-wall", "lines.lane-drop", "lines.gap-stub", "lines.lane-gap", "text.cut", "text.over-line", "zone.narrow", "pads.corridor", "travel.long",
      "flights.overlap", "flights.in-line", "flights.hidden", "lost.relation", "floor.wide"]);
    expect(site.find((x) => x.check === "text.over-line")).toMatchObject({ code: "site", row: "7, 8, 45", ok: true });
    for (const x of r.results) if (x.at) expect(Object.keys(x.at).sort()).toEqual(["x", "y"]);
    expect(Object.keys(r.measured)).toContain("site");
    expect(Object.keys(r.measured.site).sort()).toEqual(["congestion", "fitZoom", "spacing", "switchZoom"]);
  });

  it("flights.in-line and flights.hidden are advisories, on every result of them; flights.hidden fires on the push and pull page's site (orders' produce path under billing), flights.overlap on no known map", () => {
    for (const [, load] of known) {
      const r = auditMap(load());
      for (const x of r.results) expect(x.advisory, x.check).toBe(x.check === "flights.hidden" || x.check === "flights.in-line" ? true : undefined);
      expect(r.results.filter((x) => x.check === "flights.overlap" && !x.ok)).toEqual([]);
    }
    const r = auditMap(read(new URL("push_pull.code-map.json", GUIDE)));
    const hidden = r.results.find((x) => x.check === "flights.hidden" && x.floor === SITE)!;
    expect(hidden).toMatchObject({ ok: false, advisory: true, row: "—" });
    expect(hidden.detail).toMatch(/^produce svc:orders\|topic:events:order-events passes under svc:billing for \d+ px/);
  });

  it("floors run site first, then by box count, most first", () => {
    const map = read(SHOP);
    const r = auditMap(map);
    const size = (c: string) => Object.keys(map.layout.containers[c].items ?? {}).length;
    expect(r.checked[0]).toBe(SITE);
    const rest = r.checked.slice(1).map(size);
    expect(rest).toEqual([...rest].sort((a, b) => b - a));
    expect(r.checked.length).toBe(Object.keys(map.layout.containers).length);
  });
});

describe("auditMap's budget and crashes", () => {
  it("a budget the site uses up skips every later floor, the same ones on every run", () => {
    const map = read(SHOP);
    const siteCost = Object.keys(map.layout.containers[SITE].items ?? {}).length + FLOOR_COST;
    const r = auditMap(map, siteCost);
    expect(auditMap(map, siteCost)).toEqual(r);
    expect(r.checked).toEqual([SITE]);
    expect(r.skipped.length).toBe(Object.keys(map.layout.containers).length - 1);
    expect(r.results.every((x) => x.floor === SITE)).toBe(true);
    // the skipped floors also by code, in the same order, for audit.md's "Not checked"
    const model = new Model(map);
    expect(r.skippedCodes).toEqual(r.skipped.map((c) => model.codes.get(c) ?? c));
    expect(r.skippedCodes).toContain(model.codes.get("svc:worker"));
  });

  it("a floor whose plan throws is one plan.crashed result; the other floors are still checked", () => {
    const map = read(SHOP);
    // (an item id that is not a node is planned around; an item in a region the layout does not know throws)
    map.layout.containers["svc:worker"].items = { "worker::worker/": { region: "no-such-region", col: 0, row: 0 } } as never;
    const r = auditMap(map);
    const worker = r.results.filter((x) => x.floor === "svc:worker");
    expect(worker).toHaveLength(1);
    expect(worker[0]).toMatchObject({ check: "plan.crashed", ok: false, row: "—" });
    expect(worker[0].detail).not.toContain("\n");
    expect(worker[0].detail.length).toBeGreaterThan(0);
    expect(r.results.filter((x) => x.floor === SITE)).toHaveLength(19);
    // every floor was planned: none skipped, and a non-empty floor ordered after the crashed one has all 19 results
    expect(r.skipped).toEqual([]);
    expect(r.checked).toHaveLength(Object.keys(map.layout.containers).length - r.skipped.length);
    const after = r.checked.slice(r.checked.indexOf("svc:worker") + 1).filter((c) => Object.keys(map.layout.containers[c].items ?? {}).length);
    expect(after.length).toBeGreaterThan(0);
    for (const c of after) expect(r.results.filter((x) => x.floor === c), c).toHaveLength(19);
  });

  it("an empty floor is checked with no results", () => {
    const map = read(SHOP);
    map.layout.containers["svc:worker"].items = {};
    const r = auditMap(map);
    expect(r.checked).toContain("svc:worker");
    expect(r.results.filter((x) => x.floor === "svc:worker")).toEqual([]);
  });
});

describe("dist/audit.mjs", () => {
  const src = () => readFileSync(AUDIT, "utf8");

  it("is fresh against src/", () => {
    const stamped = src().match(/^\/\/ audit-inputs: ([0-9a-f]+)$/m)?.[1];
    expect(stamped, "dist/audit.mjs is stale — run `npm run build`").toBe(auditDigest());
  });

  it("holds no Pixi and no DOM, and is under 1 MB", () => {
    expect(src()).not.toMatch(/pixi/i);
    expect(src()).not.toContain("document.");
    expect(statSync(AUDIT).size).toBeLessThan(1024 * 1024);
  });

  it("runs under plain node on the demo map: one line of JSON, no failure but the known ones", () => {
    const out = execFileSync(process.execPath, [fileURLToPath(AUDIT), fileURLToPath(DEMO)], { encoding: "utf8" });
    expect(out.trimEnd().split("\n")).toHaveLength(1);
    const r = JSON.parse(out) as AuditReport;
    expect(r.checked.length).toBeGreaterThan(0);
    expect(unknown("demo", r)).toEqual([]);
  });

  it("exits 2 with a stderr line on an unreadable map", () => {
    let err: { status?: number; stderr?: string } = {};
    try { execFileSync(process.execPath, [fileURLToPath(AUDIT), "/nonexistent/code-map.json"], { encoding: "utf8", stdio: "pipe" }); }
    catch (e) { err = e as typeof err; }
    expect(err.status).toBe(2);
    expect(err.stderr!.trim().split("\n")).toHaveLength(1);
  });
});
