// src/factory/drones.ts
// When each drone flies, pure: a function of the floor's flight paths, the lit set and the time, with
// no randomness. The floor runs in cycles of one period. In each cycle, per hub:
//   - produce / enqueue (and failures into a dead-letter hub) fly in first;
//   - once the last of them lands, the hub hands on: one copy to every lit consumer group, the push to its dock, one
//     crate from a queue's waiting stack to one worker (round-robin across the takers' replicas, one per cycle), and
//     a pull's drone, which left its pad empty in time to reach the hub just then, flies back loaded;
//   - every FAIL_EVERY-th cycle a consumer with a failure flight sends a red drone from its failure pad to the
//     dead-letter hub, once its own delivery has landed; that hub then hands on in turn.
// A hub none of whose lit inbound flights fly this cycle hands nothing on. A hub with no lit inbound at all hands on
// at the start of the cycle. Every drone on the floor flies at one speed: the floor's longest flight takes about 5 s
// (`moverSpeed`, `longestFlight`).
import { moverSpeed } from "../floor/lane";
import type { Pt } from "../route/types";
import type { FlightPath } from "./flights";
import type { Messaging } from "./messaging";
import type { Stack } from "./layout";
import { T } from "./tiles";

/** What the schedule reads: the floor's flight paths, its messaging (replicas, dead-letter links) and waiting stacks. */
export interface DroneFloor { flights: FlightPath[]; messaging: Messaging; stacks: Stack[] }

/** One drone's flight in a cycle: along `points`, from `start` for `dur` seconds after the cycle starts. */
export interface Trip {
  flight: number;          // index into the floor's flights
  points: Pt[];
  /** cumulative length of `points` at each point, px (the last is the path's length) */
  lengths: number[];
  start: number;
  dur: number;
  loaded: boolean;         // carries a crate (a pull's outbound leg flies empty)
  red: boolean;            // a failure
  /** a take: which replica of which worker receives this crate (`of` replicas in all) */
  receiver?: { machine: string; replica: number; of: number };
}
export interface Drone { flight: number; x: number; y: number; loaded: boolean; red: boolean }
/** A worker's `N replicas` tag pulsing after a crate lands: `age` runs 0 → 1 over PULSE seconds. */
export interface Pulse { flight: number; machine: string; replica: number; of: number; age: number }

export interface DroneSchedule {
  /** seconds per cycle: the longest possible cycle plus a pause; 0 when nothing is lit */
  period: number;
  cycle(n: number): Trip[];
  /** What flies at `t`. Pass `out` to have it filled in place (its arrays and objects reused: no garbage per frame). */
  at(t: number, out?: { drones: Drone[]; pulses: Pulse[] }): { drones: Drone[]; pulses: Pulse[] };
}

/** A machine's failures fly with one of its deliveries out of this many (a dead-letter hub with no lit inbound
 *  hands on in one cycle out of this many). */
export const FAIL_EVERY = 3;
/** How long a receiving worker's tag pulses, s. */
export const PULSE = 0.8;
/** The quiet between cycles, s (at least PULSE, so a pulse ends inside its cycle). */
const PAUSE = 1;

const cumulative = (pts: Pt[]) => { const l = [0]; for (let i = 1; i < pts.length; i++) l.push(l[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)); return l; };
const INBOUND = new Set(["produce", "enqueue", "failure"]);

/** The point `d` px along `pts`, whose cumulative lengths are `lengths` (clamped to its ends), written into `into`. */
export function pointAlong(pts: Pt[], lengths: number[], d: number, into: { x: number; y: number } = { x: 0, y: 0 }) {
  const total = lengths[lengths.length - 1], x = Math.max(0, Math.min(total, d));
  let i = 1;
  while (i < lengths.length - 1 && lengths[i] < x) i++;
  const seg = lengths[i] - lengths[i - 1], t = seg ? (x - lengths[i - 1]) / seg : 1;
  into.x = pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t;
  into.y = pts[i - 1].y + (pts[i].y - pts[i - 1].y) * t;
  return into;
}

const pathLength = (pts: Pt[]) => { const l = cumulative(pts); return l[l.length - 1]; };

/** The floor's longest flight path, px, lit or not (a take counts its hop from the waiting stack): it sets the one
 *  speed every drone on the floor flies at, so the speed does not change with what is lit. */
export function longestFlight(floor: DroneFloor): number {
  const stackAt = new Map(floor.stacks.map((s) => [s.item, { x: s.x * T + T / 2, y: s.y * T + T / 2 }]));
  return Math.max(0, ...floor.flights.map((f) => {
    const from = f.flight === "take" ? stackAt.get(f.item) : undefined;
    return pathLength(from ? [from, ...f.points] : f.points);
  }));
}

/** `longest`: the length that sets the drones' speed (the floor's longest flight, or longer when the caller also flies
 *  drones along routes no flight covers). */
export function droneSchedule(floor: DroneFloor, lit: ReadonlySet<string>, longest = longestFlight(floor)): DroneSchedule {
  const { flights, messaging } = floor;
  const speed = moverSpeed("event", longest);
  const durOfLen = (len: number) => Math.max(0.1, len / speed);
  const durOf = (pts: Pt[]) => durOfLen(pathLength(pts));
  const on = flights.map((f) => lit.has(f.key));
  const hubs = new Map(messaging.airfields.flatMap((a) => a.hubs).map((h) => [h.item, h]));
  const byTopic = new Map([...hubs.values()].map((h) => [h.topic, h.item]));
  const stackAt = new Map(floor.stacks.map((s) => [s.item, { x: s.x * T + T / 2, y: s.y * T + T / 2 }]));
  const replicas = (f: FlightPath) =>
    Math.max(1, messaging.consumers.find((c) => c.machine === f.machine && c.item === f.item && c.group === f.group)?.replicas ?? 1);
  const items = [...new Set(flights.filter((_, i) => on[i]).map((f) => f.item))];
  // a queue's turns: each lit take flight once per replica, in flight order
  const slots = new Map<string, { flight: number; replica: number; of: number }[]>();
  flights.forEach((f, i) => {
    if (!on[i] || f.flight !== "take") return;
    const list = slots.get(f.item) ?? [];
    const of = replicas(f);
    for (let r = 0; r < of; r++) list.push({ flight: i, replica: r, of });
    slots.set(f.item, list);
  });

  /** Trips of cycle `n`; `everything`: every take and failure flies (to size the period). */
  const build = (n: number, everything: boolean): Trip[] => {
    const done = new Map<string, Trip[]>();
    const busy = new Set<string>();
    const trip = (i: number, points: Pt[], start: number, loaded = true, receiver?: Trip["receiver"]): Trip => {
      const lengths = cumulative(points);
      return { flight: i, points, lengths, start, dur: durOfLen(lengths[lengths.length - 1]), loaded, red: flights[i].dead, ...(receiver ? { receiver } : {}) };
    };
    /** When `machine` last received from hub `item` this cycle: null when it has no lit delivery from it at all,
     *  undefined when it has one but none came this cycle. */
    const receipt = (machine: string, item: string): number | null | undefined => {
      if (!flights.some((f, i) => on[i] && f.item === item && f.machine === machine && !INBOUND.has(f.flight))) return null;
      const got = hubTrips(item).filter((t) => {
        const f = flights[t.flight];
        if (f.machine !== machine || INBOUND.has(f.flight)) return false;
        return f.flight === "pull" ? t.loaded : f.flight === "take" ? t.receiver?.machine === machine : true;
      });
      return got.length ? Math.max(...got.map((t) => t.start + t.dur)) : undefined;
    };
    /** How many deliveries `machine` has had from hub `item` in cycles 0..n: every cycle, unless it only takes from a
     *  queue, when it is its share of the turns. */
    const received = (machine: string, item: string, n: number): number => {
      const every = flights.some((f, i) => on[i] && f.item === item && f.machine === machine && !INBOUND.has(f.flight) && f.flight !== "take");
      const turns = slots.get(item) ?? [];
      if (every || !turns.length) return n + 1;
      const mine = (p: number) => flights[turns[p].flight].machine === machine;
      const per = turns.filter((_, p) => mine(p)).length, rem = (n + 1) % turns.length;
      return Math.floor((n + 1) / turns.length) * per + turns.slice(0, rem).filter((_, p) => mine(p)).length;
    };
    const hubTrips = (item: string): Trip[] => {
      const memo = done.get(item);
      if (memo) return memo;
      if (busy.has(item)) return [];   // a dead-letter loop: break it
      busy.add(item);
      const out: Trip[] = [];
      let inbound = 0;
      flights.forEach((f, i) => {
        if (!on[i] || f.item !== item || !INBOUND.has(f.flight)) return;
        inbound++;
        if (f.flight !== "failure") { out.push(trip(i, f.points, 0)); return; }
        const source = hubs.get(item)?.dlqOf ? byTopic.get(hubs.get(item)!.dlqOf!) : undefined;
        const got = source !== undefined && source !== item ? receipt(f.machine, source) : null;
        // the machine's k-th delivery this far (counting this cycle's): every FAIL_EVERY-th one fails
        const k = got === null ? n + 1 : received(f.machine, source!, n);
        if (everything || (got !== undefined && k % FAIL_EVERY === 0)) out.push(trip(i, f.points, got ?? 0));
      });
      // nothing lit flies in: a plain hub hands on every cycle, a dead-letter hub only as often as failures come
      const quiet = everything || !hubs.get(item)?.dlqOf || n % FAIL_EVERY === FAIL_EVERY - 1;
      const landed = inbound === 0 ? (quiet ? 0 : undefined) : out.length ? Math.max(...out.map((t) => t.start + t.dur)) : undefined;
      if (landed !== undefined) {
        const turns = slots.get(item) ?? [];
        const turn = turns.length ? turns[n % turns.length] : undefined;
        flights.forEach((f, i) => {
          if (!on[i] || f.item !== item || INBOUND.has(f.flight)) return;
          if (f.flight === "copy" || f.flight === "push") out.push(trip(i, f.points, landed));
          else if (f.flight === "take") {
            if (!everything && turn?.flight !== i) return;
            const from = stackAt.get(item);
            const r = turn?.flight === i ? turn : { replica: 0, of: replicas(f) };
            out.push(trip(i, from ? [from, ...f.points] : f.points, landed, true, { machine: f.machine, replica: r.replica, of: r.of }));
          } else if (f.flight === "pull") {
            const leg = durOf(f.points);
            out.push(trip(i, f.points, Math.max(0, landed - leg), false));
            out.push(trip(i, [...f.points].reverse(), Math.max(leg, landed)));
          }
        });
      }
      busy.delete(item);
      done.set(item, out);
      return out;
    };
    return items.flatMap(hubTrips).sort((a, b) => a.flight - b.flight || a.start - b.start);
  };

  const span = Math.max(0, ...build(0, true).map((t) => t.start + t.dur));
  const period = items.length ? span + PAUSE : 0;
  let last: { n: number; trips: Trip[] } | null = null;
  const cycle = (n: number) => {
    if (last?.n !== n) last = { n, trips: build(n, false) };
    return last.trips;
  };
  return {
    period,
    cycle,
    at(t: number, out = { drones: [] as Drone[], pulses: [] as Pulse[] }) {
      let nd = 0, np = 0;
      if (period) {
        const n = Math.floor(t / period), tau = t - n * period;
        for (const tr of cycle(n)) {
          const end = tr.start + tr.dur;
          if (tau >= tr.start && tau < end) {
            const d = out.drones[nd] ?? (out.drones[nd] = { flight: 0, x: 0, y: 0, loaded: false, red: false });
            pointAlong(tr.points, tr.lengths, ((tau - tr.start) / tr.dur) * tr.lengths[tr.lengths.length - 1], d);
            d.flight = tr.flight; d.loaded = tr.loaded; d.red = tr.red;
            nd++;
          }
          if (tr.receiver && tau >= end && tau < end + PULSE) {
            const p = out.pulses[np] ?? (out.pulses[np] = { flight: 0, machine: "", replica: 0, of: 1, age: 0 });
            p.flight = tr.flight; p.machine = tr.receiver.machine; p.replica = tr.receiver.replica; p.of = tr.receiver.of;
            p.age = (tau - end) / PULSE;
            np++;
          }
        }
      }
      out.drones.length = nd;
      out.pulses.length = np;
      return out;
    },
  };
}
