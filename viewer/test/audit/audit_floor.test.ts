// The floor checks the map audit runs (pads on corridor tiles, long trips, relations lost from the floor) and the
// numbers it only measures (congestion, spacing, Fit zoom against the names/codes switch). Pure functions.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import type { TileRoute } from "../../src/factory/router";
import { T } from "../../src/factory/tiles";
import { fitZoom } from "../../src/floor/fitscale";
import { codeZoom } from "../../src/factory/fit";
import { lostViolations, measure, padCorridorViolations, travelViolations } from "../../src/audit/floor";
import shop from "../fixtures/shop.code-map.json";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const DAGS = "jobs/dags::dags/";
const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
const shopM = new Model(shop as unknown as CodeMap);
const plan = (m: Model, c: string) => { const b = m.bundles(c); return planFloor(m, c, b.doors, b.bundles, b.layered); };
const floors = [
  { name: "the demo's site", m: demo, c: SITE, p: plan(demo, SITE) },
  { name: "the demo's dags", m: demo, c: DAGS, p: plan(demo, DAGS) },
  { name: "the shop's site", m: shopM, c: SITE, p: plan(shopM, SITE) },
];
const [site, dags, shopSite] = floors;
const inBox = (p: FloorPlan, x: number, y: number) => [...p.tf.boxes.values()].some((b) => x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h);

describe("floor checks return violations", () => {
  for (const { name, m, c, p } of floors) it(`${name} floor: no pad on a corridor tile, no relation lost`, () => {
    expect(padCorridorViolations(p)).toEqual([]);
    expect(lostViolations(m, c, p)).toEqual([]);
  });

  it("padCorridorViolations: a pad moved into a corridor is reported at its tile", () => {
    const p = site.p, pad = p.tf.landing!.pads[0], box = p.tf.boxes.get(pad.machine)!;
    const x = box.x - 1, y = box.y;
    expect(inBox(p, x, y)).toBe(false);
    const q: FloorPlan = { ...p, tf: { ...p.tf, landing: { ...p.tf.landing!, pads: [{ ...pad, x, y }, ...p.tf.landing!.pads.slice(1)] } } };
    const v = padCorridorViolations(q);
    expect(v).toEqual([{ detail: `${pad.role} pad of ${pad.machine} (${pad.topic}) on a corridor tile`, at: { x, y } }]);
  });

  // Only trains and drones are timed (row 25: drones crawling along long flight paths). Belts, pipes and taps run at a
  // steady 60 px/s by design (lane.ts `moverSpeed`), so their trip grows with the line and is not checked.
  for (const { name, p } of floors) it(`${name} floor: no train takes over 3 s, no drone over 5 s`, () => {
    expect(travelViolations(p)).toEqual([]);
  });

  it("travelViolations: a belt longer than 8 tiles is not flagged (belts run at a steady speed by design)", () => {
    const p = site.p, belt = p.routes.find((r) => r.kind === "belt" && r.pieces.length > 8)!;
    expect(belt.pieces.length * T / 60).toBeGreaterThan(3);   // over 3 s at the belts' 60 px/s
    const long: TileRoute = { ...belt, pieces: Array.from({ length: 40 }, () => ({ ...belt.pieces[0] })) };
    expect(travelViolations({ ...p, routes: p.routes.map((r) => (r === belt ? long : r)) })).toEqual([]);
  });

  // The viewer's trains cross their rail in at most 3 s, and a floor's drones its longest flight in 5 s (`moverSpeed`
  // scales with that length), so a lengthened rail or flight fails only at a speed that does not scale: the tests pass
  // one (a steady 60 px/s), as text.ts's tests pass other fitting functions.
  const steady = () => 60;
  it("travelViolations: a rail lengthened past 3 s is reported at a steady speed, at its first piece; the viewer's train speed keeps it within 3 s", () => {
    const p = shopSite.p, rail = p.routes.find((r) => r.kind === "rail")!;
    const long: TileRoute = { ...rail, pieces: Array.from({ length: 8 }, () => ({ ...rail.pieces[0] })) };
    const q = { ...p, routes: p.routes.map((r) => (r === rail ? long : r)) };
    expect(travelViolations(q, steady)).toContainEqual({ detail: `rail ${rail.key} takes 3.2 s (8 tiles)`, at: { x: rail.pieces[0].x, y: rail.pieces[0].y } });
    const longer: TileRoute = { ...rail, pieces: Array.from({ length: 80 }, () => ({ ...rail.pieces[0] })) };
    expect(travelViolations({ ...p, routes: p.routes.map((r) => (r === rail ? longer : r)) })).toEqual([]);
  });

  it("travelViolations: a trip a rounding error over 3 s is not reported (TRIP_MAX + 1e-6)", () => {
    const p = shopSite.p, rail = p.routes.find((r) => r.kind === "rail")!;
    const near = (_k: string, len: number) => (len / 3) * (1 - 1e-12);   // 3.000000000003 s
    expect(travelViolations({ ...p, routes: [rail] }, near).filter((v) => v.detail.startsWith("rail "))).toEqual([]);
  });

  it("travelViolations: a flight longer than 180 px is reported at a steady speed, never at the viewer's drone speed", () => {
    const v = travelViolations(site.p, steady);
    expect(v.some((x) => / flight .* takes \d+\.\d s \(\d+ px\)$/.test(x.detail))).toBe(true);
    expect(v.every((x) => Number.isInteger(x.at!.x) && Number.isInteger(x.at!.y))).toBe(true);
  });

  it("travelViolations: a rail in a layer is checked in its layer view", () => {
    const p = dags.p, [id, l] = Object.entries(p.layers!)[0];
    const r = l!.routes.find((x) => x.pieces.length > 0)!;
    const long: TileRoute = { ...r, kind: "rail", pieces: Array.from({ length: 20 }, () => ({ ...r.pieces[0] })) };
    const q: FloorPlan = { ...p, layers: { [id]: { routes: l!.routes.map((x) => (x === r ? long : x)) } } };
    expect(travelViolations(q, steady).map((v) => v.detail)).toContain(`rail ${r.key} takes 8.0 s (20 tiles) (layer ${id})`);
  });

  it("lostViolations: a bundle whose key is removed from the plan's routes is lost", () => {
    const p = site.p, gone = p.routes.find((r) => r.kind === "belt")!;
    const v = lostViolations(demo, SITE, { ...p, routes: p.routes.filter((r) => r !== gone) });
    expect(v).toHaveLength(1);
    const kind = demo.bundles(SITE).bundles.find((b) => b.key === gone.key)!.kind;
    expect(v[0].detail).toBe(`relation ${gone.key} (${kind}) is in neither the base nor a layer`);
  });

  it("lostViolations: a layer line removed from its layer is lost; an event carried by flights is not", () => {
    const p = dags.p, [id, l] = Object.entries(p.layers!)[0];
    const gone = l!.routes[0];
    const v = lostViolations(demo, DAGS, { ...p, layers: { [id]: { routes: l!.routes.slice(1) } } });
    expect(v.map((x) => x.detail)).toEqual([expect.stringMatching(new RegExp(`^relation ${gone.key.replace(/[|.*+?^${}()[\]\\]/g, "\\$&")} \\(.*\\) is in neither the base nor a layer \\(layer ${id}\\)$`))]);
    // the site's events fly: their drone routes may go, the flights still carry them
    const s = site.p, drones = s.routes.filter((r) => r.kind === "drone");
    expect(drones.length).toBeGreaterThan(0);
    expect(lostViolations(demo, SITE, { ...s, routes: s.routes.filter((r) => r.kind !== "drone") })).toEqual([]);
  });
});

describe("floor measures", () => {
  for (const { name, m, c, p } of floors) it(`${name} floor: finite numbers, congestion and area in [0, 1]`, () => {
    const x = measure(p, m, c);
    for (const n of [x.congestion, x.spacing.area, x.spacing.spread, x.fitZoom, x.switchZoom]) expect(Number.isFinite(n)).toBe(true);
    for (const n of [x.congestion, x.spacing.area]) { expect(n).toBeGreaterThanOrEqual(0); expect(n).toBeLessThanOrEqual(1); }
    expect(x.spacing.spread).toBeGreaterThanOrEqual(0);
    expect(x.fitZoom).toBe(fitZoom(p.tf.cols * T, p.tf.rows * T, 1440, 900, c === SITE));
  });

  it("the demo's site: Fit at 1440x900 against the switch of its smallest name (a hub's, 10 px)", () => {
    const x = measure(site.p, demo, SITE);
    expect(x.switchZoom).toBe(codeZoom(10));
    expect(x.fitZoom).toBeLessThan(x.switchZoom);   // Fit shows codes (factory_plan.test.ts reads the same at 1100x800)
  });

  it("congestion counts each above-ground line tile once, against the tiles outside every box", () => {
    const p = shopSite.p, x = measure(p, shopM, SITE);
    const keys = new Set(p.routes.flatMap((r) => r.pieces.filter((q) => !q.under && !inBox(p, q.x, q.y)).map((q) => `${q.x},${q.y}`)));
    let free = 0;
    for (let y = 0; y < p.tf.rows; y++) for (let xx = 0; xx < p.tf.cols; xx++) if (!inBox(p, xx, y)) free++;
    expect(x.congestion).toBeCloseTo(keys.size / free, 12);
  });
});
