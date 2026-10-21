// test/factory_layout.test.ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { labelSpot, labelTiles, layoutTiles, settleChests, toGeometry, type TileFloor } from "../../src/factory/layout";
import { LANE_H, T, type Rect } from "../../src/factory/tiles";
import { planFloor } from "../../src/factory/plan";
import { chestFit, shownWhole } from "../../src/factory/fit";
import { nameSpec } from "../../src/factory/machines";
import { floorPrefix, shownName } from "../../src/floor/names";
import { checkRails, checkTrunks, plugged } from "./factory_trunks";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const BIG = process.env.VIZ_BIG_MAP ?? "";
const model = new Model(shop as unknown as CodeMap);
const lay = (c: string) => layoutTiles(model, c, model.bundles(c).doors);
const overlaps = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

function sane(tf: TileFloor, c: string) {
  const boxes = [...tf.boxes.values()];
  for (const a of boxes) for (const b of boxes) if (a.id < b.id) expect(overlaps(a, b), `${c}: ${a.id} overlaps ${b.id}`).toBe(false);
  for (const l of tf.lanes) {
    const band = { x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H };
    for (const b of boxes) expect(overlaps(band, b), `${c}: lane ${l.id} runs through ${b.id}`).toBe(false);
  }
  for (const r of [...boxes, ...tf.zones]) {
    expect(r.x).toBeGreaterThanOrEqual(0);
    expect(r.y).toBeGreaterThanOrEqual(0);
    expect(r.x + r.w).toBeLessThanOrEqual(tf.cols);
    expect(r.y + r.h).toBeLessThanOrEqual(tf.rows);
  }
  for (const z of tf.zones) expect(z.w, `${c}: zone ${z.name} is narrower than its label`).toBeGreaterThanOrEqual(labelTiles(z.name));
  for (const z of tf.zones) {   // the label row at the bottom holds no machine
    for (const b of boxes) expect(overlaps({ x: z.x, y: z.y + z.h - 1, w: z.w, h: 1 }, b), `${c}: ${b.id} sits on ${z.name}'s label row`).toBe(false);
  }
}

describe("factory layout", () => {
  it("lays out the site floor in zones, the yard column on the left", () => {
    const tf = lay(SITE);
    sane(tf, SITE);
    for (const id of Object.keys(model.floor(SITE)!.items)) expect(tf.boxes.has(id), id).toBe(true);
    expect(tf.boxes.get("lib:common")!.foot).toBe("rack");
    expect(tf.boxes.get("3p:feed")!).toMatchObject({ foot: "dock", region: "outside" });
    expect(tf.boxes.get("topic:kafka:orders")!.foot).toBe("hub");
    const wh = tf.boxes.get("db:postgres:DB_HOST")!;
    expect(wh).toMatchObject({ foot: "warehouse", x: 2 });
    const lane = tf.lanes.find((l) => l.id === "db:postgres:DB_HOST")!;
    expect(lane.x0).toBe(wh.x + wh.w);
    const services = ["svc:shop", "svc:worker"].map((id) => tf.boxes.get(id)!);
    for (const s of services) expect(lane.x1).toBeGreaterThanOrEqual(s.x + s.w);   // the lane runs under every machine
    expect(tf.zones.map((z) => z.name)).toEqual(expect.arrayContaining(["library shelf", "production line", "outside world", "kafka", "storage"]));
    expect(tf.zones.find((z) => z.name === "kafka")!.airfield).toBe(true);
  });

  it("frames every inside floor with in, installed-libraries and out columns", () => {
    for (const c of Object.keys(model.map.layout.containers)) {
      if (c === SITE) continue;
      const { doors } = model.bundles(c);
      const tf = lay(c);
      sane(tf, c);
      const work = [...tf.boxes.values()].filter((b) => !["in", "out", "installed"].includes(b.region) && b.kind !== "datastore");
      for (const d of doors) {
        const b = tf.boxes.get(d.id)!;
        expect(b, `${c}: door ${d.id}`).toBeDefined();
        if (model.kindOf(d.anchor) === "library") expect(b).toMatchObject({ foot: "installed", region: "installed" });
        else if (model.kindOf(d.anchor) === "datastore") expect(tf.lanes.some((l) => l.id === d.anchor)).toBe(true);
        else if (d.side === "in") for (const w of work) expect(b.x + b.w, `${c}: in-door ${d.id} left of ${w.id}`).toBeLessThan(w.x);
        else for (const w of work) expect(b.x, `${c}: out-door ${d.id} right of ${w.id}`).toBeGreaterThan(w.x + w.w);
      }
      expect(tf.zones.some((z) => z.name === "storage")).toBe(false);   // no storage zone inside a factory
    }
  });

  it("runs every lane under every machine and places every floor item once", () => {
    for (const c of Object.keys(model.map.layout.containers)) {
      const tf = lay(c);
      const doors = model.bundles(c).doors;
      const ids = Object.keys(model.floor(c)!.items);
      for (const id of ids) expect(tf.boxes.has(id), `${c}: item ${id} has a box`).toBe(true);
      const doorIds = new Set(doors.map((d) => d.id));
      expect(ids.some((id) => doorIds.has(id)), `${c}: door id clashes with an item`).toBe(false);
      expect(tf.boxes.size, `${c}: boxes = items + doors`).toBe(ids.length + doorIds.size);
      for (const l of tf.lanes) for (const b of tf.boxes.values()) {
        if (["in", "out", "installed"].includes(b.region)) continue;
        expect(b.x + b.w, `${c}: lane ${l.id} ends before ${b.id}`).toBeLessThanOrEqual(l.x1);
      }
    }
  });

  it("gives a lane gap the extra rows asked for (`laneGaps`): the lanes below move down, the ones above stay", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const base = layoutTiles(demo, SITE, demo.bundles(SITE).doors);
    const wider = layoutTiles(demo, SITE, demo.bundles(SITE).doors, { laneGaps: [0, 1, 0, 0] });
    expect(base.lanes.length).toBe(4);
    expect(wider.lanes.map((l, i) => l.y - base.lanes[i].y)).toEqual([0, 0, 1, 1]);
  });

  it("survives a floor with nothing on it", () => {
    const tiny = new Model({
      meta: { schema_version: 2, repo: "t", commit: "c", scanned_at: "", languages: [] },
      nodes: [], relations: [], problems: [],
      layout: { version: 1, containers: { site: { strategy: "main-bus", items: {} } } },
    } as CodeMap);
    const tf = layoutTiles(tiny, SITE);
    expect(tf.zones).toEqual([]);
    expect(Number.isFinite(tf.cols) && tf.cols > 0 && Number.isFinite(tf.rows) && tf.rows > 0).toBe(true);
  });

  it("lays out an inside floor with doors but no items", () => {
    const tiny = new Model({
      meta: { schema_version: 2, repo: "t", commit: "c", scanned_at: "", languages: [] },
      nodes: [
        { id: "svc:a", kind: "service", name: "a" }, { id: "lib:l", kind: "library", name: "l" },
        { id: "db:d", kind: "datastore", name: "d" }, { id: "svc:b", kind: "service", name: "b" },
      ],
      relations: [], problems: [],
      layout: { version: 1, containers: { site: { strategy: "main-bus", items: {} }, "svc:a": { strategy: "main-bus", items: {} } } },
    } as unknown as CodeMap);
    const doors = [
      { id: "door:svc:b", anchor: "svc:b", side: "in" as const }, { id: "door:svc:b/out", anchor: "svc:b", side: "out" as const },
      { id: "door:lib:l", anchor: "lib:l", side: "in" as const }, { id: "door:db:d", anchor: "db:d", side: "out" as const },
    ];
    const tf = layoutTiles(tiny, "svc:a", doors);
    expect(Number.isFinite(tf.cols) && tf.cols > 0 && Number.isFinite(tf.rows) && tf.rows > 0).toBe(true);
    for (const z of tf.zones) for (const v of [z.x, z.y, z.w, z.h]) expect(Number.isFinite(v)).toBe(true);
    expect(tf.zones.map((z) => z.name).sort()).toEqual(["in", "installed libraries", "out"]);
    expect(tf.lanes.map((l) => l.id)).toEqual(["db:d"]);
    const col = (id: string) => tf.boxes.get(id)!.x;
    expect(col("door:svc:b")).toBe(col("door:lib:l"));            // in and library doors share the left column
    expect(col("door:svc:b/out")).toBeGreaterThan(col("door:svc:b"));   // out door on the right
    expect(tf.boxes.has("door:db:d")).toBe(true);
  });

  it("spreads doors evenly down a tall column, at least 3 tiles apart, and the work rows down the room", () => {
    const nodes = [{ id: "svc:a", kind: "service", name: "a" }, { id: "svc:w", kind: "service", name: "w" }, { id: "svc:x", kind: "service", name: "x" },
      { id: "svc:y", kind: "service", name: "y" }, { id: "svc:z", kind: "service", name: "z" }];
    // a 2 x 2 block: wide enough that it is not re-wrapped
    const items = { "svc:w": { region: "line", col: 0, row: 0 }, "svc:x": { region: "line", col: 0, row: 1 },
      "svc:y": { region: "line", col: 1, row: 0 }, "svc:z": { region: "line", col: 1, row: 1 } };
    const tiny = new Model({
      meta: { schema_version: 2, repo: "t", commit: "c", scanned_at: "", languages: [] },
      nodes: [...nodes, ...Array.from({ length: 6 }, (_, i) => ({ id: `svc:o${i}`, kind: "service", name: `o${i}` })),
        ...Array.from({ length: 4 }, (_, i) => ({ id: `lib:l${i}`, kind: "library", name: `l${i}` }))],
      relations: [], problems: [],
      layout: { version: 1, containers: { site: { strategy: "main-bus", items: {} }, "svc:a": { strategy: "main-bus", items } } },
    } as unknown as CodeMap);
    const doors = Array.from({ length: 6 }, (_, i) => ({ id: `door:o${i}`, anchor: `svc:o${i}`, side: "out" as const }));
    const inDoors = [0, 1, 2].map((i) => ({ id: `door:i${i}`, anchor: `svc:o${i}`, side: "in" as const }));
    const libDoors = [0, 1, 2, 3].map((i) => ({ id: `door:l${i}`, anchor: `lib:l${i}`, side: "in" as const }));
    const tf = layoutTiles(tiny, "svc:a", [...doors, ...inDoors, ...libDoors]);
    sane(tf, "tall");
    for (const ids of [inDoors, libDoors]) {   // the in and installed-library columns keep 3 tiles between doors too
      const c = ids.map((d) => tf.boxes.get(d.id)!).sort((p, q) => p.y - q.y);
      for (let i = 1; i < c.length; i++) expect(c[i].y - (c[i - 1].y + c[i - 1].h), `${c[i].region} gap ${i}`).toBeGreaterThanOrEqual(3);
    }
    const col = doors.map((d) => tf.boxes.get(d.id)!).sort((p, q) => p.y - q.y);
    for (let i = 1; i < col.length; i++) expect(col[i].y - (col[i - 1].y + col[i - 1].h), `gap ${i}`).toBeGreaterThanOrEqual(3);
    const z = tf.zones.find((q) => q.name === "out")!;
    expect(z.y + z.h - (col[5].y + col[5].h)).toBeLessThanOrEqual(2 + 5);   // the last door stands at the column's foot
    const rows = [...new Set(["svc:w", "svc:x"].map((id) => tf.boxes.get(id)!.y))].sort((p, q) => p - q);
    expect(rows).toHaveLength(2);
    const out = tf.boxes.get("door:o0")!, work = [...tf.boxes.values()].filter((b) => b.region === "line");
    for (const w of work) expect(w.x + w.w).toBeLessThan(out.x);   // the out column stays right of everything
    expect(z.y + z.h - (rows[1] + 5)).toBeLessThanOrEqual(2 + 4 + 1);   // the lower work row reaches down the room too

    // requested corridor widths add to the room's spread, they do not eat it: each corridor grows by exactly its request
    const all = [...doors, ...inDoors, ...libDoors];
    expect(tf.aisles!.cols).toHaveLength(1);
    expect(tf.aisles!.rows).toHaveLength(1);
    const wide = layoutTiles(tiny, "svc:a", all, { colGaps: [2], rowGaps: [3] });
    sane(wide, "tall, wider corridors");
    expect(wide.aisles!.cols[0].w).toBe(tf.aisles!.cols[0].w + 2);
    expect(wide.aisles!.rows[0].h).toBe(tf.aisles!.rows[0].h + 3);
    for (const b of work) {
      const w2 = wide.boxes.get(b.id)!;
      expect(w2.x, b.id).toBeGreaterThanOrEqual(b.x);
      expect(w2.y, b.id).toBeGreaterThanOrEqual(b.y);
    }
  });

  it("re-wraps a tall production line to a screen shape, keeping reading order", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const tf = layoutTiles(demo, SITE, demo.bundles(SITE).doors);
    sane(tf, "demo site");
    const z = tf.zones.find((q) => q.name === "production line")!;
    expect(z.w / z.h).toBeGreaterThan(1.2);
    expect(z.w / z.h).toBeLessThan(2.2);
    const items = Object.entries(demo.floor(SITE)!.items).filter(([id, c]) => ["line", "grid"].includes(c.region) && demo.kindOf(id) !== "external")
      .sort(([, p], [, q]) => p.col - q.col || p.row - q.row);
    const xs = items.map(([id]) => tf.boxes.get(id)!.x);
    for (let i = 1; i < xs.length; i++) expect(xs[i], `item ${i} not in an earlier column`).toBeGreaterThanOrEqual(xs[i - 1]);
    expect(new Set(xs).size).toBeGreaterThan(2);
  });

  it("sets floor 0 zones side by side: a landscape floor, no zone left far below the one above", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const tf = layoutTiles(demo, SITE, demo.bundles(SITE).doors);
    sane(tf, "demo site");
    expect(tf.cols / tf.rows).toBeGreaterThanOrEqual(1.0);
    const byY = [...tf.zones].sort((p, q) => p.y - q.y);
    for (const z of byY) {
      const above = byY.filter((q) => q.y < z.y && q.y + q.h <= z.y);
      if (!above.length) continue;
      const gap = z.y - Math.max(...above.map((q) => q.y + q.h));
      expect(gap, `${z.name}: empty band above`).toBeLessThanOrEqual(6);
    }
    const line = tf.zones.find((q) => q.name === "production line")!, out = tf.zones.find((q) => q.name === "outside world")!;
    expect(out.h).toBeLessThanOrEqual(line.h);
    expect(out.x).toBeGreaterThanOrEqual(line.x + line.w);
    const air = tf.zones.filter((q) => q.airfield), bay = tf.zones.find((q) => q.name === "read-only")!, store = tf.zones.find((q) => q.name === "storage")!;
    expect(bay.x).toBeGreaterThanOrEqual(Math.max(...air.map((q) => q.x + q.w)));
    expect(bay.y + bay.h).toBeLessThanOrEqual(store.y);
  });

  it("without airfields the read-only bay stays below storage: no band of its own above the lanes", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    const items = map.layout.containers[SITE].items;
    const probe = new Model(map);
    for (const id of Object.keys(items)) if (probe.kindOf(id) === "topic") delete items[id];
    const demo = new Model(map);
    const tf = layoutTiles(demo, SITE, demo.bundles(SITE).doors);
    sane(tf, "demo site, no airfields");
    expect(tf.zones.some((q) => q.airfield)).toBe(false);
    const bay = tf.zones.find((q) => q.name === "read-only")!, store = tf.zones.find((q) => q.name === "storage")!;
    expect(bay.y).toBeGreaterThanOrEqual(store.y + store.h);
    for (const b of tf.boxes.values()) if (b.region === "bay") for (const l of tf.lanes) expect(l.x1, l.id).toBeGreaterThanOrEqual(b.x + b.w);
  });

  it("puts a dead-letter hub in the slot right after its source hub, in the same airfield", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    for (const [m, label] of [[demo, "demo"], [model, "fixture"]] as const) {
      const tf = layoutTiles(m, SITE, m.bundles(SITE).doors);
      sane(tf, `${label} site`);
      const hubs = [...tf.boxes.values()].filter((b) => b.kind === "topic");
      const dlqs = hubs.filter((b) => m.nodes.get(b.id)?.dead_letter_of);
      expect(dlqs.length, label).toBeGreaterThan(0);
      for (const d of dlqs) {
        const src = tf.boxes.get(m.nodes.get(d.id)!.dead_letter_of!)!;
        expect(src, `${label} ${d.id} source`).toBeDefined();
        expect(d.y, `${label} ${d.id} same row`).toBe(src.y);
        expect(d.x, `${label} ${d.id} right of its source`).toBeGreaterThan(src.x);
        const between = hubs.filter((b) => b.y === d.y && b.x > src.x && b.x < d.x);
        expect(between.map((b) => b.id), `${label} ${d.id} next slot`).toEqual([]);
        const z = tf.zones.find((q) => q.airfield && q.name === d.id.split(":")[1])!;
        for (const b of [src, d]) expect(b.x >= z.x && b.x + b.w <= z.x + z.w, `${label} ${b.id} in ${z.name}`).toBe(true);
      }
    }
    // the demo's sqs dead queue sorts first by id, yet stands after violations.fifo
    const tf = layoutTiles(demo, SITE, demo.bundles(SITE).doors);
    expect(tf.boxes.get("topic:sqs:violations-dead.fifo")!.x).toBeGreaterThan(tf.boxes.get("topic:sqs:violations.fifo")!.x);
    expect(layoutTiles(demo, SITE, demo.bundles(SITE).doors)).toEqual(tf);
  });

  it("gives every queue hub one free tile beside it for its waiting stack, inside its zone, and no other hub one", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    let seen = 0;
    for (const c of Object.keys(demo.map.layout.containers)) {
      const tf = layoutTiles(demo, c, demo.bundles(c).doors);
      const queues = [...tf.boxes.values()].filter((b) => {
        const t = demo.nodes.get(b.id.startsWith("door:") ? b.id.slice(5) : b.id);
        return t?.kind === "topic" && t.delivery === "queue";
      });
      expect((tf.stacks ?? []).map((s) => s.item).sort(), c).toEqual(queues.map((b) => b.id).sort());
      if (!queues.length) { expect(tf.stacks, c).toBeUndefined(); continue; }
      for (const s of tf.stacks!) {
        seen++;
        const hub = tf.boxes.get(s.item)!, tile = { x: s.x, y: s.y, w: 1, h: 1 };
        const beside = overlaps({ x: hub.x - 1, y: hub.y, w: hub.w + 2, h: hub.h }, tile) || overlaps({ x: hub.x, y: hub.y - 1, w: hub.w, h: hub.h + 2 }, tile);
        expect(beside && !overlaps(hub, tile), `${c} ${s.item} stack beside its hub`).toBe(true);
        for (const b of tf.boxes.values()) expect(overlaps(b, tile), `${c} ${s.item} stack on ${b.id}`).toBe(false);
        for (const l of tf.lanes) expect(overlaps({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H }, tile), `${c} stack on lane ${l.id}`).toBe(false);
        expect(tf.zones.some((z) => overlaps(z, tile) && overlaps(z, hub)), `${c} ${s.item} stack in its hub's zone`).toBe(true);
      }
    }
    expect(seen).toBeGreaterThanOrEqual(2);   // the site's two sqs queues at least
  });

  it("gives one scheduler with seven destinations (six added) a 7-row rail yard and seven stations, the floor still sane", () => {
    // the fixture with six more services on the production line, each a batch destination of the worker
    const map = structuredClone(shop) as unknown as CodeMap;
    const spots: [number, number][] = [[3, 0], [0, 1], [1, 1], [2, 1], [3, 1], [1, 2]];
    spots.forEach(([col, row], i) => {
      map.nodes.push({ id: `svc:d${i}`, kind: "service", name: `d${i}` } as CodeMap["nodes"][number]);
      map.layout.containers.site.items[`svc:d${i}`] = { region: "line", col, row };
      map.relations.push({ kind: "batch", from: "svc:worker", to: `svc:d${i}`, id: `r:batch:d${i}`, key: `job d${i}`, confidence: "confirmed",
        schedule: [`${i} 3 * * *`], job: `job_d${i}`, data: "forward", evidence: [] } as unknown as CodeMap["relations"][number]);
    });
    const m = new Model(map);
    const { bundles, doors } = m.bundles(SITE);
    const p = planFloor(m, SITE, doors, bundles);
    sane(p.tf, "six destinations");
    const r = p.tf.rails!;
    const y = r.yards.find((q) => q.source === "svc:worker")!;
    expect(y.platforms.map((q) => q.dest).sort()).toEqual(spots.map((_, i) => `svc:d${i}`).concat("svc:shop").sort());
    // its rails share exits: a ladder, one tile wider for its throat
    expect([y.w, y.h, !!y.ladder], "4 wide on any side (5 with a throat), a row per destination, no header").toEqual([5, 7, true]);
    expect(r.stations).toHaveLength(7);
    expect(p.routes.filter((q) => q.failed), "no failed line").toHaveLength(0);
    checkTrunks(p.tf, p.routes, "six destinations");
    for (const q of p.routes) if (q.pieces.length) plugged(p.tf, q);
    expect(checkRails(p.tf, p.routes, bundles, "six destinations"), "a rail per destination").toBe(7);
    expect(planFloor(m, SITE, doors, bundles)).toEqual(p);
  });

  it.skipIf(!BIG)("keeps the layout invariants on every floor of the big map", () => {
    const big = new Model(JSON.parse(readFileSync(BIG, "utf8")) as CodeMap);
    for (const c of Object.keys(big.map.layout.containers)) sane(layoutTiles(big, c, big.bundles(c).doors), c);
  });

  it("converts tiles to pixels for the camera", () => {
    const tf = lay(SITE);
    const geo = toGeometry(tf);
    const b = tf.boxes.get("svc:shop")!;
    expect(geo.machines.get("svc:shop")).toMatchObject({ x: b.x * T, y: b.y * T, w: b.w * T, h: b.h * T });
    expect(geo.bounds).toEqual({ x: 0, y: 0, w: tf.cols * T, h: tf.rows * T });
  });

  it("puts a zone's name in the left corner, else the right, else the first clear run", () => {
    const z = { name: "storage", x: 0, y: 0, w: 20, h: 4, airfield: false };
    const row = z.y + z.h - 1;
    expect(labelSpot(z, 5, () => false)).toBe(0);
    expect(labelSpot(z, 5, (x, y) => y === row && x === 2)).toBe(15);
    expect(labelSpot(z, 5, (x, y) => y === row && (x === 2 || x === 17))).toBe(3);
    expect(labelSpot(z, 5, (_x, y) => y === row)).toBe(0);   // nowhere clear: left corner anyway
  });
});

/** Tiles between two boxes, the larger of the gaps across and down (0 when they touch). */
const chebyshevGap = (a: Rect, b: Rect) => Math.max(0, a.x - (b.x + b.w), b.x - (a.x + a.w), a.y - (b.y + b.h), b.y - (a.y + a.h));

/** A tiny site: `line` services in one production-line row, one cache (`db:c`) every listed method reads or writes. */
function cacheSite(line: string[], users: [string, "db-read" | "db-write"][], store = "cache", name = "c"): Model {
  const items: Record<string, { region: string; col: number; row: number }> = { "db:c": { region: "bus", col: 0, row: 0 } };
  line.forEach((id, i) => { items[id] = { region: "line", col: i, row: 0 }; });
  return new Model({
    meta: { schema_version: 2, repo: "t", commit: "c", scanned_at: "", languages: [] },
    nodes: [...line.map((id) => ({ id, kind: "service", name: id.slice(4) })),
      ...line.flatMap((id) => [1, 2].map((k) => ({ id: `${id}::m${k}`, kind: "method", name: `m${k}`, parent: id }))),
      { id: "db:c", kind: "datastore", name, store }],
    relations: users.map(([from, kind], i) => ({ id: `r${i}`, kind, from, to: "db:c", confidence: "confirmed" })),
    problems: [],
    layout: { version: 1, containers: { site: { strategy: "main-bus", items } } },
  } as unknown as CodeMap);
}

describe("factory layout: caches", () => {
  const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);

  it("demo F0: reservations-redis is a 2x2 chest beside reservations, with no lane; the shared cache keeps its lane", () => {
    const m = demo(), { bundles, doors } = m.bundles(SITE);
    const { tf, routes } = planFloor(m, SITE, doors, bundles);
    sane(tf, "demo site");
    const chest = tf.boxes.get("db:redis:REDIS_URL")!, owner = tf.boxes.get("svc:reservations")!;
    // the narrowest chest that shows "reservations-redis" whole: 4x3, "reservations-" / "redis"; no room below, so right
    expect(chest).toMatchObject({ foot: "chest", kind: "datastore", w: 4, h: 3 });
    expect(chest.x).toBe(owner.x + owner.w + 1);
    expect(chebyshevGap(chest, owner)).toBeLessThanOrEqual(2);
    // its name is shown whole, by the fit the painter draws (nameSpec's room, chestFit's lines)
    const name = shownName(m, chest.id, floorPrefix(m, Object.keys(m.floor(SITE)!.items)));
    const fit = chestFit(name, chest.w, chest.h)!;
    expect(fit.lines).toEqual(["reservations-", "redis"]);
    expect(shownWhole(name, fit.lines)).toBe(true);
    const spec = nameSpec(chest);
    expect(fit.size).toBeGreaterThanOrEqual(Math.min(...spec.sizes));
    for (const l of fit.lines) expect(l.length * fit.size * 0.56, l).toBeLessThanOrEqual(spec.w);
    expect(spec.top + fit.lines.length * (fit.size + 2)).toBeLessThanOrEqual((chest.y + chest.h) * T - 8);
    expect(tf.lanes.some((l) => l.id === "db:redis:REDIS_URL")).toBe(false);
    expect(tf.lanes.some((l) => l.id === "db:redis:SHARED_CACHE_URL")).toBe(true);
    expect(tf.lanes.map((l) => l.id).sort()).toEqual(["db:bigquery:BQ_PROJECT", "db:postgres:DB_HOST", "db:redis:SHARED_CACHE_URL", "db:s3:RECEIPTS_BUCKET"]);
    expect(tf.notes ?? []).toEqual([]);
    for (const r of routes) if (r.pieces.length) plugged(tf, r);
    checkTrunks(tf, routes, "demo site");
    const tap = routes.find((r) => r.key === "db:redis:REDIS_URL|svc:reservations")!;
    expect(tap).toMatchObject({ kind: "tapRW", tap: "db:redis:REDIS_URL" });
    expect(tap.pieces, "the tap pair crosses the one-tile gap").toHaveLength(1);
  });

  it("a cache one service reads and writes from two methods is a chest beside it (ends counted by machine)", () => {
    const m = cacheSite(["svc:a", "svc:b"], [["svc:a::m1", "db-read"], ["svc:a::m2", "db-write"]]);
    const { bundles, doors } = m.bundles(SITE);
    const { tf, routes } = planFloor(m, SITE, doors, bundles);
    sane(tf, "chest site");
    const chest = tf.boxes.get("db:c")!;
    expect(chest.foot).toBe("chest");
    expect(chebyshevGap(chest, tf.boxes.get("svc:a")!)).toBeLessThanOrEqual(2);
    expect(tf.lanes).toEqual([]);
    expect(tf.zones.some((z) => z.name === "storage")).toBe(false);
    const r = routes.find((q) => q.key === "db:c|svc:a")!;
    expect(r).toMatchObject({ kind: "tapRW", tap: "db:c", failed: undefined });
    plugged(tf, r);
    expect(r.pieces, "the tap pair crosses the one-tile gap").toHaveLength(1);
  });

  it("fixture site: shop's redis is a chest beside shop, its tap pair across the gap (a rail leaving shop's yard keeps off it)", () => {
    const { bundles, doors } = model.bundles(SITE);
    const { tf, routes } = planFloor(model, SITE, doors, bundles);
    sane(tf, "fixture site");
    const chest = tf.boxes.get("db:redis:REDIS_URL")!;
    expect(chest.foot).toBe("chest");
    expect(chebyshevGap(chest, tf.boxes.get("svc:shop")!)).toBeLessThanOrEqual(2);
    const tap = routes.find((r) => r.key === "db:redis:REDIS_URL|svc:shop")!;
    expect(tap).toMatchObject({ kind: "tapRW", failed: undefined });
    expect(tap.pieces).toHaveLength(1);
    for (const r of routes) if (r.pieces.length) plugged(tf, r);
    checkTrunks(tf, routes, "fixture site");
  });

  it("a single-owner cache with no room beside its service stays a lane, with a layout note", () => {
    const m = cacheSite(["svc:a"], [["svc:a::m1", "db-read"]]);
    const tf = layoutTiles(m, SITE, m.bundles(SITE).doors);
    sane(tf, "no-room site");
    expect(tf.boxes.get("db:c")!.foot).toBe("warehouse");
    expect(tf.lanes.map((l) => l.id)).toEqual(["db:c"]);
    expect(tf.notes).toEqual([expect.stringContaining("db:c")]);
  });

  it("a single-owner cache whose name no chest up to a lane-end box can show whole stays a lane, with a layout note", () => {
    const m = cacheSite(["svc:a", "svc:b"], [["svc:a::m1", "db-read"]], "cache", "an-extraordinarily-long-cache-name-for-the-session-store");
    const tf = layoutTiles(m, SITE, m.bundles(SITE).doors);
    sane(tf, "long-name site");
    expect(tf.boxes.get("db:c")!.foot).toBe("warehouse");
    expect(tf.lanes.map((l) => l.id)).toEqual(["db:c"]);
    expect(tf.notes).toEqual(["chest: db:c stays a lane: its name does not fit a chest"]);
  });

  it("a chest lost to another cache's new lane falls back too: the floor is laid out until the laned set settles", () => {
    // c1 never has room; c2 has room only while c1 is a chest (c1's lane would take it)
    const seen: string[][] = [];
    const pass = (laned: ReadonlySet<string>): TileFloor => {
      seen.push([...laned].sort());
      const foot = (id: string) => (laned.has(id) || id === "db:c1" || laned.has("db:c1") ? "warehouse" : "chest");
      const boxes = new Map(["db:c1", "db:c2"].map((id) => [id, { id, kind: "datastore", foot: foot(id), region: "bus", x: 0, y: 0, w: 2, h: 2 }] as const));
      return { boxes, lanes: [], zones: [], cols: 1, rows: 1, strategy: "main-bus", site: true } as unknown as TileFloor;
    };
    const tf = settleChests(["db:c1", "db:c2"], pass);
    expect(seen, "c1 falls back, then c2 (lost only after c1's lane), then the set settles").toEqual([[], ["db:c1"], ["db:c1", "db:c2"]]);
    expect([...tf.boxes.values()].map((b) => b.foot)).toEqual(["warehouse", "warehouse"]);
    // no cache: one pass
    seen.length = 0;
    settleChests([], pass);
    expect(seen).toEqual([[]]);
  });

  it("two single-owner caches, one with no chest: it keeps a lane with its note, the other is a chest, every bundle routes", () => {
    const long = "an-extraordinarily-long-cache-name-for-the-session-store";
    const items: Record<string, { region: string; col: number; row: number }> = {
      "db:c1": { region: "bus", col: 0, row: 0 }, "db:c2": { region: "bus", col: 0, row: 1 },
      "svc:a": { region: "line", col: 0, row: 0 }, "svc:b": { region: "line", col: 1, row: 0 } };
    const m = new Model({
      meta: { schema_version: 2, repo: "t", commit: "c", scanned_at: "", languages: [] },
      nodes: [...["svc:a", "svc:b"].flatMap((id) => [{ id, kind: "service", name: id.slice(4) }, { id: `${id}::m1`, kind: "method", name: "m1", parent: id }]),
        { id: "db:c1", kind: "datastore", name: long, store: "cache" }, { id: "db:c2", kind: "datastore", name: "c2", store: "cache" }],
      relations: [{ id: "r1", kind: "db-read", from: "svc:a::m1", to: "db:c1", confidence: "confirmed" },
        { id: "r2", kind: "db-write", from: "svc:a::m1", to: "db:c2", confidence: "confirmed" }],
      problems: [],
      layout: { version: 1, containers: { site: { strategy: "main-bus", items } } },
    } as unknown as CodeMap);
    const { bundles, doors } = m.bundles(SITE);
    const { tf, routes } = planFloor(m, SITE, doors, bundles);
    sane(tf, "two-cache site");
    expect(tf.boxes.get("db:c1")!.foot).toBe("warehouse");
    expect(tf.lanes.map((l) => l.id)).toEqual(["db:c1"]);
    expect(tf.boxes.get("db:c2")!.foot).toBe("chest");
    expect(tf.notes).toEqual(["chest: db:c1 stays a lane: its name does not fit a chest"]);
    expect(routes.map((r) => r.key).sort()).toEqual(bundles.map((b) => b.key).sort());
    for (const r of routes) {
      expect(r.failed, r.key).toBeUndefined();
      expect(r.pieces.length, r.key).toBeGreaterThan(0);
      plugged(tf, r);
    }
  });

  it("a cache two services use, and a bucket one service uses, keep their lanes", () => {
    for (const m of [cacheSite(["svc:a", "svc:b"], [["svc:a::m1", "db-read"], ["svc:b::m1", "db-write"]]),
      cacheSite(["svc:a", "svc:b"], [["svc:a::m1", "db-write"]], "bucket")]) {
      const tf = layoutTiles(m, SITE, m.bundles(SITE).doors);
      expect(tf.boxes.get("db:c")!.foot).toBe("warehouse");
      expect(tf.lanes.map((l) => l.id)).toEqual(["db:c"]);
    }
  });
});
