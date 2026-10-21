// planJob is planFloor over the floor's bundles, and a plan survives the structured clone the layout worker sends it
// through: every floor of the demo, the shop fixture and the guide maps, compared whole and through the pure functions
// the scene runs on a plan (geometry, train paths, flight paths, the keys flights cover).
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { Model } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { planJob, planWorkerState, type PlanReply } from "../../src/factory/plan-job";
import { toGeometry } from "../../src/factory/layout";
import { trainPaths } from "../../src/factory/rail-place";
import { coveredKeys, flightPaths } from "../../src/factory/flights";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const SHOP = new URL("../fixtures/shop.code-map.json", import.meta.url);
const GUIDE = new URL("../../guide/maps/", import.meta.url);
const MAPS: [string, string][] = [
  ["demo", readFileSync(DEMO, "utf8")],
  ["shop", readFileSync(SHOP, "utf8")],
  ...readdirSync(GUIDE).filter((f) => f.endsWith(".code-map.json")).sort().map((f): [string, string] => [f, readFileSync(new URL(f, GUIDE), "utf8")]),
];
const floors = (m: Model) => Object.keys(m.map.layout.containers).filter((c) => m.floor(c));

describe("planJob", () => {
  it.each(MAPS)("%s: equals planFloor over the floor's bundles, and its structured clone plans the same", (_name, text) => {
    const m = new Model(JSON.parse(text) as CodeMap);
    for (const c of floors(m)) {
      const b = m.bundles(c);
      const plan = planJob(m, c);
      expect(plan, c).toEqual(planFloor(m, c, b.doors, b.bundles, b.layered));
      const clone = structuredClone(plan);
      expect(clone, c).toStrictEqual(plan);   // no class instance, function or undefined field lost on the way
      expect(toGeometry(clone.tf), c).toEqual(toGeometry(plan.tf));
      expect(trainPaths(clone.tf, clone.routes), c).toEqual(trainPaths(plan.tf, plan.routes));
      const paths = flightPaths(clone.tf);
      expect(paths, c).toEqual(flightPaths(plan.tf));
      expect(coveredKeys(paths, b.bundles), c).toEqual(coveredKeys(flightPaths(plan.tf), b.bundles));
    }
  }, 120_000);
});

describe("planWorkerState", () => {
  const [, text] = MAPS[0];
  const m = new Model(JSON.parse(text) as CodeMap);

  it("answers a plan after the map with planJob's plan, for every floor", () => {
    const st = planWorkerState();
    expect(st.handle({ kind: "map", text })).toBeNull();
    let id = 0;
    for (const c of floors(m)) {
      const r = st.handle({ kind: "plan", id: ++id, container: c }) as Extract<PlanReply, { plan: unknown }>;
      expect(r.id).toBe(id);
      expect(r.container).toBe(c);
      expect(r.plan, c).toEqual(planJob(m, c));
    }
  }, 60_000);

  it("answers a plan before the map, or for an unknown floor, with an error, never a throw", () => {
    const st = planWorkerState();
    expect(st.handle({ kind: "plan", id: 1, container: "site" })).toEqual({ id: 1, container: "site", error: expect.any(String) });
    st.handle({ kind: "map", text });
    expect(st.handle({ kind: "plan", id: 2, container: "no-such-floor" })).toEqual({ id: 2, container: "no-such-floor", error: expect.any(String) });
    expect("plan" in st.handle({ kind: "plan", id: 3, container: "site" })!).toBe(true);
  });

  it("answers a map that is not JSON with an error", () => {
    const st = planWorkerState();
    st.handle({ kind: "map", text: "{" });
    expect(st.handle({ kind: "plan", id: 1, container: "site" })).toEqual({ id: 1, container: "site", error: expect.any(String) });
  });
});
