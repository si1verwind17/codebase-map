// src/factory/router.ts
// Lines as tiles: each bundle becomes a chain of 1×1 pieces found by A* on the floor grid. A line
// that must cross another passes under it; lines routed first stay on top, so the picture is stable. Lines from one
// machine leave as one trunk and split off it; lines into one machine merge onto one.
import { flies, type Bundle } from "../model/model";
import type { Pt, Route } from "../route/types";
import { laneGaps, type TileFloor, type TileLane } from "./layout";
import { laneNameTiles } from "./clear";
import { reservedRects, webhookDockId } from "./pads";
import { RUN, railEnds, stationId, yardId, type RailEnd } from "./yards";
import { DIRS, LANE_H, OPP, STEP, T, dirInto, type Box, type Dir, type Piece, type Rect } from "./tiles";

export type LineKind = "belt" | "pipe" | "rail" | "tapW" | "tapR" | "tapRW" | "drone";
export interface TileRoute extends Route { kind: LineKind; pieces: Piece[]; both: boolean; failed?: boolean }

const TURN = 3;        // a corner costs three straight tiles: lines stay straight where they can
const UNDER = 6;       // going under another line costs more than a short detour, less than a long one
const MAX_UNDER = 4;   // tiles an underground run may span (a lane is three)
const RANK: Record<LineKind, number> = { pipe: 0, belt: 1, rail: 2, tapRW: 3, tapW: 3, tapR: 3, drone: 9 };
const CHEST_RANK = 1.5;   // a chest's taps: between belts (1) and rails (2)
const HUG = 3;         // stepping beside a machine the line does not touch: keep those tiles for the lines that end there
const FREE = -1, BOX = -2, LANE = -3;
const BASE = 0x3fffffff;   // a base line's tile under a layer's routing: a line index past any layer's own
const CORNER = 3;      // an end on a side's outermost tile (beside the machine's corner) costs about a turn: lines meet a side straight on, nearer its middle
const OFF = 1.25;      // each tile an end sits off its side's middle: more than the tile it saves, so a line along a side runs on to the middle and leaves the tiles before it to the next line
const RIDE = 0.3;      // a tile shared with a trunk costs less than a fresh one: lines bundle when that is about as short
const EDGE = 1;        // a tile on a broker airfield's edge column costs a little more: its name grows along its row into them
const BADGE = 2;       // a tile of the room right of a heavily used item, where its `used by N` badge grows to read at Fit
const BADGE_ROOM = { w: 7, h: 2 };   // tiles: a `used by 10` badge at about 2.2x
const NAME = 3;        // crossing or ending on a short lane where its name sits: about a turn, so a line goes a little way round for it

export function lineKind(b: Bundle, tap: boolean): LineKind {
  if (tap) return b.kinds["db-write"] && b.kinds["db-read"] ? "tapRW" : b.kinds["db-write"] ? "tapW" : "tapR";
  if (flies(b.kind)) return "drone";
  if (b.kind === "stream") return "pipe";
  if (b.kind === "batch") return "rail";
  return "belt";
}

const DX = DIRS.map((d) => STEP[d][0]), DY = DIRS.map((d) => STEP[d][1]);   // STEP by direction index, for the search's inner loop

const centre = (r: Rect): Pt => ({ x: (r.x + r.w / 2) * T, y: (r.y + r.h / 2) * T });
const band = (l: TileLane): Rect => ({ x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H });

/** `base`: given, this is a layer's pass: the lines already laid on this floor, which `bundles` route over. Their tiles on top are
 *  held by a line no layer line may ride: a layer line goes round them where it can and under them where it must, never
 *  along them; they are read, never changed. */
export function routeTiles(tf: TileFloor, bundles: Bundle[], base?: TileRoute[]): TileRoute[] {
  const { cols, rows } = tf;
  const occ = new Int32Array(cols * rows).fill(FREE);
  const at = (x: number, y: number) => y * cols + x;
  const ok = (x: number, y: number) => x >= 0 && y >= 0 && x < cols && y < rows;
  const fill = (r: Rect, v: number) => { for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) if (ok(x, y)) occ[at(x, y)] = v; };
  for (const l of tf.lanes) fill(band(l), LANE);
  for (const b of tf.boxes.values()) fill(b, BOX);
  for (const r of reservedRects(tf)) fill(r, BOX);   // receiving docks, waiting stacks, rail yards, signs and stations: no line runs over or under them (pads sit inside their machines)
  // a base line's tile: a line with no `meta`, so no layer line shares it (it crosses it as it crosses a lane)
  for (const r of base ?? []) for (const p of r.pieces) if (!p.under && ok(p.x, p.y) && occ[at(p.x, p.y)] === FREE) occ[at(p.x, p.y)] = BASE;
  const owner = new Int32Array(cols * rows).fill(-1);   // which machine covers a tile
  const index = new Map<string, number>();
  const own = (id: string, b: Rect) => {
    index.set(id, index.size);
    for (let y = b.y; y < b.y + b.h; y++) for (let x = b.x; x < b.x + b.w; x++) if (ok(x, y)) owner[at(x, y)] = index.size - 1;
  };
  for (const b of tf.boxes.values()) own(b.id, b);
  // rail yards and stations: a rail's two ends (trunks group on them), and walls other lines keep off as a machine's
  const rails = railEnds(tf);
  for (const y of tf.rails?.yards ?? []) own(yardId(y.source), y);
  for (const st of tf.rails?.stations ?? []) own(stationId(st), st);
  // a webhook dock: the end of the belts from outside into its service (they merge onto one trunk there)
  const hooks = new Map<string, { id: string; rect: Rect; into: Dir }>();
  for (const d of tf.webhooks ?? []) {
    own(webhookDockId(d.machine), d);
    for (const k of d.keys) hooks.set(k, { id: webhookDockId(d.machine), rect: d, into: OPP[d.side] });
  }
  // the tiles a rail starts and ends on (every exit of its yard, its station's entry) are its own: another line
  // treats them as a wall, so a rail is never walled in by a belt routed before it
  const gate = rails.size ? new Int32Array(cols * rows).fill(-1) : null;
  for (const e of rails.values()) {
    for (const x of e.yardExits) if (ok(x.x, x.y)) gate![at(x.x, x.y)] = index.get(yardId(e.yard!.source))!;
    if (ok(e.entry.x, e.entry.y)) gate![at(e.entry.x, e.entry.y)] = index.get(stationId(e.station))!;
  }

  // a broker airfield's two edge columns (one tile off its hubs): lines pass beside the airfield rather than along its
  // edge, so its name keeps the room to grow at Fit (a line down the edge hid pubsub's name on the demo site)
  const edge = new Uint8Array(cols * rows);   // the extra cost of a tile names or badges grow into
  for (const z of tf.zones) if (z.airfield) for (let y = z.y; y < z.y + z.h; y++) for (const x of [z.x, z.x + z.w - 1]) if (ok(x, y)) edge[at(x, y)] = EDGE;
  // a zone's label row (its bottom row, which the layout keeps for its name): a line runs along it only where it must
  for (const z of tf.zones) for (let x = z.x; x < z.x + z.w; x++) if (ok(x, z.y + z.h - 1)) edge[at(x, z.y + z.h - 1)] = EDGE;
  // the rows of a lane gap next to its lanes, where their taps end and their underground runs come up: a line along a
  // gap of three or more rows keeps to its inner rows where it can, clear of those stubs
  for (const g of laneGaps(tf)) if (g.y1 - g.y0 > 2) for (const y of [g.y0, g.y1 - 1]) for (let x = g.x0; x < g.x1; x++) if (ok(x, y)) edge[at(x, y)] = Math.max(edge[at(x, y)], EDGE);
  // a heavily used item's badge room, right of it and ending above its middle row (left free for a line to plug in
  // there): lines pass elsewhere where they can, so the badge reads at Fit
  for (const b of tf.boxes.values()) if (b.region === "hubs") {
    const y0 = b.y + Math.floor(b.h / 2) - BADGE_ROOM.h;
    for (let y = y0; y < y0 + BADGE_ROOM.h; y++) for (let x = b.x + b.w; x < b.x + b.w + BADGE_ROOM.w; x++) if (ok(x, y)) edge[at(x, y)] = Math.max(edge[at(x, y)], BADGE);
  }

  // a short lane's name tiles (clear.ts `laneNameTiles`): a line passing under them or ending on them costs NAME
  const named = new Uint8Array(cols * rows);
  for (const l of tf.lanes) {
    const n = laneNameTiles(l, l.label);
    if (n) for (let y = l.y; y < l.y + LANE_H; y++) for (let x = n[0]; x < n[1]; x++) if (ok(x, y)) named[at(x, y)] = 1;
  }

  // the machines beside each tile (up to two; MANY when more), for the cost of hugging a machine a line does not touch
  const MANY = -9;
  const nb = new Int32Array(cols * rows * 2).fill(-1);
  for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
    const t = at(x, y);
    for (let d = 0; d < 4; d++) {
      const nx = x + STEP[DIRS[d]][0], ny = y + STEP[DIRS[d]][1];
      if (!ok(nx, ny)) continue;
      const o = owner[at(nx, ny)];
      if (o < 0 || o === nb[2 * t] || o === nb[2 * t + 1]) continue;
      if (nb[2 * t] === -1) nb[2 * t] = o; else if (nb[2 * t + 1] === -1) nb[2 * t + 1] = o; else nb[2 * t + 1] = MANY;
    }
  }

  type Job = { b: Bundle; src: Box; dst: Rect; kind: LineKind; reverse: boolean; tap?: string; est: number; to: string; rail?: RailEnd; lane?: boolean;
    /** the only way the line may run into `dst`: a webhook dock is entered on its open side, toward its machine */ into?: Dir };
  const jobs: Job[] = [];
  const out: TileRoute[] = [];
  const laneOf = (b: Box) => tf.lanes.find((l) => l.id === b.id);
  /** A rail from its yard (a platform's exit) to its station. The yard stands in as the line's source box: its id names
   *  the yard (trunks group on it); kind, foot and region are placeholders no rule reads. */
  const railJob = (b: Bundle, rail: RailEnd) => {
    const y = rail.yard, st = rail.station;
    // a yard-less rail (its scheduler off the floor) leaves its door as a belt would
    const src: Box | undefined = y ? { id: yardId(y.source), kind: "yard", foot: "package", region: "rail", x: y.x, y: y.y, w: y.w, h: y.h } : tf.boxes.get(rail.door!);
    if (!src) return;
    const from = rail.own ?? src;
    jobs.push({ b, src, dst: st, kind: "rail", reverse: false, est: Math.abs(from.x - st.x) + Math.abs(from.y - st.y), to: stationId(st), rail });
  };
  for (const b of bundles) {
    const A = tf.boxes.get(b.a), B = tf.boxes.get(b.b);
    if (!A || !B) continue;
    const both = b.flow === "both";
    if (flies(b.kind)) {   // drones fly over the floor: no tiles
      const [s, d] = b.flow === "b→a" ? [B, A] : [A, B];
      out.push({ key: b.key, kind: "drone", both, pieces: [], points: [centre(s), centre(d)] });
      continue;
    }
    const rail = rails.get(b.key);
    if (rail && b.kind === "batch") { railJob(b, rail); continue; }
    const la = laneOf(A), lb = laneOf(B);
    if (!!la !== !!lb) {   // one end has a lane: the line drops onto the lane, not onto the box at its end
      const [box, laneBox, lane] = lb ? [A, B, lb] : [B, A, la!];
      const store = laneBox.kind === "datastore";
      const kind = lineKind(b, store);
      const fromLane = store ? kind === "tapR" : lb ? b.flow === "b→a" : b.flow === "a→b";
      jobs.push({ b, src: box, dst: band(lane), kind, reverse: fromLane, tap: store ? lane.id : undefined, est: Math.abs(box.y - lane.y), to: laneBox.id, lane: true });
      continue;
    }
    const hook = hooks.get(b.key);
    if (hook) {   // an inbound webhook: searched from the outside dock to the service's receiving dock, turned when its data runs back
      const src = A.kind === "external" ? A : B, back = b.flow === (src === A ? "b→a" : "a→b");
      jobs.push({ b, src, dst: hook.rect, kind: lineKind(b, false), reverse: back, est: Math.abs(src.x - hook.rect.x) + Math.abs(src.y - hook.rect.y), to: hook.id, into: hook.into });
      continue;
    }
    const ca = A.kind === "datastore", cb = B.kind === "datastore";
    if (ca !== cb) {   // a store standing as a box with no lane (a cache chest beside its one machine): a tap, box to box
      const [box, chest] = cb ? [A, B] : [B, A];
      const kind = lineKind(b, true);
      jobs.push({ b, src: box, dst: chest, kind, reverse: kind === "tapR", tap: chest.id, est: Math.abs(box.x - chest.x) + Math.abs(box.y - chest.y), to: chest.id });
      continue;
    }
    const [src, dst] = b.flow === "b→a" ? [B, A] : [A, B];
    jobs.push({ b, src, dst, kind: lineKind(b, false), reverse: false, est: Math.abs(src.x - dst.x) + Math.abs(src.y - dst.y), to: dst.id });
  }
  // a station whose rail no batch bundle carries gets it from a stand-in bundle (tf.rails.shells): every platform a track.
  // The base's own lines: a layer's pass (over `base`) routes only its bundles
  if (!base) for (const sh of tf.rails?.shells ?? []) { const rail = rails.get(sh.key); if (rail) railJob(sh, rail); }
  // One trunk per line: it rides the trunk of its data source (a split) or of its data target (a merge), whichever end
  // has more lines of its kind (at least two; a tie goes to the source), else it runs alone. A line read from a lane
  // is searched machine to lane, so its data source is the search's target (`to`).
  const ends = (j: Job) => { const t = `${j.kind}|${j.reverse}`; return { src: `s|${j.src.id}|${t}`, dst: `d|${j.to}|${t}` }; };
  const count = new Map<string, number>();
  for (const j of jobs) for (const k of Object.values(ends(j))) count.set(k, (count.get(k) ?? 0) + 1);
  const plan = new Map<Job, { mode: "src" | "dst" | null; group: string; size: number }>();
  for (const j of jobs) {
    const e = ends(j);
    const order: ("src" | "dst")[] = j.reverse ? ["dst", "src"] : ["src", "dst"];   // data source first
    const [first, second] = order, nf = count.get(e[first])!, ns = count.get(e[second])!;
    const m = nf >= 2 && nf >= ns ? first : ns >= 2 ? second : null;   // the bigger group; a tie goes to the data source
    plan.set(j, m ? { mode: m, group: e[m], size: count.get(e[m])! } : { mode: null, group: j.b.key, size: 1 });
  }
  // biggest groups first, a group's lines together: the first one lays the trunk
  // a chest's taps go after the belts and before the rails: they cross the one-tile gap the layout keeps between the chest
  // and its machine, which a rail leaving a yard beside the machine would otherwise take (the fixture's shop); routed
  // before the belts too they pushed the demo's belts round (42 crossings against 38). A lane's taps go last: they drop
  // onto the lane under everything
  const rank = (j: Job) => (j.tap && !tf.lanes.some((l) => l.id === j.tap) ? CHEST_RANK : RANK[j.kind]);
  jobs.sort((p, q) => rank(p) - rank(q) || plan.get(q)!.size - plan.get(p)!.size
    || (plan.get(p)!.size > 1 ? (plan.get(p)!.group < plan.get(q)!.group ? -1 : plan.get(p)!.group > plan.get(q)!.group ? 1 : 0) : 0)
    || p.est - q.est || p.b.key.localeCompare(q.b.key));

  // What each routed line is, and how it crosses each tile it holds: a later line may share the tile (a trunk).
  const g = new Float64Array(cols * rows * 4).fill(Infinity);   // search scratch, shared by every search
  const prev = new Int32Array(cols * rows * 4).fill(-1);
  const done = new Uint8Array(cols * rows * 4);
  const goaled = new Uint8Array(cols * rows * 4);   // states whose goal entry is already queued
  const touched = new Int32Array(cols * rows * 4);   // states the last search set (each once: its g left Infinity)
  let nTouched = 0;
  const heap = new Heap();   // the open list, shared by every search
  const meta: { src: string; to: string; rev: boolean; kind: LineKind }[] = [];
  const tileIn = new Int8Array(cols * rows), tileOut = new Int8Array(cols * rows);
  const dirIdx = (d: Dir) => DIRS.indexOf(d);
  let cur: Job | null = null;   // the line being searched (pass 1 and 2)
  // every line on a tile shares the source (or the target) recorded here; MIXED once two holders differ
  const MIXED = -2;
  const tileSrc = new Int32Array(cols * rows).fill(-1), tileTo = new Int32Array(cols * rows).fill(-1);
  const tileN = new Int32Array(cols * rows);   // lines on top of a tile
  const tileJoin = new Uint8Array(cols * rows);   // a junction plate stands here
  const housed = new Uint8Array(cols * rows);     // some line's underground housing stands here
  const tileHood = new Uint8Array(cols * rows);   // the holder's next piece is underground: a rider follows it under as one belt
  const tileTun = new Int32Array(cols * rows);   // how many tiles that underground run spans
  // every line on top of a tile, with its data-flow ends and the axis it crosses the tile on (as drawn)
  const holders: ({ src: string; dst: string; axis: number }[] | undefined)[] = new Array(cols * rows);
  const flowEnds = (j: Job) => j.reverse ? { src: j.to, dst: j.src.id } : { src: j.src.id, dst: j.to };
  let me: Job | null = null;   // the line being searched, while it may ride a trunk
  let mode: "src" | "dst" = "src";   // src: it starts on a trunk of its own source; dst: it ends on a trunk of its own target
  // set as each search starts: the index of `me`'s source and target machines (NaN when none, which no tile holds), and flowEnds(cur)
  let meSrc = NaN, meTo = NaN;
  let curEnds: { src: string; dst: string } | null = null;

  // pass 1: each line may ride the trunk its plan names; pass 2 re-routes what failed, trying either end
  const slot = new Map<Job, number>();
  const placed = new Map<string, number>();   // lines laid per source and per target: is there a trunk to ride?
  const place = (j: Job, cells: Piece[] | null) => {
    const id = slot.get(j) ?? out.length;
    const both = j.b.flow === "both";
    let r: TileRoute;
    if (!cells) r = { key: j.b.key, kind: j.kind, both, pieces: [], points: [centre(j.src), centre(j.dst)], tap: j.tap, failed: true };
    else {
      if (me) markJoins(cells);
      const s = index.get(j.src.id)!, t = index.get(j.to)!;
      for (const p of cells) if (!p.under && occ[at(p.x, p.y)] >= 0) {
        const c = at(p.x, p.y);
        if (tileSrc[c] !== s) tileSrc[c] = MIXED;
        if (tileTo[c] !== t) tileTo[c] = MIXED;
      }
      const fe = flowEnds(j);
      for (const p of cells) if (!p.under) {
        const c = at(p.x, p.y);
        if (p.join) tileJoin[c] = 1;
        if (p.hoodBefore || p.hoodAfter) housed[c] = 1;
        tileN[c]++;
        const list = holders[c] ?? (holders[c] = []);
        list.push({ ...fe, axis: dirIdx(j.reverse ? p.out : p.in) % 2 });
      }
      cells.forEach((p, i) => {
        if (p.under || occ[at(p.x, p.y)] !== FREE) return;
        const c = at(p.x, p.y);
        tileSrc[c] = s; tileTo[c] = t;
        occ[c] = id; tileIn[c] = dirIdx(p.in); tileOut[c] = dirIdx(p.out); tileHood[c] = p.hoodBefore ? 1 : 0;
        let n = 0;
        if (p.hoodBefore) while (cells[i + 1 + n]?.under) n++;
        tileTun[c] = n;
      });
      meta[id] = { src: j.src.id, to: j.to, rev: j.reverse, kind: j.kind };
      for (const k of Object.values(ends(j))) placed.set(k, (placed.get(k) ?? 0) + 1);
      const pieces = j.reverse ? reversed(cells) : cells;
      r = { key: j.b.key, kind: j.kind, both, pieces, points: piecesToPoints(pieces), tap: j.tap, failed: undefined };
    }
    if (slot.has(j)) out[id] = r; else { slot.set(j, id); out.push(r); }
    return !!cells;
  };
  const failedJobs: Job[] = [];
  for (const j of jobs) {
    const m = plan.get(j)!.mode;
    cur = j; me = m ? j : null; mode = m ?? "src";
    if (!place(j, clean(j, MAX_UNDER))) failedJobs.push(j);
  }
  for (const j of failedJobs) {   // one trunk per line: shared at its start (src) or at its end (dst), never both
    me = cur = j;
    let cells: Piece[] | null = null;
    tries: for (const u of [MAX_UNDER, 12]) for (const m of ["src", "dst"] as const) {
      mode = m;
      cells = clean(j, u);
      if (cells) break tries;
    }
    place(j, cells);
  }
  me = null;
  return out;

  /** A search whose line never crosses its own tile on top: a tile it would repeat is closed and the search rerun. */
  function clean(j: Job, maxUnder: number): Piece[] | null {
    const closed: [number, number][] = [];
    try {
      for (let n = 0; n < 4; n++) {
        const cells = search(j.src, j.dst, maxUnder, j.to, j.rail, j.into, j.lane);
        if (!cells) return null;
        const seen = new Set<number>();
        const again = cells.find((p) => { if (p.under) return false; const t = at(p.x, p.y); if (seen.has(t)) return true; seen.add(t); return false; });
        if (!again) return cells;
        closed.push([at(again.x, again.y), occ[at(again.x, again.y)]]);
        occ[at(again.x, again.y)] = BOX;
      }
      return null;
    } finally {
      for (const [t, v] of closed.reverse()) occ[t] = v;
    }
  }
  /** Does tile t carry (on top) any line sharing a data-flow end with the one being searched, along the axis of a tunnel heading `d`? */
  function mateAlong(t: number, d: number): boolean {
    const list = holders[t], fe = curEnds;
    if (!list || !fe) return false;
    return list.some((h) => (h.src === fe.src || h.dst === fe.dst) && h.axis === d % 2);
  }
  /** May the line being searched run on tile t (held by line v) arriving in direction d? */
  function shares(v: number, t: number, d: number): boolean {
    const m = meta[v];
    if (!me || !m || m.rev !== me.reverse || m.kind !== me.kind) return false;
    return mode === "src" ? tileSrc[t] === meSrc && tileIn[t] === d : tileTo[t] === meTo;
  }
  /** The tile one step from t along direction index d, or -1 off the floor. */
  function next(t: number, d: number): number {
    const x = (t % cols) + STEP[DIRS[d]][0], y = ((t / cols) | 0) + STEP[DIRS[d]][1];
    return ok(x, y) ? at(x, y) : -1;
  }
  /** May a line leave the trunk at t (a split)? Not where the trunk alone runs on into tiles others share: the holder would
   *  hop between partners. Likewise a line may join at t (a merge) only if the trunk did not arrive there shared. */
  function canLeave(t: number): boolean {
    const n = next(t, tileOut[t]);
    return roomAt(t) && (tileN[t] >= 2 || n < 0 || tileN[n] <= 1);
  }
  function canJoin(t: number): boolean {
    const p = next(t, (tileIn[t] + 2) % 4);
    return roomAt(t) && (tileN[t] >= 2 || p < 0 || tileN[p] <= 1);
  }
  /** Room round a junction (the owner's 2 in, 1 out): the trunk runs straight through it, and the trunk tiles either side
   *  are plain pieces -- no other junction, no underground housing -- as is the tile on the junction itself. The plate
   *  keeps off the factory walls: no machine touches its tile on any side (a plate against a wall reads as part of it). */
  function roomAt(t: number): boolean {
    if (tileIn[t] !== tileOut[t] || tileJoin[t] || housed[t] || nb[2 * t] !== -1) return false;
    const plain = (n: number) => n < 0 || (!tileJoin[n] && !housed[n]);
    return plain(next(t, tileOut[t])) && plain(next(t, (tileIn[t] + 2) % 4));
  }
  /** Which way may the line go on from a trunk tile it arrived at: -1 anywhere (it splits off), else the way the trunk runs. */
  function forced(t: number): number {
    return mode === "src" ? -1 : tileOut[t];
  }
  /** Mark the one junction of a line on a trunk: its last shared tile (split, shared source) or its first (merge, shared target). */
  function markJoins(cells: Piece[]) {
    const shared = cells.filter((p) => !p.under && occ[at(p.x, p.y)] >= 0);
    if (!shared.length) return;
    if (mode === "src") shared[shared.length - 1].join = "split";
    else shared[0].join = "merge";
  }

  /** A* from any side of `src` to any tile beside `dst` (with `entry`, only running into it that way); null when walled in. A rail (`rail`) starts only on its own
   *  platform's exit, or on another exit of its yard where a trunk it rides starts, and ends only on an end of its
   *  station, running into it along the destination's wall. */
  function search(src: Box, dst: Rect, maxUnder: number, dstId?: string, rail?: RailEnd, entry?: Dir, lane = false): Piece[] | null {
    const mine = [index.get(src.id), dstId === undefined ? undefined : index.get(dstId)];
    curEnds = cur ? flowEnds(cur) : null;
    meSrc = me ? index.get(me.src.id) ?? NaN : NaN; meTo = me ? index.get(me.to) ?? NaN : NaN;
    // the line's own machines (a rail's destination counts as its own): hugging any other costs HUG, in the loop below
    const m0 = mine[0] ?? -1, m1 = mine[1] ?? -1, m2 = rail ? index.get(rail.dest)! : -1;
    /** A tile as this line sees it: another rail's start or end tile is a wall. */
    const eff = gate ? (t: number) => (gate[t] >= 0 && gate[t] !== m0 && gate[t] !== m1 ? BOX : occ[t]) : (t: number) => occ[t];
    // walled in at either end: no need to explore the floor
    const rides = (t: number) => { const m = meta[occ[t]]; return !!me && !!m && m.rev === me.reverse && m.kind === me.kind; };
    const startOk = (t: number, d: number) => eff(t) === FREE || (me !== null && mode === "src" && occ[t] >= 0 && shares(occ[t], t, d));
    const endOk = (t: number) => eff(t) === FREE || (occ[t] >= 0 && rides(t)
      && (mode === "src" ? tileSrc[t] === meSrc : tileTo[t] === meTo));
    /** A rail's start tiles: its own exit when free, any exit of its yard a trunk to ride starts on (on a ladder, its own
     *  exit only: the yard planned which rails leave together). */
    const starts: [number, number, number, number][] = rail?.yard
      ? rail.yardExits.filter((e) => ok(e.x, e.y) && (!rail.yard!.ladder || e === rail.own)).map((e) => [e.x, e.y, DIRS.indexOf(e.d), e === rail.own ? 1 : 0])
      : [];
    const startAt = (x: number, y: number, di: number, mineToo: number) => {
      const t = at(x, y), v = eff(t);
      return (v === FREE && mineToo === 1) || (me !== null && mode === "src" && occ[t] >= 0 && shares(occ[t], t, di));
    };
    const isEnd = (x: number, y: number) => !!rail && rail.entry.x === x && rail.entry.y === y;
    // a free-standing yard's rail runs straight for RUN tiles from each exit before it turns: tile -> the way it runs
    let lead: Map<number, number> | null = null;
    if (rail?.yard?.free) {
      lead = new Map();
      for (const e of rail.yardExits) for (let s = 0; s < RUN; s++) if (ok(e.x + STEP[e.d][0] * s, e.y + STEP[e.d][1] * s)) lead.set(at(e.x + STEP[e.d][0] * s, e.y + STEP[e.d][1] * s), DIRS.indexOf(e.d));
    }
    if (rail?.yard) { if (!starts.some(([x, y, di, o]) => startAt(x, y, di, o))) return null; }
    else if (!DIRS.some((d, di) => side(src, d).some(([x, y]) => ok(x, y) && startOk(at(x, y), di)))) return null;
    if (rail) { if (!(ok(rail.entry.x, rail.entry.y) && endOk(at(rail.entry.x, rail.entry.y)))) return null; }
    else if (!DIRS.some((d) => (!entry || d === OPP[entry]) && side(dst, d).some(([x, y]) => ok(x, y) && endOk(at(x, y))))) return null;
    for (let i = 0; i < nTouched; i++) { const t = touched[i]; g[t] = Infinity; prev[t] = -1; done[t] = 0; goaled[t] = 0; }   // reset only what the last search used
    nTouched = 0;
    heap.clear();
    const GOAL = g.length;   // a goal entry (GOAL + tile state) is queued with its end's off-centre cost, so a tile beside the corner loses to the middle
    const key = (x: number, y: number, d: number) => at(x, y) * 4 + d;
    const dx0 = dst.x - 1, dx1 = dst.x + dst.w, dy0 = dst.y - 1, dy1 = dst.y + dst.h;
    // with a trunk to ride a tile may cost only RIDE: scale the estimate so the search still finds the trunk
    const hw = me && (placed.get(ends(me)[mode]) ?? 0) > 0 ? RIDE : 1;
    const h = (x: number, y: number) => hw * (Math.max(0, dx0 - x, x - dx1) + Math.max(0, dy0 - y, y - dy1));
    const relax = (nk: number, cost: number, from: number, x: number, y: number) => {
      if (cost < g[nk]) { if (g[nk] === Infinity) touched[nTouched++] = nk; g[nk] = cost; prev[nk] = from; heap.push(cost + h(x, y), nk); }
    };
    if (rail?.yard) for (const [x, y, di, o] of starts) { if (startAt(x, y, di, o)) relax(key(x, y, di), 0, -1, x, y); }
    else for (let di = 0; di < 4; di++) for (const [x, y, off] of side(src, DIRS[di])) {
      if (!ok(x, y)) continue;
      const v = eff(at(x, y));
      if (v === FREE || (me && mode === "src" && v >= 0 && shares(v, at(x, y), di))) relax(key(x, y, di), v === FREE ? endCost(src, DIRS[di], off) : 0, -1, x, y);
    }
    const rider = me !== null, dstMode = mode === "dst";   // fixed for the whole search
    while (heap.size) {
      let k = heap.pop();
      if (k >= GOAL) {
        k -= GOAL;
        return build(k, dirInto(dst, (k >> 2) % cols, ((k >> 2) / cols) | 0)!);
      }
      if (done[k]) continue;
      done[k] = 1;
      const cell = k >> 2, di = k & 3, x = cell % cols, y = (cell / cols) | 0;
      const here = cell, hv = occ[here], gk = g[k];
      const riding = rider && hv >= 0;   // on a trunk: stay on it (dst) or leave it (src), never tunnel on its own
      const only = riding ? forced(here) : -1;   // on a trunk tile: leave only as the trunk allows
      const near = x >= dx0 && x <= dx1 && y >= dy0 && y <= dy1;   // only a tile in the ring round dst can step into it
      const into0 = !near || (rail && !isEnd(x, y)) ? null : dirInto(dst, x, y), into = entry && into0 !== entry ? null : into0;
      const leaves = !(riding && !dstMode) || canLeave(here);   // a rider may split off here
      const lock = lead !== null && lead.get(here) === di ? di : -1;   // still on a free-standing yard's exit run
      if (into && (only < 0 || into === DIRS[only]) && leaves) {
        const end = next(here, dirIdx(into));
        const off = hv === FREE ? endCost(dst, into, offMid(dst, x, y, into), lane) + (end >= 0 && named[end] ? NAME : 0) : 0;   // plugging into a trunk's tile is free: its first tile was centred
        if (off === 0) return build(k, into);
        if (!goaled[k]) { goaled[k] = 1; heap.push(g[k] + off, GOAL + k); }
      }
      for (let ni = 0; ni < 4; ni++) {
        if (ni === (di + 2) % 4) continue;   // no U-turns
        if (only >= 0 && ni !== only) continue;
        if (lock >= 0 && ni !== lock) continue;
        const dx = DX[ni], dy = DY[ni];
        const nx = x + dx, ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
        const nt = cell + dy * cols + dx, v = eff(nt);
        if (v === FREE) {
          // hug written out: this is the search's hottest step (same sums, in the same order)
          if (!(riding && dstMode) && leaves) {
            const a = nb[2 * nt], b = nb[2 * nt + 1];
            const cost = gk + 1 + (((a >= 0 && a !== m0 && a !== m1 && a !== m2) || (b >= 0 && b !== m0 && b !== m1 && b !== m2) || b === MANY ? HUG : 0) + edge[nt]) + (ni === di ? 0 : TURN);
            relax(nt * 4 + ni, cost, k, nx, ny);
          }
        } else if (v !== BOX) {
          // a trunk going under: its riders go under with it, entering and coming up where its holder does
          if (riding && tileHood[here] && ni === tileOut[here]) {
            const n = tileTun[here], ex = x + dx * (n + 1), ey = y + dy * (n + 1);
            let clear = ok(ex, ey) && eff(at(ex, ey)) >= 0 && shares(occ[at(ex, ey)], at(ex, ey), ni);
            for (let s = 1; s <= n && clear; s++) clear = eff(at(x + dx * s, y + dy * s)) !== BOX && !mateAlong(at(x + dx * s, y + dy * s), ni);
            if (clear) relax(key(ex, ey, ni), g[k] + RIDE * (n + 1), k, ex, ey);
            continue;
          }
          const share = me !== null && v >= 0 && (riding || mode === "dst") && shares(v, at(nx, ny), ni)
            && (!riding || ni === tileOut[here])   // on a trunk, carry on only along the holder's own path
            && (riding || canJoin(at(nx, ny)));
          // riding follows turns and machines the trunk already passes: only the tile's share is paid
          const rose = share && prev[k] >= 0 && Math.abs((prev[k] >> 2) % cols - x) + Math.abs(((prev[k] >> 2) / cols | 0) - y) > 1;   // this tile is a tunnel's exit
          if (share && !(rose && hv === FREE)) relax(key(nx, ny, ni), g[k] + RIDE + (riding || ni === di ? 0 : TURN), k, nx, ny);
          if (ni !== di || riding) continue;   // straight on, under another line or a lane, to the next free tile
          if (prev[k] >= 0 && occ[prev[k] >> 2] >= 0) continue;   // the tile a branch steps onto from its junction is a plain piece, not a housing
          let hidden = mateAlong(at(nx, ny), ni);   // never run lengthwise under a line it shares an end with
          let name = named[nt];
          for (let s = 2; s <= maxUnder + 1 && !hidden; s++) {
            const tx = x + dx * s, ty = y + dy * s;
            if (!ok(tx, ty)) break;
            const tv = eff(at(tx, ty));
            if (tv === BOX) break;
            if (tv === FREE) { relax(key(tx, ty, ni), g[k] + s + UNDER + (name ? NAME : 0), k, tx, ty); break; }
            hidden = mateAlong(at(tx, ty), ni);
            name |= named[at(tx, ty)];
          }
        }
      }
    }
    return null;

    function build(k: number, into: Dir): Piece[] {
      const chain: number[] = [];
      for (let c = k; c !== -1; c = prev[c]) chain.push(c);
      chain.reverse();
      const ps: Piece[] = [];
      for (const c of chain) {
        const cell = c >> 2, d = DIRS[c & 3], x = cell % cols, y = (cell / cols) | 0;
        const last = ps[ps.length - 1];
        if (last) {   // tiles a tunnel skipped are underground
          const [dx, dy] = STEP[d];
          for (let tx = last.x + dx, ty = last.y + dy; tx !== x || ty !== y; tx += dx, ty += dy)
            ps.push({ x: tx, y: ty, in: d, out: d, under: true, hoodBefore: false, hoodAfter: false });
        }
        ps.push({ x, y, in: d, out: d, under: false, hoodBefore: false, hoodAfter: false });
      }
      for (let i = 0; i < ps.length; i++) {
        ps[i].out = i + 1 < ps.length ? ps[i + 1].in : into;
        ps[i].hoodBefore = !ps[i].under && !!ps[i + 1]?.under;
        ps[i].hoodAfter = !ps[i].under && !!ps[i - 1]?.under;
      }
      return ps;
    }
  }
}

/** How far tile (x, y), just outside the side of `b` it enters through (`d`, the travel direction), is from that side's middle. */
function offMid(b: Rect, x: number, y: number, d: Dir): number {
  return d === "e" || d === "w" ? Math.abs(y - (b.y + (b.h - 1) / 2)) : Math.abs(x - (b.x + (b.w - 1) / 2));
}

/** Is a tile `off` from the middle of a side of `b` that side's outermost tile (a side of three or more tiles)? */
function cornerTile(b: Rect, d: Dir, off: number): boolean {
  const n = d === "n" || d === "s" ? b.w : b.h;
  return n >= 3 && off === (n - 1) / 2;
}

/** What an end `off` tiles from a side's middle costs: OFF a tile, at least CORNER on the outermost tile. A lane
 *  (`lane`) runs under every machine above it: no tile of its side is better than another, so a line drops straight
 *  onto it and only its outermost tile costs CORNER. */
function endCost(b: Rect, d: Dir, off: number, lane = false): number {
  return Math.max(lane ? 0 : off * OFF, cornerTile(b, d, off) ? CORNER : 0);
}

/** Tiles just outside one side of a box, with each tile's distance from the middle of that side. */
function side(b: Rect, d: Dir): [number, number, number][] {
  const out: [number, number, number][] = [];
  if (d === "n" || d === "s") {
    const y = d === "n" ? b.y - 1 : b.y + b.h, mid = b.x + (b.w - 1) / 2;
    for (let x = b.x; x < b.x + b.w; x++) out.push([x, y, Math.abs(x - mid)]);
  } else {
    const x = d === "w" ? b.x - 1 : b.x + b.w, mid = b.y + (b.h - 1) / 2;
    for (let y = b.y; y < b.y + b.h; y++) out.push([x, y, Math.abs(y - mid)]);
  }
  return out;
}

/** Pixel corners of a tile line: from its entry edge, through each corner tile's centre, to its exit edge. */
export function piecesToPoints(ps: Piece[]): Pt[] {
  if (!ps.length) return [];
  const c = (p: Piece): Pt => ({ x: p.x * T + T / 2, y: p.y * T + T / 2 });
  const f = ps[0], l = ps[ps.length - 1];
  const pts: Pt[] = [{ x: c(f).x - (STEP[f.in][0] * T) / 2, y: c(f).y - (STEP[f.in][1] * T) / 2 }];
  for (const p of ps) if (p.in !== p.out) pts.push(c(p));
  pts.push({ x: c(l).x + (STEP[l.out][0] * T) / 2, y: c(l).y + (STEP[l.out][1] * T) / 2 });
  return pts;
}

/** The same line travelled the other way (a read runs from the lane up to the machine). */
export function reversed(ps: Piece[]): Piece[] {
  return ps.slice().reverse().map((p) => ({ ...p, in: OPP[p.out], out: OPP[p.in], hoodBefore: p.hoodAfter, hoodAfter: p.hoodBefore, ...(p.join ? { join: p.join === "split" ? "merge" as const : "split" as const } : {}) }));
}

/** Is a tile covered by a machine, a lane or a line drawn on top? (Zone and lane names avoid these.) */
export function takenTiles(tf: TileFloor, routes: TileRoute[]): (x: number, y: number) => boolean {
  const taken = new Set<number>();
  const mark = (r: Rect) => { for (let y = r.y; y < r.y + r.h; y++) for (let x = r.x; x < r.x + r.w; x++) taken.add(y * tf.cols + x); };
  for (const b of tf.boxes.values()) mark(b);
  for (const r of reservedRects(tf)) mark(r);
  for (const r of routes) for (const p of r.pieces) if (!p.under) taken.add(p.y * tf.cols + p.x);
  return (x, y) => taken.has(y * tf.cols + x);
}

/** A binary min-heap of keys by priority, on typed arrays that grow as needed and are kept between searches (`clear`).
 *  The same comparisons as swapping sifts, so ties pop in the same order: the plans do not change. */
class Heap {
  private f = new Float64Array(1024);
  private k = new Int32Array(1024);
  size = 0;
  clear() { this.size = 0; }
  push(f: number, k: number) {
    if (this.size === this.k.length) {
      const nf = new Float64Array(this.size * 2), nk = new Int32Array(this.size * 2);
      nf.set(this.f); nk.set(this.k); this.f = nf; this.k = nk;
    }
    const F = this.f, K = this.k;
    let i = this.size++;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (F[p] <= f) break;
      F[i] = F[p]; K[i] = K[p];
      i = p;
    }
    F[i] = f; K[i] = k;
  }
  /** Bottom-up: down the path of smaller children (the right one only when strictly smaller) to a leaf, back up to
   *  the deepest entry on it still below the last one, which goes there as the path above moves up one. A top-down
   *  sift stops at that same place, as priorities only grow down the path: the same heap, fewer comparisons. */
  pop(): number {
    const F = this.f, K = this.k;
    const top = K[0], n = --this.size;
    if (n) {
      const lf = F[n], lk = K[n];
      let j = 0;
      for (let l = 1; l < n; l = 2 * j + 1) j = l + (+(F[l + 1] < F[l]) & +(l + 1 < n));   // no branch to mispredict; l + 1 <= n is in the array
      while (j > 0 && F[j] >= lf) j = (j - 1) >> 1;
      let cf = lf, ck = lk;
      while (j > 0) {
        const tf = F[j], tk = K[j];
        F[j] = cf; K[j] = ck; cf = tf; ck = tk;
        j = (j - 1) >> 1;
      }
      F[0] = cf; K[0] = ck;
    }
    return top;
  }
}
