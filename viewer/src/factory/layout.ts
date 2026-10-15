// src/factory/layout.ts
// Grid cells from the map's layout to tile boxes, lanes and zones (spec §2–3). Viewer-side: no scanner change.
import type { Door, Model } from "../model/model";
import { doorAnchor, SITE } from "../model/model";
import type { Cell, Floor } from "../model/types";
import type { FloorGeometry, Machine } from "../route/types";
import type { Landing, WebhookDock } from "./pads";
import type { Rails } from "./yards";
import { FOOT, LANE_H, T, footprintFor, type Box, type Footprint, type Rect } from "./tiles";
import { chestSize } from "./fit";
import { floorPrefix, shownName } from "../floor/names";
import { IN_PROCESS } from "./messaging";

/** Tiles a zone's label needs: its upper-case name at 9.5 px (a generous 7.5 px a letter) plus a margin. */
export const labelTiles = (name: string): number => Math.ceil((name.length * 7.5 + 12) / T);

export interface Zone extends Rect { name: string; airfield: boolean }
/** A database (or busy item) lane: LANE_H tiles tall from row `y`, from `x0` (its box's right edge) to `x1`. */
export interface TileLane { id: string; label: string; x0: number; x1: number; y: number }
/** The work grid's corridors: `cols[i]` runs down between machine columns i and i+1, `rows[j]` across between rows
 *  j and j+1 (a corridor narrower than one tile, where grids of different pitch meet, has w or h of 0). */
export interface Aisles { cols: Rect[]; rows: Rect[] }
/** The one tile a queue hub keeps beside it for its waiting stack. `item` is the hub's box, `topic` the topic node. */
export interface Stack { item: string; topic: string; x: number; y: number }
export interface TileFloor {
  boxes: Map<string, Box>; lanes: TileLane[]; zones: Zone[];
  cols: number; rows: number; strategy: Floor["strategy"]; site: boolean;
  aisles?: Aisles;
  /** Waiting-stack tiles of the queue hubs; absent on a floor with none. */
  stacks?: Stack[];
  /** Pads (inside their machines) and receiving docks (reserved), placed by planFloor before routing (see pads.ts);
   *  absent on a floor with no hub. */
  landing?: Landing;
  /** Rail yards, stations and sign tiles (reserved), placed by planFloor before routing (see yards.ts); absent on a
   *  floor with no yard. */
  rails?: Rails;
  /** Inbound webhook receiving docks (reserved), placed by planFloor after the push docks and before the rails (see
   *  pads.ts `webhookDocks`); absent off the site and on a site with none. */
  webhooks?: WebhookDock[];
  /** Layout debug notes: what the layout wanted and could not do (a single-owner cache with no room for its chest). */
  notes?: string[];
  /** The one-tile gap between each cache chest and its machine, the tiles its tap pair crosses (layoutOnce): no dock
   *  stands on them. Absent when the floor has no chest. */
  chestGaps?: Rect[];
}
/** `gap`: extra tiles in every corridor, aisle and lane spacing. `colGaps[i]` / `rowGaps[j]`: extra tiles in the
 *  work grid's corridor i (between machine columns i and i+1) / row corridor j only (crowded corridors widen). */
export interface LayoutOpts { gap?: number; colGaps?: number[]; rowGaps?: number[];
  /** Single-owner caches that keep their lane: no room beside their machine for a chest (layoutTiles grows it until
   *  every such cache is a chest or listed here). */
  laned?: ReadonlySet<string>;
  /** Rows the in column keeps free below `door`, for a free-standing rail yard (yards.ts `inYardRows`). */
  inYard?: { door: string; rows: number } }

const M = 2;      // margin round the floor
const GX0 = 6;    // tiles between machines in a row: room for lines to run between them
const GY0 = 4;    // and between rows
const PAD = 1;    // a zone's edge stands one tile off its machines
const DOOR_GAP = 3;  // tiles between doors in a column, at the least
const LABEL = 1;  // and keeps one more row at its bottom for its name

export function layoutTiles(model: Model, container: string, doors: Door[] = [], opts: LayoutOpts = {}): TileFloor {
  return settleChests(soleCaches(model, container).keys(), (laned) => layoutOnce(model, container, doors, laned.size ? { ...opts, laned } : opts), opts.laned);
}

/** Lays a floor out (`pass`) until every single-owner cache (`sole`) is either a chest or in the `laned` set: a cache
 *  with no room for its chest keeps its lane, and the floor is laid out again with that lane. A new lane may take
 *  another chest's room, so this repeats until the set stops changing; it only grows, so it ends within one pass per
 *  cache. Every cache then has a chest or a lane, and every note names a real lane. */
export function settleChests(sole: Iterable<string>, pass: (laned: ReadonlySet<string>) => TileFloor, start: ReadonlySet<string> = new Set()): TileFloor {
  const caches = [...sole];
  let laned = new Set(start), tf = pass(laned);
  for (let i = 0; i < caches.length; i++) {
    const lost = caches.filter((id) => !laned.has(id) && tf.boxes.get(id)?.foot !== "chest");
    if (!lost.length) break;
    laned = new Set([...laned, ...lost]);
    tf = pass(laned);
  }
  return tf;
}

/** Caches only one machine uses on the site floor, each with that machine: store id → machine id. "One machine" is
 *  counted by lifted bundle ends, so a service's several methods are one user. Inside a factory, none. */
function soleCaches(model: Model, container: string): Map<string, string> {
  const out = new Map<string, string>();
  if (container !== SITE) return out;
  const items = model.floor(SITE)?.items ?? {};
  const users = new Map<string, Set<string>>();
  for (const b of model.bundles(SITE).bundles) for (const [s, o] of [[b.a, b.b], [b.b, b.a]]) {
    const n = model.nodes.get(s);
    if (n?.kind !== "datastore" || n.store !== "cache" || !(s in items)) continue;
    (users.get(s) ?? users.set(s, new Set()).get(s)!).add(o);
  }
  for (const [s, us] of users) if (us.size === 1) out.set(s, [...us][0]);
  return out;
}

function layoutOnce(model: Model, container: string, doors: Door[], opts: LayoutOpts): TileFloor {
  const gap = opts.gap ?? 0;   // extra tiles in every corridor, aisle and lane spacing (floors that cannot route widen)
  const GX = GX0 + gap, GY = GY0 + gap;
  const floor = model.floor(container);
  if (!floor) throw new Error(`no floor for ${container}`);
  const site = container === SITE;
  const boxes = new Map<string, Box>();
  const zones: Zone[] = [];
  const lanes: TileLane[] = [];
  const kindOf = (id: string) => model.kindOf(id);
  const pairs = model.implementLinks(container);   // trait → implementation, lifted to this floor's items

  const put = (id: string, kind: string, region: string, x: number, y: number, foot: Footprint = footprintFor(kind, site), size = FOOT[foot]): Box => {
    const [w, h] = size;
    const b: Box = { id, kind, foot, region, x, y, w, h };
    boxes.set(id, b);
    return b;
  };
  const cells = (...regions: string[]): [string, Cell][] =>
    Object.entries(floor.items).filter(([, c]) => regions.includes(c.region)).sort(([, p], [, q]) => p.row - q.row || p.col - q.col);
  /** The scanner's cells on a uniform grid from (x0, y0), gaps left by items placed elsewhere closed up.
   *  `wrap`: a grid taller than 0.8 x its width (pitch counted) is re-wrapped to a screen shape. */
  const grid = (list: [string, Cell][], region: string, x0: number, y0: number, wrap = false): Box[] => {
    if (!list.length) return [];
    const sizes = list.map(([id]) => FOOT[footprintFor(kindOf(id), site)]);
    const pw = Math.max(...sizes.map((s) => s[0])) + GX, ph = Math.max(...sizes.map((s) => s[1])) + GY;
    const cols = [...new Set(list.map(([, c]) => c.col))].sort((a, b) => a - b);
    const rows = [...new Set(list.map(([, c]) => c.row))].sort((a, b) => a - b);
    if (wrap && rows.length * ph > 0.8 * cols.length * pw) {
      const n = list.length;
      // reading order: the scanner's (col, row), filled column by column, top to bottom
      const ordered = [...list].sort(([, p], [, q]) => p.col - q.col || p.row - q.row);
      let best = 1, bestD = Infinity;
      for (let c = 1; c <= n; c++) {
        const d = Math.abs((c * pw) / (Math.ceil(n / c) * ph) - 1.6);
        if (d < bestD - 1e-9) { best = c; bestD = d; }
      }
      const per = Math.ceil(n / best);
      // a column is a run: the slot after an interface is the one below it
      const runs = Array.from({ length: Math.ceil(n / per) }, (_, c) => Math.min(per, n - c * per));
      const ids = besideOrder(ordered.map(([id]) => id), runs) ?? ordered.map(([id]) => id);
      return ids.map((id, i) => put(id, kindOf(id), region, x0 + Math.floor(i / per) * pw, y0 + (i % per) * ph));
    }
    // reading order as the re-wrap's: the scanner's (col, row), column by column, top to bottom
    const ordered = [...list].sort(([, p], [, q]) => p.col - q.col || p.row - q.row);
    const slots = ordered.map(([, c]) => [cols.indexOf(c.col), rows.indexOf(c.row)] as const);
    // a run is a column's slots one under the other (a scanner gap ends it): the slot after an interface is the one below
    const runs: number[] = [];
    slots.forEach(([cx, ry], i) => { if (i && cx === slots[i - 1][0] && ry === slots[i - 1][1] + 1) runs[runs.length - 1]++; else runs.push(1); });
    const ids = besideOrder(ordered.map(([id]) => id), runs);
    if (ids) return ids.map((id, i) => put(id, kindOf(id), region, x0 + slots[i][0] * pw, y0 + slots[i][1] * ph));
    return list.map(([id, c]) => put(id, kindOf(id), region, x0 + cols.indexOf(c.col) * pw, y0 + rows.indexOf(c.row) * ph));
  };
  /** Implementations beside their interfaces (owner, 2026-10-06), within one region's grid. `ids` in reading order;
   *  `runs`: the grid's slots in that order cut into runs of neighbours (consecutive slots of a run touch). A unit is an
   *  interface followed by its implementations (each beside the first interface it implements, by id; an
   *  implementation that is itself implemented brings its own after it). A unit takes the reading place of its earliest
   *  item (an interface read after its implementation moves up to it: fewer lines cross than when the implementation
   *  always moves). Each run takes the first unit that still fits in it, so a pair is never cut by a run's end while a
   *  smaller unit fills the gap (a unit no run can hold is cut). Undefined when no pair lies inside `ids`: the grid as
   *  before. */
  const besideOrder = (ids: string[], runs: number[]): string[] | undefined => {
    const here = new Set(ids);
    const anchor = new Map<string, string>();
    for (const l of pairs) if (here.has(l.trait) && here.has(l.impl) && (!anchor.has(l.impl) || l.trait < anchor.get(l.impl)!)) anchor.set(l.impl, l.trait);
    if (!anchor.size) return undefined;
    const done = new Set<string>();
    const emit = (id: string, unit: string[]) => {
      if (done.has(id)) return;
      done.add(id);
      unit.push(id);
      for (const i of ids) if (anchor.get(i) === id) emit(i, unit);
    };
    const units: string[][] = [];
    for (const id of ids) if (!anchor.has(id) && !done.has(id)) { const u: string[] = []; emit(id, u); units.push(u); }
    for (const id of ids) if (!done.has(id)) { const u: string[] = []; emit(id, u); units.push(u); }   // a loop of implements
    const at = new Map(ids.map((id, i) => [id, i])), first = (u: string[]) => Math.min(...u.map((id) => at.get(id)!));
    units.sort((p, q) => first(p) - first(q));
    const out: string[] = [];
    for (const len of runs) {
      let room = len;
      while (room > 0 && units.length) {
        const k = Math.max(0, units.findIndex((u) => u.length <= room));
        const u = units.splice(k, 1)[0];
        out.push(...u.slice(0, room));
        if (u.length > room) units.unshift(u.slice(room));
        room -= Math.min(room, u.length);
      }
    }
    return out;
  };
  /** The work grid: its corridors get their own extra width. Machines right of / below corridor i move over by the
   *  sum of the extras before them, so no two machines come closer. */
  let workList: Box[] = [];
  const work = (list: Box[]) => {
    workList = list;
    const xs = [...new Set(list.map((b) => b.x))].sort((p, q) => p - q);
    const ys = [...new Set(list.map((b) => b.y))].sort((p, q) => p - q);
    const sum = (g: number[] | undefined, n: number) => { let t = 0; for (let i = 0; i < n; i++) t += g?.[i] ?? 0; return t; };
    for (const b of list) { b.x += sum(opts.colGaps, xs.indexOf(b.x)); b.y += sum(opts.rowGaps, ys.indexOf(b.y)); }
  };
  /** The work grid's corridors where its machines finally stand (after any spreading down the room). Approximate on an
   *  inside floor with several region grids: their pitches differ, so a "column" is any distinct left edge and a
   *  corridor between two of them may be narrower than the real aisle (or 0 where grids of different pitch meet). */
  const measureAisles = (list: Box[]): Aisles => {
    if (!list.length) return { cols: [], rows: [] };
    const xs = [...new Set(list.map((b) => b.x))].sort((p, q) => p - q);
    const ys = [...new Set(list.map((b) => b.y))].sort((p, q) => p - q);
    const x0 = xs[0], y0 = ys[0], x1 = right(list, 0), y1 = bottom(list, 0);
    const reach = (pick: (b: Box) => boolean, far: (b: Box) => number) => Math.max(...list.filter(pick).map(far));
    return {
      cols: xs.slice(1).map((x, i) => { const l = reach((b) => b.x === xs[i], (b) => b.x + b.w); return { x: l, y: y0, w: Math.max(0, x - l), h: y1 - y0 }; }),
      rows: ys.slice(1).map((y, j) => { const t = reach((b) => b.y === ys[j], (b) => b.y + b.h); return { x: x0, y: t, w: x1 - x0, h: Math.max(0, y - t) }; }),
    };
  };
  const isQueue = (topic: string) => { const n = model.nodes.get(topic); return (n?.kind === "topic" || n?.kind === "in-process-queue") && n.delivery === "queue"; };
  /** A queue hub's waiting stack: the tile right of its bottom row (as the mock draws it). */
  const stackTile = (b: Rect): Rect => ({ x: b.x + b.w, y: b.y + b.h - 1, w: 1, h: 1 });
  /** Hub order in an airfield: the scanner's, but each dead-letter hub moved to the slot right after its source. */
  const dlqNext = (ids: string[]): string[] => {
    const here = new Set(ids);
    const srcOf = (id: string) => { const s = model.nodes.get(id)?.dead_letter_of; return s && s !== id && here.has(s) ? s : undefined; };
    const out: string[] = [], done = new Set<string>();
    const emit = (id: string) => {
      if (done.has(id)) return;
      done.add(id);
      out.push(id);
      for (const d of ids) if (srcOf(d) === id) emit(d);
    };
    for (const id of ids) if (!srcOf(id)) emit(id);
    for (const id of ids) emit(id);   // a loop of dead letters: the scanner's order
    return out;
  };
  const right = (list: Rect[], fallback: number) => (list.length ? Math.max(...list.map((b) => b.x + b.w)) : fallback);
  const bottom = (list: Rect[], fallback: number) => (list.length ? Math.max(...list.map((b) => b.y + b.h)) : fallback);
  /** A zone round `list`, one tile off its machines, with a label row at the bottom; undefined when empty. */
  const zone = (name: string, list: Rect[], airfield = false): Zone | undefined => {
    if (!list.length) return undefined;
    const x = Math.min(...list.map((b) => b.x)) - PAD, y = Math.min(...list.map((b) => b.y)) - PAD;
    const z: Zone = { name, x, y, w: Math.max(right(list, 0) + PAD - x, labelTiles(name)), h: bottom(list, 0) + PAD + LABEL - y, airfield };
    zones.push(z);
    return z;
  };
  /** First content row below a zone (a two-tile aisle between zones). */
  const next = (z: Zone | undefined, y: number) => (z ? z.y + z.h + 2 + gap + PAD : y);
  const laneBand = (l: TileLane): Rect => ({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H });
  /** One lane per database or busy item, its box at the lane's left end; returns the next free row. */
  const laneRows = (list: { id: string; box: string; kind: string }[], x: number, y: number, x1: number): number => {
    for (const l of list) {
      const b = put(l.box, l.kind, l.kind === "datastore" ? "bus" : "lane", x, y, l.kind === "datastore" ? "warehouse" : undefined);
      lanes.push({ id: l.id, label: model.label(l.id), x0: x + b.w, x1: Math.max(x1, x + b.w + 6), y: y + Math.floor((b.h - LANE_H) / 2) });
      y += Math.max(b.h, LANE_H) + 2 + gap;
    }
    return y;
  };

  const chests = new Map([...soleCaches(model, container)].filter(([id]) => !opts.laned?.has(id)));   // store → its one machine
  // a chest shows its name as the floor list does (the floor's shared prefix off), whole, or the cache keeps its lane
  const chestName = (id: string) => shownName(model, id, floorPrefix(model, Object.keys(floor.items)));
  const why = (id: string) => (chestSize(chestName(id)) ? `no room beside ${soleCaches(model, container).get(id)}` : "its name does not fit a chest");
  const gaps: Rect[] = [];
  const notes = [...opts.laned ?? []].sort().map((id) => `chest: ${id} stays a lane: ${why(id)}`);
  if (site) {
    const stores = cells("bus").filter(([id]) => kindOf(id) === "datastore" && !chests.has(id));
    const busy = cells("lane");
    const x0 = M + (stores.length || busy.length ? FOOT.warehouse[0] + GX : 0) + PAD;   // the yard column: lane-end boxes on the left
    let y = M + PAD;
    const shelf = grid(cells("shelf"), "shelf", x0, y);
    const hubs = grid(cells("hubs"), "hubs", x0, shelf.length ? bottom(shelf, y) + GY : y);
    y = next(zone("library shelf", [...shelf, ...hubs]), y);

    const line = cells("line", "grid");
    const works = grid(line.filter(([id]) => kindOf(id) !== "external"), "line", x0, y, true);
    work(works);
    const ox = right(works, x0) + GX + 2 * PAD;
    // the externals wrap into as many columns as keep the zone no taller than the production line, in order
    const [dw, dh] = FOOT.dock;
    const perCol = Math.max(1, Math.floor((bottom(works, y) - y + GY) / (dh + GY)));
    const outside = line.filter(([id]) => kindOf(id) === "external")
      .map(([id], i) => put(id, "external", "outside", ox + Math.floor(i / perCol) * (dw + GX), y + (i % perCol) * (dh + GY)));
    y = Math.max(next(zone("production line", works), y), next(zone("outside world", outside), y));

    // message brokers: an airfield each, its topics as hubs in a row
    const topics = cells("bus").filter(([id]) => kindOf(id) === "topic");
    const brokers = [...new Set(topics.map(([id]) => id.split(":")[1]))].sort();
    let ax = x0;
    const ay = y;
    let yAir = y;
    for (const br of brokers) {
      const own = dlqNext(topics.filter(([id]) => id.split(":")[1] === br).map(([id]) => id))
        .map((id, i) => put(id, "topic", "airfield", ax + i * (FOOT.hub[0] + GX), ay));
      const z = zone(br, [...own, ...own.flatMap((b) => (isQueue(b.id) ? [stackTile(b)] : []))], true)!;
      ax = z.x + z.w + 2 + gap + PAD;
      yAir = Math.max(yAir, next(z, y));
    }
    // read-only: with airfields, the same band, right of the last one (its taps drop onto the lanes below);
    // without, below storage as before: a band of its own above the lanes would only lengthen every tap
    if (brokers.length) y = Math.max(yAir, next(zone("read-only", grid(cells("bay"), "bay", ax, ay)), y));

    // storage: lanes run from their warehouse (far left) under every machine above
    const x1 = right([...boxes.values()], x0 + 20) + PAD;
    const sy = y;
    y = laneRows([...stores.map(([id]) => ({ id, box: id, kind: "datastore" })), ...busy.map(([id]) => ({ id, box: id, kind: kindOf(id) }))], M, y, x1);
    const rest = grid(cells("bus").filter(([id]) => kindOf(id) !== "topic" && kindOf(id) !== "datastore"), "bus", x0, y);
    const stored = [...boxes.values()].filter((b) => b.y >= sy && (b.region === "bus" || b.region === "lane"));
    y = next(zone("storage", [...stored, ...rest, ...lanes.map(laneBand)]), y);
    if (!brokers.length) zone("read-only", grid(cells("bay"), "bay", x0, y));

    // the storage rest-grid (and a bay below it) was placed after x1 was fixed: lanes still run under every machine
    const edge = right([...boxes.values()], 0) + PAD;
    for (const l of lanes) l.x1 = Math.max(l.x1, edge);

    // single-owner caches: a chest just big enough for its whole name, one tile off its machine, on the first side with
    // room (below, right, left, above)
    for (const [id, owner] of [...chests].sort(([p], [q]) => (p < q ? -1 : p > q ? 1 : 0))) {
      const size = chestSize(chestName(id));
      const spot = size && chestSpot(boxes.get(owner), size, [...boxes.values()], lanes.map(laneBand), zones);
      if (spot) { put(id, "datastore", "chest", spot.x, spot.y, "chest", size!); gaps.push(chestGap(boxes.get(owner)!, { ...spot, w: size![0], h: size![1] })); }
      else notes.push(`chest: ${id} stays a lane: ${why(id)}`);
    }
  } else {
    const isLib = (d: Door) => kindOf(d.anchor) === "library";
    const isStore = (d: Door) => kindOf(d.anchor) === "datastore";
    const ins = doors.filter((d) => d.side === "in" && !isLib(d) && !isStore(d));
    const outs = doors.filter((d) => d.side === "out" && !isLib(d) && !isStore(d));
    const libs = doors.filter(isLib);
    const colW = FOOT.door[0] + 2 * PAD;
    const cx = M + PAD;
    const wx = M + (ins.length || libs.length ? colW + GX : 0) + PAD;   // the work area, right of the left column
    const top = M + PAD;
    let y = top;
    const placedAll: Box[] = [];
    for (const region of ["shelf", "hubs", "line", "grid", "bus", "bay"]) {
      const placed = grid(cells(region), region, wx, y, region === "line");
      placedAll.push(...placed);
      if (placed.length) y = bottom(placed, y) + GY;
    }
    work(placedAll);
    if (placedAll.length) y = bottom(placedAll, y) + GY;
    // the service's in-process queues: hubs in a row on its own airfield (zoned below, once rows are spread)
    const inq = cells("airfield").map(([id], i) => put(id, kindOf(id), "airfield", wx + i * (FOOT.hub[0] + GX), y));
    if (inq.length) y = bottom(inq, y) + PAD + LABEL + GY;
    const x1 = right([...boxes.values()], wx + 20) + PAD;
    y = laneRows([...doors.filter(isStore).map((d) => ({ id: d.anchor, box: d.id, kind: "datastore" })),
      ...cells("lane").map(([id]) => ({ id, box: id, kind: kindOf(id) }))], wx, y, x1);
    const floorBottom = Math.max(y, top + 6);
    // the room and its spread are sized as if the traffic extras were not there, so they add to the spread, not eat it
    const rowExtras = (opts.rowGaps ?? []).reduce((t, g) => t + g, 0);
    const plainBottom = Math.max(y - rowExtras, top + 6);

    // The room: as tall as the work area or, if taller, what the door columns need at DOOR_GAP between doors.
    const dh = FOOT.door[1], ih = FOOT.installed[1];
    const tail = PAD + LABEL;   // a column zone's bottom edge below its last door
    const both = ins.length > 0 && libs.length > 0;
    const yardDoor = ins.find((d) => d.id === opts.inYard?.door)?.id;
    const keep = yardDoor ? opts.inYard!.rows : 0;   // the in column's rows for a free-standing yard, below its door
    const leftNeed = top + keep + ins.length * dh + libs.length * ih + (Math.max(0, ins.length + libs.length - 1) - (both ? 1 : 0)) * DOOR_GAP + (both ? 1 + 2 * PAD + LABEL : 0) + tail;
    const rightNeed = top + outs.length * dh + Math.max(0, outs.length - 1) * DOOR_GAP + tail;
    const plainRoom = Math.max(plainBottom, leftNeed, rightNeed);

    // Spread the work area's rows evenly down the room: the spare height goes between row starts.
    const extra = plainRoom - plainBottom;
    const lanesBox = (l: TileLane) => [...boxes.values()].find((b) => b.x + b.w === l.x0 && b.y <= l.y && l.y < b.y + b.h);
    const rowYs = [...new Set([...boxes.values()].map((b) => b.y))].sort((p, q) => p - q);
    const colXs = [...new Set([...boxes.values()].map((b) => b.x))].sort((p, q) => p - q);
    const rowPer = extra > 0 && rowYs.length > 1 ? Math.floor(extra / (rowYs.length - 1)) : 0;
    // columns get the same extra per gap as the rows, so corridors run as wide across as down
    const colPer = colXs.length > 1 ? rowPer : 0;
    const room = Math.max(plainRoom, floorBottom + rowPer * Math.max(0, rowYs.length - 1));   // the extras make the room taller
    if (rowPer > 0) {
      const lb = new Map(lanes.map((l) => [l, lanesBox(l)] as const));
      for (const l of lanes) { const b = lb.get(l); if (b) l.y += rowYs.indexOf(b.y) * rowPer; }
      for (const b of boxes.values()) { b.y += rowYs.indexOf(b.y) * rowPer; b.x += colXs.indexOf(b.x) * colPer; }
      for (const l of lanes) { const b = lb.get(l); if (b) l.x0 = b.x + b.w; }
      const edge = right([...boxes.values()], 0) + PAD;
      for (const l of lanes) l.x1 = Math.max(l.x1 + colPer * (colXs.length - 1), edge);   // lanes still run under every machine
    }
    zone(IN_PROCESS, [...inq, ...inq.flatMap((b) => (isQueue(b.id) ? [stackTile(b)] : []))], true);
    /** A fixed-width column zone from row y0; returns the first row below it. */
    const column = (name: string, list: Box[], x: number, y0: number, y1 = 0): number => {
      if (!list.length) return y0;
      const z: Zone = { name, x: x - PAD, y: y0 - PAD, w: Math.max(colW, labelTiles(name)), h: Math.max(y1, bottom(list, y0) + tail) - (y0 - PAD), airfield: false };
      zones.push(z);
      return z.y + z.h + 1 + PAD;
    };
    /** Doors spread evenly down the column: the spare room divided between them (at least DOOR_GAP apart). */
    const spread = (n: number, used: number, avail: number) => (n > 1 ? Math.max(DOOR_GAP, DOOR_GAP + Math.floor((avail - used) / (n - 1))) : 0);
    const gL = spread(ins.length + libs.length - (both ? 1 : 0), leftNeed - top, room - top);
    let dy = top;
    const inBoxes = ins.map((d) => { const b = put(d.id, "door", "in", cx, dy, "door"); dy += dh + gL + (d.id === yardDoor ? keep : 0); return b; });
    const libTop = column("in", inBoxes, cx, top, yardDoor ? bottom([boxes.get(yardDoor)!], top) + keep + tail : 0);
    dy = libTop;
    const libBoxes = libs.map((d) => { const b = put(d.id, "door", "installed", cx, dy, "installed"); dy += ih + gL; return b; });
    column("installed libraries", libBoxes, cx, libTop, room);
    const ox = right([...boxes.values(), ...lanes.map(laneBand)], x1) + GX + PAD;
    const gR = spread(outs.length, rightNeed - top, room - top);
    const outBoxes = outs.map((d, i) => put(d.id, "door", "out", ox, top + i * (dh + gR), "door"));
    column("out", outBoxes, ox, top, Math.max(room, ...zones.map((z) => z.y + z.h)));   // the out column runs the room's height
  }

  const all: Rect[] = [...boxes.values(), ...zones, ...lanes.map(laneBand)];
  const tf: TileFloor = { boxes, lanes, zones, cols: right(all, 18) + M, rows: bottom(all, 10) + M, strategy: floor.strategy, site, aisles: measureAisles(workList) };
  if (notes.length) tf.notes = notes;
  if (gaps.length) tf.chestGaps = gaps;
  const stacks = queueStacks(tf, (id) => { const t = doorAnchor(id); return isQueue(t) ? t : undefined; });
  if (stacks.length) tf.stacks = stacks;
  return tf;
}

/** Where a `w`×`h` cache chest stands beside its machine `b`: one tile off it (the gap its taps cross), centred on that side, on
 *  the first side with room in the order below, right, left, above. Room: the chest and a one-tile ring round it (the
 *  gap, and a corridor on its other sides) touch no box or lane and stay inside `b`'s zone, off its label row, so the
 *  zone's edges and names are untouched. Undefined when no side has room (or `b` is in no zone). */
function chestSpot(b: Box | undefined, [w, h]: readonly [number, number], boxes: Rect[], lanes: Rect[], zones: Rect[]): { x: number; y: number } | undefined {
  if (!b) return undefined;
  const z = zones.find((q) => b.x >= q.x && b.y >= q.y && b.x + b.w <= q.x + q.w && b.y + b.h <= q.y + q.h);
  if (!z) return undefined;
  const midX = b.x + Math.floor((b.w - w) / 2), midY = b.y + Math.floor((b.h - h) / 2);
  const sides = [{ x: midX, y: b.y + b.h + 1 }, { x: b.x + b.w + 1, y: midY }, { x: b.x - 1 - w, y: midY }, { x: midX, y: b.y - 1 - h }];
  const hit = (r: Rect, q: Rect) => r.x < q.x + q.w && q.x < r.x + r.w && r.y < q.y + q.h && q.y < r.y + r.h;
  return sides.find((s) => {
    const ring = { x: s.x - 1, y: s.y - 1, w: w + 2, h: h + 2 };
    return ring.x >= z.x && ring.y >= z.y && ring.x + ring.w <= z.x + z.w && ring.y + ring.h <= z.y + z.h - LABEL
      && !boxes.some((q) => hit(ring, q)) && !lanes.some((q) => hit(ring, q));
  });
}

/** The tiles between chest `c` and its machine `b` (one tile apart on one side), across the run both share. */
function chestGap(b: Rect, c: Rect): Rect {
  const x0 = Math.max(b.x, c.x), x1 = Math.min(b.x + b.w, c.x + c.w), y0 = Math.max(b.y, c.y), y1 = Math.min(b.y + b.h, c.y + c.h);
  if (x1 > x0) return { x: x0, y: c.y > b.y ? b.y + b.h : b.y - 1, w: x1 - x0, h: 1 };
  return { x: c.x > b.x ? b.x + b.w : b.x - 1, y: y0, w: 1, h: y1 - y0 };
}

/** One free tile beside each queue hub (`topicOf` names a hub's topic when it is a queue): right of its bottom row, else
 *  left of it, else under or over its middle; a tile on another box, a lane or another stack is not free. */
function queueStacks(tf: TileFloor, topicOf: (id: string) => string | undefined): Stack[] {
  const out: Stack[] = [];
  const taken = (x: number, y: number) => x < 0 || y < 0 || x >= tf.cols || y >= tf.rows
    || [...tf.boxes.values()].some((b) => x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h)
    || tf.lanes.some((l) => x >= l.x0 && x < l.x1 && y >= l.y && y < l.y + LANE_H)
    || out.some((s) => s.x === x && s.y === y);
  for (const b of [...tf.boxes.values()].sort((p, q) => (p.id < q.id ? -1 : p.id > q.id ? 1 : 0))) {
    const topic = topicOf(b.id);
    if (!topic) continue;
    const mid = b.x + Math.floor((b.w - 1) / 2);
    const spot = ([[b.x + b.w, b.y + b.h - 1], [b.x - 1, b.y + b.h - 1], [mid, b.y + b.h], [mid, b.y - 1]] as const).find(([x, y]) => !taken(x, y));
    if (spot) out.push({ item: b.id, topic, x: spot[0], y: spot[1] });
  }
  return out;
}

/** Pixel geometry for everything that does not care about tiles: camera, floor changes, part travel. */
export function toGeometry(tf: TileFloor): FloorGeometry {
  const machines = new Map<string, Machine>();
  for (const b of tf.boxes.values()) machines.set(b.id, { id: b.id, kind: b.kind, x: b.x * T, y: b.y * T, w: b.w * T, h: b.h * T });
  return { machines, bounds: { x: 0, y: 0, w: tf.cols * T, h: tf.rows * T } };
}

/** Left tile of a zone's name on its bottom row: the left corner if clear, else the right, else the first clear run. */
export function labelSpot(z: Zone, width: number, taken: (x: number, y: number) => boolean): number {
  const y = z.y + z.h - 1;
  const free = (x0: number) => { for (let x = x0; x < x0 + width; x++) if (taken(x, y)) return false; return true; };
  const xs = [z.x, z.x + z.w - width];
  for (let x = z.x + 1; x < z.x + z.w - width; x++) xs.push(x);
  return xs.find(free) ?? z.x;
}
