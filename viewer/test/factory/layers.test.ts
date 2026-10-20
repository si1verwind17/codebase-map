// Layers (spec §15): a heavily used item's lines do not fit a floor's base layer: they go into that item's extra layer;
// the base layer and its plan stay exactly as before, and each layer's lines route over the base after it.
import { existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { floorLayers, floorLineCount, peekKeys, type LayerBundle } from "../../src/model/layers";
import { defaultLit } from "../../src/floor/lit";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import { Clearance, badgeBox, badgeSize, labelBox, layerTileRects, placeBadges, planZoneLabel, type PxRect } from "../../src/factory/clear";
import { railLabels } from "../../src/factory/rail-place";
import { coveredKeys, flightPaths, messagingObstacles } from "../../src/factory/flights";
import { T } from "../../src/factory/tiles";
import { checkTrunks, plugged } from "./factory_trunks";
import shop from "../fixtures/shop.code-map.json";

const BIG = process.env.VIZ_BIG_MAP ?? "";
const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
const DAGS = "jobs/dags::dags/", COMMON = "jobs/dags::dags._common";

const flat = (_k: string, v: unknown) => (v instanceof Map ? [...v.entries()] : v instanceof Set ? [...v] : v);
/** A plan's base, whole: everything but the layers. */
const baseOf = ({ layers: _l, ...p }: FloorPlan) => JSON.stringify([p.gap, { ...p.tf, boxes: [...p.tf.boxes.values()] }, p.routes, p.landing], flat);
/** Every floor's base plan with the layer pass and without it: the same digest (and each floor the same, in `expect`). */
function baseDigest(m: Model) {
  const h = createHash("sha256");
  for (const c of Object.keys(m.map.layout.containers)) {
    const b = m.bundles(c);
    const plain = planFloor(m, c, b.doors, b.bundles), layered = planFloor(m, c, b.doors, b.bundles, b.layered);
    expect(plain.layers, c).toBeUndefined();
    expect(baseOf(layered), c).toBe(baseOf(plain));
    h.update(baseOf(plain));
  }
  return h.digest("hex").slice(0, 16);
}

/** A layer's lines: exactly its bundles (no base line, no stand-in rail), plugged into their ends, the trunk rules against
 *  their own set, never on top of a base line's tile. */
function checkLayer(p: FloorPlan, layered: LayerBundle[], label: string) {
  const top = new Set(p.routes.flatMap((r) => r.pieces.filter((q) => !q.under).map((q) => `${q.x},${q.y}`)));
  expect(Object.keys(p.layers ?? {}).sort(), label).toEqual([...new Set(layered.map((b) => b.layer))].sort());
  for (const [id, l] of Object.entries(p.layers ?? {})) {
    expect(l!.routes.map((r) => r.key).sort(), `${label} ${id}`).toEqual(layered.filter((b) => b.layer === id).map((b) => b.key).sort());
    checkTrunks(p.tf, l!.routes, `${label} ${id}`);
    for (const r of l!.routes) {
      expect(r.kind, `${label} ${id} ${r.key}`).not.toBe("rail");
      if (r.pieces.length) plugged(p.tf, r);
      for (const q of r.pieces) if (!q.under) expect(top.has(`${q.x},${q.y}`), `${label} ${id} ${r.key} on a base tile ${q.x},${q.y}`).toBe(false);
    }
  }
}

/** Every layered floor of a map: its layers checked (`checkLayer`), at most one failed line in each. */
function checkAllLayers(m: Model) {
  let floors = 0;
  for (const c of Object.keys(m.map.layout.containers)) {
    const b = m.bundles(c);
    if (!b.layered.length) continue;
    floors++;
    const p = planFloor(m, c, b.doors, b.bundles, b.layered);
    checkLayer(p, b.layered, c);
    for (const l of Object.values(p.layers ?? {})) expect(l!.routes.filter((r) => r.failed).length, c).toBeLessThanOrEqual(1);
  }
  return floors;
}

/** The demo with `hubs` as `container`'s heavily used items. */
function demoWithHubs(container: string, hubs: string[]) {
  const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
  map.layout.containers[container].hubs = hubs;
  return new Model(map);
}

describe("layers", () => {
  it("demo: the dags floor has one layer, _common.py's, named by its code, of its 10 lines; every other floor none (F0 included)", () => {
    const m = demo();
    for (const c of Object.keys(m.map.layout.containers)) {
      const layers = floorLayers(m, c);
      if (c === DAGS) expect(layers).toEqual([{ id: COMMON, name: m.codes.get(COMMON), full: "_common.py", count: 10, item: COMMON, usedBy: 10 }]);
      else expect(layers, c).toEqual([]);
    }
    expect(floorLayers(m, SITE)).toEqual([]);
    // the 10 lines run from each caller into _common.py, and none of them is in the base layer
    const b = m.bundles(DAGS);
    expect(b.layered).toHaveLength(10);
    for (const x of b.layered) {
      expect(x.layer).toBe(COMMON);
      expect(x.into).toBe(true);
      expect((x.a === COMMON && x.flow === "b→a") || (x.b === COMMON && x.flow === "a→b"), x.key).toBe(true);
    }
    expect(b.bundles.some((x) => x.a === COMMON || x.b === COMMON)).toBe(false);
  });

  it("the fixture has no heavily used item: no layer", () => {
    const m = new Model(shop as unknown as CodeMap);
    for (const c of Object.keys(m.map.layout.containers)) {
      expect(m.bundles(c).layered, c).toEqual([]);
      expect(floorLayers(m, c), c).toEqual([]);
    }
  });

  // digests of every floor's base plan, taken when layers came in (6ccf2f1): the same with the layer pass and without it
  it("demo and fixture: every floor's base plan is the same with the layer pass and without it", () => {
    expect(baseDigest(demo())).toBe("055727f3eb3015b8");   // demo re-pinned at rules 3 (requests one way) and the graded end cost
    expect(baseDigest(new Model(shop as unknown as CodeMap))).toBe("d1dd3884b79fa12d");
  });

  it("demo: the dags floor's 10 calls route over the base, plugged, on their own trunks, at most one failed", () => {
    const m = demo(), b = m.bundles(DAGS);
    const p = planFloor(m, DAGS, b.doors, b.bundles, b.layered);
    expect(Object.keys(p.layers ?? {})).toEqual([COMMON]);
    expect(p.layers![COMMON]!.routes.filter((r) => r.failed).length).toBeLessThanOrEqual(1);
    checkLayer(p, b.layered, DAGS);
    expect(checkAllLayers(m)).toBe(1);
    expect(planFloor(m, DAGS, b.doors, b.bundles, b.layered)).toEqual(p);   // deterministic
  });

  it("a layer's pass routes only its own lines: never the base's stand-in rails (a hub on a floor with one)", () => {
    const c = "svc:demand-forecast", m = demoWithHubs(c, ["pipelines_shared::pipelines_shared/"]), b = m.bundles(c);
    const p = planFloor(m, c, b.doors, b.bundles, b.layered);
    expect(p.tf.rails?.shells.length, "the floor keeps a stand-in rail").toBeGreaterThan(0);
    expect(b.layered.length).toBeGreaterThan(0);
    checkLayer(p, b.layered, c);
    expect(p.routes.some((r) => p.tf.rails!.shells.some((sh) => sh.key === r.key)), "the base routes its stand-in rail").toBe(true);
  });

  it("every line into and out of the item is in its one layer; `used by N` counts those into it, by the kind each is drawn as", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    const caller = "jobs/dags::dags.bq_bay_events_export";
    map.relations.push({ id: "r:request:test", kind: "request", from: "jobs/dags::dags._common#bq/0", to: `${caller}#export_snapshot/0`, key: null, confidence: "confirmed", evidence: [] } as unknown as CodeMap["relations"][number]);
    const b = new Model(map).bundles(DAGS);
    const mixed = b.layered.find((x) => x.a === COMMON && x.b === caller)!;
    expect(mixed.kinds).toEqual({ calls: 3, request: 1 });
    expect(mixed.kind).toBe("request");
    expect(mixed.layer, "a line out of the item is in its layer too").toBe(COMMON);
    expect(mixed.into, "drawn as a request from it: the calls into it do not decide").toBe(false);
    expect(b.layered.filter((x) => x !== mixed).every((x) => x.layer === COMMON && x.into)).toBe(true);
    const m2 = new Model(map);
    expect(floorLayers(m2, DAGS).map((l) => [l.id, l.count, l.usedBy])).toEqual([[COMMON, 10, 9]]);
  });

  it("a line between two heavily used items is in both their layers, routed in each, into one and out of the other, counted once in totals", () => {
    const caller = "jobs/dags::dags.bq_bay_events_export", m = demoWithHubs(DAGS, [COMMON, caller]), b = m.bundles(DAGS);
    const joint = b.layered.filter((x) => (x.a === COMMON && x.b === caller) || (x.a === caller && x.b === COMMON));
    expect(joint.map((x) => [x.layer, x.into]).sort()).toEqual([[COMMON, true], [caller, false]].sort());
    expect(new Set(joint.map((x) => x.key)).size).toBe(1);
    const key = joint[0].key;
    // each layer holds every line into and out of its item; _common.py is still used by all 10
    const layers = floorLayers(m, DAGS);
    expect(layers.map((l) => l.id)).toEqual([COMMON, caller]);
    expect(layers[0]).toMatchObject({ count: 10, usedBy: 10 });
    expect(layers[1].count).toBe(b.layered.filter((x) => x.layer === caller).length);
    expect(layers[1].usedBy).toBe(b.layered.filter((x) => x.layer === caller && x.into).length);
    // routed in each layer, every layer's lines checked as any layer's are
    const p = planFloor(m, DAGS, b.doors, b.bundles, b.layered);
    expect(p.layers![COMMON]!.routes.filter((r) => r.key === key)).toHaveLength(1);
    expect(p.layers![caller]!.routes.filter((r) => r.key === key)).toHaveLength(1);
    checkLayer(p, b.layered, DAGS);
    // totals and lit sets carry the shared line once
    const keys = [...b.bundles, ...b.layered].map((x) => x.key);
    expect(floorLineCount(b)).toBe(new Set(keys).size);
    expect(floorLineCount(b)).toBe(keys.length - 1);
    const lit = defaultLit(m, DAGS);
    expect(lit.filter((k) => k === key)).toHaveLength(1);
    expect(new Set(lit).size).toBe(lit.length);
  });

  it("two joined heavily used items: each layer has at most one failed line", () => {
    const caller = "jobs/dags::dags.bq_bay_events_export", m = demoWithHubs(DAGS, [COMMON, caller]), b = m.bundles(DAGS);
    const p = planFloor(m, DAGS, b.doors, b.bundles, b.layered);
    for (const [id, l] of Object.entries(p.layers!)) expect(l!.routes.filter((r) => r.failed).length, id).toBeLessThanOrEqual(1);
  });

  const hit = (a: PxRect, c: PxRect) => a.x0 < c.x1 && a.x1 > c.x0 && a.y0 < c.y1 && a.y1 > c.y0;
  for (const [name, hubs] of [["one hub (the demo)", [COMMON]], ["two joined hubs", [COMMON, "jobs/dags::dags.bq_bay_events_export"]]] as const)
    for (const W of [undefined, 62, 70])
    it(`${name}, badge ${W ?? "estimated"} px wide: each \`used by N\` badge has a clear spot that grows past 2x, and overlaps neither another badge nor a machine, a zone name, a base line tile or any layer's line`, () => {
      const m = demoWithHubs(DAGS, [...hubs]), b = m.bundles(DAGS);
      const p = planFloor(m, DAGS, b.doors, b.bundles, b.layered);
      // as factory-draw.ts places them: the base's obstacles, the zone names, the rail labels, then placeBadges (it joins the layers' tiles)
      const { tf } = p, flights = flightPaths(tf), clear = new Clearance(messagingObstacles(tf, p.routes, flights, coveredKeys(flights, b.bundles)), tf.cols + 8);
      const names = tf.zones.map((z) => labelBox(planZoneLabel(z, clear), 1));
      railLabels(m, DAGS, tf, clear);
      // the draw plans with badgeSize (never smaller than the drawn badge); 62 is about as Archivo measures `used by 10`
      const items = floorLayers(m, DAGS).filter((l) => l.usedBy > 0).map((l) => { const q = tf.boxes.get(l.item)!, z = badgeSize(l.usedBy); return { id: l.item, m: { x: q.x * T, y: q.y * T, w: q.w * T, h: q.h * T }, w: W ?? z.w, h: z.h }; });
      const spots = placeBadges(items, clear, layerTileRects(p.layers));
      expect([...spots.keys()]).toEqual(items.map((i) => i.id));
      // never the fallback; large enough to read at Fit (the dags floor's Fit needs about 2.13x for 10 px text)
      for (const i of items) expect(spots.get(i.id), i.id).toMatchObject({ clear: true, maxK: expect.toSatisfy((k: number) => k > 2.2) });
      const rect = (q: { x: number; y: number }) => ({ x0: q.x * T, y0: q.y * T, x1: (q.x + 1) * T, y1: (q.y + 1) * T });
      const base = p.routes.flatMap((r) => r.pieces.map(rect)), layered = layerTileRects(p.layers);
      expect(layered.length).toBeGreaterThan(0);
      const machines = [...tf.boxes.values()].map((q) => ({ x0: q.x * T, y0: q.y * T, x1: (q.x + q.w) * T, y1: (q.y + q.h) * T }));
      for (const k of [1, 2, 4]) {
        const boxes = items.map((i) => badgeBox(spots.get(i.id)!, Math.min(k, spots.get(i.id)!.maxK)));
        for (const [i, box] of boxes.entries()) {
          for (const j of boxes.keys()) if (j > i) expect(hit(box, boxes[j]), `badges ${i}, ${j} at ${k}x`).toBe(false);
          expect(machines.some((o) => hit(box, o)), `${items[i].id} on a machine at ${k}x`).toBe(false);
          expect(names.some((o) => hit(box, o)), `${items[i].id} on a zone name at ${k}x`).toBe(false);
          expect(base.some((o) => hit(box, o)), `${items[i].id} on a base line tile at ${k}x`).toBe(false);
          expect(layered.some((o) => hit(box, o)), `${items[i].id} on a layer line tile at ${k}x`).toBe(false);
        }
      }
    });

  it("a batch line into a heavily used item stays in the base: a rail needs the yard and station only the base plans", () => {
    const c = "svc:demand-forecast", hub = "forecast::forecast/", m = demoWithHubs(c, [hub]), b = m.bundles(c);
    const batch = b.bundles.filter((x) => (x.a === hub || x.b === hub) && x.kind === "batch");
    expect(batch.length).toBeGreaterThan(0);
    expect(b.layered.some((x) => x.kind === "batch")).toBe(false);
    expect(b.layered.length).toBeGreaterThan(0);
    const p = planFloor(m, c, b.doors, b.bundles, b.layered);
    checkLayer(p, b.layered, c);
    for (const x of batch) expect(p.routes.find((r) => r.key === x.key)?.kind, x.key).toBe("rail");
  });

  it.runIf(BIG && existsSync(BIG))("the large real map (VIZ_BIG_MAP): one hub floor, one layer of 14 lines (10 calls into the item, 4 from it), routed over the base quickly; every base plan unchanged", () => {
    const m = new Model(JSON.parse(readFileSync(BIG, "utf8")));
    const hubFloors = Object.keys(m.map.layout.containers).filter((c) => floorLayers(m, c).length);
    expect(hubFloors).toHaveLength(1);
    const HUB_FLOOR = hubFloors[0];
    const hub = m.floor(HUB_FLOOR)!.hubs![0];
    expect(floorLayers(m, HUB_FLOOR)).toEqual([
      { id: hub, name: m.codes.get(hub), full: m.itemName(hub), count: 14, item: hub, usedBy: 10 },
    ]);
    const b = m.bundles(HUB_FLOOR);
    // one warm-up, then the median of 5 runs: a single run flakes under full-suite load
    let p = planFloor(m, HUB_FLOOR, b.doors, b.bundles, b.layered);
    const runs: number[] = [];
    for (let i = 0; i < 5; i++) {
      const t0 = performance.now();
      p = planFloor(m, HUB_FLOOR, b.doors, b.bundles, b.layered);
      runs.push(performance.now() - t0);
    }
    expect(runs.sort((x, y) => x - y)[2]).toBeLessThan(250);
    checkLayer(p, b.layered, HUB_FLOOR);
    expect(checkAllLayers(m)).toBe(1);
    expect(baseDigest(m)).toBe("c0ca658df12cccd4");
  });
});

describe("peekKeys: the layer lines a selected base node shows", () => {
  const ln = (key: string, a: string, b: string, layer: string) => ({ key, a, b, layer });
  const layered = [ln("x|h1", "x", "h1", "h1"), ln("h1|h2", "h1", "h2", "h1"), ln("h1|h2", "h1", "h2", "h2"), ln("y|h2", "y", "h2", "h2")];
  it("takes the node's own lines per layer, a line in two layers from the first in list order only", () => {
    expect(peekKeys(layered, ["h1", "h2"], "h2")).toEqual(new Map([["h1", new Set(["h1|h2"])], ["h2", new Set(["y|h2"])]]));
    expect(peekKeys(layered, ["h2", "h1"], "h2")).toEqual(new Map([["h2", new Set(["h1|h2", "y|h2"])]]));
    expect(peekKeys(layered, ["h1", "h2"], "x")).toEqual(new Map([["h1", new Set(["x|h1"])]]));
    expect(peekKeys(layered, ["h1", "h2"], "nobody").size).toBe(0);
  });
  it("finds bq_tariff_snapshot's one layer belt on the demo dags floor", () => {
    const m = demo(), b = m.bundles(DAGS), p = peekKeys(b.layered, floorLayers(m, DAGS).map((l) => l.id), "jobs/dags::dags.bq_tariff_snapshot");
    expect([...p.keys()]).toEqual([COMMON]);
    expect(p.get(COMMON)!.size).toBe(1);
  });
});
