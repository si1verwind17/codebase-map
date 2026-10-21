// The floor camera: pan and wheel zoom, continuous depth (zoom into a building to enter it, out to go up), fitting,
// focusing, and the tweened moves the ticker steps (stepTween). The canvas's `data-camera` says "moving" or "idle".
import type { Rect } from "../route/types";
import { SITE } from "../model/model";
import { isClick } from "./lane";
import { clampFit, fitScale as fitScaleOf } from "./fitscale";
import { hasFloor, real, type SceneState } from "./state";

/** Zoom in past ENTER_AT × the fitted scale (and at least READABLE) over a building to enter it;
 *  out past LEAVE_AT × fitted to leave the floor. READABLE lets labels be read before the floor changes. */
const ENTER_AT = 1.8;
const READABLE = 1.3;
const LEAVE_AT = 0.6;

export const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

// ---- continuous floor changes: the new floor appears exactly where the old view was, then settles
export function toScreen(st: SceneState, r: Rect): Rect {
  const s = st.world.scale.x;
  return { x: st.world.x + r.x * s, y: st.world.y + r.y * s, w: r.w * s, h: r.h * s };
}

/** The floor as drawn, frame included. */
export function floorRect(st: SceneState): Rect {
  const b = st.geo?.bounds ?? { x: 0, y: 0, w: 400, h: 300 };
  return st.container === SITE ? b : { x: b.x - 16, y: b.y - 44, w: b.w + 32, h: b.h + 60 };
}

/** Run `step(t)` each frame for `ms` (t from 0 to 1), then resolve. */
export function animate(st: SceneState, ms: number, step: (t: number) => void): Promise<void> {
  return new Promise((done) => {
    let elapsed = 0;
    const tick = (tk: { deltaMS: number }) => {
      elapsed += tk.deltaMS;
      const t = Math.min(1, elapsed / ms);
      step(t);
      if (t >= 1) { st.app.ticker.remove(tick); done(); }
    };
    step(0);
    st.app.ticker.add(tick);
  });
}

export function focusTo(st: SceneState, id: string, zoom: number): Promise<void> {
  return new Promise((done) => focus(st, id, zoom, done));
}

export function setupCamera(st: SceneState) {
  let drag: { x: number; y: number; wx: number; wy: number } | null = null;
  st.app.stage.on("pointerdown", (e) => {
    if (e.target !== st.app.stage) return;
    drag = { x: e.global.x, y: e.global.y, wx: st.world.x, wy: st.world.y };
  });
  st.app.stage.on("pointermove", (e) => {
    if (!drag) return;
    st.world.position.set(drag.wx + e.global.x - drag.x, drag.wy + e.global.y - drag.y);
  });
  const stop = () => { drag = null; };
  st.app.stage.on("pointerup", (e) => {   // a click on empty floor clears the selection; a drag keeps it
    if (drag && isClick(e.global.x - drag.x, e.global.y - drag.y)) st.events.select(null);
    drag = null;
  }).on("pointerupoutside", stop);
  st.app.canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    if (performance.now() < st.depthQuietUntil) return;   // a fresh floor stays fitted while the wheel settles
    const f = Math.exp(-ev.deltaY / 500);
    const s = clamp(st.world.scale.x * f, 0.12, 4);
    const rect = st.app.canvas.getBoundingClientRect();
    const px = ev.clientX - rect.left, py = ev.clientY - rect.top;
    const wx = (px - st.world.x) / st.world.scale.x, wy = (py - st.world.y) / st.world.scale.y;
    st.world.scale.set(s);
    st.world.position.set(px - wx * s, py - wy * s);
    markZoom(st);   // after the pan too: the canvas reports the camera as it now is
    depthCheck(st, px, py);
  }, { passive: false });
}

/** Continuous depth: zooming far into a building enters it; far out of a floor goes up. */
function depthCheck(st: SceneState, px: number, py: number) {
  if (!st.geo || performance.now() < st.depthQuietUntil || st.tween) return;
  const s = st.world.scale.x;
  const fit = clampFit(fitScale(st));
  if (s > Math.max(fit * ENTER_AT, READABLE)) {
    const wx = (px - st.world.x) / s, wy = (py - st.world.y) / s;
    for (const m of st.geo.machines.values())
      if (wx >= m.x - 12 && wx <= m.x + m.w + 12 && wy >= m.y - 12 && wy <= m.y + m.h + 12 && hasFloor(st, m.id)) {
        st.depthQuietUntil = performance.now() + 600;
        st.events.enter(real(st, m.id));
        return;
      }
  } else if (s < fit * LEAVE_AT && st.container !== SITE) {
    st.depthQuietUntil = performance.now() + 600;
    st.events.up();
  }
}

/** The zoom that fits this floor; kept so a travelling part can stay in view. */
export function fitScaleFor(st: SceneState) {
  return clampFit(fitScale(st));
}

function fitScale(st: SceneState) {
  if (!st.geo) return 1;
  const { w, h } = st.geo.bounds;
  return fitScaleOf(w, h, st.app.screen.width, st.app.screen.height, st.container === SITE, st.bottomInset);
}

export function fit(st: SceneState, animate = true) {
  if (!st.geo) return;
  const s = clampFit(fitScale(st));
  const { w, h } = st.geo.bounds;
  const x = (st.app.screen.width - w * s) / 2, y = (st.app.screen.height - st.bottomInset - h * s) / 2 + 14 * s;
  camera(st, x, y, s, animate);
}

/** Zoom toward a machine (used before entering it, and to follow a travelling part). */
export function focus(st: SceneState, id: string, zoom = 1.6, done?: () => void) {
  const m = st.geo?.machines.get(id);
  if (!m) { done?.(); return; }
  const s = clamp(zoom, 0.12, 4);
  const visibleH = st.app.screen.height - st.bottomInset;
  camera(st, st.app.screen.width / 2 - (m.x + m.w / 2) * s, visibleH / 2 - (m.y + m.h / 2) * s, s, true, done);
}

/** Whether machine `id`'s whole box is on the canvas now (above the bottom inset); undefined when it is not a machine
 *  of this floor. */
export function inView(st: SceneState, id: string): boolean | undefined {
  const m = st.geo?.machines.get(id);
  if (!m) return undefined;
  const r = toScreen(st, m);
  return r.x >= 0 && r.y >= 0 && r.x + r.w <= st.app.screen.width && r.y + r.h <= st.app.screen.height - st.bottomInset;
}

/** Centre machine `id` on the canvas at the current zoom (a pan, never a zoom): animated unless `animate` is false or
 *  Still motion is on. */
export function panTo(st: SceneState, id: string, animate: boolean) {
  const m = st.geo?.machines.get(id);
  if (!m) return;
  const s = st.world.scale.x;
  camera(st, st.app.screen.width / 2 - (m.x + m.w / 2) * s, (st.app.screen.height - st.bottomInset) / 2 - (m.y + m.h / 2) * s, s, animate);
}

/** Tests read the camera (the canvas's `data-zoom` and `data-pan`, the world's offset as "x y") to check that
 *  something did or did not move it; the zoom is written as labels.ts `syncLabels` writes it while words are measured
 *  (`String`), which compares it with `data-texts-zoom`. */
export const markZoom = (st: SceneState) => {
  st.app.canvas.dataset.zoom = String(st.world.scale.x);
  st.app.canvas.dataset.pan = `${st.world.x} ${st.world.y}`;
};

export function camera(st: SceneState, x: number, y: number, s: number, animate: boolean, done?: () => void, ms = 420) {
  if (!animate || st.reduced) {
    st.world.position.set(x, y);
    st.world.scale.set(s);
    markZoom(st);
    if (!st.planWaits) st.app.canvas.dataset.camera = "idle";   // a floor change waiting on its plan is still a move
    done?.();
    return;
  }
  const replaced = st.tween?.done;   // a move cut short still answers its caller, or a staged step waits forever
  st.tween = { from: [st.world.x, st.world.y, st.world.scale.x], to: [x, y, s], t: 0, ms, done };
  st.app.canvas.dataset.camera = "moving";   // tests wait on idle instead of sleeping
  replaced?.();
}

/** One frame of the camera tween (called by the scene's tick). */
export function stepTween(st: SceneState, ms: number) {
  if (st.tween) {
    const tw = st.tween;
    tw.t = Math.min(1, tw.t + ms / tw.ms);
    const e = 1 - Math.pow(2, -10 * tw.t);
    const [x, y, s] = tw.from.map((f, i) => f + (tw.to[i] - f) * e);
    st.world.position.set(x, y);
    st.world.scale.set(s);
    markZoom(st);
    if (tw.t >= 1) { const d = tw.done; st.tween = null; if (!st.planWaits) st.app.canvas.dataset.camera = "idle"; d?.(); }
  }
}
