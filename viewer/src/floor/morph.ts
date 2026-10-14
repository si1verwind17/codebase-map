// The box that carries the reader between floors: a building grows into the page (in), a page shrinks
// into its building (out). Pure geometry; the scene draws it.
import type { Rect } from "../route/types";

/** Cubic ease-in-out: slow start, slow finish, so the eye can follow the box. */
export function ease(t: number): number {
  const k = Math.min(1, Math.max(0, t));
  return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
}

/** The rectangle `t` of the way (eased) from `a` to `b`. */
export function morphRect(a: Rect, b: Rect, t: number): Rect {
  const e = ease(t);
  return { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, w: a.w + (b.w - a.w) * e, h: a.h + (b.h - a.h) * e };
}
