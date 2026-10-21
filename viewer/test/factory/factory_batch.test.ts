import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import shop from "../fixtures/shop.code-map.json";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { layoutTiles } from "../../src/factory/layout";
import { batch, rate, runsPerDay, summarise, type Batch, type Job } from "../../src/factory/batch";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demoMap = (): CodeMap => JSON.parse(readFileSync(DEMO, "utf8"));

function on(model: Model, container: string): Batch {
  const { bundles, doors } = model.bundles(container);
  return batch(model, container, layoutTiles(model, container, doors), bundles);
}
const job = (schedule: string[] | null, name = "j"): Job => ({ relation: `r:${name}`, job: name, schedule, target: "t" });

describe("batch model", () => {
  const demo = new Model(demoMap());
  const site = on(demo, SITE);
  const yard = (b: Batch, source: string) => b.yards.find((y) => y.source === source)!;

  it("gives nightly-jobs ten self jobs on the site and sums their runs", () => {
    const y = yard(site, "svc:nightly-jobs");
    expect(y.inner).toBe(false);
    expect(y.platforms).toEqual([]);
    expect(y.selfJobs).toHaveLength(10);
    expect(y.selfJobs.map((j) => j.job)).toEqual([...y.selfJobs.map((j) => j.job)].sort());
    expect(y.sign).toBe("10 jobs · 149×/day");
  });

  it("gives feature-store one self job, signed with its time", () => {
    const y = yard(site, "svc:feature-store");
    expect(y.selfJobs.map((j) => j.job)).toEqual(["zone_features"]);
    expect(y.platforms).toEqual([]);
    expect(y.sign).toBe("daily 01:00");
  });

  it("gives demand-forecast a platform to feature-store for the DAG it triggers, beside its own job", () => {
    const y = yard(site, "svc:demand-forecast");
    expect(y.selfJobs.map((j) => j.job)).toEqual(["demand_forecast"]);
    expect(y.platforms).toHaveLength(1);
    const p = y.platforms[0];
    expect(p.dest).toBe("svc:feature-store");
    expect(p.jobs.map((j) => [j.job, j.schedule, j.target])).toEqual([
      ["refresh_zone_features", null, "features::features.zone_features#zone_features/0"],
    ]);
    expect(p.runsPerDay).toBeNull();
    expect(y.sign).toBe("2 jobs · 1×/day + on demand");
  });

  it("sorts yards by source and lists only batch schedulers", () => {
    expect(site.yards.map((y) => y.source)).toEqual(["svc:demand-forecast", "svc:feature-store", "svc:nightly-jobs"]);
  });

  it("makes the scheduling service's own floor an inner yard", () => {
    const inner = on(demo, "svc:nightly-jobs");
    expect(inner.yards).toHaveLength(1);
    const y = inner.yards[0];
    expect(y).toMatchObject({ source: "svc:nightly-jobs", inner: true, selfJobs: [] });
    expect(y.platforms.map((p) => [p.dest, p.jobs.length])).toEqual([["jobs/dags::dags/", 10]]);
    expect(y.sign).toBe("10 jobs · 149×/day");
  });

  it("gives one platform per DAG item on the floor below, the scheduler being an ancestor", () => {
    const dags = on(demo, "jobs/dags::dags/");
    expect(dags.yards).toHaveLength(1);
    const y = dags.yards[0];
    expect(y.inner).toBe(true);
    expect(y.source).toBe("jobs/dags::dags/");
    expect(y.platforms).toHaveLength(10);
    expect(y.platforms.map((p) => p.dest)).toEqual([...y.platforms.map((p) => p.dest)].sort());
    const hourly = y.platforms.find((p) => p.dest === "jobs/dags::dags.zone_utilisation_hourly")!;
    expect(hourly.jobs.map((j) => j.job)).toEqual(["zone_utilisation_hourly"]);
    expect(hourly.runsPerDay).toBe(24);
    expect(y.platforms.some((p) => p.dest === "jobs/dags::dags._common")).toBe(false);
  });

  it("gives a platform whose destination is a door box on an inner floor: the service's own job runs outside it", () => {
    const tf = (c: string) => layoutTiles(demo, c, demo.bundles(c).doors);
    const b = on(demo, "svc:demand-forecast");
    expect(b.yards).toHaveLength(1);
    const y = b.yards[0];
    expect(y).toMatchObject({ source: "svc:demand-forecast", inner: true, selfJobs: [] });
    expect(y.platforms.map((p) => p.dest)).toEqual(["door:svc:feature-store", "forecast::forecast/"]);
    const door = y.platforms[0];
    expect(tf("svc:demand-forecast").boxes.get(door.dest)!.kind).toBe("door");
    expect(door.jobs.map((j) => j.job)).toEqual(["refresh_zone_features"]);
    expect(y.sign).toBe("2 jobs · 1×/day + on demand");
  });

  it("gives no yard on a floor that neither end of a job lands on: an ancestor's job between two other floors", () => {
    // _common sits beside the DAG files (doors here) under dags/, which schedules them; pipelines_shared sits under
    // demand-forecast, whose jobs run in forecast/ and feature-store (doors here)
    for (const c of ["jobs/dags::dags._common", "pipelines_shared::pipelines_shared/", "pipelines_shared::pipelines_shared.warehouse"])
      expect(on(demo, c).yards, c).toEqual([]);
  });

  it("reads the fixture's nightly export as a platform signed daily 02:00", () => {
    const b = on(new Model(shop as unknown as CodeMap), SITE);
    expect(b.yards).toHaveLength(1);
    const y = b.yards[0];
    expect(y.source).toBe("svc:worker");
    expect(y.platforms.map((p) => [p.dest, p.jobs.map((j) => j.job), p.runsPerDay])).toEqual([["svc:shop", ["nightly_export"], 1]]);
    expect(y.sign).toBe("daily 02:00");
  });

  it("gives no yards on a map without batch relations", () => {
    const map = shop as unknown as CodeMap;
    const bare = { ...map, relations: map.relations.filter((r) => r.kind !== "batch") } as CodeMap;
    expect(on(new Model(bare), SITE).yards).toEqual([]);
  });
});

describe("runsPerDay", () => {
  it.each<[string, number | null]>([
    ["*/15 * * * *", 96],
    ["0 * * * *", 24],
    ["30 2 * * *", 1],
    ["0 1 * * 1", 1 / 7],
    ["0 0 1 * *", 1 / 30],
    ["0 */15 * * * *", 96],
    ["0 0 9 * * *", 1],
    ["0,30 8-17 * * *", 20],
    ["0 9 * * 1-5", 5 / 7],
    ["0 9 * * MON,FRI", 2 / 7],
    ["manual", null],
    ["on reservation-events", null],
    ["every so often", null],
    ["61 * * * *", null],
    ["*/0 * * * *", null],
    ["", null],
  ])("%s", (cron, want) => {
    const got = runsPerDay(cron);
    if (want === null) expect(got).toBeNull();
    else expect(got).toBeCloseTo(want, 10);
  });
});

describe("summarise", () => {
  it.each<[string[] | null, string]>([
    [["0 2 * * *"], "daily 02:00"],
    [["5 * * * *"], "hourly :05"],
    [["*/15 * * * *"], "every 15 min"],
    [["*/45 * * * *"], "48×/day"],
    [["*/7 * * * *"], "216×/day"],
    [["*/30 * * * *"], "every 30 min"],
    [["0 1 * * 1"], "weekly Mon 01:00"],
    [null, "on demand"],
    [[], "on demand"],
    [["manual"], "on demand"],
    [["on reservation-events"], "on reservation-events"],
  ])("one job %j reads %s", (schedule, want) => {
    expect(summarise([job(schedule)])).toBe(want);
  });

  it("counts several jobs with their rounded runs and on-demand tail", () => {
    expect(summarise([job(["0 * * * *"], "a"), job(["30 2 * * *"], "b")])).toBe("2 jobs · 25×/day");
    expect(summarise([job(["0 2 * * *"], "a"), job(null, "b")])).toBe("2 jobs · 1×/day + on demand");
    expect(summarise([job(null, "a"), job(["manual"], "b")])).toBe("2 jobs · on demand");
  });

  it("a weekday job is not rounded up to once a day", () => {
    expect(rate(5 / 7)).toBe("5×/week");
    expect(rate(4 / 7)).toBe("4×/week");
    expect(rate(1)).toBe("1×/day");
    expect(summarise([job(["0 9 * * 1-5"], "a"), job(null, "b")])).toBe("2 jobs · 5×/week + on demand");
    expect(summarise([job(["0 9 * * 1-4"], "a"), job(null, "b")])).toBe("2 jobs · 4×/week + on demand");
  });

  it("never says 0×/day and is never empty", () => {
    const weekly = summarise([job(["0 1 * * 1"], "a"), job(["0 4 * * 1"], "b")]);
    expect(weekly).not.toMatch(/0×\/day/);
    expect(weekly).toBe("2 jobs · 2×/week");
    for (const s of [
      summarise([]),
      summarise([job(["garbage"])]),
      summarise([job(["garbage"], "a"), job(["junk"], "b")]),
    ]) {
      expect(s).not.toBe("");
      expect(s).not.toMatch(/0×\/day/);
    }
  });
});
