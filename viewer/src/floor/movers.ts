// Moving parts on lit lines: items along belts and pipes, the drones of each flight kind, flown to the pure schedule in
// factory/drones.ts, and one train per lit rail, run to the pure schedule in factory/trains.ts. The scene clears the motion layer and calls `build`
// whenever the lit lines, the floor or reduced motion change, and `tick` every frame unless motion is reduced.
import { Container, Graphics, type Text } from "pixi.js";
import { flies, type Bundle } from "../model/model";
import type { Pt, Route } from "../route/types";
import { droneSchedule, type Drone, type DroneFloor, type DroneSchedule, type Pulse } from "../factory/drones";
import type { PxRect } from "../factory/clear";
import { replicaPulse, tagKey, type FlightPath, type Placed } from "../factory/flights";
import type { TrainPath } from "../factory/rail-place";
import { trainSchedule, type Car, type Train, type TrainSchedule } from "../factory/trains";
import { moverSpeed } from "./lane";
import { C, F } from "./palette";

interface Mover { route: Route; kind: string; both: boolean; toStore: boolean; lengths: number[]; total: number; g: Graphics; phase: number; cycle: number }

const KEYLINE = { width: 1, color: C.ink, pixelLine: true };
const WAGON_LINE = { width: 1.2, color: C.ink };
const dist = (a: Pt, b: Pt) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Does an item moving along the route's points (start to end) travel into the store? A tap's points run from its
 *  machine to the lane, except a read-only factory tap (`tapR`), which runs from the lane; a line to a store box
 *  runs the way its data flows, into the store unless the line only reads. */
export function forwardToStore(route: Route & { kind?: string }, kind: string): boolean {
  if (route.tap) return route.kind !== "tapR";
  return kind !== "db-read";
}

/** An item's fill: into a store red, out of it slate (the colours of the write and read lines), a request yellow. */
export function packetInk(kind: string, toStore: boolean): number {
  if (kind !== "db-write" && kind !== "db-read") return C.yellow;
  return toStore ? C.red : C.slate;
}

/** A worker's `N replicas` tag, which pulses as a queue's crate reaches one of its replicas: for the pulse its own text
 *  reads `replica k of N` (the replica that took the crate), then `base` again. Its box is sized for the longer text. */
export interface ReplicaTag { box: Placed; text: Text; base: string; shown: () => boolean }

/** Set a tag's text, shrunk to its box as the painter does. */
function tagText(tag: ReplicaTag, s: string) {
  const t = tag.text;
  if (t.destroyed || t.text === s) return;
  t.text = s;
  t.scale.set(1);
  const room = tag.box.w - 6;
  if (t.width > room) t.scale.set(room / t.width);
}

export interface MotionInput {
  routes: Route[];
  bundles: Bundle[];
  lit: ReadonlySet<string>;
  /** bundle keys drawn as flight paths: their routes carry nothing, their drones fly the schedule */
  covered: ReadonlySet<string>;
  reduced: boolean;
  /** the factory floor's flights (absent on floors without a hub), and the boxes their still arrows keep off */
  drones?: DroneFloor & { keepOff?: PxRect[] };
  /** `N replicas` tags by the `tagKey` of the take they belong to (machine, hub and group) */
  tags?: Map<string, ReplicaTag>;
  /** the factory floor's rails, platform to buffer stop: their routes carry nothing, a train runs each lit one */
  trains?: TrainPath[];
}

export class Motion {
  private movers: Mover[] = [];
  private schedule: DroneSchedule | null = null;
  private floor: DroneFloor | null = null;
  private droneG: Graphics | null = null;
  private pulseG: Graphics | null = null;
  private swapped = new Set<string>();   // tags reading `replica k of N` now
  private live = new Set<string>();      // scratch: tags pulsing this frame
  private now: { drones: Drone[]; pulses: Pulse[] } = { drones: [], pulses: [] };   // scratch: what flies this frame
  private tags = new Map<string, ReplicaTag>();
  private trainRuns: TrainSchedule | null = null;
  private trainG: Graphics | null = null;
  private trainNow: Train[] = [];   // scratch: the trains this frame, filled in place
  /** seconds since the schedule started; drones and scheduled trains drawn on the last frame (tests read them): a
   *  train counts whether it runs or waits at either end, but parked trains (Still motion: no schedule ticks) do not */
  clock = 0;
  drones = 0;
  trains = 0;

  constructor(private layer: Container) {}

  /** The layer is already cleared (but for anything the scene keeps). */
  build(m: MotionInput) {
    this.movers = [];
    this.clock = 0;
    this.drones = 0;
    this.trains = 0;
    for (const key of this.swapped) { const tag = this.tags.get(key); if (tag) tagText(tag, tag.base); }
    this.swapped.clear();
    this.tags = m.tags ?? new Map();
    this.floor = m.drones && m.drones.flights.length ? m.drones : null;
    // a lit bundle with flights flies them (one only partly carried by flights also keeps its old route's movers)
    const lit = this.floor ? new Set(this.floor.flights.map((f) => f.key).filter((k) => m.lit.has(k))) : new Set<string>();
    this.schedule = this.floor && lit.size ? droneSchedule(this.floor, lit) : null;
    this.droneG = this.pulseG = null;
    if (this.schedule && !m.reduced) {
      this.pulseG = new Graphics();
      this.droneG = new Graphics();
      this.layer.addChild(this.pulseG, this.droneG);
    }
    if (m.reduced && this.floor) {   // still: lit flights show which way they fly, as every still lit line does
      const shown = this.floor.flights.filter((f) => lit.has(f.key));
      for (const heads of stillFlightArrows(shown, m.drones?.keepOff ?? [])) {
        const g = new Graphics();
        this.layer.addChild(g);
        for (const head of heads) g.poly(head).fill(C.ink);
      }
    }
    // trains: one per lit rail; Still motion parks each at its yard (or door) end
    const rails = new Set((m.trains ?? []).map((p) => p.key));
    this.trainRuns = rails.size ? trainSchedule(m.trains!, m.lit) : null;
    this.trainG = null;
    if (this.trainRuns?.runs.length) {
      this.trainG = new Graphics();
      this.layer.addChild(this.trainG);
      if (m.reduced) {
        for (const r of this.trainRuns.runs) chevrons(this.trainG, r.points, r.lengths);
        for (const t of this.trainRuns.parked()) drawTrain(this.trainG, t);
        this.trainRuns = null;
      }
    }
    for (const r of m.routes) {
      if (!m.lit.has(r.key) || m.covered.has(r.key) || rails.has(r.key)) continue;
      const b = m.bundles.find((x) => x.key === r.key);
      if (!b) continue;   // a stand-in rail (no bundle of the model) with no train path: nothing to carry
      const lengths = [0];
      for (let i = 1; i < r.points.length; i++) lengths.push(lengths[i - 1] + dist(r.points[i - 1], r.points[i]));
      const g = new Graphics();
      this.layer.addChild(g);
      this.movers.push({ route: r, kind: b.kind, both: b.flow === "both", toStore: forwardToStore(r, b.kind), lengths, total: lengths[lengths.length - 1], g, phase: 0, cycle: 0 });
    }
    if (m.reduced) for (const mv of this.movers) chevrons(mv.g, mv.route.points, mv.lengths);
  }

  tick(ms: number) {
    this.clock += ms / 1000;
    this.flyDrones();
    this.runTrains();
    for (const mv of this.movers) {
      const g = mv.g.clear();
      const spacing = itemSpacing(mv.kind, mv.total);
      const before = mv.phase;
      mv.phase = (mv.phase + ms * 0.06 * ((moverSpeed(mv.kind, mv.total) / 60) * (60 / spacing))) % 60;
      if (mv.phase < before) mv.cycle++;   // a pass finished: a two-way belt carries the next item the other way
      for (let d = mv.phase * (spacing / 60); d < mv.total; d += spacing) {
        const forward = !mv.both || mv.cycle % 2 === 0;
        const pos = at(mv.route.points, mv.lengths, forward ? d : mv.total - d);
        if (mv.kind === "stream") g.circle(pos.x, pos.y, 2.2).fill(C.paper);
        else if (flies(mv.kind)) drone(g, pos, false, false);
        else if (mv.kind === "batch") {
          for (let c = 0; c < 3; c++) { const p = at(mv.route.points, mv.lengths, Math.max(0, (forward ? d : mv.total - d) - c * 12)); g.rect(p.x - 5, p.y - 4, 10, 8).fill(C.amber).stroke(KEYLINE); }
        } else g.rect(pos.x - 3.5, pos.y - 3.5, 7, 7).fill(packetInk(mv.kind, forward === mv.toStore)).stroke(KEYLINE);
      }
    }
  }

  private runTrains() {
    if (!this.trainRuns || !this.trainG) return;
    const g = this.trainG.clear(), now = this.trainRuns.at(this.clock, this.trainNow);
    for (const t of now) drawTrain(g, t);
    this.trains = now.length;
  }

  private flyDrones() {
    if (!this.schedule || !this.droneG || !this.pulseG || !this.floor) return;
    const { drones, pulses } = this.schedule.at(this.clock, this.now);
    const g = this.droneG.clear(), pg = this.pulseG.clear();
    for (const d of drones) drone(g, d, d.loaded, d.red);
    this.drones = drones.length;
    const live = this.live;
    live.clear();
    for (const p of pulses) {
      const f = this.floor.flights[p.flight], key = tagKey(f.machine, f.item, f.group), tag = this.tags.get(key);
      if (!tag || !tag.shown()) continue;
      live.add(key);
      const b = tag.box, grow = 2 + 5 * p.age;
      pg.rect(b.x - grow, b.y - grow, b.w + 2 * grow, b.h + 2 * grow).stroke({ width: 2, color: C.yellow, alpha: 1 - p.age });
      tagText(tag, replicaPulse(tag.base, p.replica + 1, p.of));   // which replica took this crate
      this.swapped.add(key);
    }
    for (const key of this.swapped) if (!live.has(key)) { const tag = this.tags.get(key); if (tag) tagText(tag, tag.base); this.swapped.delete(key); }
  }
}

/** Px between the items moving along a line `total` px long: one item per belt or rail (the whole line plus a pause),
 *  and about three evenly spaced blobs of water in a pipe (the owner, 2026-10-06: so a pipe reads differently from a
 *  belt). */
export function itemSpacing(kind: string, total: number): number {
  return kind === "stream" ? (total + 60) / PIPE_BLOBS : total + 60;
}
export const PIPE_BLOBS = 3;

/** A drone: a keylined body with four rotors, green (red for a failure), a yellow crate slung under it when loaded. */
function drone(g: Graphics, p: Pt, loaded: boolean, red: boolean) {
  if (loaded) g.rect(p.x - 4, p.y + 3, 8, 6).fill(C.yellow).stroke(KEYLINE);
  g.rect(p.x - 3, p.y - 3, 6, 6).fill(red ? C.red : C.green).stroke(KEYLINE);
  for (const [dx, dy] of [[-5, -5], [5, -5], [-5, 5], [5, 5]]) g.circle(p.x + dx, p.y + dy, 1.8).fill(C.ink);
}

/** A train as the approved mock draws it: an ink locomotive with a yellow window towards the buffer stop, then amber-soft
 *  keylined wagons, each with a yellow crate while loaded (the mock's `train()`). Drawn last wagon first. A self-only
 *  yard's parked train is drawn with it too (rail-paint). */
export function drawTrain(g: Graphics, t: Train) {
  const lead = t.cars[0], next = t.cars[1];
  for (let i = t.cars.length - 1; i >= 0; i--) {
    const c = t.cars[i];
    if (c.loco) {
      const w = c.horizontal ? 18 : 14, h = c.horizontal ? 14 : 18;
      g.roundRect(c.x - w / 2, c.y - h / 2, w, h, 2).fill(C.ink);
      // the window on the locomotive's front half: away from the wagon behind it
      const fx = Math.sign(lead.x - next.x), fy = Math.sign(lead.y - next.y);
      const ww = c.horizontal ? 6 : 10, wh = c.horizontal ? 10 : 6;
      g.rect(c.x + fx * 4 - ww / 2, c.y + fy * 4 - wh / 2, ww, wh).fill(C.yellow);
    } else wagon(g, c);
  }
}
function wagon(g: Graphics, c: Car) {
  const w = c.horizontal ? 16 : 12, h = c.horizontal ? 12 : 16;
  g.rect(c.x - w / 2, c.y - h / 2, w, h).fill(F.amberSoft).stroke(WAGON_LINE);
  if (c.loaded) { const cw = c.horizontal ? 10 : 6, ch = c.horizontal ? 6 : 10; g.rect(c.x - cw / 2, c.y - ch / 2, cw, ch).fill(C.yellow).stroke(KEYLINE); }
}

const euclid = (pts: Pt[]) => { const l = [0]; for (let i = 1; i < pts.length; i++) l.push(l[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)); return l; };

function chevrons(g: Graphics, pts: Pt[], lengths: number[]) {
  const total = lengths[lengths.length - 1];
  for (let d = 30; d < total - 10; d += 46) arrow(g, at(pts, lengths, d), at(pts, lengths, d + 1), C.ink, 5);
}

/** The point `d` along `pts`, given the cumulative `lengths` of its segments. */
export function at(pts: Pt[], lengths: number[], d: number): Pt {
  const total = lengths[lengths.length - 1];
  const x = clamp(d, 0, total);
  let i = 1;
  while (i < lengths.length - 1 && lengths[i] < x) i++;
  const seg = lengths[i] - lengths[i - 1] || 1;
  const t = (x - lengths[i - 1]) / seg;
  return { x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t, y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * t };
}

export function arrow(g: Graphics, from: Pt, to: Pt, color: number, size = 7) {
  if (!from || !to) return;
  const head = arrowHead(from, to, size);
  if (head.length) g.poly(head).fill(color);
}

/** An arrowhead with its tip on `to`, pointing from `from` at the true angle (an axis-aligned one is the same as it
 *  ever was): a symmetric triangle `size` deep and 2 × `wide` × `size` across its base, as [x, y, …]. Empty when the
 *  two points meet. `chevrons` samples `from` and `to` at d and d + 1 along a belt or rail, so a head within 1 px of a
 *  corner is drawn at the true (diagonal) angle of that 1 px chord: a little smaller across the axis than the old head,
 *  which snapped such a chord to 45° with full-size steps. */
export function arrowHead(from: Pt, to: Pt, size: number, wide = 0.6): number[] {
  const len = Math.hypot(to.x - from.x, to.y - from.y);
  if (!len) return [];
  const dx = (to.x - from.x) / len, dy = (to.y - from.y) / len;
  const bx = to.x - dx * size, by = to.y - dy * size, w = size * wide;
  return [to.x, to.y, bx - dy * w, by + dx * w, bx + dy * w, by - dx * w];
}

/** A still flight's arrows (Still motion), as arrowheads: along the flight at its true angle, on the line, and only on
 *  the open part of its path. A flight's path starts at a pad inside its machine and ends on a hub (or a dock), and it
 *  may cross other machines on the way (a drone flies over them): no head may touch a box of `keepOff` (machines with
 *  their shadows, hubs, docks, waiting stacks), so heads are spread evenly along each clear stretch. A flight with no
 *  stretch long enough still gets one head, at the middle of its longest clear stretch (or of its path). One direction
 *  per flight: a pull, which flies out empty and back loaded, points the loaded leg, hub → consumer (the way its data
 *  goes), as a two-way belt shows one direction in Still motion. */
export function flightArrows(f: Pick<FlightPath, "points" | "flight">, keepOff: PxRect[]): number[][] {
  const pts = f.flight === "pull" ? [...f.points].reverse() : f.points, lengths = euclid(pts), total = lengths[lengths.length - 1];
  if (!total) return [];
  const clear = STILL_HEAD + 3;   // a head's reach from its tip, plus a little air
  const open = (p: Pt) => keepOff.every((r) => p.x < r.x0 - clear || p.x > r.x1 + clear || p.y < r.y0 - clear || p.y > r.y1 + clear);
  // the clear stretches, sampled each px along the path
  const runs: [number, number][] = [];
  let from = -1;
  for (let d = 0; d <= total; d++) {
    const ok = open(at(pts, lengths, d));
    if (ok && from < 0) from = d;
    if ((!ok || d + 1 > total) && from >= 0) { runs.push([from, ok ? d : d - 1]); from = -1; }
  }
  const spots: number[] = [];
  for (const [s, e] of runs) {
    const len = e - s;
    if (len < STILL_HEAD) continue;   // too short to hold a head
    const n = Math.max(1, Math.round(len / STILL_GAP));
    for (let k = 0; k < n; k++) spots.push(s + ((k + 0.5) * len) / n);
  }
  if (!spots.length) {   // never headless: the middle of the longest clear stretch, else of the path
    const best = runs.reduce<[number, number] | null>((b, r) => (!b || r[1] - r[0] > b[1] - b[0] ? r : b), null);
    spots.push(best ? (best[0] + best[1]) / 2 : total / 2);
  }
  return spots.map((d) => {
    const p = at(pts, lengths, d), a = at(pts, lengths, d - 1), b = at(pts, lengths, d + 1);   // the tip at d
    const span = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    const ux = (b.x - a.x) / span, uy = (b.y - a.y) / span;
    return arrowHead({ x: p.x - ux, y: p.y - uy }, p, STILL_HEAD, STILL_WIDE);
  }).filter((h) => h.length);
}

/** Every lit flight's still arrows (`flightArrows`), by flight, with one more rule across flights: two flights whose
 *  paths nearly meet must not show heads pointing opposite ways side by side (on push_pull's floor 0 the produce flight
 *  into the hub and the push out of it run almost on one line). Of two opposed heads within STILL_OPPOSED px of each
 *  other, one is dropped: the one of the flight with more heads left, so no flight loses its last head to another
 *  that keeps some; on a tie the later flight yields. A flight never loses its last head: when both are down to one,
 *  the opposed pair stays (a direction cue on each beats none). Deterministic: pairs in flight order, then head order. */
export function stillFlightArrows(flights: Pick<FlightPath, "points" | "flight">[], keepOff: PxRect[]): number[][][] {
  const all = flights.map((f) => flightArrows(f, keepOff).map((h) => {
    const bx = (h[2] + h[4]) / 2, by = (h[3] + h[5]) / 2;
    return { h, x: h[0], y: h[1], dx: h[0] - bx, dy: h[1] - by, on: true };
  }));
  const left = all.map((hs) => hs.length);
  for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++)
    for (const a of all[i]) for (const b of all[j]) {
      if (!a.on || !b.on || a.dx * b.dx + a.dy * b.dy >= 0 || Math.hypot(a.x - b.x, a.y - b.y) > STILL_OPPOSED) continue;
      if (left[i] <= 1 && left[j] <= 1) continue;   // never a flight's last head: both down to one, the pair stays
      if (left[i] > left[j]) { a.on = false; left[i]--; } else { b.on = false; left[j]--; }
    }
  return all.map((hs) => hs.filter((x) => x.on).map((x) => x.h));
}
// a flight's heads are slender (7 px deep, 5.6 across): a near-equilateral head on a slanted path reads either way
const STILL_HEAD = 7, STILL_WIDE = 0.4, STILL_GAP = 46, STILL_OPPOSED = 8;
