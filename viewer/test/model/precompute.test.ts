import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { createRunner, MAX_NEARBY, nextFloors, type Deadline, type Scheduler } from "../../src/floor/precompute";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";

const demo = new Model(JSON.parse(readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8")) as CodeMap);

/** A scheduler the test steps by hand; `step(deadline)` passes an idle deadline, as requestIdleCallback does. */
function manual() {
  const waiting: ((d?: Deadline) => void)[] = [];
  const schedule: Scheduler = (slice) => { waiting.push(slice); return () => { const i = waiting.indexOf(slice); if (i >= 0) waiting.splice(i, 1); }; };
  return { schedule, waiting, step: (d?: Deadline) => waiting.shift()?.(d) };
}

describe("nextFloors", () => {
  it("on the demo's F0 lists the first MAX_NEARBY floors its machines open, in machine order", () => {
    const items = Object.keys(demo.floor(SITE)!.items);
    const want = items.filter((id) => demo.floor(id));
    expect(want.length).toBeGreaterThan(MAX_NEARBY);
    expect(nextFloors(demo, SITE)).toEqual(want.slice(0, MAX_NEARBY));
    expect(nextFloors(demo, SITE, undefined, Infinity)).toEqual(want);
  });

  it("puts the selected machine's floor first and the parent floor last", () => {
    const kids = nextFloors(demo, SITE, undefined, Infinity);
    const last = kids[kids.length - 1];
    expect(nextFloors(demo, SITE, last)[0]).toBe(last);
    expect(nextFloors(demo, SITE, last)).toEqual([last, ...kids.slice(0, MAX_NEARBY)]);
    expect(nextFloors(demo, SITE, last, Infinity).sort()).toEqual([...kids].sort());
    const inner = nextFloors(demo, kids[0]);
    expect(inner[inner.length - 1]).toBe(SITE);
    expect(nextFloors(demo, kids[0], "not-an-item")).toEqual(inner);
  });

  it("limit 0 gives the selected floor and the parent", () => {
    const kids = nextFloors(demo, SITE, undefined, Infinity);
    expect(nextFloors(demo, SITE, kids[3], 0)).toEqual([kids[3]]);
    expect(nextFloors(demo, SITE, undefined, 0)).toEqual([]);
    const inner = nextFloors(demo, kids[0], undefined, Infinity);
    expect(inner.length).toBeGreaterThan(1);
    const sel = Object.keys(demo.floor(kids[0])!.items).find((id) => demo.floor(id))!;
    expect(nextFloors(demo, kids[0], sel, 0)).toEqual([sel, SITE]);
    expect(nextFloors(demo, kids[0], undefined, 0)).toEqual([SITE]);
  });
});

describe("createRunner", () => {
  const make = (planned = new Set<string>(), busy = () => false) => {
    const t = manual(), done: string[] = [];
    const runner = createRunner({ schedule: t.schedule, busy, planned: (c) => planned.has(c), plan: (c) => { planned.add(c); done.push(c); } });
    return { t, done, runner, planned };
  };

  it("plans one floor per slice", () => {
    const { t, done, runner } = make();
    runner.start(["a", "b", "c"]);
    t.step();
    expect(done).toEqual(["a"]);
    t.step(); t.step();
    expect(done).toEqual(["a", "b", "c"]);
    expect(t.waiting).toHaveLength(0);
  });

  it("drops the queue when started again (the floor changed) or stopped", () => {
    const { t, done, runner } = make();
    runner.start(["a", "b"]);
    t.step();
    runner.start(["x"]);
    t.step();
    expect(done).toEqual(["a", "x"]);
    expect(t.waiting).toHaveLength(0);
    runner.start(["y"]);
    runner.stop();
    expect(t.waiting).toHaveLength(0);
    expect(runner.pending).toBe(0);
  });

  it("never runs a slice queued before stop, even when the scheduler cannot cancel it", () => {
    const slices: (() => void)[] = [], done: string[] = [];
    const runner = createRunner({ schedule: (s) => { slices.push(s); return () => {}; }, busy: () => false, planned: () => false, plan: (c) => { done.push(c); } });
    runner.start(["a", "b"]);
    runner.stop();
    slices.forEach((s) => s());
    expect(done).toEqual([]);
    runner.start(["c"]);   // the old slice stays dead; the new one runs
    slices.forEach((s) => s());
    expect(done).toEqual(["c"]);
  });

  it("skips floors already planned", () => {
    const { t, done, runner } = make(new Set(["a", "b"]));
    runner.start(["a", "b", "c", "d"]);
    t.step();
    expect(done).toEqual(["c"]);
    t.step();
    expect(done).toEqual(["c", "d"]);
  });

  it("plans nothing while busy and schedules again", () => {
    let moving = true;
    const { t, done, runner } = make(new Set(), () => moving);
    runner.start(["a"]);
    t.step(); t.step();
    expect(done).toEqual([]);
    expect(t.waiting).toHaveLength(1);
    moving = false;
    t.step();
    expect(done).toEqual(["a"]);
  });

  /** A runner whose plan answers later, when the test resolves it. */
  const later = () => {
    const t = manual(), started: string[] = [], answer: (() => void)[] = [];
    const runner = createRunner({ schedule: t.schedule, busy: () => false, planned: () => false,
      plan: (c) => { started.push(c); return new Promise<void>((r) => answer.push(r)); } });
    return { t, started, answer, runner };
  };
  const settle = () => new Promise<void>((r) => setTimeout(r, 0));

  it("waits for an async plan before the next slice", async () => {
    const { t, started, answer, runner } = later();
    runner.start(["a", "b"]);
    t.step();
    expect(started).toEqual(["a"]);
    expect(t.waiting, "no slice while a plan is in flight").toHaveLength(0);
    answer[0]();
    await settle();
    expect(t.waiting).toHaveLength(1);
    t.step();
    expect(started).toEqual(["a", "b"]);
  });

  it("pending counts the floor in flight", async () => {
    const { t, answer, runner } = later();
    runner.start(["a", "b"]);
    expect(runner.pending).toBe(2);
    t.step();
    expect(runner.pending).toBe(2);
    answer[0]();
    await settle();
    expect(runner.pending).toBe(1);
  });

  it("never has two plans in flight, even when started again meanwhile", async () => {
    const { t, started, answer, runner } = later();
    runner.start(["a"]);
    t.step();
    runner.start(["x"]);
    expect(t.waiting).toHaveLength(0);
    expect(runner.pending).toBe(2);
    answer[0]();
    await settle();
    t.step();
    expect(started).toEqual(["a", "x"]);
    runner.stop();
    answer[1]();
    await settle();
    expect(t.waiting, "a plan ending after stop schedules nothing").toHaveLength(0);
  });

  /** A runner with an async plan and a `warm` step that records the floors it warms. */
  const warming = (planned = new Set<string>()) => {
    const t = manual(), started: string[] = [], warmed: string[] = [], answer: ((ok: boolean) => void)[] = [];
    const runner = createRunner({ schedule: t.schedule, busy: () => false, planned: (c) => planned.has(c),
      plan: (c) => { started.push(c); return new Promise<void>((r, j) => answer.push((ok) => { if (ok) { planned.add(c); r(); } else j(new Error("no")); })); },
      warm: (c) => { if (warmed.includes(c)) return false; warmed.push(c); return true; } });
    return { t, started, warmed, answer, runner };
  };

  it("warms a floor in the slice after its plan answers, then plans the next", async () => {
    const { t, started, warmed, answer, runner } = warming();
    runner.start(["a", "b"]);
    t.step();
    answer[0](true);
    await settle();
    expect(runner.pending, "b queued, a to warm").toBe(2);
    t.step();
    expect(warmed).toEqual(["a"]);
    expect(started, "one floor per slice").toEqual(["a"]);
    t.step();
    expect(started).toEqual(["a", "b"]);
  });

  it("warms a queued floor already planned in its own slice, and skips one already warm", () => {
    const { t, started, warmed, runner } = warming(new Set(["a", "b"]));
    runner.start(["a", "b", "c"]);
    t.step();
    expect(warmed).toEqual(["a"]);
    expect(started).toEqual([]);
    t.step();
    expect(warmed).toEqual(["a", "b"]);
    runner.start(["a", "b", "c"]);
    t.step();
    expect(warmed, "a and b warm already: c is planned in the same slice").toEqual(["a", "b"]);
    expect(started).toEqual(["c"]);
  });

  it("warms nothing for a plan that failed, nor while idle time has run out", async () => {
    const { t, warmed, answer, runner } = warming();
    runner.start(["a", "b"]);
    t.step();
    answer[0](false);
    await settle();
    t.step({ timeRemaining: () => 0 });
    expect(warmed).toEqual([]);
    t.step({ timeRemaining: () => 10 });
    answer[1](true);
    await settle();
    t.step({ timeRemaining: () => 0 });
    expect(warmed).toEqual([]);
    t.step({ timeRemaining: () => 10 });
    expect(warmed).toEqual(["b"]);
    expect(runner.pending).toBe(0);
  });

  it("a slice with no idle time left plans nothing and schedules again", () => {
    const { t, done, runner } = make();
    runner.start(["a"]);
    t.step({ timeRemaining: () => 0 });
    expect(done).toEqual([]);
    expect(t.waiting).toHaveLength(1);
    t.step({ timeRemaining: () => 12 });
    expect(done).toEqual(["a"]);
  });
});
