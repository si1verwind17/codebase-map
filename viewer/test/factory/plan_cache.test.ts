// The scene's plan cache (state.ts PLAN_CACHE, an Lru): a floor whose plan was evicted is planned again when shown, and
// the side caches its first draw hangs on the plan (messaging, rail labels, badge spots) are rebuilt on the new plan,
// equal to the evicted ones, never carried over from it.
import { readFileSync } from "node:fs";
import { CanvasTextMetrics } from "pixi.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import type { FloorPlan, SceneState } from "../../src/floor/state";
import { PLAN_CACHE } from "../../src/floor/state";
import { FloorScene } from "../../src/floor/scene";
import { Lru } from "../../src/floor/lru";
import { planJob } from "../../src/factory/plan-job";
import type { Deadline, Scheduler } from "../../src/floor/precompute";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);

/** A scene with no renderer and no idle planning, node's missing text measuring stood in for (render_groups.test.ts). */
function bareScene(schedule: Scheduler = () => () => {}, planners?: ConstructorParameters<typeof FloorScene>[2]) {
  vi.spyOn(CanvasTextMetrics, "measureText").mockImplementation((text = " ") => {
    const w = text.length * 7;
    return { text, width: w, height: 14, lines: [text], lineWidths: [w], lineHeight: 14, maxLineWidth: w, fontProperties: { ascent: 11, descent: 3, fontSize: 14 } } as unknown as CanvasTextMetrics;
  });
  const scene = new FloorScene({ select: () => {}, enter: () => {}, up: () => {}, door: () => {} }, schedule, planners);
  const st = (scene as unknown as { s: SceneState }).s;
  (st as { app: unknown }).app = { canvas: { dataset: {} }, screen: { width: 1440, height: 900 } };
  return { scene, st };
}

describe("plan cache", () => {
  afterEach(() => vi.restoreAllMocks());

  it("holds PLAN_CACHE plans", () => {
    const { st } = bareScene();
    expect(st.plans).toBeInstanceOf(Lru);
    expect(st.plans.max).toBe(PLAN_CACHE);
  });

  it("an evicted floor is planned again when shown, its side caches rebuilt equal on the new plan", () => {
    const { scene, st } = bareScene();
    st.plans = new Lru<string, FloorPlan>(2);
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    // a floor with rails (rail labels) besides F0 (messaging, badges), and one more to push it out
    const floors = Object.keys(model.map.layout.containers).filter((c) => c !== SITE && model.floor(c)).sort();
    const shownPlan = (c: string) => { scene.show(model, c); return st.plans.get(c)!; };
    const railed = floors.find((c) => shownPlan(c).tf.rails)!;
    expect(railed, "the demo has a floor with rails").toBeDefined();
    st.plans.clear();

    for (const a of [SITE, railed]) {
      const first = shownPlan(a);
      const before = { msg: first.msg, rail: first.rail, badges: first.badges };
      expect(before.msg, `${a}: its first draw worked out the messaging`).toBeDefined();
      if (a === railed) expect(before.rail, "and the rail labels").toBeDefined();
      for (const other of floors.filter((c) => c !== a).slice(0, 2)) scene.show(model, other);
      expect(st.plans.has(a), `${a} evicted`).toBe(false);
      expect(st.plans.size).toBeLessThanOrEqual(2);
      const again = shownPlan(a);
      expect(again, `${a} planned again`).not.toBe(first);
      expect(again.tf).not.toBe(first.tf);
      expect(again.tf).toEqual(first.tf);
      expect(again.msg).not.toBe(before.msg);
      expect(again.msg).toEqual(before.msg);
      expect(again.rail === undefined || again.rail !== before.rail).toBe(true);
      expect(again.rail).toEqual(before.rail);
      expect(again.badges === undefined || again.badges !== before.badges).toBe(true);
      expect(again.badges).toEqual(before.badges);
      expect(st.tf).toBe(again.tf);
    }
  }, 120_000);
});

/** A planner on a model of its own, as the worker's is: nothing it works out reaches the page's model. */
const ownModelPlanner = () => {
  const own = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
  return () => ({ where: "worker" as const, plan: async (c: string) => planJob(own, c, own.bundles(c)), dispose: () => {} });
};

describe("warming the page's model", () => {
  afterEach(() => vi.restoreAllMocks());
  const settle = () => new Promise<void>((r) => setTimeout(r, 0));
  const idle: Deadline = { timeRemaining: () => 20 };

  it("a floor planned ahead has its bundles and door landings cached on the page's model afterwards", async () => {
    const slices: ((d?: Deadline) => void)[] = [];
    const { scene, st } = bareScene((s) => { slices.push(s); return () => {}; }, ownModelPlanner());
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    scene.show(model, SITE);
    const next = Object.keys(model.floor(SITE)!.items).find((id) => model.floor(id))!;
    const worked = vi.spyOn(model as unknown as { bundlesOf: (c: string, l: boolean) => unknown }, "bundlesOf");
    const landed = vi.spyOn(model as unknown as { landing: (c: string, a: string) => unknown }, "landing");
    for (let i = 0; i < 40 && !st.plans.has(next); i++) { slices.shift()?.(idle); await settle(); }
    expect(st.plans.has(next), "the nearby floor was planned").toBe(true);
    expect(worked.mock.calls.filter(([c]) => c === next), "planning it left the page's model cold").toHaveLength(0);
    slices.shift()?.(idle);
    expect(worked.mock.calls.filter(([c]) => c === next), "the slice after warmed its bundles").toHaveLength(1);
    const doors = model.bundles(next).doors;
    expect(doors.length, "a floor with doors").toBeGreaterThan(0);
    expect(landed.mock.calls.filter(([c]) => c === next), "and its doors' landings").toHaveLength(doors.length);
    worked.mockClear(); landed.mockClear();
    scene.show(model, next);
    expect(worked, "entering it works out no bundles").not.toHaveBeenCalled();
    expect(landed, "nor door landings").not.toHaveBeenCalled();
  }, 120_000);

  it("a floor waited for is warmed in idle time during the wait", async () => {
    const slices: ((d?: Deadline) => void)[] = [];
    const { scene, st } = bareScene((s) => { slices.push(s); return () => {}; }, ownModelPlanner());
    const model = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
    scene.show(model, SITE);
    slices.length = 0;
    const far = Object.keys(model.map.layout.containers).filter((c) => model.floor(c) && !st.plans.has(c)).sort().at(-1)!;
    const worked = vi.spyOn(model as unknown as { bundlesOf: (c: string, l: boolean) => unknown }, "bundlesOf");
    const wait = scene.ready(model, far);
    expect(slices, "a slice is asked for").toHaveLength(1);
    slices.shift()!({ timeRemaining: () => 0 });
    expect(worked.mock.calls.filter(([c]) => c === far), "not with no idle time left").toHaveLength(0);
    slices.shift()!(idle);
    expect(worked.mock.calls.filter(([c]) => c === far)).toHaveLength(1);
    await wait;
    worked.mockClear();
    scene.show(model, far);
    expect(worked).not.toHaveBeenCalled();
  }, 120_000);
});
