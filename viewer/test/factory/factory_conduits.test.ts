// test/factory_conduits.test.ts
// The F0 code-dependency overlay (spec §8 Libraries): optional thin dotted conduits from a service to the code it uses.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { toGeometry } from "../../src/factory/layout";
import { codeConduits, codeLinkCount, conduitDots } from "../../src/factory/conduits";
import { fitScale } from "../../src/floor/fitscale";
import { implementsDots } from "../../src/factory/implements";
import { createLayers } from "../../src/floor/state";
import shop from "../fixtures/shop.code-map.json";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = () => new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);

function site(m: Model, container = SITE) {
  const b = m.bundles(container);
  const plan = planFloor(m, container, b.doors, b.bundles);
  return { plan, geo: toGeometry(plan.tf), bundles: b.bundles };
}

describe("code conduits", () => {
  it("draws one conduit per uses-code pair on the demo F0 while the overlay is on, none while it is off", () => {
    const m = demo(), { geo } = site(m);
    const on = codeConduits(m, SITE, geo.machines, true);
    expect(on).toHaveLength(12);
    expect(codeConduits(m, SITE, geo.machines, false)).toHaveLength(0);
    // 11 run to a library on the shelf, 1 from feature-store to demand-forecast; each starts at its user
    expect(on.filter((c) => c.used.startsWith("lib:"))).toHaveLength(11);
    expect(on.find((c) => c.used === "svc:demand-forecast")?.user).toBe("svc:feature-store");
    for (const c of on) {
      const u = geo.machines.get(c.user)!, v = geo.machines.get(c.used)!;
      expect(c.points[0]).toEqual({ x: u.x + u.w / 2, y: u.y + u.h / 2 });   // the user's roof centre
      expect(c.points[1]).toEqual({ x: v.x + v.w / 2, y: v.y + v.h / 2 });   // the used box's centre
    }
  });

  it("does not touch the routed lines: the floor's bundles and plan have no uses-code", () => {
    const m = demo(), { plan, bundles } = site(m);
    expect(bundles.some((b) => b.kinds["uses-code"])).toBe(false);
    expect(plan.routes.some((r) => r.key.startsWith("lib:"))).toBe(false);
  });

  it("is F0 only: an inner floor has none", () => {
    const m = demo();
    const inner = [...m.nodes.values()].find((n) => n.kind === "service" && m.floor(n.id))!;
    const { geo } = site(m, inner.id);
    expect(codeConduits(m, inner.id, geo.machines, true)).toHaveLength(0);
  });

  it("is finer than the implements link: smaller dots at a shorter pitch", () => {
    const a = { x: 0, y: 0, w: 0, h: 0 }, b = { x: 120, y: 0, w: 0, h: 0 };
    const fine = conduitDots([{ x: 0, y: 0 }, { x: 120, y: 0 }]), coarse = implementsDots(a, b);
    expect(fine.dots.length).toBeGreaterThan(coarse.length);
    expect(fine.r).toBeLessThan(1.5);
  });

  it("breaks off around a floor label: no dot inside a blocked box or its 2 px margin", () => {
    const box = { x0: 40, y0: -6, x1: 80, y1: 6 };
    const { dots } = conduitDots([{ x: 0, y: 0 }, { x: 120, y: 0 }], [box]);
    expect(dots.some((p) => p.x >= 38 && p.x <= 82)).toBe(false);
    expect(dots.some((p) => p.x < 38) && dots.some((p) => p.x > 82)).toBe(true);
  });

  it("stays visible at Fit: on screen a dot is 1.5 px across and 4 px from the next; zoomed in it keeps its world size", () => {
    const m = demo(), { geo } = site(m), { w, h } = geo.bounds;
    const z = Math.max(0.12, Math.min(1.4, fitScale(w, h, 1440 - 232 - 312, 900, true)));   // the floor's canvas at 1440×900
    // the demo F0 (2208×1704 px) at Fit is zoomed well out: world-size dots (1.5 px at a 3.5 px pitch) would show 0.57 px
    // across at 1.34 px, so the floor sets in: dots of a 1.97 px world radius at a 10.49 px pitch
    expect([w, h]).toEqual([2208, 1704]);
    expect(z).toBeCloseTo(0.3814, 4);
    const c = codeConduits(m, SITE, geo.machines, true)[0];
    const fit = conduitDots(c.points, [], z);
    expect(fit.r).toBeCloseTo(1.9662, 4);
    expect(fit.pitch).toBeCloseTo(10.4863, 4);
    expect(2 * fit.r * z).toBeCloseTo(1.5, 9);
    expect(fit.pitch * z).toBeCloseTo(4, 9);
    const deep = conduitDots(c.points, [], 3);
    expect([deep.r, deep.pitch]).toEqual([0.75, 3.5]);
  });

  it("lies directly under the lines: the conduits layer is the one before `lines` in the world's order", () => {
    const order = Object.keys(createLayers());
    expect(order.indexOf("conduits")).toBe(order.indexOf("lines") - 1);
    expect(order.indexOf("conduits")).toBeGreaterThan(order.indexOf("lanes"));
  });

  it("counts the uses-code pairs F0 draws (the toggle and legend entry need one); a map without any has none", () => {
    expect(codeLinkCount(demo())).toBe(12);
    const map = structuredClone(shop) as unknown as CodeMap;
    expect(codeLinkCount(new Model(map))).toBe(2);
    map.relations = map.relations.filter((r) => r.kind !== "uses-code");
    const bare = new Model(map), { geo } = site(bare);
    expect(codeLinkCount(bare)).toBe(0);
    expect(codeConduits(bare, SITE, geo.machines, true)).toEqual([]);
  });
});
