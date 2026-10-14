// Painting one line tile (spec §4): belts curve round corners with a chevron riding the curve; pipes and taps
// get elbows, flanges and clamps; rails get ties; a hood stands beside every underground run.
import type { Graphics } from "pixi.js";
import { C, F } from "../floor/palette";
import type { LineKind } from "./router";
import { shape, type V } from "./shape";
import { DIRS, OPP, STEP, T, joinEdge, type Dir, type Piece } from "./tiles";

type S = ReturnType<typeof shape>;

/** An arc round the tile's inner corner at radius r, from the entry edge's side to the exit edge's side. */
function arc(g: Graphics, s: S, r: number) {
  const [ix, iy] = s.corner;
  const from = s.edge(s.inEdge), to = s.edge(s.outEdge);
  const a0 = Math.atan2(from[1] - iy, from[0] - ix);
  let d = Math.atan2(to[1] - iy, to[0] - ix) - a0;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  g.moveTo(ix + r * Math.cos(a0), iy + r * Math.sin(a0)).arc(ix, iy, r, a0, a0 + d, d < 0);
}

/** A chevron at (px, py) pointing along (ux, uy). */
function chevron(g: Graphics, px: number, py: number, ux: number, uy: number, a: number, color: number = C.paper, width = 2) {
  const nx = -uy, ny = ux;
  g.moveTo(px - ux * a + nx * a, py - uy * a + ny * a).lineTo(px + ux * a, py + uy * a).lineTo(px - ux * a - nx * a, py - uy * a - ny * a)
    .stroke({ width, color, cap: "round", join: "round" });
}

export function paintPiece(g: Graphics, p: Piece, kind: LineKind, both: boolean) {
  const s = shape(p);
  const { x, y, cx, cy, straight } = s;
  const [ox, oy] = s.outEdge;
  if (kind === "belt") {
    g.rect(x + 1, y + 1, T - 2, T - 2).fill(C.ink);
    if (straight) {
      for (const o of [-6, 6]) {
        if (ox) g.moveTo(x + 1, cy + o).lineTo(x + T - 1, cy + o); else g.moveTo(cx + o, y + 1).lineTo(cx + o, y + T - 1);
      }
      g.stroke({ width: 2, color: F.tread });
      if (both) {   // a two-way belt: two half-lanes running opposite ways
        if (ox) g.moveTo(x + 1, cy).lineTo(x + T - 1, cy); else g.moveTo(cx, y + 1).lineTo(cx, y + T - 1);
        g.stroke({ width: 1.5, color: F.split });
        const [fx, fy] = s.edge(s.outEdge), f = forwardLaneAt(p, "out");   // forward lane: right of travel
        const [nx, ny] = [f[0] - fx, f[1] - fy];                            // its offset from the edge midpoint, pointing right
        chevron(g, cx + nx, cy + ny, ox, oy, 3); chevron(g, cx - nx, cy - ny, -ox, -oy, 3);
      } else chevron(g, cx, cy, ox, oy, 4.5);
    } else {
      for (const r of [T / 2 - 6, T / 2 + 6]) arc(g, s, r);
      g.stroke({ width: 2, color: F.tread });
      // the chevron rides the middle of the curve, pointing along it
      const [ix, iy] = s.corner;
      const a = s.edge(s.inEdge), b = s.edge(s.outEdge);
      const mx = a[0] - ix + b[0] - ix, my = a[1] - iy + b[1] - iy, mn = Math.hypot(mx, my);
      const dx = -s.inEdge[0] + ox, dy = -s.inEdge[1] + oy, n = Math.hypot(dx, dy) || 1;
      if (both) {   // a two-way corner: the split line along the mid-arc, one chevron each way on the two tread arcs
        arc(g, s, T / 2);
        g.stroke({ width: 1.5, color: F.split });
        const rf = forwardLane(p).r!, rb = T - rf;   // forward rides the right-of-travel arc, backward the other
        chevron(g, ix + (mx / mn) * rf, iy + (my / mn) * rf, dx / n, dy / n, 3);
        chevron(g, ix + (mx / mn) * rb, iy + (my / mn) * rb, -dx / n, -dy / n, 3);
      } else chevron(g, ix + (mx / mn) * (T / 2), iy + (my / mn) * (T / 2), dx / n, dy / n, 4);
    }
  } else if (kind === "rail") {
    paintRailTile(g, [p]);
  } else if (kind === "tapRW") {
    // reads and writes on one tap: a pair, red and slate, side by side
    for (const [off, col] of [[-4, C.red], [4, C.slate]] as const) halves(g, s, off, 3, col);
  } else {
    const pipe = kind === "pipe";
    const col = pipe ? C.blue : kind === "tapW" ? C.red : C.slate;
    halves(g, s, 0, pipe ? 12 : 6, pipe ? C.ink : col);
    if (pipe) halves(g, s, 0, 6, col);
    if (straight) {   // a flange (pipe) or a clamp (tap) at every tile joint
      const [ex, ey] = s.edge(s.outEdge), half = pipe ? 9 : 6;
      if (ox) g.rect(ex - 2, cy - half, 4, 2 * half); else g.rect(cx - half, ey - 2, 2 * half, 4);
      g.fill(C.ink);
    }
  }
}

/** A rail tile: every piece's ties first, then every piece's two rails over them. One piece is a plain straight or
 *  curve; a junction tile (a destination peeling off a shared trunk) passes its straight and its curve together, so the
 *  tile shows both rails crossing over both sets of ties, with no plate or marker (spec §6, as in Factorio). */
export function paintRailTile(g: Graphics, ps: Piece[]) {
  for (const p of ps) railTies(g, p);
  for (const p of ps) railRails(g, p);
}

function railTies(g: Graphics, p: Piece) {
  const s = shape(p), { x, y } = s, [ox] = s.outEdge;
  if (s.straight) {
    for (let i = 0; i < 3; i++) { if (ox) g.rect(x + 2 + i * 8, y + 3, 4, T - 6); else g.rect(x + 3, y + 2 + i * 8, T - 6, 4); }
    g.fill(C.amber);
    return;
  }
  const [ix, iy] = s.corner, a = s.edge(s.inEdge), b = s.edge(s.outEdge);
  const a0 = Math.atan2(a[1] - iy, a[0] - ix);
  let d = Math.atan2(b[1] - iy, b[0] - ix) - a0;
  while (d > Math.PI) d -= 2 * Math.PI;
  while (d < -Math.PI) d += 2 * Math.PI;
  for (const f of [0.2, 0.5, 0.8]) {   // three ties fanned round the curve
    const t = a0 + d * f;
    g.moveTo(ix + 3 * Math.cos(t), iy + 3 * Math.sin(t)).lineTo(ix + 21 * Math.cos(t), iy + 21 * Math.sin(t));
  }
  g.stroke({ width: 4, color: C.amber });
}

function railRails(g: Graphics, p: Piece) {
  const s = shape(p), { x, y, cx, cy } = s, [ox] = s.outEdge;
  if (s.straight) for (const o of [-5, 5]) { if (ox) g.moveTo(x, cy + o).lineTo(x + T, cy + o); else g.moveTo(cx + o, y).lineTo(cx + o, y + T); }
  else for (const r of [7, 17]) arc(g, s, r);
  g.stroke({ width: 2, color: C.ink });
}

/** The rail pieces on top at each tile that holds more than one shape of rail (a junction where a destination peels
 *  off a shared trunk), by tile key; a shape held by several routes counts once. */
export function railJunctions(routes: RouteArms[], cols: number, order: number[] = routes.map((_, i) => i)): Map<number, { ps: Piece[]; ris: number[] }> {
  const all = new Map<number, { ps: Piece[]; ris: number[] }>();
  for (const ri of order) {
    const r = routes[ri];
    if (r.failed || r.kind !== "rail") continue;
    for (const p of r.pieces) {
      if (p.under) continue;
      const k = p.y * cols + p.x, t = all.get(k) ?? all.set(k, { ps: [], ris: [] }).get(k)!;
      if (!t.ris.includes(ri)) t.ris.push(ri);
      if (!t.ps.some((q) => q.in === p.in && q.out === p.out)) t.ps.push({ ...p, join: undefined, hoodBefore: false, hoodAfter: false });
    }
  }
  for (const [k, t] of all) if (t.ps.length < 2) all.delete(k);
  return all;
}

/** Underground: an entrance (run starts beyond the exit edge) or an exit (run ends beyond the entry edge) is a raised
 *  housing over the half of the tile toward the run, with a dark mouth on that edge. Painted apart from the piece bodies
 *  (see factoryOps) so no line's later body covers it. */
export function paintHousing(g: Graphics, p: Piece, kind: LineKind, both = false) {
  const s = shape(p);
  for (const [on, e, dir, at] of [[p.hoodBefore, s.outEdge, 1, "out"], [p.hoodAfter, s.inEdge, -1, "in"]] as [boolean, V, number, "in" | "out"][]) {
    if (!on) continue;
    let lane: V | undefined;   // two-way belt: the forward lane's offset from the edge midpoint, on the right of travel
    if (both && kind === "belt") { const m = s.edge(e), f = forwardLaneAt(p, at); lane = [f[0] - m[0], f[1] - m[1]]; }
    housing(g, s, kind, e, dir, lane);
  }
}

/** Which lane of a two-way belt carries the forward direction: always the right of travel. A straight puts it
 *  `offset` px along the right-hand normal; a corner puts it on the inner arc when the turn is clockwise (right),
 *  on the outer arc when it is anticlockwise (left), at radius `r` round the corner point. */
export function forwardLane(p: Piece): { side: "right" | "inner" | "outer"; offset?: number; r?: number } {
  if (p.in === p.out) return { side: "right", offset: 6 };
  const [ux, uy] = STEP[p.in], [vx, vy] = STEP[p.out];
  const right = ux * vy - uy * vx > 0;   // screen y points down, so a positive cross is a right turn
  return right ? { side: "inner", r: T / 2 - 6 } : { side: "outer", r: T / 2 + 6 };
}

/** Where the forward lane meets the piece's "in" or "out" edge, in pixels. */
export function forwardLaneAt(p: Piece, at: "in" | "out"): V {
  const s = shape(p), e = at === "in" ? s.inEdge : s.outEdge, m = s.edge(e), f = forwardLane(p);
  if (f.side === "right") {
    const [ux, uy] = STEP[p.out];
    return [m[0] - uy * f.offset!, m[1] + ux * f.offset!];   // right of travel on screen: (-uy, ux)
  }
  const [ix, iy] = s.corner, dx = m[0] - ix, dy = m[1] - iy, n = Math.hypot(dx, dy);
  return [ix + (dx / n) * f.r!, iy + (dy / n) * f.r!];
}

/** The underground housing on edge e; dir is +1 when travel heads out through e (entrance), -1 when it comes in (exit). */
function housing(g: Graphics, s: S, kind: LineKind, e: V, dir: number, lane?: V) {
  const [ex, ey] = s.edge(e), d = 12, w = 10;
  const [ux, uy] = [e[0] * dir, e[1] * dir];                  // along travel
  const rect = (a0: number, a1: number, b0: number, b1: number) => {   // a: depth from the edge inward, b: across, both px
    const ax = -e[0], ay = -e[1], bx = -ay, by = ax;
    const p = (a: number, b: number): V => [ex + ax * a + bx * b, ey + ay * a + by * b];
    return g.poly([...p(a0, b0), ...p(a1, b0), ...p(a1, b1), ...p(a0, b1)]);
  };
  rect(0, d, -w, w).fill(C.steel).stroke({ width: 1.5, color: C.ink });
  if (kind === "belt") {   // a chevron filling the housing half; a two-way belt shows both lanes', forward on the right of travel
    const cx = ex - e[0] * 7.5, cy = ey - e[1] * 7.5;
    if (lane) { chevron(g, cx + lane[0], cy + lane[1], ux, uy, 3.5, C.ink, 2.2); chevron(g, cx - lane[0], cy - lane[1], -ux, -uy, 3.5, C.ink, 2.2); }
    else chevron(g, cx, cy, ux, uy, 4.5, C.ink, 2.5);
  }
  else if (kind === "rail") for (const a of [3.5, 8.5]) rect(a - 1.5, a + 1.5, -w + 2, w - 2).fill(C.amber);
  else if (kind === "tapRW") { rect(4, 8, -w + 1, -0.5).fill(C.red); rect(4, 8, 0.5, w - 1).fill(C.slate); }
  else rect(4, 8, -w + 1, w - 1).fill(kind === "pipe" ? C.blue : kind === "tapW" ? C.red : C.slate);
  rect(0, 3, -w, w).fill(C.ink);                               // the dark mouth, facing the run
}

/** Two half-pieces from the joint to each joined edge, shifted `off` px to the right of travel, with a round elbow. */
function halves(g: Graphics, s: S, off: number, width: number, color: number) {
  const nIn: V = [s.inEdge[1] * off, -s.inEdge[0] * off];    // normal of the travel direction (-inEdge)
  const nOut: V = [-s.outEdge[1] * off, s.outEdge[0] * off];
  const jx = s.cx + nIn[0] + (s.straight ? 0 : nOut[0]), jy = s.cy + nIn[1] + (s.straight ? 0 : nOut[1]);
  for (const [e, n] of [[s.inEdge, nIn], [s.outEdge, nOut]] as [V, V][]) {
    const [ex, ey] = s.edge(e);
    g.moveTo(jx, jy).lineTo(ex + n[0], ey + n[1]);
  }
  g.stroke({ width, color });
  if (!s.straight) g.circle(jx, jy, width / 2).fill(color);
}

/** A selected line's underground tile: a dashed outline where it runs under. */
export function paintGhost(g: Graphics, p: Piece) {
  const x = p.x * T + 3, y = p.y * T + 3, w = T - 6;
  for (let d = 0; d < w; d += 6) {
    const e = Math.min(w, d + 3);
    g.moveTo(x + d, y).lineTo(x + e, y).moveTo(x + d, y + w).lineTo(x + e, y + w)
      .moveTo(x, y + d).lineTo(x, y + e).moveTo(x + w, y + d).lineTo(x + w, y + e);
  }
  g.stroke({ width: 2, color: C.select, alpha: 0.9 });
}

/** The directions from a tile toward the underground runs that start or end at it (an entrance looks along its travel,
 *  an exit looks back along it). */
export function runDirs(p: Piece): Dir[] {
  const out: Dir[] = [];
  if (p.hoodBefore) out.push(p.out);
  if (p.hoodAfter) out.push(OPP[p.in]);
  return out;
}

export { joinEdge };   // lives in tiles.ts, which imports no Pixi (the map audit needs it)

/** A junction's hazard plate: the whole tile, yellow with three diagonal ink stripes. Painted after every line so no piece
 *  hides it. The router gives a junction room (a straight trunk, plain tiles round it), so nothing else stands on its tile. */
export function paintPlate(g: Graphics, p: Piece) {
  const x = p.x * T + 1, y = p.y * T + 1, w = T - 2, h = T - 2;
  g.rect(x, y, w, h).fill(C.yellow).stroke({ width: 1.5, color: C.ink });
  for (let sx = x + 3; sx + 4 < x + w - 1; sx += 6) g.moveTo(sx, y + h - 3).lineTo(sx + 4, y + 3);
  g.stroke({ width: 1.4, color: C.ink });
}

/** The edges one belt tile is entered or left by, over every route on top of it. */
export interface Arms { x: number; y: number; ris: number[]; edges: Map<Dir, { enter: boolean; leave: boolean; both: boolean }>; joins: Dir[] }

/** What one shared belt tile draws: the trunk's piece (two-way lanes when anything runs both ways) and a half arm for each
 *  branch, with the way its travel runs (`in` toward the tile's centre, `out` away from it). */
export interface TileBody { p: Piece; both: boolean; branches: { edge: Dir; flow: "in" | "out" | "both" }[] }

type RouteArms = { pieces: Piece[]; kind: LineKind; failed?: boolean; both?: boolean };

/** The arms of every tile that two or more live belt routes hold on top. */
export function tileArms(routes: RouteArms[], cols: number, order: number[] = routes.map((_, i) => i)): Map<number, Arms> {
  const all = new Map<number, Arms>();
  for (const ri of order) {
    const r = routes[ri];
    if (r.failed || r.kind !== "belt") continue;
    for (const p of r.pieces) {
      if (p.under) continue;
      const k = p.y * cols + p.x;
      const a = all.get(k) ?? all.set(k, { x: p.x, y: p.y, ris: [], edges: new Map(), joins: [] }).get(k)!;
      if (!a.ris.includes(ri)) a.ris.push(ri);
      for (const [e, enter] of [[OPP[p.in], true], [p.out, false]] as [Dir, boolean][]) {
        const st = a.edges.get(e) ?? a.edges.set(e, { enter: false, leave: false, both: false }).get(e)!;
        if (enter) st.enter = true; else st.leave = true;
        if (r.both) st.both = true;
      }
      if (p.join && !a.joins.includes(joinEdge(p))) a.joins.push(joinEdge(p));
    }
  }
  for (const [k, a] of all) if (a.ris.length < 2) all.delete(k);
  return all;
}

/** One body for a tile's arms: a straight or a turn, plus a half arm per branch edge. Null when the arms are not a trunk
 *  with branches (a four-way meeting cannot happen on top: a crossing goes underground). */
export function bodyFor(a: Arms): TileBody | null {
  const E = [...a.edges.keys()], J = a.joins.filter((e) => a.edges.has(e));
  let trunk: Dir[], branches: Dir[];
  if (E.length === 2) { trunk = E; branches = []; }   // a marked junction whose branch runs along the trunk's own edges: just the trunk
  else if (J.length) { trunk = E.filter((e) => !J.includes(e)); branches = J; }
  else if (E.length === 3) {   // no marked junction: the opposite pair is the trunk
    const pair = E.find((e) => E.includes(OPP[e]))!;
    trunk = [pair, OPP[pair]]; branches = E.filter((e) => !trunk.includes(e));
  } else { trunk = E; branches = []; }
  if (trunk.length !== 2) return null;
  const [ea, eb] = trunk, sa = a.edges.get(ea)!, sb = a.edges.get(eb)!;
  const first = sa.enter || !sb.enter ? ea : eb, last = first === ea ? eb : ea;   // the travel enters by `first`
  const both = [sa, sb].some((s) => s.both || (s.enter && s.leave)) || (sa.enter && sb.enter);
  const flow = (e: Dir) => { const s = a.edges.get(e)!; return s.both || (s.enter && s.leave) ? "both" : s.enter ? "in" : "out"; };
  return {
    p: { x: a.x, y: a.y, in: OPP[first], out: last, under: false, hoodBefore: false, hoodAfter: false },
    both,
    branches: branches.map((edge) => ({ edge, flow: flow(edge) as "in" | "out" | "both" })),
  };
}

/** A shared belt tile: one piece, two-way when anything on it runs both ways. */
export function paintTile(g: Graphics, t: TileBody) {
  paintPiece(g, t.p, "belt", t.both);
}

/** An inferred line's tile: a dashed paper outline inset 2 px (4 on, 3 off). */
export function paintInferred(g: Graphics, p: Piece) {
  const x = p.x * T + 2, y = p.y * T + 2, w = T - 4, ring = 4 * w;
  const at = (d: number): [number, number] => d < w ? [x + d, y] : d < 2 * w ? [x + w, y + d - w] : d < 3 * w ? [x + w - (d - 2 * w), y + w] : [x, y + w - (d - 3 * w)];
  for (let d = 0; d < ring; d += 7) {
    const e = Math.min(d + 4, ring);
    const [ax, ay] = at(d);
    g.moveTo(ax, ay);
    for (const k of [w, 2 * w, 3 * w]) if (d < k && e > k) { const [cx, cy] = at(k); g.lineTo(cx, cy); }
    const [bx, by] = at(e >= ring ? ring - 0.001 : e);
    g.lineTo(bx, by);
  }
  g.stroke({ width: 1.5, color: C.paper });
}

/** One painting step of a factory floor. Steps come in layer order: every body (and shared belt and rail tile), then every housing, then plates, then
 *  inferred rings, so a later line's body can never cover an underground housing. `holders` are the routes (indices)
 *  that have a piece on top at a plate's tile. */
export interface Op { layer: "body" | "tile" | "rail" | "housing" | "plate" | "inferred"; ri: number; p: Piece; holders?: number[]; tile?: TileBody; both?: boolean;
  /** a rail junction tile (`layer: "rail"`): its straight and its curve, painted together by `paintRailTile` */ rails?: Piece[] }

export function factoryOps(routes: (RouteArms & { inferred?: boolean })[], cols: number, order: number[] = routes.map((_, i) => i)): Op[] {
  const live = order.filter((i) => !routes[i].failed && routes[i].kind !== ("drone" as LineKind));
  const ops: Op[] = [];
  // a belt tile several routes hold is ONE body composed from all of them, never two full pieces on top of each other;
  // a junction tile is the plate alone (the router leaves the plain tiles round it to show what joins)
  const composed = new Map<number, TileBody>(), armsAt = tileArms(routes, cols, live);
  for (const [k, a] of armsAt) { const b = bodyFor(a); if (b) composed.set(k, b); }
  // a rail junction is ONE tile with the trunk's straight and the branch's curve, lit with every rail on it; no plate
  const railAt = railJunctions(routes, cols, live);
  for (const ri of live) for (const p of routes[ri].pieces) if (!p.under) {
    if (routes[ri].kind === "belt" && composed.has(p.y * cols + p.x)) continue;
    if (routes[ri].kind === "rail" && railAt.has(p.y * cols + p.x)) continue;
    ops.push({ layer: "body", ri, p });
  }
  for (const [k, tile] of composed) if (!armsAt.get(k)!.joins.length) ops.push({ layer: "tile", ri: armsAt.get(k)!.ris[0], p: tile.p, tile, holders: armsAt.get(k)!.ris });
  for (const [, t] of railAt) ops.push({ layer: "rail", ri: t.ris[0], p: t.ps[0], rails: t.ps, holders: t.ris });
  const housed = new Map<string, Op>();   // one housing per tile, hood and kind, however many routes stand there
  for (const ri of live) for (const p of routes[ri].pieces) if (!p.under && (p.hoodBefore || p.hoodAfter)) {
    const key = `${p.y * cols + p.x}|${p.hoodBefore ? p.out : "-"}|${p.hoodAfter ? p.in : "-"}|${routes[ri].kind}`, seen = housed.get(key);
    if (seen) { seen.both = seen.both || !!routes[ri].both; continue; }
    const o: Op = { layer: "housing", ri, p, both: !!routes[ri].both };
    housed.set(key, o);
    ops.push(o);
  }
  const holders = new Map<number, number[]>();
  for (const ri of live) for (const p of routes[ri].pieces) if (!p.under) {
    const k = p.y * cols + p.x;
    holders.set(k, [...(holders.get(k) ?? []), ri]);
  }
  const done = new Set<number>();   // one plate per junction tile
  for (const ri of live) for (const p of routes[ri].pieces) {
    const k = p.y * cols + p.x;
    if (!p.join || p.under || done.has(k) || routes[ri].kind === "rail") continue;
    done.add(k);
    ops.push({ layer: "plate", ri, p, holders: holders.get(k)! });
  }
  for (const ri of live) if (routes[ri].inferred) for (const p of routes[ri].pieces) if (!p.under) ops.push({ layer: "inferred", ri, p });
  return ops;
}
