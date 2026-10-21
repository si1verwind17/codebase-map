// The text and zone checks the map audit runs: names cut from the front, labels over lines or boxes, zones narrower than
// their label. Pure functions that return violations ([] when the rule holds).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import { fitName } from "../../src/factory/fit";
import { cutViolations, FITS, labelRects, laneLabelRects, narrowZoneViolations, overLineViolations } from "../../src/audit/text";
import type { TileRoute } from "../../src/factory/router";
import { T } from "../../src/factory/tiles";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const raw = () => JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap;
const DAGS = "jobs/dags::dags/";
const demo = new Model(raw());
const plan = (m: Model, c: string) => { const b = m.bundles(c); return { b, p: planFloor(m, c, b.doors, b.bundles, b.layered) }; };
const floors = [SITE, DAGS].map((c) => ({ c, ...plan(demo, c) }));

describe("text and zone checks return violations", () => {
  for (const { c, b, p } of floors) it(`the demo's ${c} floor passes every check`, () => {
    expect(cutViolations(demo, c, p)).toEqual([]);
    expect(overLineViolations(demo, c, p, b.bundles)).toEqual([]);
    expect(narrowZoneViolations(p)).toEqual([]);
  });

  it("the checks see real labels: messaging labels on the site, a `used by N` badge on dags", () => {
    const what = (i: number) => labelRects(demo, floors[i].c, floors[i].p, floors[i].b.bundles).map((l) => l.what);
    expect(what(0).filter((w) => /^(tag|sign|plate) /.test(w)).length).toBeGreaterThan(0);
    expect(what(1).filter((w) => w.startsWith("badge 'used by ")).length).toBe(1);
  });

  it("cutViolations: a 120-character name is cut at its end, never its front", () => {
    const map = raw();
    const n = map.nodes.find((x) => x.id === "svc:billing")!;
    n.name = "io.example.parking." + "x".repeat(120 - "io.example.parking.".length - "python.trading".length) + "python.trading";
    expect(n.name).toHaveLength(120);
    const m = new Model(map), { p } = plan(m, SITE);
    expect(cutViolations(m, SITE, p)).toEqual([]);
  });

  it("cutViolations: a name fitted from the front is reported, with its shown line", () => {
    const front = (name: string, w: number, max: number, sizes?: number[]) => {
      const f = fitName(name, w, max, sizes);
      return name.includes("billing") ? { ...f, lines: ["…hon.trading"] } : f;
    };
    const { p } = floors[0];
    const v = cutViolations(demo, SITE, p, { ...FITS, name: front });
    expect(v).toHaveLength(1);
    expect(v[0].detail).toBe("name of svc:billing cut: '…hon.trading'");
    const box = p.tf.boxes.get("svc:billing")!;
    expect(v[0].at!.x).toBe(box.x);
  });

  it("overLineViolations: a layer's line through a zone label (zone names never keep off layer lines)", () => {
    const { p, b } = floors[0];
    const z = p.tf.zones[0];
    const spot = labelRects(demo, SITE, p, b.bundles).find((l) => l.what === `zone '${z.name}' label`)!.boxes[0];
    const tx = Math.floor((spot.x0 + 2) / T), ty = Math.floor((spot.y0 + 2) / T);
    const line = { key: "a|b", kind: "belt", pieces: [{ x: tx, y: ty, in: "e", out: "e", under: false }], points: [] } as unknown as TileRoute;
    const q: FloorPlan = { ...p, layers: { ...(p.layers ?? {}), ["x" as never]: { routes: [line] } } };
    const v = overLineViolations(demo, SITE, q, b.bundles);
    expect(v.map((x) => x.detail)).toContain(`zone '${z.name}' label over a belt (layer x)`);
    expect(v.every((x) => Number.isInteger(x.at!.x) && Number.isInteger(x.at!.y))).toBe(true);
  });

  it("laneLabelRects: each lane's name, inside its lane, past the lines crossing it", () => {
    const { p } = floors[0];
    const names = laneLabelRects(demo, p, []);
    expect(names.map((l) => l.what)).toEqual(["lane 'postgres' name", "lane 'bigquery' name", "lane 'shared-cache' name", "lane 'receipts-bucket' name"]);
    names.forEach((l, i) => {
      const lane = p.tf.lanes[i];
      for (const b of l.boxes) expect(b.x0 >= lane.x0 * T && b.x1 <= lane.x1 * T && b.y0 >= lane.y * T && b.y1 <= (lane.y + 3) * T, l.what).toBe(true);
    });
  });

  it("overLineViolations: a lane's name over a line (a layer's) or a drone path with no room left to keep off it", () => {
    // the reservations floor's short postgres lane: a tap crosses it near its start, and a made-up drone line crosses
    // most of the rest; the widest gap left is too narrow for the name, which runs into the path
    const c = "svc:reservations", { p, b } = plan(demo, c);
    const lane = p.tf.lanes.find((l) => l.label === "postgres")!;
    const x0 = lane.x0 * T, y0 = lane.y * T;
    const drone = { key: "x|y", kind: "drone", both: false, pieces: [], points: [{ x: x0 + 60, y: y0 }, { x: x0 + 120, y: y0 + 72 }] } as unknown as TileRoute;
    const q: FloorPlan = { ...p, routes: [...p.routes, drone] };
    expect(overLineViolations(demo, c, q, b.bundles).map((v) => v.detail)).toContain("lane 'postgres' name over the path of x|y");
    expect(overLineViolations(demo, c, p, b.bundles)).toEqual([]);
    const spot = laneLabelRects(demo, p, [])[0].boxes[0];
    const line = { key: "a|b", kind: "belt", pieces: [{ x: Math.floor(spot.x0 / T), y: lane.y, in: "e", out: "e", under: false }], points: [] } as unknown as TileRoute;
    const layered: FloorPlan = { ...p, layers: { ["x" as never]: { routes: [line] } } };
    expect(overLineViolations(demo, c, layered, b.bundles).map((v) => v.detail)).toContain("lane 'postgres' name over a belt (layer x)");
  });

  it("narrowZoneViolations: a zone 1 tile wide cannot hold its label", () => {
    const { p } = floors[0];
    const z = p.tf.zones[0];
    const q: FloorPlan = { ...p, tf: { ...p.tf, zones: [{ ...z, w: 1 }, ...p.tf.zones.slice(1)] } };
    const v = narrowZoneViolations(q);
    expect(v).toHaveLength(1);
    expect(v[0].detail).toBe(`zone '${z.name}' label does not fit (1 tile)`);
    expect(v[0].at).toEqual({ x: z.x, y: z.y + z.h - 1 });
  });
});
