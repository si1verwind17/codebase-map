// A trait and the class that implements it, joined by a thin dotted ink line.
// Not a belt and not routed: straight from centre to centre, drawn under the machines so only the gap shows.
import type { Graphics } from "pixi.js";
import { C } from "../floor/palette";
import type { Rect } from "./tiles";

const DOT = 1.5, GAP = 5;

/** The link itself: the straight line from the centre of `a` to the centre of `b` (a travelling part follows it too). */
export function centreLine(a: Rect, b: Rect): { x: number; y: number }[] {
  return [{ x: a.x + a.w / 2, y: a.y + a.h / 2 }, { x: b.x + b.w / 2, y: b.y + b.h / 2 }];
}

/** Dots along the straight line between the centres of `a` and `b`. */
export function implementsDots(a: Rect, b: Rect): { x: number; y: number }[] {
  const [{ x: ax, y: ay }, { x: bx, y: by }] = centreLine(a, b);
  const len = Math.hypot(bx - ax, by - ay);
  const out: { x: number; y: number }[] = [];
  for (let d = 0; d <= len; d += DOT + GAP) out.push({ x: ax + ((bx - ax) * d) / (len || 1), y: ay + ((by - ay) * d) / (len || 1) });
  return out;
}

export function paintImplements(g: Graphics, a: Rect, b: Rect) {
  for (const p of implementsDots(a, b)) g.circle(p.x, p.y, DOT);
  g.fill(C.ink);
}
