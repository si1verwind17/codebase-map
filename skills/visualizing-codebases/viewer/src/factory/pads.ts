// src/factory/pads.ts
// Where drones land (spec §5). A pad per producer, consumer group and failure is a mark inside its machine, on the
// roof's bottom row, laid from the right (the owner, 2026-10-06: the floor round the machine stays free for belts and
// pipes): it holds no floor tile. A push subscription's 1×3 receiving dock stands outside, against the side of the
// machine that faces its hub (its broker's airfield on the site, the hub's door inside a building), near the side's
// middle (never on a cache chest's gap). Docks and the queue hubs' waiting-stack tiles are reserved before routing: the router treats them as
// obstacles. Pure: painting and motion read the result.
import type { Bundle, Model } from "../model/model";
import type { Stack, TileFloor } from "./layout";
import { messaging, type Flight, type Messaging } from "./messaging";
import { LANE_H, OPP, STEP, T, type Dir, type Rect } from "./tiles";
import { plateW } from "./fit";
import { railEnds, railRects } from "./yards";
import type { TileRoute } from "./router";

/** What a pad launches or lands: a produce/enqueue, a consumer group's copy/take/pull, or a failure to a dead-letter hub. */
export type PadRole = "produce" | "consume" | "failure";
/** A pad: a mark on tile (x, y) of `machine`'s own bottom row, `inside` the box (it holds no floor tile; lines and
 *  the router never see it). `item` is the hub's box on this floor (the hub the flight flies to or from), `topic` its
 *  topic node: for a failure, the dead-letter hub. One pad per (machine, hub, role, group). */
export interface Pad { machine: string; item: string; topic: string; role: PadRole; group?: string; flight: Flight; x: number; y: number; inside: true }
/** A push subscription's receiving dock: 3 tiles along `side` of `machine`, 1 deep (w×h is 3×1 on n/s, 1×3 on e/w). */
export interface Dock { machine: string; item: string; topic: string; role: PadRole; group?: string; flight: Flight; x: number; y: number; w: number; h: number; side: Dir }
/** A dock that found no free run on any side of its machine (all four full), or a pad past the machine's bottom row
 *  (more pads than its width less one): its flight has no landing place. */
export interface Unplaced { machine: string; item: string; topic: string; role: PadRole; group?: string; flight: Flight; dock: boolean }
/** A floor's messaging with the tiles it holds: what Tasks 4 (paint) and 5 (motion) read. `unplaced` is empty on every
 *  real floor; a flight listed there falls back to its machine's centre. */
export interface Landing { messaging: Messaging; pads: Pad[]; docks: Dock[]; stacks: Stack[]; unplaced: Unplaced[] }

/** A receiving dock's length along its side, tiles. */
const DOCK = 3;
const ROLE: Record<PadRole, number> = { produce: 0, consume: 1, failure: 2 };
const byStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const centre = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });

/** A pad's mark, world px: a PAD_MARK square in its tile, centred across it and standing 3 px above the box's bottom
 *  edge (clear of a short box's second name line). */
export const PAD_MARK = 15;
export const padMark = (p: { x: number; y: number }) => ({ x: p.x * T + (T - PAD_MARK) / 2, y: (p.y + 1) * T - 3 - PAD_MARK, w: PAD_MARK, h: PAD_MARK });
/** Where a pad's drone takes off and lands: its mark's centre, world px. */
export const padCentre = (p: { x: number; y: number }) => { const m = padMark(p); return { x: m.x + m.w / 2, y: m.y + m.h / 2 }; };
/** The px a machine's pads take from the right of its bottom row (its sub line and role tag stop short of them). */
export const padReserve = (pads: number) => (pads ? pads * T : 0);

type Want = { machine: string; item: string; topic: string; role: PadRole; group?: string; flight: Flight; dock: boolean; prefs: Dir[] };

/** The floor's messaging and its reserved tiles; undefined on a floor with no hub (it lays out and routes as before). */
export function landing(model: Model, container: string, tf: TileFloor, bundles: Bundle[]): Landing | undefined {
  const msg = messaging(model, container, tf, bundles);
  if (!msg.airfields.length) return undefined;
  const hubBroker = new Map(msg.airfields.flatMap((a) => a.hubs.map((h) => [h.item, a.broker] as const)));
  /** What a dock faces: its broker's airfield on the site, the hub itself (a door) inside a building. */
  const facing = (item: string): Rect => {
    const z = tf.site ? tf.zones.find((q) => q.airfield && q.name === hubBroker.get(item)) : undefined;
    return z ?? tf.boxes.get(item)!;
  };
  const wants: Want[] = [];
  const want = (w: Omit<Want, "prefs">) => wants.push({ ...w, prefs: sides(tf.boxes.get(w.machine)!, facing(w.item), tf.site) });
  for (const p of msg.producers) want({ machine: p.machine, item: p.item, topic: p.topic, role: "produce", flight: p.flight, dock: false });
  for (const c of msg.consumers) want({ machine: c.machine, item: c.item, topic: c.topic, role: "consume", flight: c.flight, dock: c.subscription === "push", ...(c.group !== undefined ? { group: c.group } : {}) });
  for (const f of msg.failures) want({ machine: f.machine, item: f.item, topic: f.dlq, role: "failure", flight: f.flight, dock: false });

  // tiles already held: machines, lanes, waiting stacks; docks join as they are placed
  const held = new Set<number>();
  const key = (x: number, y: number) => y * tf.cols + x;
  const hold = (r: Rect) => { for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y)); };
  for (const b of tf.boxes.values()) hold(b);
  for (const l of tf.lanes) hold({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H });
  for (const s of tf.stacks ?? []) hold({ x: s.x, y: s.y, w: 1, h: 1 });
  for (const g of tf.chestGaps ?? []) hold(g);   // a chest's tap pair crosses its gap: no dock takes it
  const free = (r: Rect) => {
    if (r.x < 0 || r.y < 0 || r.x + r.w > tf.cols || r.y + r.h > tf.rows) return false;
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (held.has(key(x, y))) return false;
    return true;
  };

  const pads: Pad[] = [], docks: Dock[] = [], unplaced: Unplaced[] = [];
  const strip = (p: Want) => { const { prefs: _, ...w } = p; return w; };
  const machines = [...new Set(wants.map((w) => w.machine))].sort(byStr);
  for (const id of machines) {
    const m = tf.boxes.get(id)!;
    // pads: side by side on the bottom row, from the right, left to right in the order of the hubs they fly to (so
    // straight flights do not cross at the machine); the leftmost tile stays for the sub line's start
    const mine = wants.filter((w) => w.machine === id && !w.dock).sort((p, q) => centre(tf.boxes.get(p.item)!).x - centre(tf.boxes.get(q.item)!).x
      || ROLE[p.role] - ROLE[q.role] || byStr(p.topic, q.topic) || byStr(p.group ?? "", q.group ?? ""));
    const room = Math.max(0, m.w - 1), laid = mine.slice(0, room);
    laid.forEach((w, i) => {
      const { prefs: _, dock: __, ...rest } = w;
      pads.push({ ...rest, x: m.x + m.w - laid.length + i, y: m.y + m.h - 1, inside: true });
    });
    for (const w of mine.slice(room)) unplaced.push(strip(w));
    let pending = wants.filter((w) => w.machine === id && w.dock).map((w) => ({ w, pref: 0 }));
    const closed = new Set<Dir>();
    while (pending.length) {
      // every pending dock on its first side not yet laid; one side at a time, the most wanted first (ties in n e s w order)
      for (const p of pending) while (p.pref < 4 && closed.has(p.w.prefs[p.pref])) p.pref++;
      for (const p of pending) if (p.pref >= 4) unplaced.push(strip(p.w));   // all four sides full: recorded, not dropped silently
      pending = pending.filter((p) => p.pref < 4);
      if (!pending.length) break;
      const count = new Map<Dir, number>();
      for (const p of pending) count.set(p.w.prefs[p.pref], (count.get(p.w.prefs[p.pref]) ?? 0) + 1);
      const side = (["n", "e", "s", "w"] as Dir[]).filter((d) => count.has(d)).sort((a, b) => count.get(b)! - count.get(a)!)[0];
      closed.add(side);
      const here = pending.filter((p) => p.w.prefs[p.pref] === side);
      // along the side in the order of the hubs they fly to, so flight paths do not cross at the machine
      const axis = side === "n" || side === "s" ? "x" : "y";
      here.sort((p, q) => centre(tf.boxes.get(p.w.item)!)[axis] - centre(tf.boxes.get(q.w.item)!)[axis]
        || byStr(p.w.topic, q.w.topic) || byStr(p.w.group ?? "", q.w.group ?? ""));
      // one tile off the middle toward the hubs: a shorter flight, and the middle tile stays for the machine's lines
      const toward = here.reduce((t, p) => t + centre(tf.boxes.get(p.w.item)!)[axis], 0) / here.length - centre(m)[axis];
      const offs = layRun(m, side, here.length, free, Math.abs(toward) < 1 ? 0 : Math.sign(toward));
      const done = new Set<(typeof here)[number]>();
      for (let i = 0; i < here.length; i++) {
        const p = here[i], at = offs[i];
        if (at === undefined) { p.pref++; continue; }   // no room on this side: try its next one
        done.add(p);
        const w = p.w, rect = tileRect(m, side, at, DOCK);
        hold(rect);
        docks.push({ machine: w.machine, item: w.item, topic: w.topic, role: w.role, ...(w.group !== undefined ? { group: w.group } : {}), flight: w.flight, ...rect, side });
      }
      pending = pending.filter((p) => !done.has(p));
    }
  }
  const order = (a: { machine: string; item: string; group?: string }, b: { machine: string; item: string; group?: string }) =>
    byStr(a.machine, b.machine) || byStr(a.item, b.item) || byStr(a.group ?? "", b.group ?? "");
  pads.sort((a, b) => order(a, b) || ROLE[a.role] - ROLE[b.role]);
  docks.sort(order);
  unplaced.sort((a, b) => order(a, b) || ROLE[a.role] - ROLE[b.role]);
  return { messaging: msg, pads, docks, stacks: tf.stacks ?? [], unplaced };
}

/** Every floor tile messaging and the rails hold: waiting stacks and receiving docks (push and webhook), then rail yards, sign tiles and
 *  stations (the router's obstacles). Pads sit inside their machines and hold none. */
export function reservedRects(tf: TileFloor): Rect[] {
  return [
    ...(tf.stacks ?? []).map((s) => ({ x: s.x, y: s.y, w: 1, h: 1 })),
    ...(tf.landing?.docks ?? []).map((d) => ({ x: d.x, y: d.y, w: d.w, h: d.h })),
    ...(tf.webhooks ?? []).map((d) => ({ x: d.x, y: d.y, w: d.w, h: d.h })),
    ...railRects(tf),
  ];
}

/** The sides of `m` in the order they face `t`: the main axis first (on the site, the vertical one when `t` is wholly
 *  above or below), then the other, then their opposites. */
function sides(m: Rect, t: Rect, site: boolean): Dir[] {
  const a = centre(m), b = centre(t), dx = b.x - a.x, dy = b.y - a.y;
  const v: Dir = dy >= 0 ? "s" : "n", h: Dir = dx >= 0 ? "e" : "w";
  const opp: Record<Dir, Dir> = { n: "s", s: "n", e: "w", w: "e" };
  // on the site the airfields are a band below the production line: a machine wholly above or below its airfield
  // launches from the side facing it (n or s), not from a side facing along the band into the next corridor
  const apart = t.y >= m.y + m.h || t.y + t.h <= m.y;
  const vertical = (site && apart) || Math.abs(dy) >= Math.abs(dx);
  const [p, q] = vertical ? [v, h] : [h, v];
  return [p, q, opp[q], opp[p]];
}

/** Offsets along `side` for a run of `count` docks (`len` tiles each, DOCK by default) laid end to end, as near the
 *  side's middle as free
 *  tiles allow, one tile toward `lean` (-1, 0, 1) when the side has room either way; when the whole run fits nowhere,
 *  the last docks are dropped (undefined) until it does. */
function layRun(m: Rect, side: Dir, count: number, free: (r: Rect) => boolean, lean: number, len = DOCK): (number | undefined)[] {
  const n = side === "n" || side === "s" ? m.w : m.h;
  for (let k = count; k > 0; k--) {
    const total = k * len;
    if (total > n) continue;
    // the lean never puts a run on a long side's outermost tile (a 3-tile side has nothing else off its middle)
    const mid = Math.floor((n - total) / 2), leaned = mid + lean;
    const ideal = n - total >= 2 && (n <= 3 || (leaned >= 1 && leaned + total <= n - 1)) ? leaned : mid;
    const starts = [ideal];
    for (let d = 1; d <= n; d++) starts.push(ideal + d, ideal - d);
    for (const s0 of starts) {
      if (s0 < 0 || s0 + total > n) continue;
      const offs = Array.from({ length: k }, (_, i) => s0 + i * len);
      if (offs.every((o) => free(tileRect(m, side, o, len)))) return [...offs, ...Array.from({ length: count - k }, () => undefined)];
    }
  }
  return Array.from({ length: count }, () => undefined);
}

/** The rect `len` tiles long just outside `side` of `m`, starting `off` tiles along it. */
function tileRect(m: Rect, side: Dir, off: number, len: number): Rect {
  switch (side) {
    case "n": return { x: m.x + off, y: m.y - 1, w: len, h: 1 };
    case "s": return { x: m.x + off, y: m.y + m.h, w: len, h: 1 };
    case "w": return { x: m.x - 1, y: m.y + off, w: 1, h: len };
    case "e": return { x: m.x + m.w, y: m.y + off, w: 1, h: len };
  }
}

/** An inbound webhook's receiving dock (spec §7): on the site, every `request` from an outside service into a service
 *  ends here, not at the service's wall. One per service, 1 deep against a side (the push dock's art); `keys` are the
 *  bundles whose belts plug into it, `signs` the distinct routes it receives (each relation's key, `webhook` with none),
 *  sorted. `face` is what is written on the dock itself (a level dock only: no word is turned): its route, or the first
 *  and `+N`; where that fits no side, the first route's method (with `+N`), else `webhook`. The dock is DOCK long, or as long as
 *  its face needs plus a tile of stripes, up to its side's length. Undefined `face`: the dock lists its routes on hover
 *  only (as it does whenever the face does not read every route whole). */
export interface WebhookDock { machine: string; keys: string[]; signs: string[]; face?: string; x: number; y: number; w: number; h: number; side: Dir }

/** A webhook dock's id as a line end (the router's trunk groups and the plug checks). */
export const webhookDockId = (machine: string) => `webhook:${machine}`;
/** A webhook's sign: the relation's key, `webhook` when it has none. */
export const webhookSign = (key?: string | null) => key?.trim() || "webhook";

/** The inbound webhook bundles on the site, by their service: its bundle keys, its signs, and its callers' boxes. */
function inboundWebhooks(model: Model, tf: TileFloor, bundles: Bundle[]): Map<string, { keys: string[]; signs: Set<string>; callers: Rect[] }> {
  const inbound = new Map<string, { keys: string[]; signs: Set<string>; callers: Rect[] }>();
  if (!tf.site) return inbound;
  const ext = (id: string) => tf.boxes.get(id)?.kind === "external";
  for (const b of bundles) {
    if (b.kind !== "request" || ext(b.a) === ext(b.b)) continue;
    const [outside, machine] = ext(b.a) ? [b.a, b.b] : [b.b, b.a];
    if (tf.boxes.get(machine)?.kind !== "service") continue;
    const calls = b.relations.filter((r) => r.kind === "request" && model.kindOf(r.from) === "external");
    if (!calls.length) continue;
    const w = inbound.get(machine) ?? inbound.set(machine, { keys: [], signs: new Set(), callers: [] }).get(machine)!;
    w.keys.push(b.key);
    for (const r of calls) w.signs.add(webhookSign(r.key));
    w.callers.push(tf.boxes.get(outside)!);
  }
  return inbound;
}

/** Does the site have an inbound webhook (a request from an outside service into a service)? Only then does planFloor
 *  route a first time to see where its belts arrive. */
export const hasWebhooks = (model: Model, tf: TileFloor, bundles: Bundle[]) => inboundWebhooks(model, tf, bundles).size > 0;

/** The site's inbound webhook docks, placed after the push docks and the rails (their tiles, and the tiles rails start
 *  and end on, held) from a first routing of the floor (`routes`, no dock yet): each dock stands on the side of its
 *  service its first belt arrived at, else on the first side with a free run in the push dock's order (facing its
 *  callers). Undefined on an inside floor or a site with none. A service whose four sides have no free run gets no
 *  dock: its belts plug into its wall as before, and `notes` says so. */
export function webhookDocks(model: Model, tf: TileFloor, bundles: Bundle[], routes: TileRoute[]): { docks: WebhookDock[]; notes: string[] } | undefined {
  const inbound = inboundWebhooks(model, tf, bundles);
  if (!inbound.size) return undefined;
  const held = new Set<number>();
  const key = (x: number, y: number) => y * tf.cols + x;
  const hold = (r: Rect) => { for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y)); };
  for (const b of tf.boxes.values()) hold(b);
  for (const l of tf.lanes) hold({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H });
  for (const r of reservedRects(tf)) hold(r);
  for (const e of railEnds(tf).values()) for (const t of [...e.yardExits, e.entry]) hold({ x: t.x, y: t.y, w: 1, h: 1 });
  for (const g of tf.chestGaps ?? []) hold(g);   // a chest's tap pair crosses its gap: no dock takes it
  const free = (r: Rect) => {
    if (r.x < 0 || r.y < 0 || r.x + r.w > tf.cols || r.y + r.h > tf.rows) return false;
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (held.has(key(x, y))) return false;
    return true;
  };
  /** The side of `m` a routed line plugs into, if it does. */
  const plugSide = (m: Rect, r: TileRoute | undefined): Dir | undefined => {
    const ps = r?.pieces ?? [];
    if (!ps.length) return undefined;
    const f = ps[0], l = ps[ps.length - 1];
    const inBox = (x: number, y: number) => x >= m.x && y >= m.y && x < m.x + m.w && y < m.y + m.h;
    if (inBox(l.x + STEP[l.out][0], l.y + STEP[l.out][1])) return OPP[l.out];
    if (inBox(f.x - STEP[f.in][0], f.y - STEP[f.in][1])) return f.in;
    return undefined;
  };
  const docks: WebhookDock[] = [], notes: string[] = [];
  for (const machine of [...inbound.keys()].sort(byStr)) {
    const w = inbound.get(machine)!, m = tf.boxes.get(machine)!, keys = [...w.keys].sort(byStr);
    const cs = w.callers.map(centre), at = { x: cs.reduce((s, c) => s + c.x, 0) / cs.length, y: cs.reduce((s, c) => s + c.y, 0) / cs.length };
    const order = sides(m, { x: at.x, y: at.y, w: 0, h: 0 }, tf.site);
    const arrived = plugSide(m, routes.find((r) => r.key === keys[0]));
    const prefs = arrived ? [arrived, ...order.filter((d) => d !== arrived)] : order;
    const signs = [...w.signs].sort(byStr);
    // what the face may say, best first: every route (or the first and `+N`), then the first route's method (and `+N`),
    // then `webhook` (the dock's own kind: only when there is no key, or nothing else fits)
    const method = /^([A-Z]+)\s/.exec(signs[0])?.[1], more = signs.length > 1 ? ` +${signs.length - 1}` : "";
    const words = [...new Set([`${signs[0]}${more}`, ...(method ? [`${method}${more}`] : []), "webhook"])];
    let placed = false;
    sides: for (const side of prefs) {
      const level = side === "n" || side === "s", n = level ? m.w : m.h;
      // each wording that fits this side's length, then a bare dock (hover only); an upright dock carries no words
      const tries: { face?: string; len: number }[] = level
        ? words.map((t) => ({ face: t, len: Math.max(DOCK, Math.ceil(plateW(t, 10) / T) + 1) })).filter((q) => q.len <= n)
        : [];
      tries.push({ len: DOCK });
      const axis = level ? "x" : "y";
      const toward = at[axis] - centre(m)[axis];
      for (const q of tries) {
        const [off] = layRun(m, side, 1, free, Math.abs(toward) < 1 ? 0 : Math.sign(toward), q.len);
        if (off === undefined) continue;
        const rect = tileRect(m, side, off, q.len);
        hold(rect);
        docks.push({ machine, keys, signs, ...(q.face !== undefined ? { face: q.face } : {}), ...rect, side });
        placed = true;
        break sides;
      }
    }
    if (!placed) notes.push(`webhook dock: ${machine} has no free side; its belts plug into its wall`);
  }
  return { docks, notes };
}
