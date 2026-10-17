// Drawing helpers for the factory drawing (factory-draw.ts): the sub-assembly frame, the door and the stroke helpers.
// Names and sub lines come from labels.ts, pointer wiring from wiring.ts.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import type { Model } from "../model/model";
import type { FloorGeometry, Machine, Rect } from "../route/types";
import type { Pt } from "../route/types";
import { arrow } from "./movers";
import { C, FONT, PICKED_RING } from "./palette";
import { bigCode, doorText } from "../factory/machines";
import { doorWords, fitDoorName } from "../factory/boxname";
import type { SceneState } from "./state";
import { label } from "./labels";
import { wireDoor } from "./wiring";

export const KEYLINE = { width: 1, color: C.ink, pixelLine: true };

export function drawFrame(st: SceneState, model: Model, geo: FloorGeometry) {
  const { w, h } = geo.bounds;
  const f = st.layers.frame;
  f.rect(-16, -44, w + 32, h + 60).fill({ color: C.paper, alpha: 0.35 }).stroke({ width: 2, color: C.ink });
  const title = `SUB-ASSEMBLY  ${model.codes.get(st.container) ?? ""}  ${model.label(st.container)}`;
  const t = new Text({ resolution: 2, text: title, style: label(13, "700", C.paper) });
  f.rect(-16, -44, t.width + 28, 28).fill(C.ink);
  t.position.set(-2, -38);
  st.layers.tags.addChild(t);
}

/** The 7-tile door wraps its name by width, 2 lines down to 10 px.
 *  `restyle`: the scene's emphasis pass, which a click on the door runs (wiring.ts). */
export function drawDoor(st: SceneState, model: Model, m: Machine, restyle: () => void) {
  const d = st.doors.get(m.id)!;
  const v = new Container();
  const g = new Graphics();
  dashed(g, [{ x: m.x, y: m.y }, { x: m.x + m.w, y: m.y }, { x: m.x + m.w, y: m.y + m.h }, { x: m.x, y: m.y + m.h }, { x: m.x, y: m.y }], 5, 4, { width: 1.5, color: C.ink });
  g.rect(m.x, m.y, m.w, m.h).fill({ color: C.paper, alpha: 0.6 });
  const ax = d.side === "out" ? m.x + m.w - 22 : m.x + 6;
  arrow(g, { x: ax, y: m.y + m.h / 2 }, { x: ax + 16, y: m.y + m.h / 2 }, C.ink, 9);
  g.moveTo(ax, m.y + m.h / 2).lineTo(ax + 10, m.y + m.h / 2).stroke({ width: 2.5, color: C.ink });
  v.addChild(g);
  const head = new Text({ resolution: 2, text: d.side === "out" ? "TO" : "FROM", style: label(9.5, "700", C.slate) });
  const words = doorWords(model, st.container, d.anchor);
  const fit = fitDoorName(words, m.w);   // boxname.ts: the audit reads the same fit
  const name = new Text({ resolution: 2, text: fit.lines.join("\n"), style: new TextStyle({ fontFamily: FONT, fontSize: fit.size, fontWeight: "600", fill: C.ink, lineHeight: fit.size + 2.5 }) });
  const x0 = doorText(m, d.side).x;
  head.position.set(x0, m.y + 5);
  name.position.set(x0, m.y + 19);
  v.addChild(head, name);
  // zoomed far out the door shows the code of the building it opens, not the unreadable name
  const big = bigCode(model.codes.get(model.doorShows(st.container, d.anchor)) ?? "", m.x, m.y, m.w, m.h);
  v.addChild(big);
  st.codeParts.push({ names: [name], big, smalls: [{ objs: [head], size: 9.5 }] });
  st.minName = Math.min(st.minName, fit.size);
  wireDoor(st, model, m, v, new Graphics().rect(m.x - 5, m.y - 5, m.w + 10, m.h + 10).stroke(PICKED_RING), restyle);
}

// ------------------------------------------------------------------ helpers
const dist = (a: Pt, b: Pt) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);
export const near = (m: Rect, p: Pt) => p.x >= m.x - 1 && p.x <= m.x + m.w + 1 && p.y >= m.y - 1 && p.y <= m.y + m.h + 1;

export function stroke(g: Graphics, pts: Pt[], style: { width: number; color: number; alpha?: number; cap?: "round" }, inferred: boolean) {
  if (inferred) { dashed(g, pts, 9, 6, style); return; }
  g.moveTo(pts[0].x, pts[0].y);
  for (const p of pts.slice(1)) g.lineTo(p.x, p.y);
  g.stroke({ ...style, join: "miter" });
}

export function dashed(g: Graphics, pts: Pt[], on: number, off: number, style: { width: number; color: number; alpha?: number; cap?: "round" }) {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], len = dist(a, b);
    for (let d = 0; d < len; d += on + off) {
      const e = Math.min(len, d + on);
      g.moveTo(a.x + ((b.x - a.x) * d) / len, a.y + ((b.y - a.y) * d) / len).lineTo(a.x + ((b.x - a.x) * e) / len, a.y + ((b.y - a.y) * e) / len);
    }
  }
  g.stroke(style);
}
