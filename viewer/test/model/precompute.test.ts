import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { createRunner, nextFloors, type Scheduler } from "../../src/floor/precompute";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";

const demo = new Model(JSON.parse(readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8")) as CodeMap);

/** A scheduler the test steps by hand. */
function manual() {
  const waiting: (() => void)[] = [];
  const schedule: Scheduler = (slice) => { waiting.push(slice); return () => { const i = waiting.indexOf(slice); if (i >= 0) waiting.splice(i, 1); }; };
  return { schedule, waiting, step: () => waiting.shift()?.() };
}

describe("nextFloors", () => {
  it("on the demo's F0 lists the floors its machines open, in machine order", () => {
    const items = Object.keys(demo.floor(SITE)!.items);
    const want = items.filter((id) => demo.floor(id));
    expect(want.length).toBeGreaterThan(3);
    expect(nextFloors(demo, SITE)).toEqual(want);
  });

  it("puts the selected machine's floor first and the parent floor last", () => {
    const kids = nextFloors(demo, SITE);
    const last = kids[kids.length - 1];
    expect(nextFloors(demo, SITE, last)[0]).toBe(last);
    expect(nextFloors(demo, SITE, last).sort()).toEqual([...kids].sort());
    const inner = nextFloors(demo, kids[0]);
    expect(inner[inner.length - 1]).toBe(SITE);
    expect(nextFloors(demo, kids[0], "not-an-item")).toEqual(inner);
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
    const runner = createRunner({ schedule: (s) => { slices.push(s); return () => {}; }, busy: () => false, planned: () => false, plan: (c) => done.push(c) });
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
});
