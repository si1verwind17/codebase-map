// src/factory/trains.ts
// When each train runs, pure: a function of the floor's train paths, the lit set and the time, with
// no randomness. One train per lit rail: a locomotive and 2–3 wagons. In each period it waits at its yard platform (or
// door) loaded, runs to the station, waits there (unloading halfway), and runs back empty, the locomotive staying at
// the station end. A busier platform (more runs per day) has a shorter period, so it departs more often:
//   period = PERIOD_MAX − (PERIOD_MAX − PERIOD_MIN) · min(1, ln(1 + r) / ln(1 + BUSY))
// with r its runs per day (on demand: 0). Each way takes the layout pass's time (`moverSpeed`: at most about 3 s), so
// even the busiest track leaves a wait of over a second at its yard. Every train first leaves within FIRST s of the
// floor opening (the controller, 2026-10-06), at frac(i · φ) · FIRST for the rail at index i (capped by its yard
// wait, so it starts out waiting at its yard): a yard's trains do not all leave together, and none keeps the reader
// waiting a whole quiet period. Later departures follow the cadence.
import { moverSpeed } from "../floor/lane";
import type { Pt } from "../route/types";
import type { TrainPath } from "./rail-place";
import { T } from "./tiles";

/** Seconds between departures on the quietest track (on demand, weekly, daily…) and on the busiest. */
export const PERIOD_MAX = 24;
export const PERIOD_MIN = 9;
/** Runs per day at and above which a track departs every PERIOD_MIN s (every 15 minutes). */
export const BUSY = 96;
/** Seconds a train waits at its station. */
export const DWELL = 1.5;
/** Px between the centres of neighbouring cars, and half a locomotive's length. */
const GAP = 22, NOSE = 9;
const GOLDEN = 0.6180339887;
/** Every train's first departure comes within this many seconds of the floor opening. */
export const FIRST = 3;

/** A track's period, s: monotonic in its runs per day, PERIOD_MAX for on demand and PERIOD_MIN from BUSY up. */
export function trainPeriod(runsPerDay: number | null): number {
  const r = Math.max(0, runsPerDay ?? 0);
  return PERIOD_MAX - (PERIOD_MAX - PERIOD_MIN) * Math.min(1, Math.log1p(r) / Math.log1p(BUSY));
}

/** One rail's run: where its locomotive waits at either end (px along the path) and its timing. A wagon that has not
 *  yet pulled out stands under the locomotive's place at the yard end (s0). */
export interface TrainRun {
  key: string; points: Pt[]; lengths: number[];
  wagons: number;
  /** the locomotive's distance along the path at the yard (or door) end and at the buffer stop */
  s0: number; s1: number;
  period: number;
  /** seconds each way */
  run: number;
  /** seconds into its period at t = 0 */
  phase: number;
}
/** One car: its centre, whether it lies along x, the locomotive or a wagon, and (a wagon) whether it carries a crate. */
export interface Car { x: number; y: number; horizontal: boolean; loco: boolean; loaded: boolean }
export interface Train { key: string; cars: Car[]; moving: boolean; atYard: boolean }

export interface TrainSchedule {
  runs: TrainRun[];
  /** What runs at `t` s. Pass `out` to have it filled in place (its trains, car arrays and cars reused: no garbage
   *  per frame); without it every call returns fresh objects. */
  at(t: number, out?: Train[]): Train[];
  /** Every train at its yard (or door) end, still: what Still motion shows. */
  parked(): Train[];
  /** The first time ≥ 0 at which the train on `key` leaves its yard end. */
  departAt(key: string): number;
}

const cumulative = (pts: Pt[]) => { const l = [0]; for (let i = 1; i < pts.length; i++) l.push(l[i - 1] + Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y)); return l; };

/** The point `d` px along `pts` (clamped to its ends) and whether its segment there lies along x, written into `into`. */
function along(pts: Pt[], lengths: number[], d: number, into: Car): void {
  const total = lengths[lengths.length - 1];
  const x = Math.max(0, Math.min(total, d));
  let i = 1;
  while (i < lengths.length - 1 && lengths[i] < x) i++;
  const a = pts[i - 1] ?? pts[0], b = pts[i] ?? a;
  const seg = lengths[i] - lengths[i - 1] || 1, t = (x - lengths[i - 1]) / seg;
  into.x = a.x + (b.x - a.x) * t;
  into.y = a.y + (b.y - a.y) * t;
  into.horizontal = a.y === b.y;
}

/** Trains for the lit ones of `paths`; `period` maps a platform's runs per day to its period (the cadence). */
export function trainSchedule(paths: TrainPath[], lit: ReadonlySet<string>, period: (runsPerDay: number | null) => number = trainPeriod): TrainSchedule {
  const runs: TrainRun[] = [];
  paths.forEach((p, i) => {
    if (!lit.has(p.key) || p.points.length < 2) return;
    const lengths = cumulative(p.points), total = lengths[lengths.length - 1];
    const wagons = total >= 8 * T ? 3 : 2;
    // at the yard the locomotive stands on its own platform tile, its wagons drawn in under it (a yard's links share
    // tiles: a whole train waiting there would lie across its neighbours'); they pull out behind it as it leaves
    const s1 = Math.max(0, total - NOSE), s0 = Math.min(NOSE, s1);
    const len = s1 - s0, P = period(p.runsPerDay);
    const run = len > 0 ? len / moverSpeed("train", len) : 0;
    const W = P - 2 * run - DWELL, first = ((i * GOLDEN) % 1) * Math.min(FIRST, W);
    runs.push({ key: p.key, points: p.points, lengths, wagons, s0, s1, period: P, run, phase: (((W - first) % P) + P) % P });
  });
  const wait = (r: TrainRun) => r.period - 2 * r.run - DWELL;   // at the yard end
  /** Fill `tr` (its cars reused) with run `r`'s train, its locomotive `d` px along the path. */
  const train = (tr: Train, r: TrainRun, d: number, moving: boolean, atYard: boolean, loaded: boolean): Train => {
    tr.key = r.key; tr.moving = moving; tr.atYard = atYard;
    tr.cars.length = Math.min(tr.cars.length, r.wagons + 1);
    for (let c = 0; c <= r.wagons; c++) {
      const car = tr.cars[c] ?? (tr.cars[c] = { x: 0, y: 0, horizontal: true, loco: false, loaded: false });
      along(r.points, r.lengths, Math.max(r.s0, d - c * GAP), car);
      car.loco = c === 0;
      car.loaded = c > 0 && loaded;
    }
    return tr;
  };
  const fresh = (): Train => ({ key: "", cars: [], moving: false, atYard: true });
  const state = (tr: Train, r: TrainRun, t: number): Train => {
    const W = wait(r), u = (((t + r.phase) % r.period) + r.period) % r.period;
    if (u < W) return train(tr, r, r.s0, false, true, true);
    if (u < W + r.run) return train(tr, r, r.s0 + (r.s1 - r.s0) * ((u - W) / r.run), true, false, true);
    if (u < W + r.run + DWELL) return train(tr, r, r.s1, false, false, u < W + r.run + DWELL / 2);
    return train(tr, r, r.s1 - (r.s1 - r.s0) * Math.min(1, (u - W - r.run - DWELL) / (r.run || 1)), true, false, false);
  };
  return {
    runs,
    at: (t, out) => {
      const res = out ?? [];
      res.length = Math.min(res.length, runs.length);
      for (let k = 0; k < runs.length; k++) state(res[k] ?? (res[k] = fresh()), runs[k], t);
      return res;
    },
    parked: () => runs.map((r) => train(fresh(), r, r.s0, false, true, true)),
    departAt: (key) => { const r = runs.find((q) => q.key === key)!; return (((wait(r) - r.phase) % r.period) + r.period) % r.period; },
  };
}
