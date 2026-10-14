// The text and zone checks the map audit runs: names cut from the front, labels over lines or boxes, zones narrower than
// their label. Pure functions that return violations ([] when the rule holds).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor, type FloorPlan } from "../../src/factory/plan";
import { fitName } from "../../src/factory/fit";
import { cutViolations, FITS, labelRects, narrowZoneViolations, overLineViolations } from "../../src/audit/text";
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
    // (the site's production line zone has no clear spot in its bottom rows: its name falls back to the corner, over the
    // stripe webhook's belt -- a real finding, pinned below)
    expect(overLineViolations(demo, c, p, b.bundles).filter((v) => !v.detail.startsWith("zone 'production line'"))).toEqual([]);
    expect(narrowZoneViolations(p)).toEqual([]);
  });

  it("a real finding: the site's production line name sits over the stripe webhook's belt (no clear spot, corner fallback)", () => {
    const { b, p } = floors[0];
    expect(overLineViolations(demo, SITE, p, b.bundles)).toEqual([{ detail: "zone 'production line' label over a belt", at: { x: 14, y: 35 } }]);
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
