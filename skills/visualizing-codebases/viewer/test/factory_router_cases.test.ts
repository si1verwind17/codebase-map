// test/factory_router_cases.test.ts
// Small hand-built floors for the tile router: each routes a few lines between a few boxes and asserts the exact
// pieces (checked by hand against the floor drawn above each case), plus the shared invariants.
import { describe, expect, it } from "vitest";
import type { Bundle } from "../src/model/model";
import type { TileFloor } from "../src/factory/layout";
import { routeTiles, type TileRoute } from "../src/factory/router";
import { checkTrunks, offWalls, plugged } from "./factory_trunks";
import type { Box, Dir, Piece } from "../src/factory/tiles";

const box = (id: string, x: number, y: number, w = 3, h = 3, kind = "service"): Box => ({ id, kind, foot: "package", region: "line", x, y, w, h });
const floorOf = (boxes: Box[], cols: number, rows: number): TileFloor =>
  ({ boxes: new Map(boxes.map((b) => [b.id, b])), lanes: [], zones: [], cols, rows, strategy: "layered", site: false });
const bundle = (a: string, b: string, kinds: Bundle["kinds"] = { request: 1 }): Bundle =>
  ({ key: `${a}|${b}`, a, b, relations: [], kinds, inferred: 0, kind: (Object.keys(kinds)[0] as Bundle["kind"]), flow: "a→b" });

type Mark = "under" | "hoodBefore" | "hoodAfter" | "split" | "merge";
/** One expected piece, written out: tile, way in, way out, and any marks. */
const pc = (x: number, y: number, i: Dir, o: Dir, ...m: Mark[]): Piece => ({
  x, y, in: i, out: o, under: m.includes("under"), hoodBefore: m.includes("hoodBefore"), hoodAfter: m.includes("hoodAfter"),
  ...(m.includes("split") ? { join: "split" as const } : m.includes("merge") ? { join: "merge" as const } : {}),
});
/** A straight run of pieces from (x0, y0) for n tiles heading d. */
const run = (x0: number, y0: number, d: Dir, n: number): Piece[] => {
  const s = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] }[d];
  return Array.from({ length: n }, (_, k) => pc(x0 + s[0] * k, y0 + s[1] * k, d, d));
};
const byKey = (routes: TileRoute[], k: string) => routes.find((r) => r.key === k)!;
/** Every invariant the router promises: plugged in, no tile twice on top, trunks well formed, plates off the walls. */
function invariants(tf: TileFloor, bundles: Bundle[], routes: TileRoute[]) {
  for (const r of routes) {
    expect(r.failed, r.key).toBeUndefined();
    plugged(tf, r);
    const top = r.pieces.filter((p) => !p.under).map((p) => `${p.x},${p.y}`);
    expect(new Set(top).size, `${r.key} repeats a tile`).toBe(top.length);
    expect(r.pieces[0].under || r.pieces[r.pieces.length - 1].under, `${r.key} starts or ends underground`).toBe(false);
    for (const p of r.pieces) if (p.join) offWalls(tf, r, p, "");
  }
  checkTrunks(tf, routes);
  expect(routeTiles(tf, bundles)).toEqual(routes);   // deterministic
}

describe("tile router, hand-built floors", () => {
  //    0123456789012345678
  //  0 ........PPP........
  //  1 ........PPP........
  //  2 ........PPP....TTT.     T0
  //  3 .........v.....TTT.
  //  4 .........v.....TTT.
  //  5 .SSS+++++u++++J>^..     the trunk goes under the pipe at 9,5 and splits at 14,5
  //  6 .SSS.....v....v....
  //  7 .SSS.....v....v....
  //  8 .........v....v....
  //  9 .........v....vTTT.     T1
  // 10 .........v....>TTT.
  // 11 .........v.....TTT.
  // 12 .........v.........
  // 13 ........QQQ........
  it("a trunk of two lines from one source hops under a crossing pipe as one belt and comes back up", () => {
    const tf = floorOf([box("S", 1, 5), box("P", 8, 0), box("Q", 8, 13), box("T0", 15, 2), box("T1", 15, 9)], 19, 16);
    const bundles = [bundle("P", "Q", { stream: 1 }), bundle("S", "T0"), bundle("S", "T1")];
    const routes = routeTiles(tf, bundles);
    const trunk = [...run(4, 5, "e", 4), pc(8, 5, "e", "e", "hoodBefore"), pc(9, 5, "e", "e", "under"), pc(10, 5, "e", "e", "hoodAfter"), ...run(11, 5, "e", 3)];
    expect(byKey(routes, "P|Q").pieces).toEqual(run(9, 3, "s", 10));
    expect(byKey(routes, "S|T0").pieces).toEqual([...trunk, pc(14, 5, "e", "e"), pc(15, 5, "e", "e"), pc(16, 5, "e", "n")]);
    expect(byKey(routes, "S|T1").pieces).toEqual([...trunk, pc(14, 5, "e", "s", "split"), ...run(14, 6, "s", 4), pc(14, 10, "s", "e")]);
    for (const k of ["S|T0", "S|T1"]) {   // one under/out pair each, in === out underground
      const ps = byKey(routes, k).pieces, under = ps.filter((p) => p.under);
      expect(under).toHaveLength(1);
      expect(under.every((p) => p.in === p.out)).toBe(true);
      expect(ps.filter((p) => p.hoodBefore)).toHaveLength(1);
      expect(ps.filter((p) => p.hoodAfter)).toHaveLength(1);
    }
    invariants(tf, bundles, routes);
  });

  //    0123456789012345
  //  1 ............TTT.     T0
  //  2 ............TTT.
  //  3 ............TTT.
  //  4 .............^..
  //  5 .SSS.........^..
  //  6 .SSS+++++++J>^..     shared 4..10, junction plate at 11,6
  //  7 .SSS.......v....
  //  8 ...........v....
  //  9 ...........vTTT.     T1
  // 10 ...........>TTT.
  // 11 ............TTT.
  it("a trunk splits at one junction plate, clear of every machine, before its two targets", () => {
    const tf = floorOf([box("S", 1, 5), box("T0", 12, 1), box("T1", 12, 9)], 16, 13);
    const bundles = [bundle("S", "T0"), bundle("S", "T1")];
    const routes = routeTiles(tf, bundles);
    expect(byKey(routes, "S|T0").pieces).toEqual([...run(4, 6, "e", 9), pc(13, 6, "e", "n"), pc(13, 5, "n", "n"), pc(13, 4, "n", "n")]);
    expect(byKey(routes, "S|T1").pieces).toEqual([...run(4, 6, "e", 7), pc(11, 6, "e", "s", "split"), ...run(11, 7, "s", 3), pc(11, 10, "s", "e")]);
    const joins = routes.flatMap((r) => r.pieces.filter((p) => p.join));
    expect(joins).toHaveLength(1);
    invariants(tf, bundles, routes);
  });

  //    0123456789012
  //  0 NNNNNNCNNNNNN     four walls leave one row and one column open: they meet at the single tile 6,6
  //  1 NNNNNNvNNNNNN
  //  5 NNNNNNvNNNNNN
  //  6 A>>>>>u>>>>>B     A|B holds 6,6 on top; C|D goes under it
  //  7 SSSSSSvSSSSSS
  // 11 SSSSSSvSSSSSS
  // 12 SSSSSSDSSSSSS
  it("two unrelated lines forced through one tile: the later goes under, they share no tile on top", () => {
    const tf = floorOf([box("A", 0, 6, 1, 1), box("B", 12, 6, 1, 1), box("C", 6, 0, 1, 1), box("D", 6, 12, 1, 1),
      box("NW", 0, 0, 6, 6), box("NE", 7, 0, 6, 6), box("SW", 0, 7, 6, 6), box("SE", 7, 7, 6, 6)], 13, 13);
    const bundles = [bundle("A", "B"), bundle("C", "D")];
    const routes = routeTiles(tf, bundles);
    expect(byKey(routes, "A|B").pieces).toEqual(run(1, 6, "e", 11));
    expect(byKey(routes, "C|D").pieces).toEqual([...run(6, 1, "s", 4), pc(6, 5, "s", "s", "hoodBefore"), pc(6, 6, "s", "s", "under"),
      pc(6, 7, "s", "s", "hoodAfter"), ...run(6, 8, "s", 4)]);
    const tops = routes.map((r) => new Set(r.pieces.filter((p) => !p.under).map((p) => `${p.x},${p.y}`)));
    expect([...tops[0]].filter((t) => tops[1].has(t))).toEqual([]);
    expect(routes.flatMap((r) => r.pieces.filter((p) => p.join))).toEqual([]);
    invariants(tf, bundles, routes);
  });

  //    012345
  //  1 ..WWW.
  //  2 S.WDW.     D is walled in on all four sides
  //  3 ..WWW.
  it("a line to a walled-in target fails, with no pieces through the walls", () => {
    const tf = floorOf([box("S", 0, 2, 1, 1), box("D", 3, 2, 1, 1),
      box("W1", 2, 1, 3, 1), box("W2", 2, 3, 3, 1), box("W3", 2, 2, 1, 1), box("W4", 4, 2, 1, 1)], 6, 5);
    const [r] = routeTiles(tf, [bundle("S", "D")]);
    expect(r).toMatchObject({ key: "S|D", kind: "belt", failed: true, pieces: [] });
    expect(r.points).toHaveLength(2);
  });
});
