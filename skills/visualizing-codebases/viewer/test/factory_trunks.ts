// Shared checks for tile lines: plug-in ends and the trunk rules (one trunk per line, one junction, labelled by data flow).
import { expect } from "vitest";
import type { TileFloor } from "../src/factory/layout";
import type { TileRoute } from "../src/factory/router";
import { LANE_H, STEP, inside, type Dir, type Rect } from "../src/factory/tiles";
import { exitOf } from "../src/factory/yards";
import { flowOf, pluggedViolations, plateWallViolations, trunkViolations } from "../src/audit/lines";
import type { Piece } from "../src/factory/tiles";

export { flowOf };

/** The trunk rules (and junction plates off the walls) over a floor's lines; the checks themselves live in src/audit/lines.ts. */
export function checkTrunks(tf: TileFloor, routes: TileRoute[], label = "") {
  expect([...trunkViolations(tf, routes), ...routes.flatMap((r) => plateWallViolations(tf, r))].map((v) => v.detail), label).toEqual([]);
}

/** Every tile line is a contiguous chain whose ends plug into its two endpoints, and never sits on a machine. */
export function plugged(tf: TileFloor, r: TileRoute) {
  expect(pluggedViolations(tf, r).map((v) => v.detail), r.key).toEqual([]);
}

/** How many line ends plug into a machine side's outermost tile (sides of 3+ tiles only) -- the ends that should sit mid-side. */
export function outerEnds(tf: TileFloor, routes: TileRoute[]): { ends: number; outer: number } {
  let ends = 0, outer = 0;
  const count = (b: Rect | undefined, x: number, y: number, d: "n" | "e" | "s" | "w") => {
    if (!b || !inside(b, x, y)) return false;
    const vertical = d === "n" || d === "s", n = vertical ? b.w : b.h, i = vertical ? x - b.x : y - b.y;
    ends++;
    if (n >= 3 && (i === 0 || i === n - 1)) outer++;
    return true;
  };
  for (const r of routes) {
    if (!r.pieces.length) continue;
    const f = r.pieces[0], l = r.pieces[r.pieces.length - 1];
    for (const b of tf.boxes.values()) {
      count(b, f.x - STEP[f.in][0], f.y - STEP[f.in][1], f.in) ;
      count(b, l.x + STEP[l.out][0], l.y + STEP[l.out][1], l.out);
    }
  }
  return { ends, outer };
}

/** A junction plate keeps off the factory walls: its tile touches no machine box on any side. */
export function offWalls(tf: TileFloor, r: TileRoute, p: Piece, label: string) {
  expect(plateWallViolations(tf, { ...r, pieces: [p] }).map((v) => v.detail), label).toEqual([]);
}

/** Rail yards and stations have their place: every yard of the floor's batch stands flush against its machine's side
 *  (a free-standing yard in the in column, one free row below its door; an inner yard with no door at the floor's
 *  left edge) at its footprint (level, 4 wide or 5 with a ladder's throat, a row per platform), every station flush against its destination's
 *  side; none overlaps a box, lane, dock, stack, other yard, station or sign, or leaves the floor; no line runs over or
 *  under one. Every station has exactly one rail (its `track`), routed: it leaves through the tile past one of the yard's
 *  platforms (its own unless it rides a trunk out; on a ladder, past the throat at its own exit row), off the row's
 *  end, and ends on its station's entry, running into
 *  the station along the wall; it is plugged. Nothing is unplaced. Returns the rails checked (one per station). */
export function checkRails(tf: TileFloor, routes: TileRoute[], bundles: { key: string; kind: string }[], label = ""): number {
  const r = tf.rails;
  if (!r) return 0;
  const ov = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  const touches = (o: Rect, m: Rect, side: Dir) => {
    const flush = side === "e" ? o.x === m.x + m.w : side === "w" ? o.x + o.w === m.x : side === "s" ? o.y === m.y + m.h : o.y + o.h === m.y;
    const span = side === "e" || side === "w" ? o.y < m.y + m.h && m.y < o.y + o.h : o.x < m.x + m.w && m.x < o.x + o.w;
    return flush && span;
  };
  const held: [string, Rect][] = [];
  expect(r.unplaced, `${label} every yard and station placed`).toEqual([]);
  expect(r.yards.length, `${label} every yard placed`).toBe(r.batch.yards.length);
  for (const y of r.yards) {
    const n = r.batch.yards.find((b) => b.source === y.source)!.platforms.length;
    const upright = y.side === "e" || y.side === "w";
    // level on every side, no header row: 4 wide (5 with a ladder's throat), a row per platform (a self-only yard is a 4x1 strip)
    expect([y.w, y.h], `${label} yard ${y.source} footprint`).toEqual([y.ladder ? 5 : 4, Math.max(1, n)]);
    // its rails leave the row ends: away from the machine against an e or w side, along an n or s side
    expect(upright ? y.out === y.side : y.out === "e" || y.out === "w", `${label} yard ${y.source} rails leave by ${y.out}`).toBe(true);
    // an inner yard at a door of the in column lands in the rows the layout kept for it, not beside its door
    if (r.batch.yards.find((b) => b.source === y.source)!.inner && tf.boxes.get(y.machine!)?.region === "in") expect(y.free, `${label} yard ${y.source} stands free in the rows kept for it`).toBe(true);
    if (y.free) {
      const door = tf.boxes.get(y.machine!)!, col = tf.zones.find((z) => z.name === "in")!;
      expect([door.region, y.y, y.x >= door.x && y.x + y.w <= door.x + door.w], `${label} yard ${y.source} below its door in the in column`).toEqual(["in", door.y + door.h + 1, true]);
      expect(y.y + y.h < col.y + col.h - 1, `${label} yard ${y.source} inside the in column, off its name's row`).toBe(true);
    } else if (y.machine) expect(touches(y, tf.boxes.get(y.machine)!, y.side), `${label} yard ${y.source} flush against ${y.machine} ${y.side}`).toBe(true);
    else expect(y.x, `${label} yard ${y.source} at the left edge`).toBeLessThanOrEqual(3);
    expect(y.platforms.length, `${label} yard ${y.source} one platform per destination`).toBe(n);
    for (const p of y.platforms) {
      expect(inside(y, p.x, p.y), `${label} platform ${p.dest} in its yard`).toBe(true);
      // at its row's end; on a ladder, the throat between it and the row's end
      const k = y.ladder ? 2 : 1;
      expect([inside(y, p.x + STEP[y.out][0] * (k - 1), p.y), inside(y, p.x + STEP[y.out][0] * k, p.y)], `${label} platform ${p.dest} at its row's end`).toEqual([true, false]);
    }
    held.push([`yard ${y.source}`, y]);
    if (y.sign) {
      const s = { x: y.sign.x, y: y.sign.y, w: 1, h: 1 };
      if (n) {
        expect(inside(y, s.x, s.y), `${label} sign of ${y.source} beside its yard`).toBe(false);
        expect(ov({ x: y.x - 1, y: y.y - 1, w: y.w + 2, h: y.h + 2 }, s), `${label} sign of ${y.source} touches its yard`).toBe(true);
        held.push([`sign ${y.source}`, s]);
      } else expect(inside(y, s.x, s.y), `${label} sign of ${y.source} inside its 4x1 yard`).toBe(true);
    }
  }
  expect(r.stations.filter((s) => !s.door).length, `${label} a station per platform`).toBe(r.yards.reduce((t, y) => t + y.platforms.length, 0));
  for (const s of r.stations) {
    const d = tf.boxes.get(s.dest)!;
    expect(touches(s, d, s.side), `${label} station ${s.source}>${s.dest} flush against its ${s.side} side`).toBe(true);
    const along = s.side === "n" || s.side === "s" ? s.w : s.h;
    expect([Math.min(s.w, s.h), along >= 1 && along <= 3], `${label} station 1 deep, up to 3 long`).toEqual([1, true]);
    const e = s.entry;
    expect(inside(s, e.x + STEP[e.d][0], e.y + STEP[e.d][1]) && !inside(s, e.x, e.y), `${label} station ${s.dest} entry runs into it`).toBe(true);
    expect([...tf.boxes.values()].some((b) => touches({ x: e.x, y: e.y, w: 1, h: 1 }, b, s.side) && b.id === s.dest), `${label} station ${s.dest} entry along its wall`).toBe(true);
    held.push([`station ${s.source}>${s.dest}`, s]);
  }
  const others: [string, Rect][] = [
    ...[...tf.boxes.values()].map((b) => [`box ${b.id}`, b] as [string, Rect]),
    ...tf.lanes.map((l) => [`lane ${l.id}`, { x: l.x0, y: l.y, w: l.x1 - l.x0, h: LANE_H }] as [string, Rect]),
    ...(tf.landing?.docks ?? []).map((d) => [`dock ${d.machine}`, d] as [string, Rect]),
    ...(tf.stacks ?? []).map((s) => [`stack ${s.item}`, { x: s.x, y: s.y, w: 1, h: 1 }] as [string, Rect]),
  ];
  for (const [name, h] of held) {
    expect(h.x >= 0 && h.y >= 0 && h.x + h.w <= tf.cols && h.y + h.h <= tf.rows, `${label} ${name} on the floor`).toBe(true);
    for (const [o, q] of [...others, ...held]) if (o !== name) expect(ov(h, q), `${label} ${name} overlaps ${o}`).toBe(false);
    for (const q of routes) for (const p of q.pieces) expect(inside(h, p.x, p.y), `${label} ${q.key} runs ${p.under ? "under" : "over"} ${name}`).toBe(false);
  }
  let rails = 0;
  for (const st of r.stations) {
    const mine = routes.filter((q) => q.key === st.track);
    expect(mine.length, `${label} station ${st.source}>${st.dest} has exactly one rail`).toBe(1);
    const q = mine[0];
    expect([q.kind, !!q.failed, q.pieces.length > 0], `${label} ${q.key} a routed rail`).toEqual(["rail", false, true]);
    if (!st.track.startsWith("rail:")) expect(bundles.find((x) => x.key === st.track)?.kind, `${label} ${q.key} a batch bundle`).toBe("batch");
    rails++;
    const f = q.pieces[0], l = q.pieces[q.pieces.length - 1];
    const before = { x: f.x - STEP[f.in][0], y: f.y - STEP[f.in][1] };
    if (st.door) {   // a yard-less rail (its scheduler off the floor) leaves its door, from any side
      expect(st.source, `${label} ${q.key} a door's station names the door`).toBe(st.door);
      expect(tf.boxes.get(st.door)?.foot, `${label} ${q.key} comes in by a door`).toBe("door");
      expect(inside(tf.boxes.get(st.door)!, before.x, before.y), `${label} ${q.key} leaves its door`).toBe(true);
      expect(st.platform?.jobs.length, `${label} ${q.key} a door's station holds its jobs`).toBeGreaterThan(0);
    } else {
      const y = r.yards.find((v) => v.source === st.source)!;
      if (y.ladder) {   // a ladder: past the throat at its own exit row, as the yard planned
        const e = exitOf(y, y.platforms.findIndex((p) => p.dest === st.dest));
        expect([f.x, f.y, f.in], `${label} ${q.key} leaves its ladder by its exit row`).toEqual([e.x, e.y, y.out]);
      } else {
        const plat = y.platforms.find((p) => p.x === before.x && p.y === before.y);
        expect(plat, `${label} ${q.key} leaves its yard past a platform`).toBeDefined();
        expect(f.in, `${label} ${q.key} leaves its yard off a row's end`).toBe(y.out);
        if (!q.pieces.some((p) => p.join === "split")) expect(plat!.dest, `${label} ${q.key} leaves past its own platform`).toBe(st.dest);
      }
    }
    expect([l.x, l.y, l.out], `${label} ${q.key} ends on its station's entry`).toEqual([st.entry.x, st.entry.y, st.entry.d]);
    plugged(tf, q);
  }
  // and every batch bundle with both ends on the floor is some station's rail: no rail ends at a bare machine side
  for (const b of bundles) if (b.kind === "batch") {
    const q = routes.find((x) => x.key === b.key);
    if (q && q.pieces.length) expect(r.stations.some((s) => s.track === b.key), `${label} ${b.key} ends at a station`).toBe(true);
  }
  return rails;
}
