// Trains (spec §6, Task 4), the pure part: one train per lit rail, its cadence by the platform's runs per day, the
// waits at both ends, the layout pass's speed rule, and the demo floors' trains.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planFloor } from "../../src/factory/plan";
import { trainPaths, type TrainPath } from "../../src/factory/rail-place";
import { DWELL, FIRST, PERIOD_MAX, PERIOD_MIN, trainPeriod, trainSchedule } from "../../src/factory/trains";
import { defaultLit, litFor } from "../../src/floor/lit";

const DEMO = new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url);
const demo = new Model(JSON.parse(readFileSync(DEMO, "utf8")) as CodeMap);
const paths = (c: string) => { const { bundles, doors } = demo.bundles(c); const p = planFloor(demo, c, doors, bundles); return trainPaths(p.tf, p.routes); };

/** A straight synthetic rail `len` px long. */
const line = (key: string, len: number, runsPerDay: number | null): TrainPath => ({
  key, points: [{ x: 0, y: 0 }, { x: len, y: 0 }], platform: `platform:a>${key}`, station: `station:a>${key}`, source: "a", dest: key, runsPerDay,
});
/** Times in [0, span) the train on `key` leaves its yard end, sampled every `dt` s. */
function departures(s: ReturnType<typeof trainSchedule>, key: string, span: number, dt = 0.05): number {
  let n = 0, was = true;
  for (let t = 0; t < span; t += dt) {
    const tr = s.at(t).find((q) => q.key === key)!;
    const home = !tr.moving && tr.atYard;
    if (was && !home && tr.moving) n++;
    was = home;
  }
  return n;
}

describe("trains", () => {
  it("cadence: monotonic in runs per day, bounded, on demand and daily the slowest; never a blur", () => {
    const rs = [null, 0, 1 / 7, 1, 2, 4, 24, 96, 149, 1440];
    const ps = rs.map(trainPeriod);
    for (let i = 1; i < ps.length; i++) expect(ps[i], `${rs[i]}`).toBeLessThanOrEqual(ps[i - 1]);
    for (const p of ps) { expect(p).toBeGreaterThanOrEqual(PERIOD_MIN); expect(p).toBeLessThanOrEqual(PERIOD_MAX); }
    expect(trainPeriod(null)).toBe(PERIOD_MAX);
    expect(trainPeriod(96)).toBe(PERIOD_MIN);
    expect(trainPeriod(1) - trainPeriod(96), "a 96×/day track visibly busier than a daily one").toBeGreaterThan(8);
    expect(trainPeriod(24)).toBeLessThan(trainPeriod(1) - 3);
  });

  it("is deterministic: the same paths and time give the same trains", () => {
    const ps = [line("x", 400, 1), line("y", 900, 96), line("z", 60, null)];
    const a = trainSchedule(ps, new Set(["x", "y", "z"])), b = trainSchedule(ps, new Set(["x", "y", "z"]));
    for (const t of [0, 0.3, 2.5, 7.1, 13, 40.25]) expect(a.at(t)).toEqual(b.at(t));
  });

  it("only lit rails run, one train per rail, a locomotive and 2–3 wagons", () => {
    const ps = [line("x", 400, 1), line("y", 900, 96), line("z", 60, null)];
    const s = trainSchedule(ps, new Set(["x", "z"]));
    const now = s.at(1);
    expect(now.map((q) => q.key).sort()).toEqual(["x", "z"]);
    for (const tr of now) {
      expect(tr.cars[0].loco).toBe(true);
      expect(tr.cars.slice(1).every((c) => !c.loco)).toBe(true);
      expect(tr.cars.length - 1).toBeGreaterThanOrEqual(2);
      expect(tr.cars.length - 1).toBeLessThanOrEqual(3);
    }
    expect(trainSchedule(ps, new Set()).at(1)).toEqual([]);
  });

  it("a busier track departs more often", () => {
    const s = trainSchedule([line("daily", 500, 1), line("q15", 500, 96), line("hourly", 500, 24)], new Set(["daily", "q15", "hourly"]));
    const span = 120;
    const d = { daily: departures(s, "daily", span), hourly: departures(s, "hourly", span), q15: departures(s, "q15", span) };
    expect(d.q15).toBeGreaterThan(d.hourly);
    expect(d.hourly).toBeGreaterThan(d.daily);
    expect(d.daily).toBeGreaterThan(0);
  });

  it("waits at both ends; runs out loaded and back empty within about 3 s each way", () => {
    const p = line("x", 1500, 1), s = trainSchedule([p], new Set(["x"])), run = s.runs[0];
    expect(run.run).toBeLessThanOrEqual(3 + 1e-9);   // the layout pass: a path in at most about 3 s
    const short = trainSchedule([line("s", 150, 1)], new Set(["s"])).runs[0];
    expect(short.run).toBeCloseTo((short.s1 - short.s0) / 60, 6);   // a short rail: the belts' steady 60 px/s
    let yardWait = 0, stationWait = 0, out = 0, back = 0;
    const dt = 0.01;
    for (let t = 0; t < run.period; t += dt) {
      const tr = s.at(t)[0];
      if (!tr.moving && tr.atYard) yardWait += dt;
      else if (!tr.moving) stationWait += dt;
      else if (tr.cars[1].loaded) out += dt; else back += dt;
    }
    expect(yardWait).toBeGreaterThan(1);
    expect(stationWait).toBeCloseTo(DWELL, 1);
    expect(out).toBeCloseTo(run.run, 1);
    expect(back).toBeCloseTo(run.run, 1);
    // waiting at the station, the locomotive's nose is at the buffer stop, its wagons behind it on the line; at the yard
    // the whole train stands on its platform tile (wagons under the locomotive), and pulls out locomotive first
    const station = s.at(s.departAt("x") + run.run + DWELL / 2)[0], yard = s.parked()[0], out1 = s.at(s.departAt("x") + run.run / 2)[0];
    expect(station.atYard).toBe(false);
    expect(station.cars[0].x).toBeGreaterThan(1500 - 20);
    expect(station.cars[1].x).toBeLessThan(station.cars[0].x);
    for (const c of yard.cars) expect(c.x).toBeLessThan(24 - 8);
    expect(out1.moving).toBe(true);
    expect(out1.cars[0].x).toBeGreaterThan(out1.cars[1].x);
  });

  it("parked: every train sits at its yard or door end, not moving", () => {
    const ps = paths("features::features/");
    const s = trainSchedule(ps, new Set(ps.map((p) => p.key)));
    const parked = s.parked();
    expect(parked.length).toBe(ps.length);
    for (const tr of parked) {
      const p = ps.find((q) => q.key === tr.key)!, a = p.points[0];
      expect(tr.moving).toBe(false);
      expect(tr.atYard).toBe(true);
      const last = tr.cars[tr.cars.length - 1];
      expect(Math.abs(last.x - a.x) + Math.abs(last.y - a.y), `${tr.key} near its yard or door end`).toBeLessThan(24);
    }
  });

  it("demo floors: F0 runs demand-forecast → feature-store; dags/ runs ten, the 96× and 24× tracks more often than the daily", () => {
    const f0 = paths(SITE);
    expect(f0.map((p) => [p.source, p.dest])).toContainEqual(["svc:demand-forecast", "svc:feature-store"]);
    const lit0 = new Set(defaultLit(demo, SITE, f0.map((p) => p.key)));
    expect(trainSchedule(f0, lit0).at(0).length).toBe(f0.length);

    const dags = paths("jobs/dags::dags/");
    expect(dags.length).toBe(10);
    const s = trainSchedule(dags, new Set(defaultLit(demo, "jobs/dags::dags/", dags.map((p) => p.key))));
    expect(s.at(0).length).toBe(10);
    const busy = dags.filter((p) => (p.runsPerDay ?? 0) >= 24), daily = dags.filter((p) => p.runsPerDay !== null && p.runsPerDay <= 1);
    expect(busy.length).toBeGreaterThan(0);
    expect(daily.length).toBeGreaterThan(0);
    for (const b of busy) for (const d of daily) expect(departures(s, b.key, 150, 0.1), `${b.key} vs ${d.key}`).toBeGreaterThan(departures(s, d.key, 150, 0.1));
    for (const r of s.runs) expect(r.period, "none is a blur").toBeGreaterThanOrEqual(PERIOD_MIN);

    const feat = paths("features::features/");
    // the features floor: S6's yard to zone_features.py, and the S4 door to its station on zone_features.py
    expect(feat.length).toBe(2);
    expect(new Set(feat.map((p) => p.dest)).size).toBe(1);
    expect(feat.filter((p) => p.source.startsWith("door:")).length).toBe(1);
    expect(trainSchedule(feat, new Set(defaultLit(demo, "features::features/", feat.map((p) => p.key)))).at(0).length).toBe(2);
  });

  it("every train first leaves within about 3 s of the floor opening, waiting at its yard till then; later by the cadence", () => {
    for (const c of [SITE, "jobs/dags::dags/", "features::features/"]) {
      const ps = paths(c), s = trainSchedule(ps, new Set(ps.map((p) => p.key)));
      expect(s.runs.length, c).toBe(ps.length);
      const firsts = s.runs.map((r) => s.departAt(r.key));
      for (const [k, r] of s.runs.entries()) {
        expect(firsts[k], `${c} ${r.key}`).toBeLessThanOrEqual(FIRST);
        const before = s.at(firsts[k] / 2)[k];   // till its first departure (at 0 for the first rail) it waits at its yard
        if (firsts[k] > 0.05) expect([before.moving, before.atYard], `${c} ${r.key} waits at its yard till then`).toEqual([false, true]);
        expect(s.at(firsts[k] + 0.05)[k].moving, `${c} ${r.key} leaves at its first departure`).toBe(true);
        expect(s.at(firsts[k] + r.period + 0.05)[k].moving, `${c} ${r.key} and again one period later`).toBe(true);
        expect(s.at(firsts[k] + r.period - 0.05)[k].atYard, `${c} ${r.key} not before`).toBe(true);
      }
      if (ps.length > 1) expect(new Set(firsts.map((f) => f.toFixed(3))).size, `${c} a yard's trains do not all leave together`).toBeGreaterThan(1);
    }
  });

  it("at(t, out) fills the same objects in place and matches a fresh call", () => {
    const ps = paths("jobs/dags::dags/"), s = trainSchedule(ps, new Set(ps.map((p) => p.key)));
    const out = s.at(0.5, []), trains = [...out], cars = out.map((t) => t.cars), car0 = out.map((t) => t.cars[0]);
    for (const t of [1, 4.2, 9.9, 33]) {
      const filled = s.at(t, out);
      expect(filled).toBe(out);
      expect(filled.every((q, k) => q === trains[k] && q.cars === cars[k] && q.cars[0] === car0[k])).toBe(true);
      expect(filled).toEqual(s.at(t));
    }
    expect(s.at(1, [])).toEqual(s.at(1));
  });

  it("the default lit set holds every train path's key, stand-in rails too", () => {
    for (const c of [SITE, "svc:demand-forecast", "features::features/"]) {
      const rails = paths(c).map((p) => p.key);
      const lit = defaultLit(demo, c, rails);
      for (const k of rails) expect(lit, `${c} ${k}`).toContain(k);
      for (const b of demo.bundles(c).bundles) expect(lit).toContain(b.key);
      expect(new Set(lit).size, `${c} no key twice`).toBe(lit.length);
      expect(litFor(demo, c, null, () => [], rails)).toEqual(lit);
      if (rails.length) expect(litFor(demo, c, { type: "bundle", key: rails[0] }, () => [], rails)).toEqual([rails[0]]);
    }
    expect(paths("svc:demand-forecast").some((p) => p.key.startsWith("rail:")), "a stand-in rail on demand-forecast's floor").toBe(true);
  });
});
