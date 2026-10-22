// src/factory/flights.ts
// Where messaging is painted, pure: one dotted flight path per flight from its pad or dock to its hub (or
// back), the old machine→hub drone routes those paths replace, and the clear room their plates, the consumer tags and
// the dock signs take. Painting (messaging-paint.ts) and motion read the result; nothing here draws.
import { type Bundle, type Model } from "../model/model";
import type { Pt } from "../route/types";
import { Clearance, floorObstacles, type PxRect } from "./clear";
import type { TileFloor } from "./layout";
import { FLIGHT_LABEL, type Flight } from "./messaging";
import { padCentre, type PadRole, type WebhookDock } from "./pads";
import { T, type Rect } from "./tiles";
import { PLATE_FONT, PLATE_H, plateW } from "./fit";
import type { TileRoute } from "./router";

/** One flight's dotted path. `points` run the way the drone first flies: pad → hub for produce, enqueue, failure and
 *  pull (a pull flies out empty, then back loaded); hub → pad or dock for copy, take and push. The path is one straight
 *  segment (the owner, 2026-10-06: drones fly over whatever is in the way, and the drone toggle hides the paths); to a
 *  door it stops at the door's edge. Paths that would run on top of each other into one hub land apart on its edge
 *  (`spreadLandings`). `key` is the bundle the flight's relations ride (`machine|hub`, sorted), so
 *  selection, lighting and travel resolve to it. */
export interface FlightPath {
  key: string;
  flight: Flight;
  role: PadRole;
  machine: string;
  item: string;            // the hub's box
  topic: string;           // its topic node (the dead-letter hub's, for a failure)
  group?: string;
  dock: boolean;           // lands on a receiving dock, not a pad
  dead: boolean;           // a failure: drawn red
  launch: Pt;              // the pad mark's (or dock's) centre
  hub: Pt;                 // where the path meets the hub: its centre, or, for a door, the point where it reaches the door's
                           // edge; a point spread along the edge when it would run on top of another path (`spreadLandings`)
  outbound: boolean;       // the drone first flies pad → hub (`points` start at `launch`), else hub → pad
  points: Pt[];            // the drawn path: one straight segment
  relations: string[];
}

/** A short label on a plate beside its path, a consumer's tag, or a dock's sign: a box in world px. */
export interface Placed {
  key: string; text: string; x: number; y: number; w: number; h: number;
  /** a plate's flight: its index in the paths */ of?: number;
}

const DOT = 4;   // half-size of the obstacle squares sampled along a flight path (2 px dots, round caps, a little air)
const centre = (r: Rect): Pt => ({ x: (r.x + r.w / 2) * T, y: (r.y + r.h / 2) * T });
export const flightKey = (machine: string, item: string) => [machine, item].sort().join("|");
/** A consumer tag's key: its flight's key and its group, since one machine may take from one hub in two groups. */
export const tagKey = (machine: string, item: string, group?: string) => `${flightKey(machine, item)}|${group ?? ""}`;

/** Every placed flight on the floor: one per pad and one per dock, sorted like the pads; none on a floor with no hub. */
export function flightPaths(tf: TileFloor): FlightPath[] {
  const land = tf.landing;
  if (!land) return [];
  const msg = land.messaging;
  const rels = (machine: string, item: string, role: PadRole, group?: string): string[] => {
    if (role === "produce") return msg.producers.find((p) => p.machine === machine && p.item === item)?.viaRelations ?? [];
    if (role === "failure") return msg.failures.find((f) => f.machine === machine && f.item === item)?.viaRelations ?? [];
    return msg.consumers.find((c) => c.machine === machine && c.item === item && c.group === group)?.viaRelations ?? [];
  };
  const out: FlightPath[] = [];
  const px = (r: Rect): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  const add = (w: { machine: string; item: string; topic: string; role: PadRole; group?: string; flight: Flight }, launch: Pt, dock: boolean) => {
    const hubBox = tf.boxes.get(w.item);
    if (!hubBox) return;
    const straight = [launch, centre(hubBox)];
    // a door's name fills its middle: the path stops at the door's edge, where it first reaches it, never over the words
    const pts = hubBox.foot === "door" ? clipInto(straight, px(hubBox)) : straight;
    const outbound = w.flight === "produce" || w.flight === "enqueue" || w.flight === "failure" || w.flight === "pull";
    out.push({
      key: flightKey(w.machine, w.item), flight: w.flight, role: w.role, machine: w.machine, item: w.item, topic: w.topic,
      ...(w.group !== undefined ? { group: w.group } : {}), dock, dead: w.flight === "failure", launch, hub: pts[pts.length - 1], outbound,
      points: outbound ? pts : [...pts].reverse(), relations: rels(w.machine, w.item, w.role, w.group),
    });
  };
  for (const p of land.pads) add(p, padCentre(p), false);
  for (const d of land.docks) add(d, centre(d), true);
  return spreadLandings(out, tf);
}

/** How close two paths' centre lines come before they read as one line: a path is dots 3 px wide with round caps
 *  (`paintFlight`), so lines whose centres are 3 px or less apart touch, dot over dot. */
export const OVERLAP_PX = 3;
/** How long two paths must run that close to be on top of each other, not just crossing: a tile, three dots and their
 *  gaps (2 px on, 6 off). Lines crossing at more than about 14° are that close for less (2·3 px / sin 14° ≈ 24 px), so
 *  this also asks that they come in close in direction. */
export const OVERLAP_RUN = T;
/** The least room between two landing points spread along a hub's edge: four dot widths, plainly two lines. */
export const LANDING_GAP = 12;
/** Landing points keep this far in from the edge's corners. */
const LANDING_INSET = 6;
/** How much wider a spread is tried each time, up to the whole edge, while paths in it still run together. */
const WIDEN_STEP = 4;

/** The part of a path a reader sees at its hub end: from its pad or dock to where it first reaches the hub's box (the
 *  rest, to a hub's centre, is under the hub). */
export function visiblePart(p: Pick<FlightPath, "launch" | "hub">, hubBox: PxRect): [Pt, Pt] {
  const pts = clipInto([p.launch, p.hub], hubBox);
  return [pts[0], pts[pts.length - 1]];
}

/** The stretch of segment `a`, as a part [t0, t1] of it (0 at a[0], 1 at a[1]), whose points lie within `tol` of
 *  segment `b`, or undefined. Closed form: the points within `tol` of `b` make a capsule (a band along `b` and a disc at
 *  each end), convex, so `a` meets it in one stretch, from the first of its entries to the last of its exits. */
function nearStretch(a: [Pt, Pt], b: [Pt, Pt], tol: number): [number, number] | undefined {
  const dx = a[1].x - a[0].x, dy = a[1].y - a[0].y;
  let lo = Infinity, hi = -Infinity;
  const take = (s: number, e: number) => { if (s <= e) { lo = Math.min(lo, s); hi = Math.max(hi, e); } };
  // a disc of radius tol round c: |a0 + t·d − c|² ≤ tol²
  const disc = (c: Pt) => {
    const fx = a[0].x - c.x, fy = a[0].y - c.y, A = dx * dx + dy * dy, B = 2 * (fx * dx + fy * dy), C = fx * fx + fy * fy - tol * tol;
    if (A === 0) { if (C <= 0) take(0, 1); return; }
    const disc2 = B * B - 4 * A * C;
    if (disc2 < 0) return;
    const r = Math.sqrt(disc2);
    take((-B - r) / (2 * A), (-B + r) / (2 * A));
  };
  disc(b[0]); disc(b[1]);
  const bx = b[1].x - b[0].x, by = b[1].y - b[0].y, L = Math.hypot(bx, by);
  if (L > 0) {
    // the band: 0 ≤ u ≤ L along b, |v| ≤ tol across it, with u and v linear in t
    const ux = bx / L, uy = by / L;
    const u0 = (a[0].x - b[0].x) * ux + (a[0].y - b[0].y) * uy, du = dx * ux + dy * uy;
    const v0 = -(a[0].x - b[0].x) * uy + (a[0].y - b[0].y) * ux, dv = -dx * uy + dy * ux;
    let s = -Infinity, e = Infinity;
    for (const [p0, dp, min, max] of [[u0, du, 0, L], [v0, dv, -tol, tol]]) {
      if (dp === 0) { if (p0 < min || p0 > max) { s = 1; e = 0; } continue; }
      const t1 = (min - p0) / dp, t2 = (max - p0) / dp;
      s = Math.max(s, Math.min(t1, t2)); e = Math.min(e, Math.max(t1, t2));
    }
    take(s, e);
  }
  const s = Math.max(0, lo), e = Math.min(1, hi);
  return s <= e ? [s, e] : undefined;
}
/** The part [t0, t1] of segment `a` inside rect `r` (Liang–Barsky), or undefined. */
function insideStretch(a: [Pt, Pt], r: PxRect): [number, number] | undefined {
  let t0 = 0, t1 = 1;
  const dx = a[1].x - a[0].x, dy = a[1].y - a[0].y;
  for (const [p, q] of [[-dx, a[0].x - r.x0], [dx, r.x1 - a[0].x], [-dy, a[0].y - r.y0], [dy, r.y1 - a[0].y]]) {
    if (p === 0) { if (q < 0) return undefined; continue; }
    const t = q / p;
    if (p < 0) { if (t > t1) return undefined; if (t > t0) t0 = t; } else { if (t < t0) return undefined; if (t < t1) t1 = t; }
  }
  return t0 < t1 ? [t0, t1] : undefined;
}
/** How much of segment `a`, in px, runs within `tol` of segment `b` on open floor: outside every rect of `boxes`. */
function alongside(a: [Pt, Pt], b: [Pt, Pt], tol: number, boxes: PxRect[]): number {
  const near = nearStretch(a, b, tol);
  if (!near) return 0;
  const len = Math.hypot(a[1].x - a[0].x, a[1].y - a[0].y);
  // the boxes' stretches of `a` inside `near`, merged, come off it
  const cut = boxes.map((r) => insideStretch(a, r)).filter((s): s is [number, number] => !!s && s[1] > near[0] && s[0] < near[1])
    .map(([s, e]): [number, number] => [Math.max(s, near[0]), Math.min(e, near[1])]).sort((u, v) => u[0] - v[0]);
  let covered = 0, end = near[0];
  for (const [s, e] of cut) { if (e > end) { covered += e - Math.max(s, end); end = e; } }
  return (near[1] - near[0] - covered) * len;
}
/** How long two segments run on top of each other on open floor: the shorter of each one's stretch within OVERLAP_PX
 *  of the other outside every rect of `boxes` (the same either way round). Under a box they are hidden, not on top of
 *  each other: `flights.hidden` reports that. */
export function runTogether(a: [Pt, Pt], b: [Pt, Pt], boxes: PxRect[] = []): number {
  return Math.min(alongside(a, b, OVERLAP_PX, boxes), alongside(b, a, OVERLAP_PX, boxes));
}

/** Two launches in line with a hub: one lies within OVERLAP_PX of the other's straight line to the hub's centre (one
 *  machine straight behind another). Their paths can be spread only as far as the hub's edge allows. */
export function inLine(a: Pt, b: Pt, hubCentre: Pt): boolean {
  return segDist(a, b, hubCentre) <= OVERLAP_PX || segDist(b, a, hubCentre) <= OVERLAP_PX;
}
const segDist = (q: Pt, a: Pt, b: Pt) => {
  const dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy;
  const t = l2 ? Math.max(0, Math.min(1, ((q.x - a.x) * dx + (q.y - a.y) * dy) / l2)) : 0;
  return Math.hypot(q.x - a.x - t * dx, q.y - a.y - t * dy);
};

/** Paths into one hub that run on top of each other (`runTogether` at least OVERLAP_RUN over the parts a reader sees,
 *  on open floor) get their own landing points on the hub's edge; every other path keeps its landing (the hub's
 *  centre, a door's edge), so twenty consumers spread round a hub stay as they are. A group of paths that overlap, one
 *  with the next, lands on the edge its mean direction reaches, `LANDING_GAP` apart, centred where that direction
 *  meets the edge, in the order the paths cross the edge's line, so they do not cross. Paths in line (`inLine`) cross
 *  it at one place: the nearest pad takes the middle point and the farther ones the outer points, and while two paths
 *  of the group still run together the points are spread wider, up to the whole edge. More paths than the edge holds
 *  at LANDING_GAP: the extras share the nearest point, in order (`flights.overlap` reports them); no path is dropped.
 *  A path moved this way may then run on another: the groups merge and are spread again, until none does. The path
 *  stays one straight segment, drawn under the machines as before. Deterministic: the paths keep their order, and
 *  ties go by distance, then by the paths' fields, never by where they sit in the input. */
export function spreadLandings(paths: FlightPath[], tf: TileFloor): FlightPath[] {
  const px = (r: Rect): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  const faces = keepOffBoxes(tf, 0).map((b) => b.r);
  const out = [...paths];
  const byHub = new Map<string, number[]>();
  paths.forEach((p, i) => (byHub.get(p.item) ?? byHub.set(p.item, []).get(p.item)!).push(i));
  for (const [item, idx] of byHub) {
    const box = tf.boxes.get(item);
    if (!box || idx.length < 2) continue;
    const r = px(box);
    const parent = new Map(idx.map((i) => [i, i]));
    const find = (i: number): number => (parent.get(i) === i ? i : find(parent.get(i)!));
    const union = (a: number, b: number) => { const x = find(a), y = find(b); if (x === y) return false; parent.set(Math.max(x, y), Math.min(x, y)); return true; };
    const collide = (cur: FlightPath[], a: number, b: number) => runTogether(visiblePart(cur[a], r), visiblePart(cur[b], r), faces) >= OVERLAP_RUN;
    for (let a = 0; a < idx.length; a++) for (let b = a + 1; b < idx.length; b++) if (collide(paths, idx[a], idx[b])) union(idx[a], idx[b]);
    for (let round = 0; round < idx.length; round++) {
      const groups = new Map<number, number[]>();
      for (const i of idx) (groups.get(find(i)) ?? groups.set(find(i), []).get(find(i))!).push(i);
      const cur = [...paths];
      for (const g of groups.values()) if (g.length > 1) {
        const launches = g.map((i) => paths[i].launch), ties = g.map((i) => tieKey(paths[i]));
        // the narrowest spread, from LANDING_GAP up, that leaves no two of the group on top of each other
        for (let gap = LANDING_GAP; ; gap += WIDEN_STEP) {
          const lands = landingPoints(launches, r, gap, ties);
          g.forEach((i, k) => { cur[i] = landAt(paths[i], lands.points[k]); });
          const clear = g.every((a, x) => g.slice(x + 1).every((b) => !collide(cur, a, b)));
          if (clear || lands.widest) break;
        }
      }
      for (const i of idx) out[i] = cur[i];
      // a moved path that now runs on another path of the hub: spread the two groups as one
      let merged = false;
      for (let a = 0; a < idx.length; a++) for (let b = a + 1; b < idx.length; b++)
        if (find(idx[a]) !== find(idx[b]) && collide(cur, idx[a], idx[b])) merged = union(idx[a], idx[b]) || merged;
      if (!merged) break;
    }
  }
  return out;
}

/** What orders two paths whose launches are the same distance along the edge and from the hub: their own fields. */
const tieKey = (p: FlightPath) => `${p.machine}|${p.flight}|${p.group ?? ""}|${p.dock ? 1 : 0}`;

/** The path to `hub` instead: the same flight, one straight segment from its launch. */
const landAt = (p: FlightPath, hub: Pt): FlightPath => ({ ...p, hub, points: p.outbound ? [p.launch, hub] : [hub, p.launch] });

/** One landing point per launch on box `r`'s edge, `gap` apart (see `spreadLandings`), in the launches' order;
 *  `widest`: the points already take the whole edge, so a wider gap would change nothing. `ties` orders launches the
 *  geometry cannot (default: their index). */
export function landingPoints(launches: Pt[], r: PxRect, gap = LANDING_GAP, ties?: string[]): { points: Pt[]; widest: boolean } {
  const c = { x: (r.x0 + r.x1) / 2, y: (r.y0 + r.y1) / 2 }, hw = (r.x1 - r.x0) / 2, hh = (r.y1 - r.y0) / 2;
  let mx = 0, my = 0;
  for (const l of launches) { const d = Math.hypot(l.x - c.x, l.y - c.y) || 1; mx += (l.x - c.x) / d; my += (l.y - c.y) / d; }
  if (!mx && !my) my = -1;
  // the side the mean direction leaves the box by: an n/s side runs along x, an e/w side along y
  const level = Math.abs(my) * hw >= Math.abs(mx) * hh;
  const at = level ? (my < 0 ? r.y0 : r.y1) : (mx < 0 ? r.x0 : r.x1);   // the side's line
  const lo = (level ? r.x0 : r.y0) + LANDING_INSET, hi = (level ? r.x1 : r.y1) - LANDING_INSET;
  const anchor = level ? c.x + (mx / Math.abs(my)) * hh : c.y + (my / Math.abs(mx)) * hw;
  // where each launch's straight line to the centre crosses the side's line: the order that keeps them from crossing
  const cross = launches.map((l) => {
    const [u, v, cu, cv] = level ? [l.x, l.y, c.x, c.y] : [l.y, l.x, c.y, c.x];
    return v === cv ? u : u + ((cu - u) * (at - v)) / (cv - v);
  });
  const far = launches.map((l) => Math.hypot(l.x - c.x, l.y - c.y));
  const tie = (a: number, b: number) => (ties ? (ties[a] < ties[b] ? -1 : ties[a] > ties[b] ? 1 : 0) : 0) || a - b;
  const order = launches.map((_, i) => i).sort((a, b) => cross[a] - cross[b] || far[a] - far[b] || tie(a, b));
  const n = launches.length, room = Math.max(0, hi - lo);
  const cap = Math.floor(room / LANDING_GAP) + 1, k = Math.min(n, cap);
  const step = k > 1 ? Math.min(gap, room / (k - 1)) : 0;
  const start = Math.min(Math.max(anchor - ((k - 1) * step) / 2, lo), hi - (k - 1) * step);
  const slotOf = (rank: number) => (n <= cap ? rank : Math.round((rank * (cap - 1)) / (n - 1)));
  const slots = order.map((_, rank) => start + slotOf(rank) * step);
  // launches in line with the hub (`inLine`, one run in `order`) share their run's slots: the nearest takes the slot
  // closest to where their line crosses, the farthest the outermost, so a farther path stays outside a nearer one all
  // the way in
  const placed: number[] = new Array(n);
  for (let s = 0; s < n; ) {
    let e = s + 1;
    while (e < n && inLine(launches[order[e]], launches[order[e - 1]], c)) e++;
    const run = order.slice(s, e), mid = cross[run[0]];
    const free = slots.slice(s, e).map((u, j) => ({ u, j })).sort((a, b) => Math.abs(a.u - mid) - Math.abs(b.u - mid) || a.j - b.j);
    [...run].sort((a, b) => far[a] - far[b] || tie(a, b)).forEach((i, j) => { placed[i] = free[j].u; });
    s = e;
  }
  const points = launches.map((_, i) => (level ? { x: placed[i], y: at } : { x: at, y: placed[i] }));
  return { points, widest: k < 2 || step < gap || (k - 1) * step >= room - 1e-9 };
}
/** What a still flight's arrows keep off: every box on the floor with its shadow (machines, hubs, stores, doors) and
 *  every receiving dock, webhook dock and waiting stack. A flight's path starts inside its machine (its pad), ends on
 *  its hub or dock, and may fly over other machines: its arrows sit only on the open stretches between them. */
export function flightKeepOff(tf: TileFloor): PxRect[] {
  return keepOffBoxes(tf).map((b) => b.r);
}
/** `flightKeepOff`'s rects, each with what it is (`name`) and the box it belongs to (`owner`: the box itself, a dock's
 *  or webhook dock's machine, a waiting stack's hub). `shadow`: px the boxes' shadow adds right and below (0: their
 *  faces alone). */
export function keepOffBoxes(tf: TileFloor, shadow = 5): { name: string; owner: string; r: PxRect }[] {
  const SHADOW = shadow;
  const boxes = [...tf.boxes.values()].map((r) => ({ name: r.id, owner: r.id, r: { x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T + SHADOW, y1: (r.y + r.h) * T + SHADOW } }));
  const tiles = (r: { x: number; y: number; w: number; h: number }): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  const docks = (tf.landing?.docks ?? []).map((d) => ({ name: `${d.machine}'s receiving dock`, owner: d.machine, r: tiles(d) }));
  const webhooks = (tf.webhooks ?? []).map((d) => ({ name: `${d.machine}'s webhook dock`, owner: d.machine, r: tiles(d) }));
  const stacks = (tf.landing?.stacks ?? []).map((s) => ({ name: `${s.item}'s waiting stack`, owner: s.item, r: tiles({ x: s.x, y: s.y, w: 1, h: 1 }) }));
  return [...boxes, ...docks, ...webhooks, ...stacks];
}

/** `pts` cut where they first reach `r`: the path then ends on `r`'s edge. Unchanged when they start inside it or never
 *  reach it. */
export function clipInto(pts: Pt[], r: PxRect): Pt[] {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    let t0 = 0, t1 = 1, hit = true;
    const dx = b.x - a.x, dy = b.y - a.y;
    for (const [p, q] of [[-dx, a.x - r.x0], [dx, r.x1 - a.x], [-dy, a.y - r.y0], [dy, r.y1 - a.y]]) {
      if (p === 0) { if (q < 0) hit = false; continue; }
      const t = q / p;
      if (p < 0) { if (t > t0) t0 = t; } else if (t < t1) t1 = t;
    }
    if (!hit || t0 > t1) continue;
    if (t0 <= 0) return pts;   // already inside
    return [...pts.slice(0, i), { x: a.x + dx * t0, y: a.y + dy * t0 }];
  }
  return pts;
}

/** The drone routes the flight paths replace: a bundle every relation of which some placed flight carries. A bundle only
 *  partly carried (a want left unplaced, or a relation no flight carries) keeps its old machine→hub route as well as the
 *  flights it has: nothing is lost, and the carried relations are then drawn twice (accepted; no real floor has one). */
export function coveredKeys(paths: FlightPath[], bundles: Bundle[]): Set<string> {
  const carried = new Set(paths.flatMap((p) => p.relations));
  const keys = new Set(paths.map((p) => p.key));
  return new Set(bundles.filter((b) => keys.has(b.key) && b.relations.length > 0 && b.relations.every((r) => carried.has(r.id))).map((b) => b.key));
}

/** Small squares along a path: what a label must stay off (a diagonal path's bounding box would block far too much). */
export function pathRects(pts: Pt[], half = DOT): PxRect[] {
  const out: PxRect[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], len = Math.hypot(b.x - a.x, b.y - a.y), n = Math.max(1, Math.ceil(len / half));
    for (let k = 0; k <= n; k++) {
      const x = a.x + ((b.x - a.x) * k) / n, y = a.y + ((b.y - a.y) * k) / n;
      out.push({ x0: x - half, y0: y - half, x1: x + half, y1: y + half });
    }
  }
  return out;
}

/** What labels on this floor keep off: everything `floorObstacles` lists, without the drone routes the flight paths
 *  replace, plus the flight paths themselves. A floor with no hub gets exactly `floorObstacles(tf, routes)`. */
export function messagingObstacles(tf: TileFloor, routes: TileRoute[], paths: FlightPath[], covered: Set<string>): PxRect[] {
  return [...floorObstacles(tf, covered.size ? routes.filter((r) => !covered.has(r.key)) : routes), ...paths.flatMap((p) => pathRects(p.points))];
}

/** Where along a path a plate is tried: the middle first, then stepping out to either end (not onto the pad or hub). */
const STEPS = [0.5, ...Array.from({ length: 13 }, (_, i) => [0.5 - (i + 1) * 0.03, 0.5 + (i + 1) * 0.03]).flat()];

/** One plate per flight, beside its path near the middle and never on it: candidates step out from the middle along
 *  the path, on either side, a little further each round; the first box inside the floor and clear of `clear` wins and
 *  joins it. No clear room: no plate. Deterministic: paths in the given order. */
export function placePlates(paths: FlightPath[], clear: Clearance, bounds: PxRect): Placed[] {
  const out: Placed[] = [];
  for (const [i, p] of paths.entries()) {
    const text = FLIGHT_LABEL[p.flight];
    const w = plateW(text), h = PLATE_H;
    // the polyline's segments, longest first (ties in path order): a plate sits beside the run it labels best
    const segs = p.points.slice(1).map((b, k) => [p.points[k], b] as [Pt, Pt])
      .map((sg, k) => ({ sg, k, len: Math.hypot(sg[1].x - sg[0].x, sg[1].y - sg[0].y) }))
      .sort((u, v) => v.len - u.len || u.k - v.k);
    let got: Placed | undefined;
    search: for (const gap of [6, 14]) for (const { sg: [a, b], len } of segs) {
      const nx = -(b.y - a.y) / (len || 1), ny = (b.x - a.x) / (len || 1);
      const reach = Math.abs(nx) * w / 2 + Math.abs(ny) * h / 2;   // centre to box edge along the normal
      // the upper (or, on a vertical run, the right) side first, as the mock does
      const sides = ny > 1e-9 || (Math.abs(ny) <= 1e-9 && nx < 0) ? [-1, 1] : [1, -1];
      for (const t of STEPS) for (const s of sides) {
        const cx = a.x + (b.x - a.x) * t + nx * s * (gap + reach), cy = a.y + (b.y - a.y) * t + ny * s * (gap + reach);
        const box = { x0: Math.round(cx - w / 2), y0: Math.round(cy - h / 2), x1: Math.round(cx - w / 2) + w, y1: Math.round(cy - h / 2) + h };
        if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
        got = { key: p.key, text, x: box.x0, y: box.y0, w, h, of: i };
        clear.add(box);
        break search;
      }
    }
    if (got) out.push(got);
  }
  return out;
}

/** Labels that belong to a box (a consumer's tags, a dock's sign), tried in `spots` order: the first clear one wins. */
export function placeBeside(key: string, text: string, spots: { x: number; y: number }[], clear: Clearance, bounds: PxRect, size = PLATE_FONT, w = plateW(text, size)): Placed | undefined {
  const h = PLATE_H;
  for (const s of spots) {
    const box = { x0: Math.round(s.x), y0: Math.round(s.y), x1: Math.round(s.x) + w, y1: Math.round(s.y) + h };
    if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
    clear.add(box);
    return { key, text, x: box.x0, y: box.y0, w, h };
  }
  return undefined;
}

/** Spots for a `w`-wide label under box `r` (world px, shadow included): just below it, then a tile further down (past
 *  a belt running along it); left-aligned, right-aligned, centred. */
export function spotsUnder(r: PxRect, w: number): { x: number; y: number }[] {
  const cx = (r.x0 + r.x1) / 2 - w / 2;
  return [4, 4 + T].flatMap((dy) => [r.x0, r.x1 - w, cx].map((x) => ({ x, y: r.y1 + dy })));
}
/** Spots beside box `r`, level with its bottom: right, then left. */
export function spotsBeside(r: PxRect, w: number, h = PLATE_H): { x: number; y: number }[] {
  return [{ x: r.x1 + 6, y: r.y1 - h }, { x: r.x0 - 6 - w, y: r.y1 - h }];
}

/** The consumer tags a machine wears: one line per consumer with tags (`group notifier · 2 replicas`), in the model's
 *  order, each keyed by `tagKey` (machine, hub and group). `wide` is the longest text the tag ever shows (a take's
 *  pulse, `replica 3 of 3`), which its box is sized for. None on the site: the overview is too detailed for them (the
 *  owner, 2026-10-06); the consumer's own floor shows them. */
export function consumerTags(tf: TileFloor): { machine: string; key: string; text: string; wide: string }[] {
  if (tf.site) return [];
  return (tf.landing?.messaging.consumers ?? []).filter((c) => c.tags.length).map((c) => {
    const text = c.tags.join(" · "), n = c.replicas ?? 1;
    const pulse = c.flight === "take" && n > 1 ? replicaPulse(text, n, n) : text;
    return { machine: c.machine, key: tagKey(c.machine, c.item, c.group), text, wide: pulse.length > text.length ? pulse : text };
  });
}

/** A replica tag's text while replica `k` (from 1) of `n` takes a crate: `N replicas` reads `replica k of N`. */
export const replicaPulse = (base: string, k: number, n: number) => base.replace(/\d+ replicas$/, `replica ${k} of ${n}`);
/** Does this tag name replicas (and so pulse as a queue's crates land)? */
export const isReplicaTag = (text: string) => /\d+ replicas$/.test(text);

/** A receiving dock's sign: `POST <path>` when the push endpoint is known (the relation's key is a path, or a request
 *  into the handler names one), else `push`. */
export function dockSign(model: Model, relations: string[]): string {
  const path = (key?: string | null) => {
    const m = /^(?:POST\s+)?(\/\S*)$/.exec(key?.trim() ?? "");
    return m ? m[1] : undefined;
  };
  const rels = relations.map((id) => model.map.relations.find((r) => r.id === id)).filter((r) => !!r);
  for (const r of rels) { const p = path(r!.key); if (p) return `POST ${p}`; }
  for (const r of rels) {
    const into = model.map.relations.find((q) => q.kind === "request" && q.to === r!.to && /^POST\s+\//.test(q.key ?? ""));
    if (into) return `POST ${path(into.key)}`;
  }
  return "push";
}

export interface MessagingLabels { tags: (Placed & { machine: string; inside: boolean })[]; signs: Placed[]; plates: Placed[] }

/** Every messaging label on a floor, placed in this order so the ones that say most win the room: consumer tags under
 *  their machines, dock signs, then one plate per flight. `clear` holds the floor's obstacles (and its zone names);
 *  each placed label joins it. `inside` gives a machine's free inner band (under its name, over its sub line), where a
 *  tag goes when no clear spot under the machine is left; a tag there is `inside`. */
export function messagingLabels(model: Model, tf: TileFloor, paths: FlightPath[], clear: Clearance,
  inside?: (machine: string) => PxRect | undefined): MessagingLabels {
  const bounds: PxRect = { x0: 0, y0: 0, x1: tf.cols * T, y1: tf.rows * T };
  const px = (r: Rect): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  const tags: (Placed & { machine: string; inside: boolean })[] = [];
  const bands = new Map<string, PxRect>();   // what is left of each machine's inner band as tags take it, top down
  for (const t of consumerTags(tf)) {
    const box = tf.boxes.get(t.machine);
    if (!box) continue;
    const r = px(box), w = plateW(t.wide), shadowed = { ...r, x1: r.x1 + 5, y1: r.y1 + 5 };
    let got = placeBeside(t.key, t.text, spotsUnder(shadowed, w), clear, bounds, PLATE_FONT, w);
    // no clear room under it (pads and belts crowd a busy floor): inside the machine, in the free band under its name
    const band = bands.get(t.machine) ?? inside?.(t.machine);
    if (!got && band && band.x1 - band.x0 >= w && band.y1 - band.y0 >= PLATE_H) {
      got = { key: t.key, text: t.text, x: Math.round(band.x0), y: Math.round(band.y0), w, h: PLATE_H };
      bands.set(t.machine, { ...band, y0: band.y0 + PLATE_H + 2 });
      tags.push({ ...got, machine: t.machine, inside: true });
      continue;
    }
    got ??= placeBeside(t.key, t.text, spotsBeside(shadowed, w), clear, bounds, PLATE_FONT, w);
    if (got) tags.push({ ...got, machine: t.machine, inside: false });
  }
  const signs: Placed[] = [];
  for (const d of tf.landing?.docks ?? []) {
    const path = paths.find((p) => p.dock && p.machine === d.machine && p.item === d.item && p.group === d.group);
    const text = dockSign(model, path?.relations ?? []);
    const r = px(d), w = plateW(text, 10);
    // the sign stands on the dock's open side (away from the machine), level with one of its ends (its flight comes in at
    // the middle), a little further out if a belt runs along the dock; then over or under the dock's ends
    const vertical = d.side === "w" || d.side === "e";
    const [ox, oy] = { n: [0, -1], s: [0, 1], w: [-1, 0], e: [1, 0] }[d.side];
    const base = { n: { x: 0, y: r.y0 - 4 - PLATE_H }, s: { x: 0, y: r.y1 + 4 }, w: { x: r.x0 - 4 - w, y: 0 }, e: { x: r.x1 + 4, y: 0 } }[d.side];
    const along = vertical ? [r.y0, r.y1 - PLATE_H, (r.y0 + r.y1) / 2 - PLATE_H / 2] : [r.x0, r.x1 - w, (r.x0 + r.x1) / 2 - w / 2];
    const open = [0, 12].flatMap((k) => along.map((v) => (vertical ? { x: base.x + ox * k, y: v } : { x: v, y: base.y + oy * k })));
    const ends = vertical
      ? [r.y0 - 4 - PLATE_H, r.y1 + 4].map((y) => ({ x: d.side === "w" ? r.x1 - 3 - w : r.x0 + 3, y }))   // off the machine
      : [{ x: r.x0 - 4 - w, y: (r.y0 + r.y1) / 2 - PLATE_H / 2 }, { x: r.x1 + 4, y: (r.y0 + r.y1) / 2 - PLATE_H / 2 }];
    const key = flightKey(d.machine, d.item);
    let got = placeBeside(key, text, [...open, ...ends], clear, bounds, 10);
    // no clear room round it: an upright dock's sign stands further out on its open side (never turned: every word reads
    // left to right); a level dock's goes on the dock itself, along its length, when it fits there
    const long = r.x1 - r.x0, cx = (r.x0 + r.x1) / 2, cy = (r.y0 + r.y1) / 2;
    if (!got && vertical) got = placeBeside(key, text, [24, 36, 48].flatMap((k) => along.map((v) => ({ x: base.x + ox * k, y: v }))), clear, bounds, 10);
    if (!got && !vertical && w <= long - 6) got = { key, text, x: Math.round(cx - w / 2), y: Math.round(cy - PLATE_H / 2), w, h: PLATE_H };
    if (got) signs.push(got);
  }
  return { tags, signs, plates: placePlates(paths, clear, bounds) };
}

/** The words written on a webhook dock's face (its `face`): a sign box at the dock's start, the dock's hazard stripes
 *  in the rest of its length; undefined when the face carries none (an upright dock, or a sign that fits no side: the
 *  dock's hover lists its routes). Inside the dock, so never over a line or a label. */
export function dockFace(d: WebhookDock): Placed | undefined {
  if (d.face === undefined) return undefined;
  return { key: d.machine, text: d.face, x: d.x * T + 3, y: d.y * T + (T - PLATE_H) / 2, w: plateW(d.face, 10), h: PLATE_H };
}

/** Which messaging kinds one floor has, for the legend's plain entries: a queue's waiting stack, a push dock, a pull, a
 *  dead-letter hub, a replica tag (only where tags are drawn: not on the site), an inbound webhook's receiving dock. Null
 *  when the floor has none of them. */
export interface MessagingLegend { queue?: true; push?: true; pull?: true; dead?: true; replicas?: true; webhook?: true }
export function legendKinds(tf: TileFloor, paths: FlightPath[]): MessagingLegend | null {
  const out: MessagingLegend = {};
  if (tf.webhooks?.length) out.webhook = true;   // an inbound webhook's receiving dock (pads.ts `webhookDocks`)
  const land = tf.landing;
  if (!land) return Object.keys(out).length ? out : null;
  const hubs = land.messaging.airfields.flatMap((a) => a.hubs);
  if (hubs.some((h) => h.waiting && land.stacks.some((s) => s.item === h.item))) out.queue = true;
  if (paths.some((p) => p.flight === "push")) out.push = true;
  if (paths.some((p) => p.flight === "pull")) out.pull = true;
  if (hubs.some((h) => h.dlqOf)) out.dead = true;
  const tagged = new Set(consumerTags(tf).filter((t) => isReplicaTag(t.text)).map((t) => t.key));
  if (land.messaging.consumers.some((c) => tagged.has(tagKey(c.machine, c.item, c.group)))) out.replicas = true;
  return Object.keys(out).length ? out : null;
}
