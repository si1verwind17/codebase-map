// Clear floor space (pure geometry, world px): where a zone name may grow to stay readable when the floor is zoomed out.
// Everything drawn on the floor is an obstacle; a label takes only room no obstacle touches, inside its own zone.
import type { TileFloor, TileLane, Zone } from "./layout";
import type { TileRoute } from "./router";
import { reservedRects } from "./pads";
import { LANE_H, T } from "./tiles";

export interface PxRect { x0: number; y0: number; x1: number; y1: number }

export const ZONE_FONT = 9.5;
/** A zone name's size in world px at scale 1, estimated (never measured, so layout cannot depend on font loading): a
 *  bold capital is at most 0.72 em wide, and the line box is 13 px tall. The drawn text is never larger. */
export const zoneTextSize = (name: string) => ({ w: Math.ceil(name.length * ZONE_FONT * 0.72), h: 13 });

const SHADOW = 5;     // a machine's drop shadow, right and down
const ABOVE = 20;     // chimney (16 px) and utility tabs (19 px) stand above a machine's roof
const LINE_HALF = 6;  // a drone or failed line drawn point to point is a few px wide, and its items are 14 px boxes
const MARGIN = 2;     // clear space kept between a label and anything else

/** Everything a zone name must stay off: machines with their shadows, chimneys and tabs; lanes; every line piece
 *  (housings and junction plates sit on piece tiles); drone and failed lines as drawn (flight paths). */
export function floorObstacles(tf: TileFloor, routes: TileRoute[]): PxRect[] {
  const out: PxRect[] = [];
  for (const b of tf.boxes.values()) {
    const x0 = b.x * T, y0 = b.y * T;
    out.push({ x0, y0: b.foot === "door" ? y0 : y0 - ABOVE, x1: x0 + b.w * T + SHADOW, y1: y0 + b.h * T + SHADOW });
  }
  for (const l of tf.lanes) out.push({ x0: l.x0 * T, y0: l.y * T, x1: l.x1 * T, y1: (l.y + LANE_H) * T });
  for (const r of reservedRects(tf)) out.push({ x0: r.x * T, y0: r.y * T, x1: (r.x + r.w) * T, y1: (r.y + r.h) * T });   // docks and stacks (pads are inside their machines)
  for (const r of routes) out.push(...routeRects(r));
  return out;
}

/** A line as drawn: its piece tiles (only those on top with `top`: a tunnel's pieces are under the floor), or, with no
 *  pieces (a drone or failed line drawn point to point), its segments `LINE_HALF` wide. */
function routeRects(r: TileRoute, top = false): PxRect[] {
  const out: PxRect[] = [];
  for (const p of r.pieces) if (!top || !p.under) out.push({ x0: p.x * T, y0: p.y * T, x1: (p.x + 1) * T, y1: (p.y + 1) * T });
  if (r.pieces.length) return out;
  for (let i = 1; i < r.points.length; i++) {   // squares along each segment: a diagonal's bounding box would block far too much
    const a = r.points[i - 1], b = r.points[i], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / LINE_HALF));
    for (let k = 0; k <= n; k++) {
      const x = a.x + ((b.x - a.x) * k) / n, y = a.y + ((b.y - a.y) * k) / n;
      out.push({ x0: x - LINE_HALF, y0: y - LINE_HALF, x1: x + LINE_HALF, y1: y + LINE_HALF });
    }
  }
  return out;
}

const hit = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;

/** Obstacles indexed by the tiles they touch: a query looks only at its own tiles. */
export class Clearance {
  private cells = new Map<number, PxRect[]>();
  constructor(rects: PxRect[] = [], private cols = 4096) { for (const r of rects) this.add(r); }
  private each(r: PxRect, f: (key: number) => boolean | void) {
    for (let ty = Math.floor(r.y0 / T); ty <= Math.floor((r.y1 - 1e-6) / T); ty++)
      for (let tx = Math.floor(r.x0 / T); tx <= Math.floor((r.x1 - 1e-6) / T); tx++) if (f(ty * this.cols + tx)) return true;
    return false;
  }
  add(r: PxRect) { this.each(r, (k) => { const l = this.cells.get(k); if (l) l.push(r); else this.cells.set(k, [r]); }); }
  /** Does `r`, with a small margin, touch no obstacle? */
  free(r: PxRect): boolean {
    const q = { x0: r.x0 - MARGIN, y0: r.y0 - MARGIN, x1: r.x1 + MARGIN, y1: r.y1 + MARGIN };
    return !this.each(q, (k) => this.cells.get(k)?.some((o) => hit(q, o)));
  }
}

/** Where a zone's name sits and how far it may grow: its bottom-left corner (`ax`, `ay`), the estimated text size at
 *  scale 1 and the largest scale `maxK` whose box is clear (1 where even the unscaled name is not). */
export interface ZoneLabelPlan { ax: number; ay: number; w: number; h: number; maxK: number; clear: boolean }
export const labelBox = (p: ZoneLabelPlan, k: number): PxRect => ({ x0: p.ax, y0: p.ay - p.h * k, x1: p.ax + p.w * k, y1: p.ay });

export const MAX_K = 4;   // 9 px on screen down to a zoom of 0.24; a spot reaching it is as good as any, so the corner wins ties

/** The best spot for a zone's name: bottom-left anchors on every tile column of the zone's bottom three rows, each
 *  grown (up and right) as far as it stays inside the zone and clear of every obstacle; the largest wins, the lowest
 *  and leftmost on a tie. The winning box is added to `clear`, so the next zone's name keeps off it. A zone with no
 *  clear spot keeps the old corner at scale 1 (it hides itself when that is too small to read). */
export function planZoneLabel(z: Zone, clear: Clearance): ZoneLabelPlan {
  const { w, h } = zoneTextSize(z.name);
  const inner: PxRect = { x0: z.x * T + 2, y0: z.y * T + 2, x1: (z.x + z.w) * T - 2, y1: (z.y + z.h) * T - 2 };
  const ok = (p: ZoneLabelPlan, k: number) => {
    const b = labelBox({ ...p, w, h }, k);
    return b.x0 >= inner.x0 && b.x1 <= inner.x1 && b.y0 >= inner.y0 && b.y1 <= inner.y1 && clear.free(b);
  };
  let best: ZoneLabelPlan | undefined;
  // the bottom three rows first; with no clear spot there, every row above, lowest first
  for (let j = 0; j < z.h && (j < 3 || !best); j++) for (let tx = z.x; tx < z.x + z.w; tx++) {
    const p: ZoneLabelPlan = { ax: tx * T + 6, ay: (z.y + z.h) * T - 5 - j * T, w, h, maxK: 1, clear: true };
    if (!ok(p, 1)) continue;
    let lo = 1, hi = MAX_K;
    if (ok(p, hi)) lo = hi;
    else for (let i = 0; i < 12; i++) { const mid = (lo + hi) / 2; if (ok(p, mid)) lo = mid; else hi = mid; }
    p.maxK = Math.floor(lo * 100) / 100;
    if (!best || p.maxK > best.maxK + 1e-9) best = p;
  }
  const plan = best ?? { ax: z.x * T + 6, ay: (z.y + z.h) * T - 5, w, h, maxK: 1, clear: false };
  clear.add(labelBox(plan, plan.maxK));
  return plan;
}

export const BADGE_FONT = 10.5;
/** A `used by N` badge's size in world px at scale 1, estimated as `zoneTextSize` is (a bold character is at most
 *  0.62 em wide here, plus 4 px padding each side): the drawn badge is never larger, so its spot holds it. */
export const badgeSize = (n: number) => ({ w: Math.ceil(`used by ${n}`.length * BADGE_FONT * 0.62) + 8, h: 14 });

/** Where a `used by N` badge stands beside its machine and how far it may grow: its box at scale `k` has
 *  its corner at (`ax` + `ox`·w·k, `ay` + `oy`·h·k), so the anchor (`ax`, `ay`) stays put and the badge grows away
 *  from the box (`ox` 0 grows right, -1 left; `oy` 0 grows down, -1 up, -0.5 both ways, centred). `side` is the side of
 *  the box it stands on. `maxK` is the largest scale (up to MAX_K) whose box is clear of every obstacle, so the badge
 *  keeps a readable size as the floor zooms out without lying on a line or a word; `clear` is false where no spot was
 *  clear even at scale 1. */
export interface BadgeSpot { side: "right" | "below" | "left" | "above"; ax: number; ay: number; ox: 0 | -1; oy: 0 | -0.5 | -1; w: number; h: number; maxK: number; clear: boolean }
export const badgeBox = (p: BadgeSpot, k: number): PxRect => {
  const w = p.w * k, h = p.h * k, x0 = p.ax + p.ox * w, y0 = p.ay + p.oy * h;
  return { x0, y0, x1: x0 + w, y1: y0 + h };
};

const SLIDE = 40;   // how far past the box's top and bottom a badge's anchor may slide along its right or left side, world px
/** The best spot for a `w`×`h` badge beside machine `m` (world px): the one that grows furthest while clear. First the
 *  plain spots (right and left centred on the box, below and above from its left edge), right first on a tie, then
 *  below, left, above; then each side's sliding spots, nearest the plain one first: on the right and left an anchor at
 *  every 2 px from `SLIDE` above the box to `SLIDE` below it, the badge growing down or up from it; below and above, at
 *  every 2 px along the box (never past its ends, so no line runs between it and its box), growing right or left. A
 *  later spot wins only by growing further. The
 *  winning box (at its `maxK`) joins `clear`. With no clear spot even at scale 1, it stands below at scale 1. */
export function planBadge(m: { x: number; y: number; w: number; h: number }, w: number, h: number, clear: Clearance): BadgeSpot {
  const gap = 3, cy = m.y + m.h / 2;
  const R = m.x + m.w + SHADOW + gap, L = m.x - gap, B = m.y + m.h + SHADOW + gap, A = m.y - ABOVE - gap;
  const at = (side: BadgeSpot["side"], ax: number, ay: number, ox: BadgeSpot["ox"], oy: BadgeSpot["oy"]): BadgeSpot => ({ side, ax, ay, ox, oy, w, h, maxK: 1, clear: true });
  const plain = [at("right", R, cy, 0, -0.5), at("below", m.x, B, 0, 0), at("left", L, cy, -1, -0.5), at("above", m.x, A, 0, -1)];
  const slid: { p: BadgeSpot; d: number }[] = [];
  for (let y = m.y - SLIDE; y <= m.y + m.h + SLIDE; y += 2)
    for (const oy of [0, -1] as const) for (const [side, ax, ox] of [["right", R, 0], ["left", L, -1]] as const)
      slid.push({ p: at(side, ax, y, ox, oy), d: Math.abs(y + oy * h + h / 2 - cy) });
  for (let x = m.x; x <= m.x + m.w; x += 2)
    for (const ox of [0, -1] as const) for (const [side, ay, oy] of [["below", B, 0], ["above", A, -1]] as const)
      slid.push({ p: at(side, x, ay, ox, oy), d: Math.abs(x + ox * w - m.x) });
  const order = { right: 0, below: 1, left: 2, above: 3 };
  slid.sort((a, b) => a.d - b.d || order[a.p.side] - order[b.p.side]);
  let best: BadgeSpot | undefined;
  for (const p of [...plain, ...slid.map((s) => s.p)]) {
    if (best?.maxK === MAX_K) break;
    if (!clear.free(badgeBox(p, 1))) continue;
    let lo = 1, hi = MAX_K;
    if (clear.free(badgeBox(p, hi))) lo = hi;
    else for (let i = 0; i < 12; i++) { const mid = (lo + hi) / 2; if (clear.free(badgeBox(p, mid))) lo = mid; else hi = mid; }
    p.maxK = Math.floor(lo * 100) / 100;
    if (!best || p.maxK > best.maxK + 1e-9) best = p;
  }
  const plan = best ?? { ...plain[1], clear: false };
  clear.add(badgeBox(plan, plan.maxK));
  return plan;
}

/** Every heavily used item's badge spot on a floor, placed once after the labels, in layer order (each winner joins
 *  `clear`). `layerTiles` are the tiles of every layer's lines: a badge is clear of them too, so it reads in every
 *  layer view and on the base. `spots` is the plan's cache: a placed spot is kept. */
export interface BadgeItem { id: string; m: { x: number; y: number; w: number; h: number }; w: number; h: number }
export function placeBadges(items: BadgeItem[], clear: Clearance, layerTiles: PxRect[], spots: Map<string, BadgeSpot> = new Map()): Map<string, BadgeSpot> {
  if (items.some((i) => !spots.has(i.id))) for (const r of layerTiles) clear.add(r);
  for (const i of items) if (!spots.has(i.id)) spots.set(i.id, planBadge(i.m, i.w, i.h, clear));
  return spots;
}
/** Every layer's lines as drawn: the tiles of their top pieces, and drone or failed lines point to point. */
export function layerTileRects(layers: Partial<Record<string, { routes: TileRoute[] }>> | undefined): PxRect[] {
  return Object.values(layers ?? {}).flatMap((l) => l!.routes.flatMap((r) => routeRects(r, true)));
}

/** Where a lane's name sits: from the left, the first gap between crossing lines wide enough for the name scaled to
 *  `kWant`; else the widest gap. `room` is that gap's width from the name's left edge. A line past the lane's end
 *  bounds no gap: the last one ends at the lane's end. Pure, for the test. */
export function laneLabelSpot(x0: number, x1: number, w: number, blocked: number[], kWant: number, pad = 6): { x: number; room: number } {
  const gaps: { s: number; e: number }[] = [];
  let start = x0 + pad;
  for (const b of blocked.filter((b) => b > x0 && b < x1).sort((p, q) => p - q)) {
    if (b - pad > start) gaps.push({ s: start, e: b - pad });
    start = Math.max(start, b + pad + 2);   // clear of the line (2 px half-width) plus padding
  }
  gaps.push({ s: start, e: x1 - pad });
  const g = gaps.find((q) => q.e - q.s >= w * kWant) ?? gaps.reduce((best, q) => (q.e - q.s > best.e - best.s ? q : best));
  return { x: g.s, room: g.e - g.s };
}

/** The lane name's scale the spot is chosen for: 3x its size is readable down to a zoom of 0.25. */
const LANE_WANT = 3;
export const LANE_FONT = 12;
const LANE_LABEL_H = 17;
const LANE_CHAR = 0.56;   // a bold letter of a lane's name, in em: fit.ts's estimate, a little wider than drawn

/** A lane's name plate width at scale 1, estimated (the drawing measures the text): for the router and the audit. */
export const laneNameWidth = (name: string) => Math.ceil(name.length * LANE_FONT * LANE_CHAR) + 10;

/** The tiles at a short lane's start where its name sits, as [x0, x1): a lane too short to hold its name twice over,
 *  so a line crossing it or ending on it there leaves the name no room (the router keeps lines off them where it can);
 *  undefined on a longer lane, whose name finds a gap between the lines. */
export function laneNameTiles(l: TileLane, name: string): [number, number] | undefined {
  const w = laneNameWidth(name), PAD = 6;
  if ((l.x1 - l.x0) * T >= 2 * (w + 2 * PAD + 2)) return undefined;
  return [l.x0, Math.min(l.x1, l.x0 + Math.ceil((w + 2 * PAD + 2) / T))];
}

/** A lane's name plate, `w` px wide at scale 1 (its text plus 10): its top-left corner, its height, and the largest
 *  scale its spot holds. Pure, for the map audit (text.ts), which estimates `w` where the drawing measures it. */
export function laneLabelPlan(l: TileLane, w: number, blocked: number[]): { x: number; y: number; w: number; h: number; maxK: number } {
  const tall = Math.max(1, (LANE_H * T - 6) / LANE_LABEL_H);
  // the spot is chosen for the label as it will be drawn zoomed out (up to LANE_WANT times its size), not at scale 1
  const spot = laneLabelSpot(l.x0 * T, l.x1 * T, w, blocked, Math.min(tall, LANE_WANT));
  return { x: spot.x, y: l.y * T + 4, w, h: LANE_LABEL_H, maxK: Math.max(1, Math.min(tall, spot.room / w)) };
}
