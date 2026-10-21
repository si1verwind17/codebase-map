// src/factory/yards.ts
// Where batch rails start and stop. A rail yard stands flush against its scheduler's side (an inner yard,
// whose scheduler is off the floor, stands free in the in column below its door), one platform
// row per destination (no header: the block and its rows say what it is); a station strip stands flush against each destination's side, facing the
// yard. Both, and the yard's sign tile, are reserved before routing: the router treats them as obstacles. A rail leaves
// the yard through the tile just past a platform (its exit) and ends running into one end of its station, along the
// destination's wall, as a siding does. Pure: painting and trains read the result.
import { flies, type Bundle, type Model } from "../model/model";
import type { TileRoute } from "./router";
import { batch, platformOf, type Batch, type Platform, type Yard } from "./batch";
import type { TileFloor } from "./layout";
import { LANE_H, STEP, type Dir, type Rect } from "./tiles";

/** A rail yard: `w`×`h` tiles flush against `side` of `machine` (the scheduler's box), or, on an inner floor, standing
 *  `free` in the in column below the door it comes in by (`machine` is that door, `side` only the way `out` runs: the
 *  yard is not flush against it); `machine` is null for an inner yard with no door, at the floor's left edge. On every side it lies level: 4 wide and
 *  one row per platform tall, so its words read left to right. Its rails leave the end of each row, travelling `out`:
 *  away from the machine against an e or w side; along the side (e or w, toward the destinations) against an n or s
 *  side. A yard with only self jobs is a 4×1 strip where a train stands parked, the sign on its last tile.
 *  `platforms[i]` is the yard tile at the `out` end of platform i's row: its rail leaves through the tile just past it
 *  (on a ladder, the throat's tile lies between: `ladder`).
 *  `sign` is the sign tile: beside the yard, reserved; inside it for a yard with no platforms; null when no tile beside
 *  the yard was free (the sign is the yard's hover only). */
export interface YardBox { source: string; machine: string | null; x: number; y: number; w: number; h: number; side: Dir; out: Dir; platforms: { dest: string; x: number; y: number }[]; sign: { x: number; y: number } | null;
  /** A ladder: the yard is one tile wider, its last column (on the `out` side, past the platform tiles) a throat. For
   *  each platform, the index of the platform whose row its rail leaves by: it joins the throat by one switch and runs
   *  along it to that row, which leaves the yard through the tile just past the throat. Absent on a yard where every
   *  platform has its own exit (`yardLadders`). */
  ladder?: number[];
  /** Standing free in the in column below its door (not flush against any machine): each rail leaves its exit straight for RUN tiles before it turns
   *  (router.ts), so the tracks fan out across the column instead of packing beside the yard. */
  free?: true }
/** Tiles a free-standing yard's rail runs straight from its exit before its first turn. */
export const RUN = 2;
/** A station: a strip 1 deep and up to 3 long flush against `side` of its destination `dest`, for the rail from the yard
 *  of `source`. The rail runs into it along the destination's wall from `entry`, the tile just past its end nearer the
 *  yard (travelling `entry.d`); its far end is the buffer stop. */
export interface StationBox { dest: string; source: string; x: number; y: number; w: number; h: number; side: Dir; entry: Exit;
  /** A yard-less station: its rail comes in by this door (the scheduler is off the floor, `source` is the door too);
   *  absent for a station a yard's platform feeds. */
  door?: string;
  /** a yard-less station's jobs (no yard's platform holds them) */
  platform?: Platform;
  /** The key of the route that is this station's rail: the batch bundle between the yard's machine and `dest`, or the
   *  key of one of `Rails.shells` when there is no such bundle. */
  track: string }
/** A yard or station that found no room (`dest` set for a station): recorded, not dropped silently. Empty on every
 *  real floor so far. */
export interface UnplacedRail { source: string; dest?: string;
  /** painted, not placed: the rail's yard link was cut short (its first piece is past no platform of its yard) */ link?: true }
/** A floor's batch with the tiles it holds: tf.rails, absent on a floor with no yard. `shells` are stand-in bundles
 *  (kind batch, key `rail:<first relation id>`) for the stations whose rail no batch bundle carries -- an inner yard with
 *  no door, a platform to a door whose jobs never lift onto the floor, a pair whose bundle draws as another kind -- so
 *  every platform has a routed rail. They are no bundles of the model: the scene draws them, nothing selects them. */
export interface Rails { batch: Batch; yards: YardBox[]; stations: StationBox[]; shells: Bundle[]; unplaced: UnplacedRail[] }

/** What the router needs for one rail: its yard (the line's source), its own platform's exit and every exit of the
 *  yard (a rail riding a trunk starts on the trunk's), and its station (the line's target), entered from its entry. */
export interface RailEnd { yard?: YardBox; own?: Exit; yardExits: Exit[]; station: StationBox; entry: Exit; dest: string;
  /** a yard-less rail's source: the door its off-floor scheduler's jobs come in by (no yard, no exits: it leaves the door
   *  by any side, as a belt does) */ door?: string }
/** A tile a rail starts or ends on, and the way it travels there (out of the yard; into the station). */
export interface Exit { x: number; y: number; d: Dir }
/** A yard's ladder as planned from a first routing, by yard source: its platform rows top to bottom, each with the
 *  destination of the row its rail leaves by (rows leaving by one exit lie together, that exit at an end of them). */
export type Ladders = Map<string, { dest: string; exit: string }[]>;

/** The ids a rail's two ends go by in the router (trunks group on them) and in tests. */
export const yardId = (source: string) => `yard:${source}`;
export const stationId = (s: { source: string; dest: string }) => `station:${s.source}>${s.dest}`;

const DEPTH = 4;        // a yard's depth from its machine, tiles
const STATION = 3;      // a station's longest strip
const byStr = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
const centre = (r: Rect) => ({ x: r.x + r.w / 2, y: r.y + r.h / 2 });

/** The floor's batch and its reserved tiles; undefined on a floor with no yard (it lays out and routes as before). */
export function rails(model: Model, container: string, tf: TileFloor, bundles: Bundle[], ladders?: Ladders): Rails | undefined {
  const b = batch(model, container, tf, bundles);
  const inbound = doorRails(tf, bundles);
  if (!b.yards.length && !inbound.length) return undefined;
  const key = (x: number, y: number) => y * tf.cols + x;
  const held = new Set<number>();     // boxes, lanes, stacks, docks, yards, stations, signs
  const kept = new Set<number>();     // a yard's exits and the tile past each, a station's entry: no later yard, station or sign stands on them
  const label = new Set<number>();    // zone label rows: no yard, station or sign sits on a zone's name
  const box = new Int32Array(tf.cols * tf.rows).fill(-1);   // which box covers a tile
  const ids = [...tf.boxes.keys()];
  const hold = (r: Rect) => { for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) held.add(key(x, y)); };
  ids.forEach((id, i) => { const r = tf.boxes.get(id)!; hold(r); for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) box[key(x, y)] = i; });
  for (const l of tf.lanes) hold({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H });
  for (const s of tf.stacks ?? []) hold({ x: s.x, y: s.y, w: 1, h: 1 });
  for (const d of tf.landing?.docks ?? []) hold(d);
  for (const z of tf.zones) for (let x = z.x; x < z.x + z.w; x++) label.add(key(x, z.y + z.h - 1));
  const onFloor = (x: number, y: number) => x >= 0 && y >= 0 && x < tf.cols && y < tf.rows;
  const open = (x: number, y: number) => onFloor(x, y) && !held.has(key(x, y)) && !kept.has(key(x, y));
  /** Free floor; with `named`, off every zone's label row too. */
  const clear = (r: Rect, named = true) => {
    for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (!open(x, y) || (named && label.has(key(x, y)))) return false;
    return true;
  };
  /** No box but `own` touches the rect's sides: other machines keep the tiles their lines plug into. */
  const alone = (r: Rect, own: number) => {
    for (let x = r.x - 1; x <= r.x + r.w; x++) for (let y = r.y - 1; y <= r.y + r.h; y++) {
      if ((x === r.x - 1 || x === r.x + r.w) === (y === r.y - 1 || y === r.y + r.h)) continue;   // corners and inside
      if (onFloor(x, y) && box[key(x, y)] >= 0 && box[key(x, y)] !== own) return false;
    }
    return true;
  };

  const yards: YardBox[] = [], unplaced: UnplacedRail[] = [];
  for (const y of b.yards) {
    const machine = machineOf(model, container, tf, y);
    const placed = placeYard(tf, y, machine, { clear, alone, open, ids }, ladders?.get(y.source));
    if (!placed) { unplaced.push({ source: y.source }); continue; }
    hold(placed);
    for (const e of exits(placed)) { kept.add(key(e.x, e.y)); kept.add(key(e.x + STEP[e.d][0], e.y + STEP[e.d][1])); }   // its exits and the tile past each stay open
    // the sign: beside the yard, off its exits and its machine; inside a yard with no platforms
    if (!y.platforms.length) placed.sign = { x: placed.x + placed.w - 1, y: placed.y };
    else {
      const s = signSpot(placed).find((p) => clear({ x: p.x, y: p.y, w: 1, h: 1 }) && alone({ x: p.x, y: p.y, w: 1, h: 1 }, machine ? ids.indexOf(machine) : -1));
      placed.sign = s ?? null;
      if (s) hold({ x: s.x, y: s.y, w: 1, h: 1 });
    }
    yards.push(placed);
  }

  const stations: StationBox[] = [], shells: Bundle[] = [];
  const byKey = new Map(bundles.map((q) => [q.key, q]));
  const rel = new Map(model.map.relations.map((r) => [r.id, r]));
  const carried = new Set<string>();   // batch bundles already some station's rail
  for (const y of yards) {
    const jobs = new Map(b.yards.find((q) => q.source === y.source)!.platforms.map((p) => [p.dest, p.jobs]));
    for (const [i, p] of y.platforms.entries()) {
      const d = tf.boxes.get(p.dest)!;
      const from = exitOf(y, i);
      const s = placeStation(d, from, (r) => clear(r), (e) => open(e.x, e.y) && !label.has(key(e.x, e.y)), busy(tf, bundles, p.dest, y.machine));
      if (!s) { unplaced.push({ source: y.source, dest: p.dest }); continue; }
      // its rail: the batch bundle between the yard's machine and the destination, else a stand-in
      const k = y.machine ? (y.machine < p.dest ? `${y.machine}|${p.dest}` : `${p.dest}|${y.machine}`) : "";
      let track = k;
      if (!k || byKey.get(k)?.kind !== "batch" || carried.has(k)) {
        const mine = jobs.get(p.dest)!, relations = mine.map((j) => rel.get(j.relation)!).filter(Boolean);
        track = `rail:${mine[0].relation}`;
        shells.push({ key: track, a: y.machine ?? yardId(y.source), b: p.dest, relations, kinds: { batch: relations.length },
          inferred: relations.filter((r) => r.confidence === "inferred").length, kind: "batch", flow: "a→b" });
      } else carried.add(k);
      const st: StationBox = { dest: p.dest, source: y.source, ...s, track };
      hold(st);
      kept.add(key(st.entry.x, st.entry.y));
      stations.push(st);
    }
  }
  // a job whose scheduler is off the floor comes in by its door with no yard there: its station stands at the item it
  // runs, its rail is the door's batch bundle (when no yard's station already carries that bundle)
  for (const q of inbound) {
    if (carried.has(q.key)) continue;
    const d = tf.boxes.get(q.dest)!, m = tf.boxes.get(q.door)!;
    const from: Exit = { x: Math.floor(m.x + m.w / 2), y: Math.floor(m.y + m.h / 2), d: "e" };
    const s = placeStation(d, from, (r) => clear(r), (e) => open(e.x, e.y) && !label.has(key(e.x, e.y)), busy(tf, bundles, q.dest, q.door));
    if (!s) { unplaced.push({ source: q.door, dest: q.dest }); continue; }
    carried.add(q.key);
    const st: StationBox = { dest: q.dest, source: q.door, ...s, track: q.key, door: q.door, platform: platformOf(q.dest, bundles.find((x) => x.key === q.key)!.relations) };
    hold(st);
    kept.add(key(st.entry.x, st.entry.y));
    stations.push(st);
  }
  return { batch: b, yards, stations, shells, unplaced };
}

/** Batch bundles that come in by a door to an item on the floor (their scheduler lies off it): by key. */
function doorRails(tf: TileFloor, bundles: Bundle[]): { key: string; door: string; dest: string }[] {
  const isDoor = (id: string) => tf.boxes.get(id)?.foot === "door";
  const out: { key: string; door: string; dest: string }[] = [];
  for (const q of bundles) {
    if (q.kind !== "batch" || !tf.boxes.has(q.a) || !tf.boxes.has(q.b)) continue;
    const [src, dst] = q.flow === "b→a" ? [q.b, q.a] : q.flow === "a→b" ? [q.a, q.b] : isDoor(q.a) ? [q.a, q.b] : [q.b, q.a];
    if (isDoor(src) && !isDoor(dst)) out.push({ key: q.key, door: src, dest: dst });
  }
  return out.sort((p, q) => byStr(p.key, q.key));
}

/** How many of a machine's other lines (bundles but the rail from `machine`, events excepted: drones fly) have their
 *  far end wholly past each of its sides: a lane counts as its band. A station keeps off the busy sides. */
function busy(tf: TileFloor, bundles: Bundle[], id: string, machine: string | null): Record<Dir, number> {
  const d = tf.boxes.get(id)!, out: Record<Dir, number> = { n: 0, e: 0, s: 0, w: 0 };
  for (const b of bundles) {
    if (flies(b.kind) || (b.a !== id && b.b !== id)) continue;
    const other = b.a === id ? b.b : b.a;
    if (other === machine) continue;
    const lane = tf.lanes.find((l) => l.id === other);
    const r = lane ? { x: lane.x0, y: lane.y, w: lane.x1 - lane.x0, h: LANE_H } : tf.boxes.get(other);
    if (!r) continue;
    if (r.y + r.h <= d.y) out.n++;
    if (r.x >= d.x + d.w) out.e++;
    if (r.y >= d.y + d.h) out.s++;
    if (r.x + r.w <= d.x) out.w++;
  }
  return out;
}

/** The box a yard stands against: its scheduler's own box; on an inner floor the door its jobs come in by (the one most
 *  of them use, by id on a tie), or null when no such door is on the floor. */
function machineOf(model: Model, container: string, tf: TileFloor, y: Yard): string | null {
  if (!y.inner) return y.source;
  const votes = new Map<string, number>();
  const rel = new Map(model.map.relations.map((r) => [r.id, r]));
  for (const p of y.platforms) for (const j of p.jobs) {
    const r = rel.get(j.relation);
    if (!r) continue;
    const door = model.doorId(model.anchorFor(container, r.from));
    if (tf.boxes.has(door)) votes.set(door, (votes.get(door) ?? 0) + 1);
  }
  return [...votes.entries()].sort(([p, a], [q, c]) => c - a || byStr(p, q))[0]?.[0] ?? null;
}

/** The door of the in column `y`'s jobs come in by, when `y` is an inner yard (a free-standing yard: its scheduler is off
 *  the floor); undefined otherwise. */
function inColumn(tf: TileFloor, y: Yard, machine: string | null): Rect | undefined {
  const m = machine ? tf.boxes.get(machine) : undefined;
  return y.inner && m?.region === "in" ? m : undefined;
}

/** The rows the in column keeps free below the door of the floor's free-standing yard (one free row, then a row per
 *  platform); undefined on a floor with none. The layout is run again with them (plan.ts `layFloor`). */
export function inYardRows(model: Model, container: string, tf: TileFloor, bundles: Bundle[]): { door: string; rows: number } | undefined {
  for (const y of batch(model, container, tf, bundles).yards) {
    const door = machineOf(model, container, tf, y);
    if (inColumn(tf, y, door)) return { door: door!, rows: 1 + Math.max(1, y.platforms.length) };
  }
  return undefined;
}

type Checks = { clear: (r: Rect, named?: boolean) => boolean; alone: (r: Rect, own: number) => boolean; open: (x: number, y: number) => boolean; ids: string[] };

/** The yard's rect, side, way out and platform tiles: against the machine side facing most destinations (an e or w side
 *  on a tie), level on every side (its platforms rows; against an n or s side its rails leave the row ends nearer the
 *  destinations, else the other ends), as near that side's middle as leaves the middle tile to the
 *  machine's other lines and leans toward the destinations; the first side where the yard, its exits and the tile
 *  past each exit are free, no other machine touches it and it keeps off the zones' label rows -- then, failing that
 *  everywhere, the first where the yard and its exits are free (a tall yard beside a door may cross its column's label
 *  row: the name finds its own clear room). An inner yard at a door of the in column stands free in that column, below
 *  that door; an inner yard with no door stands at the floor's left edge. With a `ladder` the yard is a tile wider (its
 *  throat), its rows in the ladder's order, and its rails leave only by the ladder's exit rows. */
function placeYard(tf: TileFloor, y: Yard, machine: string | null, c: Checks, ladder?: { dest: string; exit: string }[]): YardBox | undefined {
  const dests = y.platforms.map((p) => tf.boxes.get(p.dest)!);
  const n = dests.length;
  const door = inColumn(tf, y, machine);
  const own = machine ? c.ids.indexOf(machine) : -1;
  const W = DEPTH + (ladder ? 1 : 0);
  // where the rails leave a rect: past each platform, or on a ladder past the throat at each exit row
  const exitRows = ladder ? ladder.map((q, i) => i).filter((i) => ladder[i].exit === ladder[i].dest) : [];
  const leaving = (r: Rect, out: Dir) => (ladder ? exitsOf(out, exitRows.map((i) => ({ x: out === "e" ? r.x + r.w - 1 : r.x, y: r.y + i }))) : exitsOf(out, platformTiles(r, out, n)));
  const fits = (r: Rect, out: Dir, strict: boolean) => {
    if (!c.clear(r, strict)) return false;
    if (strict && !c.alone(r, own)) return false;
    for (const e of leaving(r, out)) {
      if (!c.open(e.x, e.y)) return false;
      if (strict && !c.open(e.x + STEP[e.d][0], e.y + STEP[e.d][1])) return false;
    }
    return true;
  };
  const make = (r: Rect, side: Dir, out: Dir): YardBox => {
    const yb: YardBox = { source: y.source, machine, ...r, side, out, platforms: [], sign: null };
    // platform rows in the order of their destinations down the yard, so tracks leaving it do not cross there
    const tiles = platformTiles(r, out, n, ladder ? 1 : 0);
    if (ladder) {   // the ladder's rows: planned from a first routing (yardLadders)
      yb.platforms = ladder.map((q, i) => ({ dest: q.dest, ...tiles[i] }));
      yb.ladder = ladder.map((q) => ladder.findIndex((o) => o.dest === q.exit));
      return yb;
    }
    const order = y.platforms.map((p, i) => ({ p, at: centre(dests[i]).y })).sort((a, q) => a.at - q.at || byStr(a.p.dest, q.p.dest));
    yb.platforms = order.map(({ p }, i) => ({ dest: p.dest, ...tiles[i] }));
    return yb;
  };
  if (door) {
    // free-standing at its door: in the in column, one free row below that door (the layout keeps those rows,
    // `inYardRows`), leftmost first, its rails leaving across the column's free width
    const w = W, h = Math.max(1, n);
    for (let x = door.x; x + w <= door.x + door.w; x++) {
      const r = { x, y: door.y + door.h + 1, w, h };
      // its rails run RUN tiles straight from each exit: the tile they turn on is free too
      if (fits(r, "e", true) && leaving(r, "e").every((e) => c.open(e.x + RUN, e.y))) return { ...make(r, "e", "e"), free: true };
    }
  }
  if (!machine) {
    // an inner yard with no door on the floor (real inner yards have their door as `machine` and stand below it, above):
    // at the floor's left edge, top-first
    const w = W, h = Math.max(1, n);
    for (const strict of [true, false]) for (let yy = 0; yy + h <= tf.rows; yy++) for (const x of [3, 2, 1]) {
      const r = { x, y: yy, w, h };
      if (fits(r, "e", strict)) return make(r, "e", "e");
    }
    return undefined;
  }
  const m = tf.boxes.get(machine)!;
  const target = dests.length ? { x: dests.reduce((t, d) => t + centre(d).x, 0) / n, y: dests.reduce((t, d) => t + centre(d).y, 0) / n } : centre(m);
  const sides = sideOrder(m, dests);
  for (const strict of [true, false]) for (const side of sides) {
    const upright = side === "e" || side === "w";
    const w = W, h = Math.max(1, n);   // level on every side: 4 wide (5 with a throat), a row per platform
    const len = upright ? h : w, L = upright ? m.h : m.w, ax = upright ? "y" : "x";
    const offs: number[] = [];
    for (let o = -(len - 1); o <= L - 1; o++) offs.push(o);
    const mid = (L - 1) / 2, lean = target[ax] - (ax === "x" ? m.x : m.y);
    const rank = (o: number) => [
      len <= L && (o < 0 || o + len > L) ? 1 : 0,                                   // within the side when it can be
      !n ? Math.min(Math.abs(o), Math.abs(L - len - o)) : 0,                         // a yard with no platforms: in a corner
      n && len < L && o <= mid && mid < o + len ? 1 : 0,                             // leave the middle tile to other lines
      Math.abs(o + len / 2 - lean),                                                  // lean toward the destinations
      o,
    ];
    offs.sort((p, q) => { const a = rank(p), bb = rank(q); for (let i = 0; i < a.length; i++) if (a[i] !== bb[i]) return a[i] - bb[i]; return 0; });
    for (const o of offs) {
      const r = rectOn(m, side, o, w, h);
      // against an e or w side the rails leave away from the machine; against an n or s side, off the row ends nearer the
      // destinations first (on a tie, e)
      const outs: Dir[] = upright ? [side] : target.x >= r.x + w / 2 ? ["e", "w"] : ["w", "e"];
      for (const out of outs) if (fits(r, out, strict)) return make(r, side, out);
    }
  }
  return undefined;
}

/** A machine's sides in the order a yard tries them: by how many destinations lie wholly past each (the centre's
 *  direction when none does), an e or w side first on a tie, then n e s w. A yard with no destinations tries e, w, n, s. */
function sideOrder(m: Rect, dests: Rect[]): Dir[] {
  if (!dests.length) return ["e", "w", "n", "s"];
  const count: Record<Dir, number> = { n: 0, e: 0, s: 0, w: 0 };
  for (const d of dests) {
    const past: Dir[] = [];
    if (d.y + d.h <= m.y) past.push("n");
    if (d.x >= m.x + m.w) past.push("e");
    if (d.y >= m.y + m.h) past.push("s");
    if (d.x + d.w <= m.x) past.push("w");
    if (!past.length) {
      const a = centre(m), b = centre(d), dx = b.x - a.x, dy = b.y - a.y;
      past.push(Math.abs(dx) >= Math.abs(dy) ? (dx >= 0 ? "e" : "w") : dy >= 0 ? "s" : "n");
    }
    for (const s of past) count[s]++;
  }
  const flat = (s: Dir) => (s === "e" || s === "w" ? 0 : 1);
  return (["n", "e", "s", "w"] as Dir[]).sort((p, q) => count[q] - count[p] || flat(p) - flat(q));
}

/** The w×h rect flush against `side` of `m`, starting `off` tiles along it. */
function rectOn(m: Rect, side: Dir, off: number, w: number, h: number): Rect {
  switch (side) {
    case "n": return { x: m.x + off, y: m.y - h, w, h };
    case "s": return { x: m.x + off, y: m.y + m.h, w, h };
    case "w": return { x: m.x - w, y: m.y + off, w, h };
    case "e": return { x: m.x + m.w, y: m.y + off, w, h };
  }
}

/** A yard rect's n platform tiles, top row first: the tile at the `out` end (e or w) of each row, `inset` tiles in from
 *  it (1 past a ladder's throat). */
function platformTiles(r: Rect, out: Dir, n: number, inset = 0): { x: number; y: number }[] {
  return Array.from({ length: n }, (_, i) => ({ x: out === "e" ? r.x + r.w - 1 - inset : r.x + inset, y: r.y + i }));
}

const exitsOf = (side: Dir, tiles: { x: number; y: number }[]): Exit[] =>
  tiles.map((p) => ({ x: p.x + STEP[side][0], y: p.y + STEP[side][1], d: side }));

/** Where the yard's rails leave it, travelling `out`, top row first: the tile just past each platform; on a ladder, the
 *  tile just past the throat at each exit row. */
export function exits(y: YardBox): Exit[] {
  if (!y.ladder) return exitsOf(y.out, y.platforms);
  return exitsOf(y.out, y.platforms.filter((_, i) => y.ladder![i] === i).map((p) => ({ x: p.x + STEP[y.out][0], y: p.y })));
}

/** The exit platform i's rail leaves by (one of `exits(y)`, the same object). */
export function exitOf(y: YardBox, i: number, all = exits(y)): Exit {
  const p = y.platforms[y.ladder ? y.ladder[i] : i], k = y.ladder ? 2 : 1;
  return all.find((e) => e.x === p.x + STEP[y.out][0] * k && e.y === p.y)!;
}

/** Each yard whose first routing sends more than one platform's rail out by one exit (a rail riding a trunk starts on
 *  the trunk's), with its ladder: the platforms leaving by one exit lie together (groups in the order of their exits
 *  down the yard, each in its rows' order), that exit at an end of the group, so the throat runs one way to it and no
 *  rail crosses another inside the yard: the end it already was at; from a middle row, the `middle` end (planFloor
 *  tries both). Undefined when no yard needs one. */
export function yardLadders(tf: TileFloor, routes: TileRoute[], middle: "top" | "bottom" = "top"): Ladders | undefined {
  const r = tf.rails;
  if (!r) return undefined;
  const byKey = new Map(routes.map((q) => [q.key, q]));
  const out: Ladders = new Map();
  for (const y of r.yards) {
    if (y.ladder || y.platforms.length < 2) continue;
    const [sx, sy] = STEP[y.out];
    const route = (i: number) => {
      const s = r.stations.find((q) => !q.door && q.source === y.source && q.dest === y.platforms[i].dest);
      const q = s && byKey.get(s.track);
      return q && !q.failed && q.pieces.length ? q : undefined;
    };
    const groups = new Map<number, number[]>();   // exit row (a platform's index) -> the platforms leaving by it
    y.platforms.forEach((_, i) => {
      const f = route(i)?.pieces[0];
      const j = f ? y.platforms.findIndex((p) => p.x === f.x - sx && p.y === f.y - sy) : -1;
      const k = j >= 0 ? j : i;
      groups.set(k, [...(groups.get(k) ?? []), i]);
    });
    if ([...groups.values()].every((g) => g.length < 2)) continue;
    const rows: { dest: string; exit: string }[] = [];
    for (const [j, g] of [...groups.entries()].sort(([a], [b]) => a - b)) {
      g.sort((a, b) => a - b);
      // an exit at an end of its group stays there; from a middle row it goes to the `middle` end
      const at = g.indexOf(j), top = at === 0 || (at !== g.length - 1 && middle === "top");
      const exit = y.platforms[top ? g[0] : g[g.length - 1]].dest;
      for (const i of g) rows.push({ dest: y.platforms[i].dest, exit });
    }
    out.set(y.source, rows);
  }
  return out.size ? out : undefined;
}

/** The two tiles just past a station's ends, along its destination's wall, each with the way a rail runs into it. */
export function stationEnds(s: Rect & { side: Dir }): Exit[] {
  if (s.side === "n" || s.side === "s") return [{ x: s.x - 1, y: s.y, d: "e" }, { x: s.x + s.w, y: s.y, d: "w" }];
  return [{ x: s.x, y: s.y - 1, d: "s" }, { x: s.x, y: s.y + s.h, d: "n" }];
}

/** Candidate sign tiles beside a yard. Against an e or w side: over its top row, then under its bottom row, nearest the
 *  machine's far side first but never against the machine. Against an n or s side: past its far row (away from the
 *  machine), from the end its rails do not leave by, then past that end, far row first. */
function signSpot(y: YardBox): { x: number; y: number }[] {
  const spots: { x: number; y: number }[] = [];
  if (y.side === "e" || y.side === "w") {
    const xs = Array.from({ length: y.w }, (_, i) => (y.side === "e" ? y.x + 1 + i : y.x + y.w - 2 - i)).filter((x) => x >= y.x && x < y.x + y.w);
    for (const yy of [y.y - 1, y.y + y.h]) for (const x of xs) spots.push({ x, y: yy });
  } else {
    const far = y.side === "n" ? y.y - 1 : y.y + y.h;
    const xs = Array.from({ length: y.w }, (_, i) => (y.out === "e" ? y.x + i : y.x + y.w - 1 - i));
    for (const x of xs) spots.push({ x, y: far });
    const end = y.out === "e" ? y.x - 1 : y.x + y.w;
    for (let i = 0; i < y.h; i++) spots.push({ x: end, y: y.side === "n" ? y.y + i : y.y + y.h - 1 - i });
  }
  return spots;
}

/** A station strip on the side of `d` facing the yard exit `from`: as long as the side allows up to 3 with a tile of
 *  wall beyond each end (so both ends run along the wall), as near the side's middle as free, its entry (the end nearer
 *  `from`) free. A side that holds a full strip of 3 goes before one that holds less (a one-tile station reads as no
 *  siding), then a side fewer of the machine's other lines head past (`busy`), then the nearer one. Only the entry is
 *  kept for the rail: the far end's tile stays free for the machine's other lines. */
function placeStation(d: Rect, from: Exit, clear: (r: Rect) => boolean, free: (e: Exit) => boolean, busy: Record<Dir, number>): Omit<StationBox, "dest" | "source" | "track"> | undefined {
  const a = centre(d), b = { x: from.x + 0.5, y: from.y + 0.5 }, dx = b.x - a.x, dy = b.y - a.y;
  const v: Dir = dy >= 0 ? "s" : "n", h: Dir = dx >= 0 ? "e" : "w";
  const opp: Record<Dir, Dir> = { n: "s", s: "n", e: "w", w: "e" };
  const [p, q] = Math.abs(dy) >= Math.abs(dx) ? [v, h] : [h, v];
  const facing = [p, q, opp[q], opp[p]];
  const order = facing.slice().sort((s1, s2) => busy[s1] - busy[s2] || facing.indexOf(s1) - facing.indexOf(s2));
  for (const least of [STATION, 1]) for (const side of order) {
    const L = side === "n" || side === "s" ? d.w : d.h;
    for (let len = Math.min(STATION, Math.max(1, L - 2)); len >= least; len--) {
      const mid = Math.floor((L - len) / 2), offs = [mid];
      for (let k = 1; k <= L; k++) offs.push(mid - k, mid + k);
      for (const o of offs) {
        if (o < 1 || o + len > L - 1) continue;
        const r = side === "n" || side === "s" ? rectOn(d, side, o, len, 1) : rectOn(d, side, o, 1, len);
        if (!clear(r)) continue;
        const dist = (e: Exit) => Math.abs(e.x - from.x) + Math.abs(e.y - from.y);
        const entry = stationEnds({ ...r, side }).sort((e, f) => dist(e) - dist(f))[0];
        if (free(entry)) return { ...r, side, entry };
      }
    }
  }
  return undefined;
}

/** Every floor tile the rails hold: yards, stations and sign tiles beside yards (the router's obstacles). */
export function railRects(tf: TileFloor): Rect[] {
  const r = tf.rails;
  if (!r) return [];
  const inside = (y: YardBox, s: { x: number; y: number }) => s.x >= y.x && s.x < y.x + y.w && s.y >= y.y && s.y < y.y + y.h;
  return [
    ...r.yards.map((y) => ({ x: y.x, y: y.y, w: y.w, h: y.h })),
    ...r.yards.flatMap((y) => (y.sign && !inside(y, y.sign) ? [{ x: y.sign.x, y: y.sign.y, w: 1, h: 1 }] : [])),
    ...r.stations.map((s) => ({ x: s.x, y: s.y, w: s.w, h: s.h })),
  ];
}

/** Every station's rail ends, keyed by its track (a batch bundle's key or a shell's): from its yard to its station.
 *  Empty on a floor with no rails. */
export function railEnds(tf: TileFloor): Map<string, RailEnd> {
  const out = new Map<string, RailEnd>();
  const r = tf.rails;
  if (!r) return out;
  for (const y of r.yards) {
    const all = exits(y);
    y.platforms.forEach((p, i) => {
      const s = r.stations.find((q) => q.source === y.source && q.dest === p.dest);
      if (s) out.set(s.track, { yard: y, own: exitOf(y, i, all), yardExits: all, station: s, entry: s.entry, dest: p.dest });
    });
  }
  for (const s of r.stations) if (s.door) out.set(s.track, { yardExits: [], station: s, entry: s.entry, dest: s.dest, door: s.door });
  return out;
}
