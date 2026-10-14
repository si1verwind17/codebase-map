// test/factory_router.test.ts
import { describe, expect, it } from "vitest";
import shop from "./fixtures/shop.code-map.json";
import { Model } from "../src/model/model";
import type { Bundle } from "../src/model/model";
import type { CodeMap } from "../src/model/types";
import { layoutTiles, type TileFloor } from "../src/factory/layout";
import { piecesToPoints, reversed, routeTiles, type TileRoute } from "../src/factory/router";
import { checkTrunks, plugged } from "./factory_trunks";
import { LANE_H, STEP, T, inside, type Box, type Piece, type Rect } from "../src/factory/tiles";

const box = (id: string, x: number, y: number, w = 3, h = 3, kind = "service"): Box => ({ id, kind, foot: "package", region: "line", x, y, w, h });
const floorOf = (boxes: Box[], cols = 20, rows = 20, lanes: TileFloor["lanes"] = []): TileFloor =>
  ({ boxes: new Map(boxes.map((b) => [b.id, b])), lanes, zones: [], cols, rows, strategy: "layered", site: false });
/** The tile just past a line's last piece: where it plugs in. */
const after = (ps: Piece[]): [number, number] => { const l = ps[ps.length - 1]; return [l.x + STEP[l.out][0], l.y + STEP[l.out][1]]; };
const bundle = (a: string, b: string, kinds: Bundle["kinds"] = { request: 1 }, flow: Bundle["flow"] = "a→b"): Bundle =>
  ({ key: `${a}|${b}`, a, b, relations: [], kinds, inferred: 0, kind: (Object.keys(kinds)[0] as Bundle["kind"]), flow });

describe("tile router", () => {
  it("routes a straight belt between two boxes, plugged in at both ends", () => {
    const tf = floorOf([box("A", 1, 8), box("B", 16, 8)]);
    const [r] = routeTiles(tf, [bundle("A", "B")]);
    expect(r).toMatchObject({ kind: "belt", failed: undefined });
    plugged(tf, r);
    expect(r.pieces.every((p) => p.in === "e" && p.out === "e" && p.y === 9)).toBe(true);
    expect(r.points).toEqual([{ x: 4 * T, y: 9.5 * T }, { x: 16 * T, y: 9.5 * T }]);
  });

  it("sends the later line under the earlier one, with a hood either side", () => {
    const tf = floorOf([box("A", 1, 8), box("B", 16, 8), box("C", 8, 1), box("D", 8, 16)]);
    const routes = routeTiles(tf, [bundle("C", "D"), bundle("A", "B")]);
    const cd = routes.find((r) => r.key === "C|D")!;
    for (const r of routes) plugged(tf, r);
    checkTrunks(tf, routes);
    const under = cd.pieces.filter((p) => p.under);
    expect(under).toHaveLength(1);
    expect(under[0]).toMatchObject({ x: 9, y: 9 });
    const i = cd.pieces.indexOf(under[0]);
    expect(cd.pieces[i - 1].hoodBefore).toBe(true);
    expect(cd.pieces[i + 1].hoodAfter).toBe(true);
  });

  it("drops a database link onto its lane as a tap; a read runs back up", () => {
    const wh = box("db", 0, 10, 2, 3, "datastore");
    const lanes = [{ id: "db", label: "db", x0: 2, x1: 18, y: 10 }];
    const tf = floorOf([box("svc", 5, 1, 5, 5), wh], 20, 16, lanes);
    const [w] = routeTiles(tf, [bundle("db", "svc", { "db-write": 1 })]);
    expect(w).toMatchObject({ kind: "tapW", tap: "db" });
    plugged(tf, w);
    expect(w.pieces[w.pieces.length - 1].out).toBe("s");
    const [rd] = routeTiles(tf, [bundle("db", "svc", { "db-read": 1 })]);
    expect(rd.kind).toBe("tapR");
    expect(rd.pieces[0].in).toBe("n");   // starts at the lane, travelling up
  });

  it("routes a line to a cache chest (a store box with no lane) as a tap, plugged at both ends", () => {
    const chest = { ...box("db", 7, 9, 2, 2, "datastore"), foot: "chest" as const, region: "chest" };
    const tf = floorOf([box("svc", 5, 1, 5, 5), chest], 20, 16);
    const [rw] = routeTiles(tf, [bundle("db", "svc", { "db-read": 1, "db-write": 1 }, "both")]);
    expect(rw).toMatchObject({ kind: "tapRW", tap: "db", failed: undefined });
    plugged(tf, rw);
    expect(inside(chest, ...after(rw.pieces))).toBe(true);   // machine to store, as a lane tap's points run
    const [w] = routeTiles(tf, [bundle("db", "svc", { "db-write": 1 })]);
    expect(w).toMatchObject({ kind: "tapW", tap: "db" });
    expect(inside(chest, ...after(w.pieces))).toBe(true);
    const [rd] = routeTiles(tf, [bundle("db", "svc", { "db-read": 1 })]);
    expect(rd).toMatchObject({ kind: "tapR", tap: "db" });
    plugged(tf, rd);
    const f = rd.pieces[0];
    expect(inside(chest, f.x - STEP[f.in][0], f.y - STEP[f.in][1])).toBe(true);   // a read runs from the store
  });

  it("flies events as drones instead of routing tiles", () => {
    const tf = floorOf([box("A", 1, 8), box("B", 16, 8)]);
    const [r] = routeTiles(tf, [bundle("A", "B", { event: 1 })]);
    expect(r).toMatchObject({ kind: "drone", pieces: [] });
    expect(r.points).toHaveLength(2);
  });

  it("marks a line it cannot route as failed instead of throwing", () => {
    // S is walled in: its only open sides face a machine and the floor edge
    const tf = floorOf([box("S", 0, 0, 2, 2), box("W1", 2, 0, 1, 3), box("W2", 0, 2, 2, 1), box("D", 4, 0, 1, 1)], 5, 3);
    const [r] = routeTiles(tf, [bundle("S", "D")]);
    expect(r.failed).toBe(true);
    expect(r.points).toHaveLength(2);
  });

  it("turns corners into points and reverses cleanly", () => {
    const ps: Piece[] = [
      { x: 2, y: 2, in: "e", out: "e", under: false, hoodBefore: false, hoodAfter: false },
      { x: 3, y: 2, in: "e", out: "s", under: false, hoodBefore: false, hoodAfter: false },
      { x: 3, y: 3, in: "s", out: "s", under: false, hoodBefore: true, hoodAfter: false },
    ];
    expect(piecesToPoints(ps)).toEqual([{ x: 2 * T, y: 2.5 * T }, { x: 3.5 * T, y: 2.5 * T }, { x: 3.5 * T, y: 4 * T }]);
    const back = reversed(ps);
    expect(back.map((p) => [p.x, p.y, p.in, p.out])).toEqual([[3, 3, "n", "n"], [3, 2, "n", "w"], [2, 2, "w", "w"]]);
    expect(back[0].hoodAfter).toBe(true);
  });

  it("routes every fixture floor: plugged in, trunks well formed, deterministic, none failed", () => {
    const model = new Model(shop as unknown as CodeMap);
    for (const c of Object.keys(model.map.layout.containers)) {
      const { bundles, doors } = model.bundles(c);
      const tf = layoutTiles(model, c, doors);
      const routes = routeTiles(tf, bundles);
      expect(routes.length).toBe(bundles.length);
      for (const r of routes) {
        expect(r.failed, `${c}: ${r.key}`).toBeUndefined();
        if (r.kind !== "drone") plugged(tf, r);
      }
      checkTrunks(tf, routes, c);
      expect(routeTiles(tf, bundles)).toEqual(routes);
    }
  });

  it("a trunk goes under a crossing line as one belt: its riders enter and come up where it does", () => {
    // a stream (routed first) walls the floor top to bottom; three lines leave S for the far side
    const tf = floorOf([box("S", 1, 9), box("P", 10, 0), box("Q", 10, 21), box("T0", 20, 2), box("T1", 20, 9), box("T2", 20, 16)], 24, 24);
    const routes = routeTiles(tf, [bundle("P", "Q", { stream: 1 }), bundle("S", "T0"), bundle("S", "T1"), bundle("S", "T2")]);
    expect(routes.filter((r) => r.failed)).toHaveLength(0);
    for (const r of routes) plugged(tf, r);
    checkTrunks(tf, routes);
    const runs = new Set<string>();
    for (const r of routes.filter((r) => r.kind === "belt")) r.pieces.forEach((p, i) => {
      if (p.under && !r.pieces[i - 1].under) { let e = i; while (r.pieces[e].under) e++; runs.add(`${r.pieces[i - 1].x},${r.pieces[i - 1].y}>${r.pieces[e].x},${r.pieces[e].y}`); }
    });
    expect(runs.size).toBe(1);
  });

  it("never tunnels along a tile held by a line it shares an end with, even when that line is not the tile's first holder", () => {
    // B2|B3 lays a trunk out of B2 and B2|B0 rides it; B7|B0 shares B0 with the rider only and must not hide under them
    const at = [["B0", 19, 7], ["B1", 14, 19], ["B2", 8, 1], ["B3", 11, 11], ["B4", 3, 13], ["B5", 17, 1], ["B6", 16, 12], ["B7", 1, 2], ["B8", 9, 6]] as const;
    const tf = floorOf(at.map(([id, x, y]) => box(id, x, y)), 24, 24);
    const keys = ["B3|B1", "B1|B8", "B7|B2", "B0|B1", "B2|B0", "B0|B6", "B2|B5", "B6|B2", "B0|B3", "B2|B3", "B4|B2", "B7|B0", "B8|B2"];
    const routes = routeTiles(tf, keys.map((k) => bundle(...(k.split("|") as [string, string]))));
    for (const r of routes) if (r.pieces.length) plugged(tf, r);
    checkTrunks(tf, routes);
  });

  // a 3x3 machine has 12 side tiles: 14 lines need a shared trunk
  const ring = () => {
    const xs = [4, 16, 28, 40, 52], out: Box[] = [box("S", 28, 28)];
    xs.forEach((x, i) => { out.push(box(`T${i}`, x, 2)); out.push(box(`U${i}`, x, 54)); });
    out.push(box("L0", 2, 16), box("L1", 2, 40), box("R0", 56, 16), box("R1", 56, 40));
    return out;
  };
  const targets = () => ring().filter((b) => b.id !== "S").map((b) => b.id);

  it("splits a trunk when a busy machine has more lines than side tiles", () => {
    const tf = floorOf(ring(), 62, 62);
    const routes = routeTiles(tf, targets().map((t) => bundle("S", t)));
    expect(routes).toHaveLength(14);
    expect(routes.filter((r) => r.failed)).toHaveLength(0);
    for (const r of routes) plugged(tf, r);
    checkTrunks(tf, routes);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "split"))).toBe(true);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "merge"))).toBe(false);
    expect(routes.every((r) => r.pieces.filter((p) => p.join).length <= 1)).toBe(true);
  });

  it("merges a trunk when many lines arrive at one machine", () => {
    const tf = floorOf(ring(), 62, 62);
    const routes = routeTiles(tf, targets().map((t) => bundle(t, "S")));
    expect(routes.filter((r) => r.failed)).toHaveLength(0);
    for (const r of routes) plugged(tf, r);
    checkTrunks(tf, routes);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "merge"))).toBe(true);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "split"))).toBe(false);
  });

  it("a lane feeding many readers splits (the line runs lane to machine), it does not merge", () => {
    const boxes = [...ring().filter((b) => b.id !== "S"), box("db", 26, 29, 3, 3, "datastore")];
    const tf = floorOf(boxes, 62, 62, [{ id: "db", label: "db", x0: 29, x1: 32, y: 29 }]);
    const routes = routeTiles(tf, targets().map((t) => bundle("db", t, { "db-read": 1 })));
    expect(routes.filter((r) => r.failed)).toHaveLength(0);
    expect(routes.every((r) => r.kind === "tapR")).toBe(true);
    for (const r of routes) plugged(tf, r);
    checkTrunks(tf, routes);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "split"))).toBe(true);
    expect(routes.some((r) => r.pieces.some((p) => p.join === "merge"))).toBe(false);
  });
});
