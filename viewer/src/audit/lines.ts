// The line checks of the map audit: plug-in ends, the trunk rules, underground runs, mid-side ends, junction plates
// off the walls, failed routes. Each is pure and returns its violations ([] when the rule holds). No Pixi here.
import { reservedRects } from "../factory/pads";
import type { TileFloor } from "../factory/layout";
import type { TileRoute } from "../factory/router";
import { LANE_H, OPP, STEP, inside, joinEdge, type Dir, type Piece, type Rect } from "../factory/tiles";
import { stationId, yardId } from "../factory/yards";
import { webhookDockId } from "../factory/pads";
import type { Violation } from "./types";

/** A line's possible ends, by id: its key's two boxes (or lanes), for a rail the rail yards and stations, and for an
 *  inbound webhook its service's receiving dock (the belt plugs into the dock, not the wall). */
export function endRects(tf: TileFloor, r: TileRoute): [string, Rect][] {
  // a stand-in rail's key (`rail:<relation>`) names no box or lane: only its yard and station are its ends
  const out: [string, Rect][] = r.key.split("|").flatMap((id): [string, Rect][] => {
    const lane = tf.lanes.find((l) => l.id === id), box = tf.boxes.get(id);
    return lane ? [[id, { x: lane.x0, y: lane.y, w: lane.x1 - lane.x0, h: LANE_H }]] : box ? [[id, box]] : [];
  });
  for (const d of tf.webhooks ?? []) if (d.keys.includes(r.key)) out.push([webhookDockId(d.machine), d]);
  if (r.kind === "rail" && tf.rails) {
    for (const y of tf.rails.yards) out.push([yardId(y.source), y]);
    for (const s of tf.rails.stations) out.push([stationId(s), s]);
  }
  return out;
}

/** Which of the line's two endpoints (by id) its first piece leaves and its last piece arrives at: the data flow. An
 *  end that touches no box (a line plugged into empty floor, which `lines.plugged` reports) goes by its tile. */
export function flowOf(tf: TileFloor, r: TileRoute): { src: string; dst: string } {
  const ends = endRects(tf, r);
  const ps = r.pieces, f = ps[0], l = ps[ps.length - 1];
  const hit = (x: number, y: number) => ends.find(([, e]) => inside(e, x, y))?.[0] ?? `tile ${x},${y}`;
  return { src: hit(f.x - STEP[f.in][0], f.y - STEP[f.in][1]), dst: hit(l.x + STEP[l.out][0], l.y + STEP[l.out][1]) };
}

type Held = { r: TileRoute; i: number }[];

/** The trunk rules: one trunk per line, one junction, labelled by data flow. (Junction plates off the walls is its own
 *  check: `plateWallViolations`.) */
export function trunkViolations(tf: TileFloor, routes: TileRoute[]): Violation[] {
  const out: Violation[] = [];
  const bad = (detail: string, at?: { x: number; y: number }) => out.push(at ? { detail, at } : { detail });
  const lines = routes.filter((r) => r.pieces.length);
  const flow = new Map(lines.map((r) => [r, flowOf(tf, r)]));
  const onTop = new Map<string, Held>();
  const below = new Map<string, Held>();
  for (const r of lines) r.pieces.forEach((p, i) => {
    const m = p.under ? below : onTop, k = `${p.x},${p.y}`;
    (m.get(k) ?? m.set(k, []).get(k)!).push({ r, i });
  });
  /** The tiles just before and after the underground run holding piece i: where it goes under and comes up. */
  const run = (ps: Piece[], i: number) => {
    let a = i, b = i;
    while (ps[a - 1]?.under) a--;
    while (ps[b + 1]?.under) b++;
    const f = ps[a - 1], l = ps[b + 1];
    return `${f?.x},${f?.y}>${l?.x},${l?.y}`;
  };
  /** A trunk goes under as one belt: piece i of r runs underground with a partner sharing `end`, same way, entering and leaving together. */
  const underWith = (r: TileRoute, i: number, end: "src" | "dst") => {
    const p = r.pieces[i], f = flow.get(r)!;
    return (below.get(`${p.x},${p.y}`) ?? []).some((o) => o.r !== r && flow.get(o.r)![end] === f[end]
      && o.r.pieces[o.i].in === p.in && run(o.r.pieces, o.i) === run(r.pieces, i));
  };
  // (c) no line repeats a tile on top; (a) no line runs lengthwise under a line it shares an end with
  for (const r of lines) {
    const seen = new Set<string>();
    for (const p of r.pieces) if (!p.under) {
      const k = `${p.x},${p.y}`;
      if (seen.has(k)) bad(`${r.key} repeats tile ${k}`, p);
      seen.add(k);
    }
    const f = flow.get(r)!;
    for (const p of r.pieces) if (p.under) {
      for (const o of onTop.get(`${p.x},${p.y}`) ?? []) {
        const fo = flow.get(o.r)!;
        if (o.r === r || (fo.src !== f.src && fo.dst !== f.dst)) continue;
        const along = (o.r.pieces[o.i].in === "n" || o.r.pieces[o.i].in === "s") === (p.in === "n" || p.in === "s");
        if (along) bad(`${r.key} runs under ${o.r.key} at ${p.x},${p.y}, along it`, p);
      }
      // underground beside a partner, along it: only as one trunk run (same way, in and out together)
      r.pieces.forEach((q, i) => {
        if (q !== p) return;
        for (const o of below.get(`${p.x},${p.y}`) ?? []) {
          const fo = flow.get(o.r)!, oq = o.r.pieces[o.i];
          if (o.r === r || (fo.src !== f.src && fo.dst !== f.dst)) continue;
          if ((oq.in === "n" || oq.in === "s") !== (p.in === "n" || p.in === "s")) continue;
          const one = (fo.src === f.src && underWith(r, i, "src")) || (fo.dst === f.dst && underWith(r, i, "dst"));
          if (!one) bad(`${r.key} runs under with ${o.r.key} at ${p.x},${p.y} but not as one trunk`, p);
        }
      });
    }
  }
  // (b) riding stays on one partner's path: consecutive shared tiles are consecutive pieces of another line
  for (const r of lines) for (let i = 0; i + 1 < r.pieces.length; i++) {
    const p = r.pieces[i], q = r.pieces[i + 1];
    if (p.under || q.under) continue;
    const hold = (x: number, y: number) => (onTop.get(`${x},${y}`) ?? []).filter((o) => o.r !== r);
    const hp = hold(p.x, p.y), hq = hold(q.x, q.y);
    if (!hp.length || !hq.length) continue;
    const same = hp.some((a) => hq.some((b) => a.r === b.r && b.i === a.i + 1));
    if (!same) bad(`${r.key} hops between lines at ${q.x},${q.y}`, q);
  }
  for (const [k, list] of onTop) for (let a = 0; a < list.length; a++) for (let b = a + 1; b < list.length; b++) {
    const A = list[a], B = list[b];
    if (A.r === B.r) continue;   // repeats are reported above
    const pa = A.r.pieces[A.i], pb = B.r.pieces[B.i], fa = flow.get(A.r)!, fb = flow.get(B.r)!;
    const leaving = fa.src === fb.src && pa.in === pb.in, arriving = fa.dst === fb.dst && pa.out === pb.out;
    if (!(leaving || arriving)) bad(`${A.r.key} and ${B.r.key} share ${k} without sharing a source (same way in) or a target (same way out)`, pa);
    const joins = [A.r, B.r].map((r) => r.pieces.filter((p) => p.join).length);
    if (!(Math.max(...joins) > 0)) bad(`${A.r.key} and ${B.r.key} share ${k} but neither has a junction`, pa);
  }
  for (const r of lines) {
    const js = r.pieces.map((p, i) => [p, i] as const).filter(([p]) => p.join);
    if (js.length > 1) bad(`${r.key} has more than one junction`, js[1][0]);
    if (!js.length) continue;
    const [p, i] = js[0], { src, dst } = flow.get(r)!;
    junctionRoom(onTop, below, r, p, bad);
    const here = (onTop.get(`${p.x},${p.y}`) ?? []).filter((o) => o.r !== r);
    if (!(here.length > 0)) bad(`${r.key} junction on a tile nobody else holds`, p);
    // on a trunk: each tile shared on top, or underground in the trunk's own run
    const sharedAt = (k: number, end: "src" | "dst") => {
      const q = r.pieces[k];
      return q.under ? underWith(r, k, end) : (onTop.get(`${q.x},${q.y}`) ?? []).some((o) => o.r !== r);
    };
    if (p.join === "split") {
      if (!here.some((o) => flow.get(o.r)!.src === src)) bad(`${r.key} split without a shared source`, p);
      for (let k = 0; k <= i; k++) if (!sharedAt(k, "src")) bad(`${r.key} not on a trunk before its split`, r.pieces[k]);
    } else {
      if (!here.some((o) => flow.get(o.r)!.dst === dst)) bad(`${r.key} merge without a shared target`, p);
      for (let k = i; k < r.pieces.length; k++) if (!sharedAt(k, "dst")) bad(`${r.key} not on a trunk after its merge`, r.pieces[k]);
    }
  }
  return out;
}

/** Room round a junction (2 in, 1 out): the trunk runs straight through it, and the trunk tiles either side and the branch's
 *  first tile are plain pieces -- no other junction, no underground housing. */
function junctionRoom(onTop: Map<string, Held>, below: Map<string, Held>, r: TileRoute, p: Piece, bad: (d: string, at?: { x: number; y: number }) => void) {
  const at = `${r.key} junction ${p.x},${p.y}`;
  const here = onTop.get(`${p.x},${p.y}`)!;
  const branch = joinEdge(p), edges = new Set<Dir>();
  for (const { r: o, i } of here) { const q = o.pieces[i]; edges.add(OPP[q.in]); edges.add(q.out); }
  edges.delete(branch);
  const trunk = [...edges];
  if (!(trunk.length === 2 && OPP[trunk[0]] === trunk[1])) bad(`${at}: the trunk does not run straight (${trunk})`, p);
  const plain = (d: Dir, what: string) => {
    const k = `${p.x + STEP[d][0]},${p.y + STEP[d][1]}`;
    for (const { r: o, i } of onTop.get(k) ?? []) {
      const q = o.pieces[i];
      if (q.join !== undefined) bad(`${at}: ${what} is another junction`, p);
      if (q.hoodBefore || q.hoodAfter) bad(`${at}: ${what} is an underground housing`, p);
    }
    if (below.has(k) && !onTop.has(k)) bad(`${at}: ${what} is underground`, p);
  };
  for (const d of trunk) plain(d, "the trunk tile " + d);
  plain(branch, "the branch tile");
  for (const { r: o, i } of here) { const q = o.pieces[i]; if (q.hoodBefore || q.hoodAfter) bad(`${at}: a housing on the junction`, p); }
}

/** Every tile line is a contiguous chain whose ends plug into its two endpoints, and never sits on a machine. */
export function pluggedViolations(tf: TileFloor, r: TileRoute): Violation[] {
  const out: Violation[] = [];
  const ps = r.pieces;
  if (!ps.length) return out;
  const ends = endRects(tf, r).map(([, e]) => e);
  for (let i = 1; i < ps.length; i++) {
    const a = ps[i - 1], p = ps[i];
    if (p.x !== a.x + STEP[a.out][0] || p.y !== a.y + STEP[a.out][1])
      out.push({ detail: `${r.key} breaks between piece ${i - 1} and ${i}: expected ${a.x + STEP[a.out][0]},${a.y + STEP[a.out][1]}, got ${p.x},${p.y}`, at: { x: p.x, y: p.y } });
    else if (p.in !== a.out) out.push({ detail: `${r.key} piece ${i} comes in by ${p.in}, the piece before leaves by ${a.out}`, at: { x: p.x, y: p.y } });
  }
  const before = { x: ps[0].x - STEP[ps[0].in][0], y: ps[0].y - STEP[ps[0].in][1] };
  const last = ps[ps.length - 1];
  const after = { x: last.x + STEP[last.out][0], y: last.y + STEP[last.out][1] };
  const hit = (p: { x: number; y: number }) => ends.findIndex((e: Rect) => inside(e, p.x, p.y));
  const hb = hit(before), ha = hit(after);
  if (hb < 0) out.push({ detail: `${r.key} starts in empty floor`, at: before });
  if (ha < 0) out.push({ detail: `${r.key} ends in empty floor`, at: after });
  if (hb === ha) out.push({ detail: `${r.key} starts and ends at the same endpoint`, at: before });
  for (const p of ps) for (const b of tf.boxes.values()) if (inside(b, p.x, p.y)) out.push({ detail: `${r.key} on ${b.id}`, at: { x: p.x, y: p.y } });
  for (const p of ps) if (p.under && p.in !== p.out) out.push({ detail: `${r.key} turns underground`, at: { x: p.x, y: p.y } });
  return out;
}

/** Every underground run has an above-ground piece before it and one after it (where it goes under and comes up). */
export function underViolations(r: TileRoute): Violation[] {
  const out: Violation[] = [];
  const ps = r.pieces;
  for (let i = 0; i < ps.length; i++) {
    if (!ps[i].under || ps[i - 1]?.under) continue;   // only a run's first piece
    let e = i;
    while (ps[e + 1]?.under) e++;
    const at = { x: ps[i].x, y: ps[i].y };
    if (i === 0) out.push({ detail: `${r.key} starts underground at ${at.x},${at.y}: no piece before the run`, at });
    if (e === ps.length - 1) out.push({ detail: `${r.key} ends underground at ${ps[e].x},${ps[e].y}: no piece after the run`, at: { x: ps[e].x, y: ps[e].y } });
  }
  return out;
}

/** Line ends that sit in the outermost tile of a machine side (sides of 3+ tiles) and turn on the tile next to the box,
 *  while that side's middle tile holds no end of any line: row 13's lines that "plug in beside a box's corner after an
 *  extra turn, not mid-side". A straight run out of a corner tile is allowed: the router charges a corner end about a
 *  turn (router.ts `CORNER`), so it plugs in there only when that beats leaving mid-side with turns. */
export function midSideViolations(tf: TileFloor, routes: TileRoute[]): Violation[] {
  type End = { box: string; side: Dir; i: number; n: number; x: number; y: number; key: string; turns: boolean };
  const ends: End[] = [];
  const add = (b: Rect & { id: string }, x: number, y: number, side: Dir, key: string, turns: boolean) => {
    if (!inside(b, x, y)) return;
    const vertical = side === "n" || side === "s";
    ends.push({ box: b.id, side, i: vertical ? x - b.x : y - b.y, n: vertical ? b.w : b.h, x, y, key, turns });
  };
  for (const r of routes) {
    if (!r.pieces.length) continue;
    const f = r.pieces[0], l = r.pieces[r.pieces.length - 1];
    for (const b of tf.boxes.values()) {
      add(b, f.x - STEP[f.in][0], f.y - STEP[f.in][1], f.in, r.key, f.in !== f.out);          // leaves the box by the side it travels towards
      add(b, l.x + STEP[l.out][0], l.y + STEP[l.out][1], OPP[l.out], r.key, l.in !== l.out);   // arrives at the side facing it
    }
  }
  const out: Violation[] = [];
  const reserved = reservedRects(tf);
  for (const e of ends) {
    if (!e.turns || e.n < 3 || !(e.i === 0 || e.i === e.n - 1)) continue;
    const mids = [Math.floor((e.n - 1) / 2), Math.ceil((e.n - 1) / 2)];
    const b = tf.boxes.get(e.box)!, vertical = e.side === "n" || e.side === "s";
    // the tile just outside the side at index i: a dock or stack standing there holds the middle as a line end would
    const beside = (i: number) => vertical ? { x: b.x + i, y: e.side === "n" ? b.y - 1 : b.y + b.h } : { x: e.side === "w" ? b.x - 1 : b.x + b.w, y: b.y + i };
    const held = mids.some((i) => { const t = beside(i); return reserved.some((r) => t.x >= r.x && t.x < r.x + r.w && t.y >= r.y && t.y < r.y + r.h); });
    const taken = held || ends.some((o) => o.box === e.box && o.side === e.side && mids.includes(o.i));
    if (!taken) out.push({ detail: `${e.key} ends in the ${e.i === 0 ? "first" : "last"} tile of ${e.box}'s ${e.side} side and turns while its middle tile is free`, at: { x: e.x, y: e.y } });
  }
  return out;
}

/** A junction plate keeps off the factory walls: its tile touches no machine box on any side (the owner's 2026-10-06
 *  comment: a plate right against a wall reads as part of the machine). Pads and docks are meant to touch theirs. */
export function plateWallViolations(tf: TileFloor, r: TileRoute): Violation[] {
  const out: Violation[] = [];
  for (const p of r.pieces) if (p.join)
    for (const b of tf.boxes.values()) for (const d of ["n", "e", "s", "w"] as Dir[])
      if (inside(b, p.x + STEP[d][0], p.y + STEP[d][1])) out.push({ detail: `${r.key} junction ${p.x},${p.y} touches ${b.id} (${d})`, at: { x: p.x, y: p.y } });
  return out;
}

/** Failed routes: any on a floor of fewer than 100 routes, more than 1% of them on a bigger one. */
export function failedViolations(routes: TileRoute[]): Violation[] {
  const failed = routes.filter((r) => r.failed);
  if (!failed.length) return [];
  if (routes.length >= 100 && failed.length <= routes.length * 0.01) return [];
  return [{ detail: `${failed.length} of ${routes.length} routes failed: ${failed.map((r) => r.key).join(", ")}` }];
}
