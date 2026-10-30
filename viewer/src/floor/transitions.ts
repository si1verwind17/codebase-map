// Floor transitions and travel: a part carried along a line, the zoom toward a building, going inside a building and
// coming out, and the cross-fade of a freshly shown floor. Plain functions over the scene's state (state.ts); `show`
// is the scene's own (scene.ts), passed in.
import { Container, Graphics, Rectangle, Sprite, Text } from "pixi.js";
import type { Model } from "../model/model";
import type { Rect } from "../route/types";
import type { Pt } from "../route/types";
import type { Bundle as LineBundle } from "../model/model";
import { morphRect } from "./morph";
import { C } from "./palette";
import { routeTiles } from "../factory/router";
import { centreLine } from "../factory/implements";
import type { SceneState } from "./state";
import * as cam from "./camera";
import { dashed, near } from "./draw";
import { label } from "./labels";

/** The scene's `show`: draws `container` of `model` as the current floor, fitted. */
export type Show = (model: Model, container: string) => void;

/** One part carried along the line from `from` to `to` (both items on this floor), then `done`.
 *  `straight`: along the straight centre-to-centre line (the dotted implements link), no route and no ghost connector. */
export function travel(st: SceneState, from: string, to: string, done?: () => void, payload?: string, opts: { straight?: boolean } = {}) {
  const a = st.geo?.machines.get(from), b = st.geo?.machines.get(to);
  if (!a || !b || st.reduced) { done?.(); return; }
  const key = [from, to].sort().join("|");
  let r = opts.straight ? undefined : st.routes.find((x) => x.key === key);
  let temp: Graphics | undefined;
  if (!r && st.tf && !opts.straight) {
    // no line on this floor (e.g. a call into library code): route a temporary connector to follow
    const [x, y] = from < to ? [from, to] : [to, from];
    const ghost: LineBundle = { key, a: x, b: y, relations: [], kinds: {}, inferred: 0, kind: "calls", flow: "both" };
    r = routeTiles(st.tf, [ghost])[0];
    if (r) {
      temp = new Graphics();
      dashed(temp, r.points, 6, 5, { width: 2.5, color: C.text });
      st.layers.motion.addChild(temp);
    }
  }
  let pts: Pt[];
  // the line here is flight paths: follow the one flying the step's way (machine → pad → hub, or hub → pad → machine)
  const flights = st.covered.has(key) ? st.flights.filter((f) => f.key === key) : [];
  const flight = flights.find((f) => f.outbound === (from === f.machine)) ?? flights[0];
  if (flight) {
    const mid = (m: Rect) => ({ x: m.x + m.w / 2, y: m.y + m.h / 2 });
    const padToHub = flight.outbound ? flight.points : [...flight.points].reverse();
    pts = from === flight.item ? [...padToHub].reverse().concat(mid(b)) : [mid(a), ...padToHub];
  } else if (r) pts = near(a, r.points[0]) ? r.points : [...r.points].reverse();
  else pts = centreLine(a, b);
  const lengths = [0];
  for (let i = 1; i < pts.length; i++) lengths.push(lengths[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
  const cut = st.traveller;
  cut?.g.destroy();
  cut?.tag?.destroy();
  cut?.temp?.destroy();
  st.traveller = null;
  cut?.done?.();
  const g = new Graphics();
  st.layers.motion.addChild(g);
  let tag: Container | undefined;
  if (payload) {
    tag = new Container();
    const t = new Text({ resolution: 2, text: payload, style: label(12, "700", C.ink) });
    tag.addChild(new Graphics().rect(-4, -2, t.width + 8, 19).fill(C.yellow).stroke({ width: 1.5, color: C.edge }), t);
    st.layers.motion.addChild(tag);
  }
  const total = lengths[lengths.length - 1];
  st.traveller = { pts, lengths, t: 0, ms: cam.clamp(1400 + total * 1.4, 1600, 3200), g, done, tag, temp };
}

export function travelTo(st: SceneState, from: string, to: string, payload?: string, opts: { straight?: boolean } = {}): Promise<void> {
  return new Promise((done) => travel(st, from, to, done, payload, opts));
}

/** Zoom toward a building before going inside it. */
export function zoomInto(st: SceneState, id: string): Promise<void> {
  return new Promise((done) => {
    const m = st.geo?.machines.get(id);
    if (!m || st.reduced) { done(); return; }
    // zoom until the building nearly fills the view, so the floor inside opens at almost its final size
    const s = cam.clamp(Math.min(st.app.screen.width * 0.92 / m.w, (st.app.screen.height - st.bottomInset) * 0.92 / m.h), 0.12, 8);
    cam.camera(st, st.app.screen.width / 2 - (m.x + m.w / 2) * s, (st.app.screen.height - st.bottomInset) / 2 - (m.y + m.h / 2) * s, s, true, done, 560);
  });
}

// ---- continuous floor changes: the new floor appears exactly where the old view was, then settles

/** Go inside `building` (on this floor) to `container`: the building's box grows until it is the page,
 *  over a still, dimmed picture of this floor; then the floor inside appears within that frame. */
export async function enter(st: SceneState, show: Show, model: Model, container: string, building?: string): Promise<void> {
  const m = building ? st.geo?.machines.get(building) : undefined;
  if (!m || st.reduced) { show(model, container); return; }
  const from = cam.toScreen(st, m);
  const code = st.model?.codes.get(building!) ?? "";
  const name = st.model?.label(building!) ?? "";
  const still = snapshot(st);                            // this floor as it looks now, kept underneath
  show(model, container);                                // the inner floor, fitted, hidden until the box lands
  st.world.alpha = 0;
  const to = cam.toScreen(st, cam.floorRect(st));
  const dim = new Graphics().rect(0, 0, st.app.screen.width, st.app.screen.height).fill({ color: C.page, alpha: 1 });
  const box = new Graphics();
  const tab = new Text({ resolution: 2, text: `SUB-ASSEMBLY  ${code}  ${name}`, style: label(13, "700", C.onInk) });
  st.overlay.addChild(still, dim, box, tab);
  await cam.animate(st, 560, (t, r = morphRect(from, to, t)) => {
    dim.alpha = 0.75 * t;                                // the old floor recedes as the box takes the page
    box.clear().rect(r.x, r.y, r.w, r.h).fill(C.paper).stroke({ width: 2, color: C.edge });
    box.rect(r.x, r.y, Math.min(r.w, tab.width + 28), 28).fill(C.ink);
    tab.position.set(r.x + 14, r.y + 6);
  });
  startFade(st, 260);                                    // the floor inside appears in the frame the box became
  await cam.animate(st, 260, (t) => { box.alpha = 1 - t; dim.alpha = 0.75 + 0.25 * t; });
  clearOverlay(st);
}

/** Come out to `container`: this page shrinks back into its building on the floor above, which brightens
 *  in around it. */
export async function leave(st: SceneState, show: Show, model: Model, container: string, from?: string): Promise<void> {
  const page = cam.toScreen(st, cam.floorRect(st));
  const pic = st.reduced ? null : snapshot(st, page);   // this floor, frame and all
  show(model, container);
  const m = from ? st.geo?.machines.get(from) : undefined;
  if (!m || !pic) { pic?.destroy(true); return; }
  const to = cam.toScreen(st, m);
  st.world.alpha = 0.25;
  st.overlay.addChild(pic);
  await cam.animate(st, 560, (t, r = morphRect(page, to, t)) => {
    pic.position.set(r.x, r.y);
    pic.width = r.w;
    pic.height = r.h;
    pic.alpha = t < 0.7 ? 1 : 1 - (t - 0.7) / 0.3;        // dissolves into the building as it lands
    st.world.alpha = 0.25 + 0.75 * t;
  });
  st.world.alpha = 1;
  clearOverlay(st);
}

/** A still picture of the screen (or a part of it), placed where it was taken. */
function snapshot(st: SceneState, r?: Rect): Sprite {
  const frame = r ?? { x: 0, y: 0, w: st.app.screen.width, h: st.app.screen.height };
  const texture = st.app.renderer.generateTexture({ target: st.app.stage, frame: new Rectangle(frame.x, frame.y, frame.w, frame.h), resolution: st.app.renderer.resolution });
  const sprite = new Sprite(texture);
  sprite.position.set(frame.x, frame.y);
  return sprite;
}

function clearOverlay(st: SceneState) {
  for (const c of st.overlay.removeChildren()) c.destroy(c instanceof Sprite ? { texture: true } : { children: true });
}

export function startFade(st: SceneState, ms: number) {
  if (st.reduced) return;
  st.fadeMs = ms;
  st.world.alpha = 0;
  st.fading = 0;
}
