// The trace pane's pan and zoom (spec S6, rulings R1–R5): the sheet scales by `k` inside a scroll box, so panning is
// the box's scroll offset (drag, wheel, arrow keys) and zooming keeps the sheet point under the pointer still. Pure
// maths; TracePane applies it.

/** Zoom limits; one wheel notch (100 px of delta) or one +/- press; the drag threshold; one arrow-key pan. */
export const ZOOM_MIN = 0.5, ZOOM_MAX = 2, ZOOM_STEP = 1.1, DRAG_SLOP = 4, PAN_STEP = 40;

export const clampZoom = (k: number): number => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, k));

/** A view of the sheet: its zoom and the scroll box's offsets (screen px). */
export interface PaneView { k: number; left: number; top: number }

/** Zoom to `k` (clamped) keeping the sheet point under (`px`, `py`) — relative to the scroll box — where it is. The
 *  offsets may come out negative or past the end: the browser clamps them when they are applied. */
export function zoomAbout(v: PaneView, k: number, px: number, py: number): PaneView {
  const next = clampZoom(k), r = next / v.k;
  return { k: next, left: (v.left + px) * r - px, top: (v.top + py) * r - py };
}

/** The zoom after a Ctrl+wheel (or a trackpad pinch) of `deltaY` px: ×ZOOM_STEP per 100 px, in when the wheel turns up. */
export const wheelZoom = (k: number, deltaY: number): number => clampZoom(k * ZOOM_STEP ** (-deltaY / 100));

/** Fit: the largest zoom ≤ 1 that shows the whole `w`×`h` sheet in a `paneW`×`paneH` box, never below ZOOM_MIN. */
export function fitZoom(w: number, h: number, paneW: number, paneH: number): number {
  if (w <= 0 || h <= 0 || paneW <= 0 || paneH <= 0) return 1;
  return clampZoom(Math.min(1, paneW / w, paneH / h));
}

/** The offsets at zoom `k` that bring rect `r` (sheet px) into a `paneW`×`paneH` box seen from the top-left: 0 on an
 *  axis where it is already in view, else centred on it there (never negative). */
export function intoView(r: { x: number; y: number; w: number; h: number }, k: number, paneW: number, paneH: number): { left: number; top: number } {
  const left = (r.x + r.w) * k <= paneW ? 0 : Math.max(0, (r.x + r.w / 2) * k - paneW / 2);
  const top = (r.y + r.h) * k <= paneH ? 0 : Math.max(0, (r.y + r.h / 2) * k - paneH / 2);
  return { left, top };
}

/** A press becomes a drag once it has moved DRAG_SLOP px. */
export const isDrag = (dx: number, dy: number): boolean => Math.hypot(dx, dy) >= DRAG_SLOP;
