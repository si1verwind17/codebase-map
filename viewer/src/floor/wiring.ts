// Pointer wiring for machines and doors, used by the factory drawing: the selection highlight, hover hints and name tags, the
// OPEN tab, click and double-click.
import { Container, Graphics, Text } from "pixi.js";
import type { Model } from "../model/model";
import type { Machine } from "../route/types";
import { arrow } from "./movers";
import { C, HOVER_RING } from "./palette";
import { label, showTag } from "./labels";
import { hasFloor, real, type SceneState } from "./state";

/** The ring a trace pane row's hover draws round its machine: thin ink, just outside the picked mark, hidden until then. */
function hoverRing(st: SceneState, m: Machine, v: Container) {
  const g = new Graphics().rect(m.x - 9, m.y - 9, m.w + 18, m.h + 18).stroke(HOVER_RING);
  g.visible = false;
  st.hoverRings.set(m.id, g);
  v.addChild(g);
}

/** A door never moves the reader on one click: hover or click shows where it leads; double-click goes.
 *  `restyle`: the scene's emphasis pass, run when a single click selects the door. */
export function wireDoor(st: SceneState, model: Model, m: Machine, v: Container, hl: Graphics, restyle: () => void) {
  const d = st.doors.get(m.id)!;
  const hint = new Container();
  const shows = model.doorShows(st.container, d.anchor), named = (id: string) => `${model.codes.get(id) ?? ""} ${model.label(id)}`;
  const ht = new Text({ resolution: 2, text: `Double-click to go to ${named(shows)}${shows === d.anchor ? "" : ` in ${named(d.anchor)}`}`, style: label(11.5, "600", C.onInk) });
  const hx = d.side === "out" ? m.x + m.w - ht.width - 12 : m.x;
  hint.addChild(new Graphics().rect(hx, m.y - 26, ht.width + 12, 20).fill(C.ink), ht);
  ht.position.set(hx + 6, m.y - 23);
  hint.visible = false;
  v.addChild(hint);
  v.eventMode = "static";
  v.cursor = "pointer";
  v.on("pointerover", () => { hint.visible = true; });
  v.on("pointerout", () => { hint.visible = st.selected?.type === "node" && st.selected.id === m.id; });
  v.on("pointertap", (e) => {
    e.stopPropagation();
    const now = performance.now();
    const double = st.lastTap?.id === m.id && now - st.lastTap.at < 350;
    st.lastTap = { id: m.id, at: now };
    if (double) { hint.visible = false; st.events.door(d.anchor); return; }
    st.selected = { type: "node", id: m.id };
    restyle();
    hint.visible = true;
  });
  st.doorHints.set(m.id, hint);
  hl.visible = false;
  st.highlights.set(m.id, hl);
  v.addChild(hl);
  hoverRing(st, m, v);
  st.machineViews.set(m.id, v);
  st.layers.machines.addChild(v);
}

/** Selection highlight, the OPEN tab, click and double-click. */
export function wireMachine(st: SceneState, m: Machine, v: Container, hl: Graphics, tag?: Container) {
  hl.visible = false;
  st.highlights.set(m.id, hl);
  v.addChild(hl);
  hoverRing(st, m, v);
  if (hasFloor(st, m.id)) {   // one click to go inside the selected building
    const tab = new Container();
    const t = new Text({ resolution: 2, text: "OPEN", style: label(12, "700", C.onInk) });
    const x0 = m.x + m.w - t.width - 32;
    const bg = new Graphics().rect(x0, m.y + m.h + 6, t.width + 28, 21).fill(C.blue);
    arrow(bg, { x: x0 + t.width + 10, y: m.y + m.h + 16.5 }, { x: x0 + t.width + 22, y: m.y + m.h + 16.5 }, C.paper, 7);
    bg.moveTo(x0 + t.width + 10, m.y + m.h + 16.5).lineTo(x0 + t.width + 16, m.y + m.h + 16.5).stroke({ width: 2, color: C.paper });
    t.position.set(x0 + 7, m.y + m.h + 8);
    tab.addChild(bg, t);
    tab.visible = false;
    tab.eventMode = "static";
    tab.cursor = "pointer";
    tab.on("pointertap", (e) => { e.stopPropagation(); st.events.enter(real(st, m.id)); });
    st.openTabs.set(m.id, tab);
    v.addChild(tab);
  }
  v.eventMode = "static";
  v.cursor = "pointer";
  if (tag) {
    st.nameTags.set(m.id, tag);
    v.on("pointerover", () => showTag(st, tag, true));
    v.on("pointerout", () => showTag(st, tag, st.selected?.type === "node" && st.selected.id === m.id));
  }
  v.on("pointertap", (e) => {
    e.stopPropagation();
    const now = performance.now();
    const double = st.lastTap?.id === m.id && now - st.lastTap.at < 350;
    st.lastTap = { id: m.id, at: now };
    if (double && hasFloor(st, m.id)) st.events.enter(real(st, m.id));
    else st.events.select({ type: "node", id: m.id });
  });
  st.machineViews.set(m.id, v);
  st.layers.machines.addChild(v);
}
