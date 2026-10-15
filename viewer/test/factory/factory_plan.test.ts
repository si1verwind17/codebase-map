import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { layoutTiles, type TileFloor } from "../../src/factory/layout";
import { corridorLoad, crossings, layFloor, planFloor, startGap, trafficGaps } from "../../src/factory/plan";
import { routeTiles, type TileRoute } from "../../src/factory/router";
import { SITE } from "../../src/model/model";
import { T, type Piece } from "../../src/factory/tiles";
import { fitScale } from "../../src/floor/fitscale";
import { bodyFor, factoryOps, tileArms } from "../../src/factory/pieces";
import { CODE_BAND, NAME_MIN_PX, codeZoom, codesMode, subShown, bigCodeHeight, nameSpec } from "../../src/factory/machines";
import { fitName } from "../../src/factory/fit";
import { Clearance, floorObstacles, labelBox, planZoneLabel, ZONE_FONT, type PxRect } from "../../src/factory/clear";
import { laneLabelSpot, MIN_PX } from "../../src/factory/ground";
import { LANE_H } from "../../src/factory/tiles";
import { checkRails, checkTrunks, plugged } from "./factory_trunks";
import { createHash } from "node:crypto";
import { messaging } from "../../src/factory/messaging";
import { batch } from "../../src/factory/batch";
import { railRects } from "../../src/factory/yards";
import { landing, padMark, reservedRects, type Landing } from "../../src/factory/pads";
import { inside, type Rect } from "../../src/factory/tiles";

const BIG = process.env.VIZ_BIG_MAP ?? "";
const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const piece = (x: number, y: number, dir: Piece["in"], under = false): Piece => ({ x, y, in: dir, out: dir, under, hoodBefore: false, hoodAfter: false });
const line = (pieces: Piece[], failed = false): TileRoute => ({ key: "k", kind: "belt", both: false, points: [], pieces, failed });

describe("floor plan", () => {
  it("lays out and routes every fixture floor with no failed line, deterministically", () => {
    const model = new Model(shop as unknown as CodeMap);
    for (const c of Object.keys(model.map.layout.containers)) {
      const { bundles, doors } = model.bundles(c);
      const a = planFloor(model, c, doors, bundles);
      expect(a.routes.filter((r) => r.failed), c).toHaveLength(0);
      expect(a.gap, c).toBe(startGap(bundles));
      checkTrunks(a.tf, a.routes, c);
      expect(planFloor(model, c, doors, bundles)).toEqual(a);
    }
  });

  it("a wider gap makes a bigger floor and the default gap is unchanged", () => {
    const model = new Model(shop as unknown as CodeMap);
    const c = Object.keys(model.map.layout.containers)[0];
    const { doors } = model.bundles(c);
    const a = layoutTiles(model, c, doors), b = layoutTiles(model, c, doors, { gap: 2 });
    expect(layoutTiles(model, c, doors, { gap: 0 })).toEqual(a);
    expect(b.cols * b.rows).toBeGreaterThanOrEqual(a.cols * a.rows);
  });

  it("measures a corridor's load as belts side by side along it, one cross-section at a time", () => {
    const r = { x: 10, y: 0, w: 4, h: 10 };
    const down = (x: number, y0: number, y1: number) => line(Array.from({ length: y1 - y0 }, (_, i) => piece(x, y0 + i, "s")));
    expect(corridorLoad(r, [down(10, 0, 10), down(11, 0, 5), down(12, 5, 10)], "down")).toBe(2);   // never three in one row
    expect(corridorLoad(r, [down(10, 0, 10), down(11, 0, 10), down(12, 0, 10)], "down")).toBe(3);
    expect(corridorLoad(r, [line([piece(10, 3, "e"), piece(11, 3, "e"), piece(12, 3, "e")])], "down")).toBe(0);   // crossing it, not along
    expect(corridorLoad(r, [down(10, 0, 10), line([...down(11, 0, 10).pieces.map((p) => ({ ...p, under: true }))]), down(12, 0, 10), down(13, 0, 10)], "down")).toBe(3);   // underground is not on top
    expect(corridorLoad(r, [down(10, 0, 10), down(11, 0, 10)].map((q) => ({ ...q, failed: true })), "down")).toBe(0);
    expect(corridorLoad(r, [down(10, 0, 4), down(11, 0, 4), down(12, 0, 4), down(13, 4, 10)], "down", [{ x: 0, y: 0, w: 30, h: 4 }])).toBe(1);   // rows where a crossing corridor meets it are skipped
  });

  it("widens only full corridors, a tile per belt past width minus two", () => {
    const model = new Model(shop as unknown as CodeMap);
    const tf = { ...layoutTiles(model, SITE, []), aisles: { cols: [{ x: 10, y: 0, w: 6, h: 10 }, { x: 30, y: 0, w: 6, h: 10 }, { x: 50, y: 0, w: 6, h: 10 }], rows: [] } };
    const belts = (x0: number, n: number) => Array.from({ length: n }, (_, k) => line(Array.from({ length: 10 }, (_, i) => piece(x0 + k, i, "s"))));
    expect(trafficGaps(tf, belts(10, 4))).toBeUndefined();   // 4 belts in 6 tiles: room to spare
    expect(trafficGaps(tf, [...belts(10, 5), ...belts(30, 6)])).toEqual({ colGaps: [1, 2, 0], rowGaps: [] });
    // a belt per tile is the most a corridor can hold on top, so it gains two; lines riding one trunk are one belt
    expect(trafficGaps(tf, [...belts(10, 6), ...belts(10, 6)])).toEqual({ colGaps: [2, 0, 0], rowGaps: [] });
  });

  it("a pad, dock or stack in a corridor counts as a belt in each cross-section it spans; a corridor without one gains nothing", () => {
    const r = { x: 10, y: 0, w: 4, h: 10 };
    const down = (x: number, y0: number, y1: number) => line(Array.from({ length: y1 - y0 }, (_, i) => piece(x, y0 + i, "s")));
    const belts = [down(10, 0, 10), down(11, 0, 10)];
    expect(corridorLoad(r, belts, "down")).toBe(2);
    expect(corridorLoad(r, belts, "down", [], [{ x: 12, y: 4, w: 1, h: 1 }])).toBe(3);   // a pad: +1 in its row
    expect(corridorLoad(r, belts, "down", [], [{ x: 12, y: 4, w: 1, h: 3 }, { x: 13, y: 5, w: 1, h: 1 }])).toBe(4);   // a 1×3 dock and a pad side by side
    expect(corridorLoad(r, belts, "down", [], [{ x: 11, y: 4, w: 1, h: 1 }])).toBe(2);   // on a belt's own tile: no new tile taken
    expect(corridorLoad(r, belts, "down", [], [{ x: 30, y: 4, w: 1, h: 3 }])).toBe(2);   // outside the corridor
    const across = { x: 0, y: 20, w: 10, h: 4 };
    expect(corridorLoad(across, [], "across", [], [{ x: 3, y: 21, w: 3, h: 1 }])).toBe(1);   // a dock along a row corridor: one per cross-section
    // in trafficGaps: the pads fill corridor 0 (4 belts + 1 pad in 6 tiles), corridor 1 has no pad and stays as it is
    const model = new Model(shop as unknown as CodeMap);
    const aisles = { cols: [{ x: 10, y: 0, w: 6, h: 10 }, { x: 30, y: 0, w: 6, h: 10 }], rows: [] };
    const four = (x0: number) => Array.from({ length: 4 }, (_, k) => down(x0 + k, 0, 10));
    const tf = { ...layoutTiles(model, SITE, []), aisles };
    expect(trafficGaps(tf, [...four(10), ...four(30)])).toBeUndefined();
    const withPad = { ...tf, stacks: [{ item: "h", topic: "h", x: 14, y: 5 }] };
    expect(trafficGaps(withPad, [...four(10), ...four(30)])).toEqual({ colGaps: [1, 0], rowGaps: [] });
  });

  it("per-gap widths widen only their own corridor, and an empty list keeps the default layout", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { doors } = demo.bundles(SITE);
    const a = layoutTiles(demo, SITE, doors), b = layoutTiles(demo, SITE, doors, { colGaps: [0, 3], rowGaps: [2] });
    expect(layoutTiles(demo, SITE, doors, { colGaps: [], rowGaps: [] })).toEqual(a);
    expect(a.aisles!.cols.length).toBeGreaterThan(1);
    expect(a.aisles!.rows.length).toBeGreaterThan(0);
    expect(b.aisles!.cols.map((r) => r.w)).toEqual(a.aisles!.cols.map((r, i) => r.w + (i === 1 ? 3 : 0)));
    expect(b.aisles!.rows.map((r) => r.h)).toEqual(a.aisles!.rows.map((r, j) => r.h + (j === 0 ? 2 : 0)));
  });

  it.runIf(BIG && existsSync(BIG))("the traffic pass widens a floor's full corridors, keeps the wider layout because it crosses less, and stays deterministic", () => {
    // a floor (no hub) where the pass wins: 23 crossings first, 16 widened. The demo had one (ReservationRepo.Live, 5 -> 4)
    // until plates kept off the factory walls (4b); its no-hub floors no longer have a winning pass, its site does (below).
    const demo = new Model(JSON.parse(readFileSync(BIG, "utf8")) as CodeMap);
    const c = "common_python::common_python.tools.market";
    const { bundles, doors } = demo.bundles(c);
    const first = layoutTiles(demo, c, doors, { gap: startGap(bundles) });
    const r1 = routeTiles(first, bundles);
    const want = trafficGaps(first, r1);
    expect(want, "floor has a full corridor").toBeDefined();
    const p = planFloor(demo, c, doors, bundles);
    expect(p.routes.filter((r) => r.failed)).toHaveLength(0);
    want!.colGaps.forEach((g, i) => expect(p.tf.aisles!.cols[i].w, `col ${i}`).toBe(first.aisles!.cols[i].w + g));
    want!.rowGaps.forEach((g, j) => expect(p.tf.aisles!.rows[j].h, `row ${j}`).toBe(first.aisles!.rows[j].h + g));
    expect([...want!.colGaps, ...want!.rowGaps].some((g) => g > 0)).toBe(true);
    expect(crossings(p.routes)).toBeLessThan(crossings(r1));
    checkTrunks(p.tf, p.routes, c);
    expect(planFloor(demo, c, doors, bundles)).toEqual(p);
  });

  it("the demo site's traffic pass, with pads reserved, is kept only when it crosses less", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const gap = startGap(bundles);
    const first = layFloor(demo, SITE, doors, bundles, { gap });
    const r1 = routeTiles(first, bundles);
    const want = trafficGaps(first, r1);
    expect(want, "demo site has a full corridor").toBeDefined();
    const second = layFloor(demo, SITE, doors, bundles, { gap, ...want });
    want!.colGaps.forEach((g, i) => expect(second.aisles!.cols[i].w, `col ${i}`).toBe(first.aisles!.cols[i].w + g));
    want!.rowGaps.forEach((g, j) => expect(second.aisles!.rows[j].h, `row ${j}`).toBe(first.aisles!.rows[j].h + g));
    const r2 = routeTiles(second, bundles), failed = (rs: TileRoute[]) => rs.filter((r) => r.failed).length;
    const taken = failed(r2) <= failed(r1) && crossings(r2) < crossings(r1);
    // both passes cross 39 (rail yards and stations, reservations-redis's chest and payments-webhook's receiving dock all
    // reserved): the widened pass must cross strictly less, so the first is kept
    expect([crossings(r1), crossings(r2), taken]).toEqual([39, 39, false]);
    const p = planFloor(demo, SITE, doors, bundles);
    expect(p.tf).toEqual(taken ? second : first);
    expect(p.routes.filter((r) => r.failed)).toHaveLength(0);
    checkTrunks(p.tf, p.routes, SITE);
    expect(planFloor(demo, SITE, doors, bundles)).toEqual(p);
  });

  // Readability at Fit: the viewer's floor area at 1440x900 with the panels open is about 1100x800 px; the scene's own
  // fitScale (no pad on floor 0, 60 px for the title, a 0.94 margin; no bottom inset assumed). A 14 px machine name should render at least 9 px tall.
  const demoFitScale = () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const { tf } = planFloor(demo, SITE, doors, bundles);
    const s = fitScale(tf.cols * T, tf.rows * T, 1100, 800, true, 0);
    console.log(`demo floor 0 at Fit: ${tf.cols}x${tf.rows} tiles, scale ${s.toFixed(3)}, 14 px name at ${(14 * s).toFixed(1)} px`);
    return s;
  };
  // 0.39 after the layout pass; 0.389 since plates keep off the walls (4b): the site's traffic pass now wins (41 -> 39
  // crossings) and widens a row corridor, two tiles taller
  it("demo floor 0 at Fit keeps the scale it has reached (0.389)", () => {
    expect(demoFitScale()).toBeGreaterThanOrEqual(0.385);
  });
  // Under zoom NAME_MIN_PX/14 a 14 px name renders under about 6 px, so the machines show their short codes instead
  // (codeZoom); the codes are drawn BIG px tall at the Fit zoom and must stay at least 9 px on screen there.
  it("demo floor 0 at Fit: the machine code label renders at least 9 px tall", () => {
    const s = demoFitScale();
    // so Fit shows codes, not names: the switch is the floor's own, from its smallest fitted name (scene.minName). With
    // the pads inside the machines (4c) Fit grew to 0.394, past the 14 px switch (0.391); the floor's smallest name is a
    // hub's (10 px), so its switch is 0.603 and Fit still shows codes (the e2e reads the mode at Fit in the browser)
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const minName = Math.min(...[...planFloor(demo, SITE, doors, bundles).tf.boxes.values()].filter((b) => b.foot !== "door")
      .map((b) => { const n = nameSpec(b); return fitName(demo.label(b.id), n.w, n.maxLines, n.sizes).size; }));
    expect(minName).toBe(10);
    expect(s).toBeLessThan(codeZoom(minName) - CODE_BAND);
    // the smallest footprint on the floor, a 3x3 hub, shrinks its code to fit: measure what is really drawn
    expect(bigCodeHeight(3 * T, 3 * T, s)).toBeGreaterThanOrEqual(9);
    expect(bigCodeHeight(7 * T, 3 * T, s)).toBeGreaterThanOrEqual(9);   // and a door
  });

  // Zone names at Fit: a name grows up and along its row into room clear of everything drawn, or hides.
  const zoneLabelsAt = (tf: ReturnType<typeof planFloor>["tf"], routes: TileRoute[], zoom: number) => {
    const clear = new Clearance(floorObstacles(tf, routes), tf.cols + 8);
    return tf.zones.map((z) => {
      const plan = planZoneLabel({ ...z, name: z.name.toUpperCase() }, clear);
      const k = Math.min(plan.maxK, Math.max(1, MIN_PX / (ZONE_FONT * zoom)));
      return { z, plan, k, shown: ZONE_FONT * zoom * k >= MIN_PX - 0.1 };
    });
  };
  /** Obstacles listed straight from the floor (not through floorObstacles): machines with shadow and chimney room, lanes, pieces, drone paths. */
  const drawn = (tf: ReturnType<typeof planFloor>["tf"], routes: TileRoute[]): PxRect[] => {
    const o: PxRect[] = [];
    for (const b of tf.boxes.values()) o.push({ x0: b.x * T, y0: b.y * T - 16, x1: (b.x + b.w) * T + 5, y1: (b.y + b.h) * T + 5 });
    for (const l of tf.lanes) o.push({ x0: l.x0 * T, y0: l.y * T, x1: l.x1 * T, y1: (l.y + LANE_H) * T });
    for (const r of routes) {
      for (const p of r.pieces) o.push({ x0: p.x * T, y0: p.y * T, x1: p.x * T + T, y1: p.y * T + T });
      if (!r.pieces.length) for (let i = 1; i < r.points.length; i++) {
        const a = r.points[i - 1], b = r.points[i];
        o.push({ x0: Math.min(a.x, b.x) - 3, y0: Math.min(a.y, b.y) - 3, x1: Math.max(a.x, b.x) + 3, y1: Math.max(a.y, b.y) + 3 });
      }
    }
    return o;
  };
  const touch = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;

  it("demo floor 0 at Fit: every shown zone name overlaps no machine, piece, lane, drone path or other name, and stays in its zone", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const { tf, routes } = planFloor(demo, SITE, doors, bundles);
    const s = fitScale(tf.cols * T, tf.rows * T, 1100, 800, true, 0);
    const labels = zoneLabelsAt(tf, routes, s), others = drawn(tf, routes);
    const shown = labels.filter((l) => l.shown);
    for (const l of shown) {
      const b = labelBox(l.plan, l.k);
      expect(b.x0 >= l.z.x * T && b.x1 <= (l.z.x + l.z.w) * T && b.y0 >= l.z.y * T && b.y1 <= (l.z.y + l.z.h) * T, `${l.z.name} inside its zone`).toBe(true);
      expect(others.filter((o) => touch(b, o)), `${l.z.name} touches something`).toHaveLength(0);
      for (const m of shown) if (m !== l) expect(touch(b, labelBox(m.plan, m.k)), `${l.z.name} / ${m.z.name}`).toBe(false);
    }
    console.log(`demo floor 0 at Fit ${s.toFixed(3)}: ${shown.length} of ${labels.length} zone names show: ${shown.map((l) => l.z.name).join(", ")}; hidden: ${labels.filter((l) => !l.shown).map((l) => `${l.z.name} (room x${l.plan.maxK}, needs x${(MIN_PX / (ZONE_FONT * s)).toFixed(2)})`).join(", ")}`);
    expect(shown.length).toBeGreaterThan(0);
    for (const n of ["kafka", "pubsub", "sqs"]) { const l = labels.find((q) => q.z.name.toLowerCase() === n); if (l) expect(l.shown, n).toBe(true); }
  });

  it("a zone name with no clear room is hidden at Fit, and planning is deterministic", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const { tf, routes } = planFloor(demo, SITE, doors, bundles);
    expect(zoneLabelsAt(tf, routes, 0.394)).toEqual(zoneLabelsAt(tf, routes, 0.394));
    const z = { name: "BOXED", x: 0, y: 0, w: 3, h: 2, airfield: false };
    const wall = new Clearance([{ x0: 0, y0: 0, x1: 3 * T, y1: 2 * T }]);
    const p = planZoneLabel(z, wall);
    expect(p.clear).toBe(false);
    expect(ZONE_FONT * 0.394 * Math.min(p.maxK, MIN_PX / (ZONE_FONT * 0.394))).toBeLessThan(MIN_PX - 0.1);
  });

  // The owner (2026-10-06): names were still readable two wheel notches further out. One notch is x e^-0.2 (deltaY 100,
  // exp(-deltaY / 500)), so names now hold until a name would render under 9 px x e^-0.4, about 6 px.
  it("one floor-wide codes switch from the smallest fitted name: names show only when every name renders at least 9·e^-0.4 px (two wheel notches past 9 px)", () => {
    expect(NAME_MIN_PX).toBeCloseTo(9 * Math.exp(-0.4), 6);
    expect(NAME_MIN_PX).toBeCloseTo(6.03, 2);
    expect(codeZoom(10)).toBeCloseTo(0.603, 3);
    expect(codeZoom(14) / (9 / 14)).toBeCloseTo(Math.exp(-0.4), 6);   // exactly two notches further out than the old 9 px switch
    expect(codesMode(0.603 - CODE_BAND - 0.01, false, 10)).toBe(true);
    expect(codesMode(0.603 - CODE_BAND + 0.01, false, 10)).toBe(false);   // names hold until under 0.563 ... when coming from names
    expect(codesMode(0.603 + CODE_BAND - 0.01, true, 10)).toBe(true);     // codes hold until over 0.643 ... when coming from codes
    expect(codesMode(0.603 + CODE_BAND + 0.01, true, 10)).toBe(false);
    for (const min of [9, 10, 11, 12, 14]) for (let z = 0.1; z < 3; z += 0.01) if (!codesMode(z, false, min)) expect(min * z, `${min} px names at ${z}`).toBeGreaterThanOrEqual(NAME_MIN_PX - 0.1 - min * CODE_BAND);
    for (const min of [9, 10, 11, 12, 14]) for (let z = 0.1; z < 3; z += 0.01) if (!codesMode(z, true, min)) expect(min * z, `${min} px names at ${z} from codes`).toBeGreaterThanOrEqual(NAME_MIN_PX);
    // a name at the old 9 px switch, and one wheel notch out from there, still shows (coming from names)
    for (const min of [10, 14]) { expect(codesMode(9 / min, false, min)).toBe(false); expect(codesMode((9 / min) * Math.exp(-0.2), false, min)).toBe(false); }
  });

  it("a sub line hides on its own under 9 px, in names mode too, and in codes mode always", () => {
    expect(subShown(10, 0.85, false)).toBe(false);
    expect(subShown(10, 0.9, false)).toBe(true);
    expect(subShown(11, 0.85, false)).toBe(true);
    expect(subShown(11, 0.8, false)).toBe(false);
    expect(subShown(11, 2, true)).toBe(false);
  });

  it("in names mode no small text renders under 9 px (code tabs, role tags, door headings, sub lines, utility tabs), and no name under 9·e^-0.4 px", () => {
    const smalls = [9.5, 10, 10.5, 11];   // role tag and door heading 9.5, sub lines 10 / 11, code tab 10.5, utility tab 11
    for (const minName of [9, 10, 11, 12, 13, 14]) {
      let was = true;
      for (let z = 0.1; z < 3; z += 0.01) {
        was = codesMode(z, was, minName);
        for (const n of smalls) if (subShown(n, z, was)) expect(n * z, `${n} px text at ${z.toFixed(2)}`).toBeGreaterThanOrEqual(9 - 0.1);
        if (!was) expect(minName * z, `${minName} px name at ${z.toFixed(2)}`).toBeGreaterThanOrEqual(NAME_MIN_PX - 0.1);
        if (was) for (const n of smalls) expect(subShown(n, z, was)).toBe(false);   // codes mode: only the big codes
      }
    }
    expect(subShown(9.5, 0.9, false)).toBe(false);   // a role tag waits for zoom 0.95
    expect(subShown(9.5, 0.95, false)).toBe(true);
  });

  it("a lane name is placed for its scaled width, in the first gap that holds it or else the widest", () => {
    // crossings at 300 and 400 leave gaps of 6..294 | 308.. | 408..: a 100 px label at 3x needs 300 px
    expect(laneLabelSpot(0, 1000, 100, [300, 400], 3).x).toBe(408);
    expect(laneLabelSpot(0, 1000, 100, [300, 400], 1).x).toBe(6);
    const w = laneLabelSpot(0, 500, 100, [100, 340], 3);   // no gap holds 300: the widest (108..334) wins
    expect([w.x, w.room]).toEqual([108, 226]);
    expect(laneLabelSpot(0, 1000, 100, [], 3)).toEqual({ x: 6, room: 988 });
  });

  // Floors with no hub lay out and route exactly as before pads existed: digests of every such floor's plan, taken at
  // 430d94d (before this change). A map with no topic at all (the big map) is all such floors. Re-taken once, on purpose,
  // when junction plates were kept off the factory walls (4b): that router rule moves trunks on every kind of floor.
  // Floors with an implements pair are left out (their implementations moved beside their interfaces, tested below):
  // the value without them is the same at 8609117 and after. Floors with a rail yard are left out too (tested below):
  // the value without them is the same at f3379ab and after.
  const noHubDigest = (m: Model) => {
    const h = createHash("sha256");
    let n = 0;
    for (const c of Object.keys(m.map.layout.containers)) {
      if (m.implementLinks(c).length) continue;
      const { bundles, doors } = m.bundles(c);
      const p = planFloor(m, c, doors, bundles);
      if (messaging(m, c, p.tf, bundles).airfields.length) continue;
      if (p.tf.rails) continue;   // rail yards and stations have their place (tested below)
      expect(p.landing, c).toBeUndefined();
      expect(p.tf.landing ?? p.tf.stacks, c).toBeUndefined();
      n++;
      h.update(JSON.stringify([c, p.gap, { ...p.tf, boxes: [...p.tf.boxes.values()] }, p.routes]));
    }
    return `${n} ${h.digest("hex").slice(0, 16)}`;
  };
  it("a floor with no hub plans exactly as before: fixture and demo", () => {
    expect(noHubDigest(new Model(shop as unknown as CodeMap))).toBe("18 a620026f9ac43394");
    expect(noHubDigest(new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap))).toBe("101 0ea4d7fb420af3bf");   // demo re-pinned at scanner 0.6.0: three name-matched calls the scanner no longer draws; the previous map still gives the old digest
  });
  it.runIf(BIG && existsSync(BIG))("a map with no topics plans every floor exactly as before (the big map)", () => {
    expect(noHubDigest(new Model(JSON.parse(readFileSync(BIG, "utf8"))))).toBe("371 8095edabe5f0f113");
  });

  /** Pads inside their machines, on the bottom row from the right (leftmost tile free), in hub order and holding no floor
   *  tile; docks against the machine side facing their hub, outside every box, lane and stack, apart, with no line on them. */
  const checkLanding = (tf: TileFloor, routes: TileRoute[], l: Landing, c: string) => {
    const m = l.messaging;
    const pushes = m.consumers.filter((q) => q.subscription === "push");
    expect(l.pads.length, `${c} one pad per producer, consumer group and failure`).toBe(m.producers.length + m.consumers.length - pushes.length + m.failures.length);
    expect(l.docks.length, `${c} one dock per push subscription`).toBe(pushes.length);
    const one = <X,>(list: X[], what: string) => { expect(list, `${c} ${what}`).toHaveLength(1); return list[0]; };
    for (const p of m.producers) expect(one(l.pads.filter((q) => q.role === "produce" && q.machine === p.machine && q.item === p.item), `produce pad ${p.machine}`).flight).toBe(p.flight);
    for (const f of m.failures) expect(one(l.pads.filter((q) => q.role === "failure" && q.machine === f.machine && q.item === f.item), `failure pad ${f.machine}`).topic).toBe(f.dlq);
    for (const k of m.consumers) {
      const mine = (q: { machine: string; item: string; group?: string }) => q.machine === k.machine && q.item === k.item && q.group === k.group;
      if (k.subscription === "push") expect(one(l.docks.filter(mine), `dock ${k.machine}`)).toMatchObject({ role: "consume", flight: "push" });
      else expect(one(l.pads.filter((q) => q.role === "consume" && mine(q)), `consume pad ${k.machine} ${k.group}`).flight).toBe(k.flight);
    }
    const out = (b: Rect, side: string): Rect => side === "n" ? { x: b.x, y: b.y - 1, w: b.w, h: 1 } : side === "s" ? { x: b.x, y: b.y + b.h, w: b.w, h: 1 }
      : side === "w" ? { x: b.x - 1, y: b.y, w: 1, h: b.h } : { x: b.x + b.w, y: b.y, w: 1, h: b.h };
    const within = (r: Rect, o: Rect) => r.x >= o.x && r.y >= o.y && r.x + r.w <= o.x + o.w && r.y + r.h <= o.y + o.h;
    const ov = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    expect(l.unplaced, `${c} every flight has its landing place`).toEqual([]);
    // pads: a machine's pads fill its bottom row's rightmost tiles, left to right in the order of their hubs
    for (const id of new Set(l.pads.map((p) => p.machine))) {
      const b = tf.boxes.get(id)!, mine = l.pads.filter((p) => p.machine === id).sort((p, q) => p.x - q.x);
      expect(mine.length, `${c} ${id}: the leftmost tile of the bottom row stays for the sub line`).toBeLessThanOrEqual(b.w - 1);
      mine.forEach((p, i) => {
        expect(p.inside, `${c} ${id} pad inside`).toBe(true);
        expect([p.x, p.y], `${c} ${id} pad ${i} on the bottom row from the right`).toEqual([b.x + b.w - mine.length + i, b.y + b.h - 1]);
        const mark = padMark(p);
        expect(mark.x >= b.x * T && mark.x + mark.w <= (b.x + b.w) * T && mark.y >= (b.y + b.h - 1) * T && mark.y + mark.h <= (b.y + b.h) * T, `${c} ${id} mark inside its tile`).toBe(true);
        if (i) { const hx = (q: { item: string }) => { const h = tf.boxes.get(q.item)!; return h.x + h.w / 2; }; expect(hx(mine[i - 1]), `${c} ${id} pads in hub order`).toBeLessThanOrEqual(hx(p)); }
      });
    }
    // reserved floor tiles are the docks and stacks only: no pad among them
    const all: [string, Rect][] = [
      ...l.docks.map((d) => [`dock ${d.machine}`, d] as [string, Rect]),
      ...l.stacks.map((s) => [`stack ${s.item}`, { x: s.x, y: s.y, w: 1, h: 1 }] as [string, Rect]),
    ];
    expect(reservedRects(tf).slice(0, all.length)).toEqual(all.map(([, r]) => ({ x: r.x, y: r.y, w: r.w, h: r.h })).sort((p, q) => Number(p.w > 1 || p.h > 1) - Number(q.w > 1 || q.h > 1)));
    const hooks = (tf.webhooks ?? []).map((d) => ({ x: d.x, y: d.y, w: d.w, h: d.h }));   // the site's inbound webhook docks
    expect(reservedRects(tf).slice(all.length), `${c} the rest are the webhook docks' and the rails' tiles`).toEqual([...hooks, ...railRects(tf)]);
    for (const x of l.docks) {
      const b = tf.boxes.get(x.machine)!;
      expect(within(x, out(b, x.side)), `${c} ${x.machine} ${x.item}: touches its ${x.side} side`).toBe(true);
      expect([x.w, x.h], `${c} dock 1×3 along its side`).toEqual(x.side === "n" || x.side === "s" ? [3, 1] : [1, 3]);
      // the side faces its hub: the airfield on the site, the hub's door inside
      const air = tf.site ? tf.zones.find((z) => z.airfield && z.name === x.item.split(":")[1]) : undefined, t = air ?? tf.boxes.get(x.item)!;
      const dx = t.x + t.w / 2 - (b.x + b.w / 2), dy = t.y + t.h / 2 - (b.y + b.h / 2);
      const toward = { n: -dy, s: dy, w: -dx, e: dx }[x.side];
      expect(toward, `${c} ${x.machine} ${x.item}: side ${x.side} faces its hub`).toBeGreaterThan(0);
    }
    for (const [name, r] of all) {
      for (const b of tf.boxes.values()) expect(ov(r, b), `${c} ${name} on ${b.id}`).toBe(false);
      for (const ln of tf.lanes) expect(ov(r, { x: ln.x0, y: ln.y, w: ln.x1 - ln.x0, h: LANE_H }), `${c} ${name} on lane ${ln.id}`).toBe(false);
      expect(r.x >= 0 && r.y >= 0 && r.x + r.w <= tf.cols && r.y + r.h <= tf.rows, `${c} ${name} on the floor`).toBe(true);
      for (const [other, o] of all) if (other !== name) expect(ov(r, o), `${c} ${name} on ${other}`).toBe(false);
      for (const q of routes) for (const p of q.pieces) expect(inside(r, p.x, p.y), `${c} ${q.key} runs ${p.under ? "under" : "over"} ${name}`).toBe(false);
    }
  };

  it("demo and fixture: every flight has its pad (inside its machine) or dock (on the side facing its hub), and no line runs through a dock or stack", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    let pads = 0, docks = 0, floors = 0;
    for (const [m, label] of [[demo, "demo"], [new Model(shop as unknown as CodeMap), "fixture"]] as const) {
      for (const c of Object.keys(m.map.layout.containers)) {
        const { bundles, doors } = m.bundles(c);
        const p = planFloor(m, c, doors, bundles);
        expect(p.routes.filter((r) => r.failed), `${label} ${c}`).toHaveLength(0);
        checkTrunks(p.tf, p.routes, `${label} ${c}`);
        for (const r of p.routes) if (r.pieces.length) plugged(p.tf, r);
        if (!p.landing) continue;
        expect(p.tf.landing).toBe(p.landing);
        floors++;
        pads += p.landing.pads.length;
        docks += p.landing.docks.length;
        checkLanding(p.tf, p.routes, p.landing, `${label} ${c}`);
        expect(planFloor(m, c, doors, bundles), `${label} ${c} deterministic`).toEqual(p);
      }
    }
    console.log(`pads: ${pads} pads and ${docks} docks on ${floors} floors`);
    expect(docks).toBeGreaterThanOrEqual(2);   // city-dashboard's push, on the site and inside it
  });

  it("demo site: the push consumer gets a dock facing pubsub, billing a copy pad and a failure pad, the workers their pads", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const { bundles, doors } = demo.bundles(SITE);
    const { tf, landing } = planFloor(demo, SITE, doors, bundles);
    const dash = tf.boxes.get("svc:city-dashboard")!, bay = tf.boxes.get("topic:pubsub:bay-status")!;
    expect(bay.x + bay.w).toBeLessThan(dash.x);
    expect(landing!.docks).toEqual([{ machine: "svc:city-dashboard", item: "topic:pubsub:bay-status", topic: "topic:pubsub:bay-status", role: "consume", group: "bay-status-dashboard", flight: "push", x: dash.x - 1, y: dash.y + 1, w: 1, h: 3, side: "w" }]);
    const of = (id: string) => landing!.pads.filter((p) => p.machine === id).map((p) => `${p.role} ${p.flight} ${p.item}${p.group ? ` ${p.group}` : ""}`);
    expect(of("svc:billing")).toEqual(["consume copy topic:kafka:reservation-events billing", "failure failure topic:kafka:reservation-events.dlq"]);
    expect(of("svc:enforcement-worker")).toEqual(["consume take topic:sqs:violations.fifo"]);
    expect(of("svc:occupancy")).toEqual(["produce enqueue topic:sqs:violations.fifo"]);
    expect(of("svc:analytics-loader")).toEqual(["consume pull topic:pubsub:bay-status bay-status-analytics"]);
    // two pads on one machine sit side by side on its bottom row, from the right, in the order of their hubs: billing's
    // copy (reservation-events) left of its failure (the dlq right of it)
    const bill = tf.boxes.get("svc:billing")!;
    const [copy, fail] = landing!.pads.filter((p) => p.machine === "svc:billing");
    expect([copy.x, copy.y, fail.x, fail.y]).toEqual([bill.x + bill.w - 2, bill.y + bill.h - 1, bill.x + bill.w - 1, bill.y + bill.h - 1]);
    expect(landing!.stacks.map((s) => s.item)).toEqual(["topic:sqs:violations-dead.fifo", "topic:sqs:violations.fifo"]);
  });

  it("one pad per role and group: a machine consuming in two groups and producing to the same hub gets three pads", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    const base = map.relations.find((r) => r.kind === "event" && r.from === "topic:kafka:reservation-events" && r.group === "notifier")!;
    map.relations.push({ ...base, id: `${base.id}:audit`, group: "audit" },
      { ...base, id: "r:event:notifier-produces", from: base.to, to: base.from, group: undefined });
    const m = new Model(map);
    const { bundles, doors } = m.bundles(SITE);
    const p = planFloor(m, SITE, doors, bundles);
    const mine = p.landing!.pads.filter((q) => q.machine === "svc:notifier");
    expect(mine.map((q) => `${q.role} ${q.group ?? ""}`)).toEqual(["produce ", "consume audit", "consume notifier"]);
    expect(new Set(mine.map((q) => `${q.x},${q.y}`)).size).toBe(3);
    checkLanding(p.tf, p.routes, p.landing!, "notifier x3");
    checkTrunks(p.tf, p.routes, "notifier x3");
    expect(p.routes.filter((r) => r.failed)).toHaveLength(0);
  });

  it("a dock with no free side, and a pad past its machine's bottom row, are recorded as unplaced, not dropped silently", () => {
    const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
    // notifier takes reservation-events in four more groups: five consume pads on a 5-wide machine, which keeps one tile
    const base = map.relations.find((r) => r.kind === "event" && r.from === "topic:kafka:reservation-events" && r.group === "notifier")!;
    for (const g of ["audit", "mail", "sms", "trace"]) map.relations.push({ ...base, id: `${base.id}:${g}`, group: g });
    const demo = new Model(map);
    const { bundles, doors } = demo.bundles(SITE);
    const tf = layoutTiles(demo, SITE, doors);
    const d = tf.boxes.get("svc:city-dashboard")!;
    // wall city-dashboard in: every tile round it is a waiting stack, so no side has room for its dock
    const ring = [];
    for (let x = d.x - 1; x <= d.x + d.w; x++) ring.push({ x, y: d.y - 1 }, { x, y: d.y + d.h });
    for (let y = d.y; y < d.y + d.h; y++) ring.push({ x: d.x - 1, y }, { x: d.x + d.w, y });
    tf.stacks = [...(tf.stacks ?? []), ...ring.map((t) => ({ item: "wall", topic: "wall", ...t }))];
    const l = landing(demo, SITE, tf, bundles)!;
    expect(l.docks).toEqual([]);
    expect(l.pads.filter((p) => p.machine === "svc:notifier").map((p) => p.group)).toEqual(["audit", "mail", "notifier", "sms"]);
    expect(l.unplaced).toEqual([
      { machine: "svc:city-dashboard", item: "topic:pubsub:bay-status", topic: "topic:pubsub:bay-status", role: "consume", group: "bay-status-dashboard", flight: "push", dock: true },
      { machine: "svc:notifier", item: "topic:kafka:reservation-events", topic: "topic:kafka:reservation-events", role: "consume", group: "trace", flight: "copy", dock: false },
    ]);
    expect(l.pads.some((p) => p.machine === "svc:billing")).toBe(true);   // walls round a machine never stop its pads: they are inside it
  });

  it.runIf(BIG && existsSync(BIG))("plans every floor of a real 1,600-node map quickly, at most 1% failed, tunnels straight", () => {
    const big = new Model(JSON.parse(readFileSync(BIG, "utf8")));
    let worst = 0, failed = 0, total = 0, widened = 0, trunks = 0, area = 0;
    for (const c of Object.keys(big.map.layout.containers)) {
      const { bundles, doors } = big.bundles(c);
      const t0 = performance.now();
      const { tf, routes, gap } = planFloor(big, c, doors, bundles);
      worst = Math.max(worst, performance.now() - t0);
      failed += routes.filter((r) => r.failed).length;
      total += routes.length;
      if (gap > startGap(bundles)) widened++;
      if (routes.some((r) => r.pieces.some((p) => p.join))) trunks++;
      area = Math.max(area, tf.cols * tf.rows);
      for (const r of routes) {
        for (const p of r.pieces) if (p.under) expect(p.in, `${c} ${r.key}`).toBe(p.out);
        if (r.pieces.length) {
          expect(r.pieces[0].under, r.key).toBe(false);
          expect(r.pieces[r.pieces.length - 1].under, r.key).toBe(false);
        }
      }
      checkTrunks(tf, routes, c);
      for (const r of routes) if (r.pieces.length) plugged(tf, r);
    }
    console.log(`big map: worst ${worst.toFixed(0)} ms, failed ${failed}, widened ${widened}, trunks ${trunks}, largest ${area} tiles`);
    expect(worst).toBeLessThan(250);
    expect(failed).toBeLessThanOrEqual(Math.ceil(total * 0.01));   // a correct picture beats 0 failed: a few stay dashed
  });

  // the owner's congested floor: method lines of order.py bundle into trunks instead of filling every corridor
  it.runIf(BIG && existsSync(BIG))("bundles order.py's lines: at least 23% fewer belt tiles on top, no more crossings", () => {
    const big = new Model(JSON.parse(readFileSync(BIG, "utf8")));
    const c = "common_python::common_python.tools.order";
    const { bundles, doors } = big.bundles(c);
    const { tf, routes } = planFloor(big, c, doors, bundles);
    expect(routes.length, "order.py floor not found").toBeGreaterThan(0);
    const top = new Set<number>();
    for (const r of routes) for (const p of r.pieces) if (!p.under) top.add(p.y * tf.cols + p.x);
    const crossed = crossings(routes);   // a trunk going under is one crossing, however many ride it
    console.log(`order.py: ${top.size} belt tiles on top, ${crossed} crossings`);
    // baseline before trunks by default (41731c4): 1629 tiles on top, 76 crossings.
    // Re-measured at d44af58 (trunks, old 4x3 corridors, gap 2): 902 tiles, 43 crossings, floor 80x53.
    // With the roomier base corridors (6x4) and startGap 1 (this change): 1091 tiles, 54 crossings, floor 90x53 --
    // longer belts for the room the owner asked for, still 33% under the baseline.
    // With ends off the corner tiles (cost 3) and room round every junction (straight trunk, plain tiles either side): 1164 tiles, 49 crossings
    // -- 71.5% of the baseline: the room the owner asked for costs about 2 points of the 30% saving.
    // The traffic pass widens its fullest row corridor (4 belts in 5 tiles), but that crosses no less (49), so the
    // first result is kept: 1164 tiles, 49 crossings.
    // With every junction plate kept off the factory walls (4b, the owner's rule): 1241 tiles, 53 crossings -- 76.2% of the
    // baseline. A rider splits or merges only on a trunk tile no machine touches, so on this narrow floor some run
    // beside the trunk a little longer: the plates the owner asked to keep clear cost about 5 points of the saving.
    expect(top.size).toBeLessThanOrEqual(Math.floor(1629 * 0.77));
    expect(crossed).toBeLessThanOrEqual(76);
  });

  it.runIf(BIG && existsSync(BIG))("big map: no two boxes overlap, no lane runs over a box, and every underground housing is painted after every body on its tile", () => {
    const big = new Model(JSON.parse(readFileSync(BIG, "utf8")));
    const ov = (a: { x: number; y: number; w: number; h: number }, b: { x: number; y: number; w: number; h: number }) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    let housings = 0, composedFail = 0;
    for (const c of Object.keys(big.map.layout.containers)) {
      const { bundles, doors } = big.bundles(c);
      const { tf, routes } = planFloor(big, c, doors, bundles);
      const bs = [...tf.boxes.values()];
      for (let i = 0; i < bs.length; i++) for (let j = i + 1; j < bs.length; j++) expect(ov(bs[i], bs[j]), `${c}: ${bs[i].id} x ${bs[j].id}`).toBe(false);
      for (const l of tf.lanes) for (const b of bs) expect(ov({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H }, b), `${c}: lane ${l.id} x ${b.id}`).toBe(false);
      const ops = factoryOps(routes.map((r) => ({ pieces: r.pieces, kind: r.kind, failed: r.failed, inferred: false })), tf.cols);
      for (const a of tileArms(routes.map((r) => ({ pieces: r.pieces, kind: r.kind, failed: r.failed, both: r.both })), tf.cols).values()) {
        const body = bodyFor(a);
        if (!body || (body.branches.length > 0 && a.joins.length === 0)) { composedFail++; process.stderr.write(`FALLBACK ${c} ${a.x},${a.y} ${JSON.stringify([...a.edges])} joins ${a.joins}\n`); }
      }
      const lastBody = new Map<number, number>(), firstHousing = new Map<number, number>();
      ops.forEach((o, i) => {
        const k = o.p.y * tf.cols + o.p.x;
        if (o.layer === "body" || o.layer === "tile") lastBody.set(k, i);
        else if (o.layer === "housing" && !firstHousing.has(k)) firstHousing.set(k, i);
        else if (o.layer === "plate") expect(firstHousing.has(k) || !routes.some((r) => r.pieces.some((p) => p.y * tf.cols + p.x === k && (p.hoodBefore || p.hoodAfter))), `${c} plate before housing`).toBe(true);
      });
      for (const r of routes) if (!r.failed) for (const p of r.pieces) if (!p.under && (p.hoodBefore || p.hoodAfter)) {
        const k = p.y * tf.cols + p.x;
        housings++;
        expect(firstHousing.get(k)!, `${c} ${p.x},${p.y}`).toBeGreaterThan(lastBody.get(k)!);
      }
    }
    expect(housings).toBeGreaterThan(0);
    expect(composedFail, "shared belt tiles that are no trunk with branches").toBe(0);
  });

  // A floor with no implements pair lays out and routes exactly as before implementations moved beside their
  // interfaces: digests of every such floor's whole plan (hub floors and their landing included), taken at 8609117.
  // The fixture and the big map (an older scanner) carry no `implements` at all: every floor is such a floor. Floors with
  // a rail yard are left out (tested below): the value without them is the same at f3379ab and after.
  const noPairDigest = (m: Model) => {
    const h = createHash("sha256");
    const flat = (_k: string, v: unknown) => (v instanceof Map ? [...v.entries()] : v instanceof Set ? [...v] : v);
    let n = 0;
    for (const c of Object.keys(m.map.layout.containers)) {
      if (m.implementLinks(c).length) continue;
      const { bundles, doors } = m.bundles(c);
      const p = planFloor(m, c, doors, bundles);
      if (p.tf.rails) continue;   // rail yards and stations have their place (tested below)
      n++;
      h.update(JSON.stringify([c, p.gap, { ...p.tf, boxes: [...p.tf.boxes.values()] }, p.routes, p.landing], flat));
    }
    return `${n} ${h.digest("hex").slice(0, 16)}`;
  };
  it("a floor with no implements pair plans exactly as before: fixture and demo", () => {
    expect(noPairDigest(new Model(shop as unknown as CodeMap))).toBe("24 53826f345d063535");
    expect(noPairDigest(new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap))).toBe("126 2315caa2841b3692");   // demo re-pinned at scanner 0.6.0: three name-matched calls the scanner no longer draws; the previous map still gives the old digest
  });
  it.runIf(BIG && existsSync(BIG))("a floor with no implements pair plans exactly as before (the big map)", () => {
    expect(noPairDigest(new Model(JSON.parse(readFileSync(BIG, "utf8"))))).toBe("371 3d5be224c7fe339d");
  });

  // A floor with no rail yard lays out and routes exactly as before yards and stations had their place: digests of
  // every such floor's whole plan (hub floors and their landing, implements pairs included), taken at f3379ab (before
  // this change). The fixture's one batch relation is stripped, so all its floors count; the big map has none at all.
  // The fixture's cache has its `store` stripped too, so its site floor plans with the cache on a lane as before chests
  // (a single-owner cache is a chest, tested in factory_layout) and stays in the digest, at its value from f3379ab.
  const noBatchDigest = (m: Model) => {
    const h = createHash("sha256");
    const flat = (_k: string, v: unknown) => (v instanceof Map ? [...v.entries()] : v instanceof Set ? [...v] : v);
    let n = 0;
    for (const c of Object.keys(m.map.layout.containers)) {
      const { bundles, doors } = m.bundles(c);
      const p = planFloor(m, c, doors, bundles);
      if (p.tf.rails) continue;
      n++;
      h.update(JSON.stringify([c, p.gap, { ...p.tf, boxes: [...p.tf.boxes.values()] }, p.routes, p.landing], flat));
    }
    return `${n} ${h.digest("hex").slice(0, 16)}`;
  };
  const noBatch = (map: CodeMap): CodeMap => ({ ...map, relations: map.relations.filter((r) => r.kind !== "batch") });
  const noStore = (map: CodeMap): CodeMap => ({ ...map, nodes: map.nodes.map(({ store: _s, ...n }) => n) });
  it("a floor with no rail yard plans exactly as before: fixture (its batch relation stripped) and demo", () => {
    expect(noBatchDigest(new Model(noStore(noBatch(shop as unknown as CodeMap))))).toBe("25 bb5d026dd2644e94");
    expect(noBatchDigest(new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap))).toBe("130 7fa61c1c9ef4bbd4");   // demo re-pinned at scanner 0.6.0: three name-matched calls the scanner no longer draws; the previous map still gives the old digest
  });
  it("demo and fixture: every rail yard and station has its place, and every rail runs from its yard to its station", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    let rails = 0, yards = 0, stations = 0, floors = 0;
    for (const [m, label] of [[demo, "demo"], [new Model(shop as unknown as CodeMap), "fixture"]] as const) {
      for (const c of Object.keys(m.map.layout.containers)) {
        const { bundles, doors } = m.bundles(c);
        const p = planFloor(m, c, doors, bundles);
        expect(p.routes.filter((r) => r.failed), `${label} ${c}`).toHaveLength(0);
        checkTrunks(p.tf, p.routes, `${label} ${c}`);
        for (const r of p.routes) if (r.pieces.length) plugged(p.tf, r);
        // a floor has rails when its batch has a yard, or a job comes in by a door to an item on it (a yard-less station)
        const inbound = bundles.some((b) => b.kind === "batch" && [b.a, b.b].some((id) => p.tf.boxes.get(id)?.foot === "door") && [b.a, b.b].every((id) => p.tf.boxes.has(id)));
        expect(!!p.tf.rails, `${label} ${c} has rails exactly when its batch has a yard or a door brings a job in`).toBe(batch(m, c, p.tf, bundles).yards.length > 0 || inbound);
        if (!p.tf.rails) continue;
        floors++;
        yards += p.tf.rails.yards.length;
        stations += p.tf.rails.stations.length;
        rails += checkRails(p.tf, p.routes, bundles, `${label} ${c}`);
        expect(planFloor(m, c, doors, bundles), `${label} ${c} deterministic`).toEqual(p);
      }
    }
    console.log(`rails: ${yards} yards, ${stations} stations, ${rails} rails from a platform to a station, on ${floors} floors`);
    expect(rails, "a routed rail per station").toBe(stations);
    // 30 stations at platforms, and 3 yard-less: demand-forecast's reference task coming in by its door to the features
    // floors (svc:feature-store, features/, features.workflows)
    expect([floors, yards, stations]).toEqual([20, 22, 33]);
  });

  it("demo: F0's yards, demand-forecast's rail to feature-store's station, and the inner yards at their scheduler's door", () => {
    const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    const plan = (c: string) => { const { bundles, doors } = demo.bundles(c); return planFloor(demo, c, doors, bundles); };
    const site = plan(SITE), r = site.tf.rails!;
    const yard = (rs: typeof r, s: string) => rs.yards.find((y) => y.source === s)!;
    // the reference task: a 4x1 yard (one platform row, no header) beside demand-forecast, its sign beside it
    const df = yard(r, "svc:demand-forecast");
    expect(df).toMatchObject({ machine: "svc:demand-forecast", w: 4, h: 1, platforms: [{ dest: "svc:feature-store" }] });
    expect(df.sign).not.toBeNull();
    const st = r.stations.find((s) => s.dest === "svc:feature-store")!;
    expect(st.source).toBe("svc:demand-forecast");
    const rail = site.routes.find((q) => q.key === "svc:demand-forecast|svc:feature-store")!;
    expect(rail.kind).toBe("rail");
    const last = rail.pieces[rail.pieces.length - 1];
    expect([last.x, last.y]).toEqual([st.entry.x, st.entry.y]);
    // self-scheduled: a 4x1 strip holding a parked train and the sign, no platform, no track
    for (const s of ["svc:nightly-jobs", "svc:feature-store"]) {
      const y = yard(r, s);
      expect(y, s).toMatchObject({ machine: s, w: 4, h: 1, platforms: [] });
      expect(inside(y, y.sign!.x, y.sign!.y), s).toBe(true);
    }
    // nightly-jobs' inner floor: the yard stands free in the in column, one free row below the door its jobs come in by
    const nj = plan("svc:nightly-jobs"), y = nj.tf.rails!.yards[0], door = nj.tf.boxes.get("door:svc:nightly-jobs")!;
    expect(y).toMatchObject({ source: "svc:nightly-jobs", machine: "door:svc:nightly-jobs", side: "e", out: "e", free: true, x: door.x, y: door.y + door.h + 1, platforms: [{ dest: "jobs/dags::dags/" }] });
    expect(door.region).toBe("in");
    // one floor down: ten platforms in a 10-row yard (5 wide: a ladder's throat), ten stations, ten rails sharing trunks out of the yard
    const dags = plan("jobs/dags::dags/"), dy = dags.tf.rails!.yards[0];
    expect([dy.machine, dy.w, dy.h, dy.platforms.length, dags.tf.rails!.stations.length]).toEqual(["door:svc:nightly-jobs", 5, 10, 10, 10]);
    expect(dags.routes.filter((q) => q.kind === "rail" && q.pieces.some((p) => p.join === "split")).length, "rails split off a shared trunk").toBeGreaterThan(0);
    // demand-forecast's floor: the reference task's platform goes to feature-store's door; its station stands against the door
    const dff = plan("svc:demand-forecast"), ds = dff.tf.rails!.stations.find((s) => s.dest === "door:svc:feature-store")!;
    expect(dff.tf.boxes.get(ds.dest)!.kind).toBe("door");
    expect(dff.tf.rails!.yards[0].machine).toBe("door:svc:demand-forecast");
    // no bundle carries the reference task here (both ends lie off this floor): a stand-in rail runs to the door's station
    expect(ds.track).toMatch(/^rail:/);
    const ref = dff.routes.find((q) => q.key === ds.track)!;
    expect([ref.kind, !!ref.failed]).toEqual(["rail", false]);
    expect(dff.tf.rails!.shells.map((b) => [b.key, b.kind, b.b])).toEqual([[ds.track, "batch", "door:svc:feature-store"]]);
    // the features floor (S6·P1): the reference task comes in by demand-forecast's door, with no yard there, and ends on a
    // station at workflows.py beside the one feature-store's own yard feeds
    const fe = plan("features::features/"), rs = fe.tf.rails!;
    const ys = rs.stations.find((s) => s.door === "door:svc:demand-forecast")!;
    expect(ys).toMatchObject({ source: "door:svc:demand-forecast", dest: "features::features.workflows", track: "door:svc:demand-forecast|features::features.workflows" });
    expect(rs.yards.some((y) => y.machine === ys.door)).toBe(false);
    expect(ys.platform!.jobs.map((j) => j.job)).toEqual(["reference_task features/compute_zone_features"]);
    const inRail = fe.routes.find((q) => q.key === ys.track)!, end = inRail.pieces[inRail.pieces.length - 1];
    expect([end.x, end.y, end.out]).toEqual([ys.entry.x, ys.entry.y, ys.entry.d]);
    expect(rs.stations.map((s) => s.source).sort()).toEqual(["door:svc:demand-forecast", "features::features/"]);
  });

  it.runIf(BIG && existsSync(BIG))("a map with no batch relation plans every floor exactly as before (the big map)", () => {
    const map = JSON.parse(readFileSync(BIG, "utf8")) as CodeMap;
    expect(map.relations.filter((r) => r.kind === "batch")).toHaveLength(0);
    expect(noBatchDigest(new Model(map))).toBe("371 3d5be224c7fe339d");
  });

  /** Neighbouring grid slots: one column (same left edge) with no box between them, or one row (same top edge). */
  const beside = (tf: TileFloor, a: string, b: string) => {
    const p = tf.boxes.get(a)!, q = tf.boxes.get(b)!, boxes = [...tf.boxes.values()];
    if (p.x === q.x) { const [lo, hi] = [Math.min(p.y, q.y), Math.max(p.y, q.y)]; return !boxes.some((o) => o.x === p.x && o.y > lo && o.y < hi); }
    if (p.y === q.y) { const [lo, hi] = [Math.min(p.x, q.x), Math.max(p.x, q.x)]; return !boxes.some((o) => o.y === p.y && o.x > lo && o.x < hi); }
    return false;
  };
  it("puts every implementation in the grid slot beside its interface (the demo)", () => {
    const m = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    let pairs = 0;
    const apart: string[] = [];
    for (const c of Object.keys(m.map.layout.containers)) {
      const links = m.implementLinks(c);
      if (!links.length) continue;
      const { bundles, doors } = m.bundles(c);
      const p = planFloor(m, c, doors, bundles);
      expect(p.routes.filter((r) => r.failed), c).toHaveLength(0);
      checkTrunks(p.tf, p.routes, c);
      for (const l of links) {
        const a = p.tf.boxes.get(l.trait)!, b = p.tf.boxes.get(l.impl)!;
        if (a.region !== b.region) { apart.push(l.key); continue; }   // never moved across zones
        pairs++;
        expect(beside(p.tf, l.trait, l.impl), `${c}: ${l.impl} beside ${l.trait}`).toBe(true);
      }
    }
    expect(pairs).toBeGreaterThanOrEqual(15);
    // the one pair in two regions: the repository trait has a busy lane of its own, its implementation stays on the line
    expect(apart).toEqual(["reservations::city.parking.reservations.ReservationRepo|reservations::city.parking.reservations.ReservationRepo$"]);
  });

  it("puts an interface's several implementations in consecutive slots after it; one of two interfaces goes by the first id", () => {
    const P = "common::city.parking.common.", c = "common::city.parking.common/";
    const plan = (impls: Record<string, string[]>) => {
      const map = JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
      for (const n of map.nodes) if (n.id.startsWith(P) && impls[n.id.slice(P.length)]) n.implements = impls[n.id.slice(P.length)].map((t) => P + t);
      const m = new Model(map), { bundles, doors } = m.bundles(c);
      return planFloor(m, c, doors, bundles).tf;
    };
    // Config$ implements EventProducer too: EventProducer, then its implementations in reading order, one under the other
    let tf = plan({ Config$: ["EventProducer"] });
    const run = ["EventProducer", "EventProducer$", "Config$"];
    const col = run.map((id) => tf.boxes.get(P + id)!);
    expect(col.map((b) => b.x)).toEqual([col[0].x, col[0].x, col[0].x]);
    for (let i = 1; i < run.length; i++) expect(col[i].y > col[i - 1].y && beside(tf, P + run[i - 1], P + run[i]), run[i]).toBe(true);
    // Jdbc$ implements Config$ as well as Jdbc: it sits beside Config$, the first by id
    tf = plan({ Jdbc$: ["Jdbc", "Config$"] });
    expect(beside(tf, `${P}Config$`, `${P}Jdbc$`)).toBe(true);
  });
});
