// The line checks the map audit runs, as pure functions that return violations ([] when the rule holds).
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import type { TileFloor } from "../../src/factory/layout";
import type { TileRoute } from "../../src/factory/router";
import { failedViolations, midSideViolations, pluggedViolations, plateWallViolations, trunkViolations, underViolations } from "../../src/audit/lines";
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
