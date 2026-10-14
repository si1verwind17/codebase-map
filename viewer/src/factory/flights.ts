// src/factory/flights.ts
// Where messaging is painted (spec §5), pure: one dotted flight path per flight from its pad or dock to its hub (or
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
 *  door it stops at the door's edge. `key` is the bundle the flight's relations ride (`machine|hub`, sorted), so
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
  hub: Pt;                 // where the path meets the hub: its centre, or, for a door, the point where it reaches the door's edge
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
  return out;
}
/** What a still flight's arrows keep off: every box on the floor with its shadow (machines, hubs, stores, doors) and
 *  every receiving dock, webhook dock and waiting stack. A flight's path starts inside its machine (its pad), ends on
 *  its hub or dock, and may fly over other machines: its arrows sit only on the open stretches between them. */
export function flightKeepOff(tf: TileFloor): PxRect[] {
  const SHADOW = 5;
  const boxes = [...tf.boxes.values()].map((r) => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T + SHADOW, y1: (r.y + r.h) * T + SHADOW }));
  const tiles = (r: { x: number; y: number; w: number; h: number }): PxRect => ({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });
  const docks = (tf.landing?.docks ?? []).map(tiles), webhooks = (tf.webhooks ?? []).map(tiles);
  const stacks = (tf.landing?.stacks ?? []).map((s) => tiles({ x: s.x, y: s.y, w: 1, h: 1 }));
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
