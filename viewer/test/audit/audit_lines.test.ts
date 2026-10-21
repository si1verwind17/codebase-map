// The line checks the map audit runs, as pure functions that return violations ([] when the rule holds).
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import type { TileFloor } from "../../src/factory/layout";
import { reversed, type TileRoute } from "../../src/factory/router";
import { failedViolations, gapStubViolations, laneDropViolations, laneGapViolations, midSideViolations, pluggedViolations, plateWallViolations, trunkViolations, underViolations } from "../../src/audit/lines";
import type { Dir, Piece } from "../../src/factory/tiles";
import shop from "../fixtures/shop.code-map.json";

const m = new Model(shop as unknown as CodeMap);
const { bundles, doors } = m.bundles(SITE);
const { tf, routes } = planFloor(m, SITE, doors, bundles);
const lines = routes.filter((r) => r.pieces.length);
const byKey = (k: string) => routes.find((r) => r.key === k)!;
const tapW = byKey("db:postgres:DB_HOST|svc:shop"), pipe = byKey("3p:feed|svc:worker");
const withRoute = (r: TileRoute, to: TileRoute): TileRoute[] => routes.map((x) => (x === r ? to : x));

describe("line checks return violations", () => {
  it("the shop site plan passes every check", () => {
    expect(trunkViolations(tf, routes)).toEqual([]);
    for (const r of lines) { expect(pluggedViolations(tf, r), r.key).toEqual([]); expect(underViolations(r), r.key).toEqual([]); expect(plateWallViolations(tf, r), r.key).toEqual([]); }
    expect(midSideViolations(tf, routes)).toEqual([]);   // (the postgres tap ends in a corner tile on a straight run: allowed, tested below)
    expect(failedViolations(routes)).toEqual([]);
  });

  it("pluggedViolations: a last piece shifted one tile breaks the chain and the plug-in", () => {
    const ps = tapW.pieces.map((p) => ({ ...p }));
    ps[ps.length - 1].x += 1;
    const v = pluggedViolations(tf, { ...tapW, pieces: ps });
    expect(v.length).toBeGreaterThan(0);
    expect(v[0].detail).toContain(tapW.key);
  });

  it("underViolations: a route that ends underground has no piece after its run", () => {
    const ps = pipe.pieces.map((p) => ({ ...p }));
    ps[ps.length - 1].under = true;
    expect(underViolations({ ...pipe, pieces: ps })).toHaveLength(1);
    ps[0].under = true;
    expect(underViolations({ ...pipe, pieces: ps })).toHaveLength(2);
  });

  it("midSideViolations: an end in the corner tile of a 3+ wide side that turns next to the box, while the middle is free", () => {
    const b = tf.boxes.get("svc:shop")!;   // 5 wide: corner 0, middle 2
    // leaves the s side's first tile going south and turns east on the tile next to the box (row 13: "after an extra turn")
    const piece = { x: b.x, y: b.y + b.h, in: "s" as const, out: "e" as const, under: false, hoodBefore: false, hoodAfter: false };
    const turning = { key: "svc:shop|x", kind: "belt", pieces: [piece] } as unknown as TileRoute;
    const v = midSideViolations(tf, [pipe, turning]);
    expect(v).toHaveLength(1);
    expect(v[0].at).toEqual({ x: b.x, y: b.y + b.h - 1 });
    expect(v[0].detail).toBe("svc:shop|x ends in the first tile of svc:shop's s side and turns while its middle tile is free");
    // with another end on the middle tile of that side the corner end is fine
    const mid = { ...piece, x: b.x + 2, out: "s" as const };
    expect(midSideViolations(tf, [pipe, turning, { key: "svc:shop|y", kind: "belt", pieces: [mid] } as unknown as TileRoute])).toEqual([]);
  });

  it("midSideViolations: a straight run out of a corner tile is allowed (the shop's postgres tap, and a made-up belt)", () => {
    const end = tapW.pieces.at(-1)!;
    expect(end.in).toBe(end.out);   // the tap reaches svc:shop's corner tile (19, 15) without turning
    expect(midSideViolations(tf, [tapW])).toEqual([]);
    const b = tf.boxes.get("svc:shop")!;
    const straight = { x: b.x, y: b.y + b.h, in: "s" as const, out: "s" as const, under: false, hoodBefore: false, hoodAfter: false };
    expect(midSideViolations(tf, [pipe, { key: "svc:shop|x", kind: "belt", pieces: [straight] } as unknown as TileRoute])).toEqual([]);
  });

  it("plateWallViolations: a junction piece next to a box touches its wall", () => {
    const b = tf.boxes.get("svc:worker")!;
    const ps = pipe.pieces.map((p) => ({ ...p }));
    ps[3] = { ...ps[3], x: b.x - 1, y: b.y + 1, join: "split" };
    const v = plateWallViolations(tf, { ...pipe, pieces: ps });
    expect(v).toHaveLength(1);
    expect(v[0].detail).toContain(b.id);
  });

  it("trunkViolations: a line plugged into empty floor is checked, not a crash (lines.plugged reports it)", () => {
    const ps = tapW.pieces.map((p) => ({ ...p, x: p.x + 40 }));   // every piece far from both of its boxes
    expect(() => trunkViolations(tf, withRoute(tapW, { ...tapW, pieces: ps }))).not.toThrow();
  });

  it("trunkViolations: a piece duplicated on top repeats a tile", () => {
    const v = trunkViolations(tf, withRoute(tapW, { ...tapW, pieces: [...tapW.pieces.slice(0, 6), tapW.pieces[5], ...tapW.pieces.slice(6)] }));
    expect(v.map((x) => x.detail).join("\n")).toContain("repeats tile");
  });

  it("failedViolations: 1 in 50 fails, 1 in 200 and 0 pass, 3 in 200 fails", () => {
    const mk = (n: number, failed: number): TileRoute[] =>
      Array.from({ length: n }, (_, i) => ({ key: `k${i}`, kind: "belt", pieces: [], ...(i < failed ? { failed: true } : {}) }) as unknown as TileRoute);
    const one = failedViolations(mk(50, 1));
    expect(one).toHaveLength(1);
    expect(one[0].detail).toBe("1 of 50 routes failed: k0");
    expect(failedViolations(mk(200, 1))).toEqual([]);
    expect(failedViolations(mk(200, 3))).toHaveLength(1);
    expect(failedViolations(mk(50, 0))).toEqual([]);
  });
});

/** A line through `tiles` ([x, y] on top, [x, y, true] underground), coming in by `first` and going out by `last`:
 *  each piece's in and out follow from its neighbours, housings either side of each underground run. */
const chain = (key: string, first: Dir, tiles: [number, number, boolean?][], last: Dir): TileRoute => {
  const dirOf = ([ax, ay]: [number, number, boolean?], [bx, by]: [number, number, boolean?]): Dir => (bx > ax ? "e" : bx < ax ? "w" : by > ay ? "s" : "n");
  const pieces: Piece[] = tiles.map(([x, y, u], i) => ({ x, y, under: !!u, in: i ? dirOf(tiles[i - 1], tiles[i]) : first,
    out: i + 1 < tiles.length ? dirOf(tiles[i], tiles[i + 1]) : last, hoodBefore: !u && !!tiles[i + 1]?.[2], hoodAfter: !u && !!tiles[i - 1]?.[2] }));
  return { key, kind: "tapW", both: false, pieces, points: [] } as unknown as TileRoute;
};
const col = (x: number, y0: number, y1: number, under = (_y: number) => false): [number, number, boolean?][] =>
  Array.from({ length: y1 - y0 + 1 }, (_, i) => [x, y0 + i, under(y0 + i)]);
const row = (y: number, x0: number, x1: number): [number, number][] =>
  Array.from({ length: Math.abs(x1 - x0) + 1 }, (_, i) => [x0 + Math.sign(x1 - x0) * i, y]);

/** A machine above three long lanes, `gap` rows apart: lane "L1" from row 10, "L2" and "L3" below. */
const lanesFloor = (gap = 2): TileFloor => ({
  boxes: new Map([["svc", { id: "svc", kind: "service", foot: "package", region: "line", x: 5, y: 1, w: 5, h: 5 }]]),
  lanes: [{ id: "L1", label: "L1", x0: 2, x1: 40, y: 10 }, { id: "L2", label: "L2", x0: 2, x1: 40, y: 13 + gap }, { id: "L3", label: "L3", x0: 2, x1: 40, y: 16 + 2 * gap }],
  zones: [], cols: 44, rows: 30, strategy: "layered", site: false }) as unknown as TileFloor;
const under = (...lanes: [number, number][]) => (y: number) => lanes.some(([a, b]) => y >= a && y <= b);

describe("lane checks (the owner's 2026-10-21 storage lanes)", () => {
  const tf = lanesFloor();   // L1 rows 10-12, gap 13-14, L2 rows 15-17, gap 18-19, L3 rows 20-22

  it("laneDropViolations: a tap that comes up between lanes and hooks sideways before it drops; a straight drop passes", () => {
    const hook = chain("svc|L2", "s", [...col(7, 6, 13, under([10, 12])), ...row(13, 8, 9), [9, 14]], "s");
    const v = laneDropViolations(tf, [hook]);
    expect(v.map((x) => x.detail)).toEqual(["svc|L2 turns e at 7,13 on its way to lane L2, where it could go straight on"]);
    expect(v[0].at).toEqual({ x: 7, y: 13 });
    expect(laneDropViolations(tf, [chain("svc|L2", "s", col(7, 6, 14, under([10, 12])), "s")])).toEqual([]);
    // the same hook where another line holds the drop's tile: going straight on is not free
    expect(laneDropViolations(tf, [hook, chain("x|y", "e", row(14, 3, 8), "e")])).toEqual([]);
    // a read runs from the lane up: walked the other way, the same hook
    const read = { ...hook, pieces: reversed(hook.pieces) };
    expect(laneDropViolations(tf, [read])).toHaveLength(1);
    // a turn among the machines, far above the lanes, is a trunk's: not this check's
    expect(laneDropViolations(tf, [chain("svc|L1", "s", [...col(7, 6, 7), ...row(7, 8, 9), ...col(9, 8, 9)], "s")])).toEqual([]);
  });

  it("gapStubViolations: a line along a two-row gap that a tap passes under together with the lane below", () => {
    const belt = chain("a|b", "e", row(14, 3, 30), "e");
    const tap = chain("svc|L3", "s", col(12, 6, 19, under([10, 12], [14, 17])), "s");   // up at 13, under the belt and L2 at once
    const v = gapStubViolations(tf, [belt, tap]);
    expect(v.map((x) => x.detail)).toEqual(["svc|L3 passes under a|b at 12,14 and under lane L2 in one run: its stub ends on the line"]);
    // three rows: the belt on the inner row, the tap up either side of it
    const wide = lanesFloor(3);   // gap 13-15, L2 16-18, gap 19-21, L3 22-24
    const inner = chain("a|b", "e", row(14, 3, 30), "e");
    const tap3 = chain("svc|L3", "s", col(12, 6, 21, under([10, 12], [14, 14], [16, 18])), "s");
    expect(gapStubViolations(wide, [inner, tap3])).toEqual([]);
  });

  it("laneGapViolations: a line along a two-row gap fills it; along the inner row of three it does not, along two of three it does", () => {
    const belt = chain("a|b", "e", row(14, 3, 30), "e");
    expect(laneGapViolations(tf, [belt]).map((x) => x.detail)).toEqual(["the gap between lanes L1 and L2 (2 rows) is full: a|b runs along it next to a lane"]);
    expect(laneGapViolations(tf, [chain("svc|L2", "s", col(7, 6, 14, under([10, 12])), "s")])).toEqual([]);   // a drop crosses the gap
    const wide = lanesFloor(3);
    expect(laneGapViolations(wide, [belt])).toEqual([]);
    expect(laneGapViolations(wide, [belt, chain("c|d", "e", row(15, 3, 30), "e")])).toHaveLength(1);
  });
});

