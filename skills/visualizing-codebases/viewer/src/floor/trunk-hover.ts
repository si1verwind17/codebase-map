// The trunk hover card (spec §8 Hover): hovering a tile two or more lines share (a trunk's run, a splitter or merger
// plate) shows its lines on an ink card, in the rail hover lists' style. The card stands on the tile, not the pointer:
// above it, or below when there is no room above; it never covers the tile. It hides on pointer-out, on a floor change
// (the scene clears the layer), on a selection change and when the camera moves. It takes no pointer events: a click on
// the tile reaches the line beneath and selects as before.
import { Container, type FederatedPointerEvent } from "pixi.js";
import type { Bundle } from "../model/model";
import { cardScale, fillCard } from "../factory/messaging-paint";
import type { TileRoute } from "../factory/router";
import { T } from "../factory/tiles";
import { sharedTiles, trunkCard, type SharedTile } from "../factory/trunk-card";
import type { SceneState } from "./state";

const GAP = 4;      // world px between the card and its tile
const MARGIN = 8;   // screen px the card keeps from the canvas's sides

/** Builds the card for this floor and returns how a line's hit area is wired to it (the scene calls it per line). */
export function trunkHover(st: SceneState, routes: TileRoute[], bundleOf: (r: TileRoute) => Bundle,
  end: (id: string) => { code: string; name: string }): (hit: Container) => void {
  const tiles = sharedTiles(routes, (r) => st.covered.has(r.key));
  const words = new Map<string, string>();
  const tip = new Container();
  tip.visible = false;
  tip.label = "trunk-tip";
  tip.eventMode = "none";
  st.layers.tags.addChild(tip);
  let on: string | null = null;
  const hide = () => {
    if (on === null) return;
    on = null;
    tip.visible = false;
    st.trunkTip.shownAt = null;
    delete st.app.canvas.dataset.trunkTip;
  };
  const show = (k: string, t: SharedTile) => {
    let text = words.get(k);
    if (text === undefined) { text = trunkCard(t.ris.map((i) => bundleOf(routes[i])), end); words.set(k, text); }
    const z = st.world.scale.x, s = cardScale(z), { w, h } = fillCard(tip, text, () => ({ x: 0, y: 0 }));
    const x0 = t.x * T, y0 = t.y * T, sw = st.app.screen.width;
    const above = y0 - GAP - h * s, room = st.world.y + above * z >= 0;
    // kept on screen sideways: it stands above or below the tile, so a shift left or right never covers it
    let x = x0;
    const right = st.world.x + (x + w * s) * z - (sw - MARGIN);
    if (right > 0) x -= right / z;
    const left = MARGIN - (st.world.x + x * z);
    if (left > 0) x += left / z;
    tip.scale.set(s);
    tip.position.set(x, room ? above : y0 + T + GAP);
    tip.visible = true;
    on = k;
    st.trunkTip.shownAt = [st.world.x, st.world.y, z];
    st.app.canvas.dataset.trunkTip = text;
  };
  const move = (e: FederatedPointerEvent) => {
    if (e.buttons) { hide(); return; }   // a drag pans the camera: no card
    const p = e.getLocalPosition(st.layers.lines), k = `${Math.floor(p.x / T)},${Math.floor(p.y / T)}`;
    if (k === on) return;
    const t = tiles.get(k);
    if (t) show(k, t);
    else hide();
  };
  // one handle hides every card on the floor: the base's and each extra layer's (each call adds its own to the last)
  const prev = st.trunkTip;
  st.trunkTip = { hide: () => { prev.hide(); hide(); }, shownAt: null };
  return (hit) => {
    if (!tiles.size) return;
    hit.on("pointerover", move).on("pointermove", move).on("pointerout", hide);
  };
}
