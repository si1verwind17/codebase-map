// Words on the floor: the label text style, the factory's zoom-following labels and full-name tags, the utility tab
// hints, and the short names and sub lines written on machines.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import type { Model } from "../model/model";
import type { Machine } from "../route/types";
import { shownName } from "./names";
import { factorySubOf } from "../factory/subline";
import { C, FONT } from "./palette";
import { codesMode, subShown } from "../factory/machines";
import { applyZoom } from "../factory/ground";
import type { SceneState } from "./state";
import type { TileRoute } from "../factory/router";
import type { Piece } from "../factory/tiles";

export const label = (size: number, weight: "400" | "500" | "600" | "700", fill = C.text) =>
  new TextStyle({ fontFamily: FONT, fontSize: size, fontWeight: weight, fill });

/** Every word drawn on the floor, and how many are turned (tests read both; every word reads left to
 *  right, so none should be). */
export function wordsRead(st: SceneState) {
  const words: string[] = [];
  let turned = 0;
  const walk = (c: Container, angle: number) => {
    const a = angle + c.rotation;
    if (c instanceof Text) { words.push(c.text); if (Math.abs(a) > 1e-6) turned++; }
    for (const k of c.children) walk(k, a);
  };
  for (const l of Object.values(st.layers)) walk(l, 0);
  st.app.canvas.dataset.floor = st.container;
  st.app.canvas.dataset.turnedText = String(turned);
  st.app.canvas.dataset.words = words.join("|");
}

/** Tests turn the word measure on (`textsRead`, `linesRead`) by setting `vizMeasureTexts` before the page loads; the
 *  shipped viewer never measures. */
export const measuring = () => (globalThis as { vizMeasureTexts?: unknown }).vizMeasureTexts === true;

/** Every word shown now, in world px, at the zoom the labels last settled at (tests read it: no word sits on a line or on
 *  another word), stamped with the floor and the zoom. A word in a box drawn just for it (a container holding only that
 *  box and the word: a plate, a tag, a lane name) is measured by its box. Each says what it belongs to: `line`, the keys
 *  of the lines it fades with (a sign or plate of their own); `card`, a hover or selection card (a name tag, a hint, a
 *  tab, a hover list), drawn above everything on purpose. Only while `measuring()`. */
export function textsRead(st: SceneState) {
  const lineOf = new Map<Container, string[]>(), cards = new Set<Container>();
  for (const [k, views] of st.lineViews) for (const v of views) lineOf.set(v, [...(lineOf.get(v) ?? []), k]);
  for (const m of [st.nameTags, st.doorHints, st.openTabs]) for (const c of m.values()) cards.add(c);
  const s = st.world.scale.x, r = (v: number) => Math.round(v * 10) / 10;
  const out: { t: string; x: number; y: number; w: number; h: number; line?: string[]; card?: true }[] = [];
  const walk = (c: Container, own: { line?: string[]; card?: true }) => {
    if (!c.visible || !c.renderable || c.alpha === 0) return;
    const card = cards.has(c) || /tip$|^utility-hint:/.test(c.label ?? "") || undefined;
    const o = { line: lineOf.get(c) ?? own.line, card: card ?? own.card };
    if (c instanceof Text) {
      const p = c.parent!, boxed = p.children.length === 2 && p.children.some((k) => k instanceof Graphics);
      const b = (boxed ? p : c).getBounds();
      out.push({ t: c.text, x: r((b.x - st.world.x) / s), y: r((b.y - st.world.y) / s), w: r(b.width / s), h: r(b.height / s), ...(o.line ? { line: o.line } : {}), ...(o.card ? { card: true as const } : {}) });
    }
    for (const k of c.children) walk(k, o);
  };
  for (const l of Object.values(st.layers)) walk(l, {});
  st.textsZoom = st.labelZoom;
  st.app.canvas.dataset.textsFloor = st.container;
  st.app.canvas.dataset.textsZoom = String(s);
  st.app.canvas.dataset.texts = JSON.stringify(out);
}

/** The lines on top now (tests read them with `textsRead`): `data-line-tiles`, by line key, the `x,y` tiles of routed pieces
 *  (a rail's yard link and siding too); `data-line-paths`, by key, the dotted flight and drone paths (while they show) as
 *  polylines in world px, cut where a building stands over them. While an extra layer shows, that layer's lines alone (the
 *  base is a 12% background, not on top). F0's code-dependency conduits, while the Code links toggle draws them, are paths
 *  too. Once per draw, per layer change and per Code links toggle, only while `measuring()`. */
export function linesRead(st: SceneState) {
  const tiles: Record<string, string[]> = {};
  const add = (key: string, ps: Piece[]) => { for (const p of ps) if (!p.under) (tiles[key] ??= []).push(`${p.x},${p.y}`); };
  const paths: Record<string, number[][]> = {};
  const boxes = st.tf ? [...st.tf.boxes.values()] : [];
  const under = (x: number, y: number) => boxes.some((b) => x >= b.x * 24 && x < (b.x + b.w) * 24 && y >= b.y * 24 && y < (b.y + b.h) * 24);
  const path = (key: string, pts: { x: number; y: number }[]) => {   // the polyline, cut where a building stands over it
    let run: number[] = [];
    const flush = () => { if (run.length >= 4) (paths[key] ??= []).push(run); run = []; };
    for (let i = 0; i + 1 < pts.length; i++) {
      const a = pts[i], b = pts[i + 1], n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 2));
      for (let k = 0; k <= n; k++) {
        const x = a.x + (b.x - a.x) * k / n, y = a.y + (b.y - a.y) * k / n;
        if (under(x, y)) flush(); else run.push(Math.round(x * 10) / 10, Math.round(y * 10) / 10);
      }
    }
    flush();
  };
  const routes = (rs: TileRoute[], skip: (r: TileRoute) => boolean) => {
    for (const rt of rs) {
      if (skip(rt)) continue;
      if (rt.kind === "drone") { if (st.dronePaths) path(rt.key, rt.points); } else add(rt.key, rt.pieces);
    }
  };
  if (st.layer === null) {
    routes(st.routes as TileRoute[], (r) => st.covered.has(r.key));
    for (const [k, ps] of st.railExtra) add(k, ps);
    if (st.dronePaths) for (const f of st.flights) path(f.key, f.points);
  } else routes(st.layerViews.get(st.layer)?.routes ?? [], () => false);
  for (const c of st.conduits) path(`conduit:${c.user}|${c.used}`, c.points);
  st.app.canvas.dataset.lineTiles = JSON.stringify(tiles);
  st.app.canvas.dataset.linePaths = JSON.stringify(paths);
}

/** The full name beside a machine, in the door hint's style, readable at any zoom. */
export function nameTag(st: SceneState, model: Model, m: Machine): Container {
  const tag = new Container();
  const t = new Text({ resolution: 2, text: `${model.codes.get(m.id) ?? ""} ${model.itemName(m.id)}`.trim(), style: label(11.5, "600", C.onInk) });
  t.position.set(6, -23);
  tag.addChild(new Graphics().rect(0, -26, t.width + 12, 20).fill(C.ink), t);
  tag.position.set(m.x, m.y);   // grows up and to the right from the machine's top-left corner
  tag.visible = false;
  st.layers.tags.addChild(tag);
  return tag;
}

/** The full-name tag shows only while the roof name is hidden (codes mode): in names mode the roof already says it. */
export function showTag(st: SceneState, tag: Container, on: boolean) {
  if (on) st.tagWanted.add(tag); else st.tagWanted.delete(tag);
  tag.visible = on && st.codeMode;
  if (tag.visible) tag.scale.set(Math.max(1, 12 / (11.5 * st.world.scale.x)));
}

/** Labels follow the zoom. One switch for the whole floor: under `codeZoom(minName) - BAND` every machine
 *  and door shows its short code, over `+ BAND` every one shows its name (so each name renders at least NAME_MIN_PX,
 *  about 6 px; the band keeps a wheel resting on the threshold from flickering). In names mode a sub line hides on its
 *  own under 9 px. Zone and lane names grow to stay readable. Called when the zoom moved. */
export function syncLabels(st: SceneState, force = false) {
  const z = st.world.scale.x;
  st.labelZoom = z;
  const code = codesMode(z, st.codeMode, st.minName);
  const flipped = code !== st.codeMode || force;
  if (flipped) {
    st.codeMode = code;
    for (const p of st.codeParts) { for (const n of p.names) n.visible = !code; p.big.visible = code; }
    st.app.canvas.dataset.labels = code ? "codes" : "names";
    for (const t of st.nameTags.values()) showTag(st, t, st.tagWanted.has(t));
  }
  st.app.canvas.dataset.namePx = (st.minName * z).toFixed(2);   // the smallest name as it renders now (tests read it)
  if (measuring()) st.app.canvas.dataset.zoom = String(z);      // the zoom now, which `textsRead` stamps once it rests
  for (const p of st.codeParts) for (const q of p.smalls) for (const o of q.objs) o.visible = subShown(q.size, z, code);
  for (const q of st.msgSmalls) for (const o of q.objs) o.visible = subShown(q.size, z, code);   // plates, tags, dock signs
  if (force || Math.abs(Math.log(z / (st.labelScaled || z))) > 0.02) {
    st.labelScaled = z;
    for (const l of st.zoomLabels) applyZoom(l, z);
    for (const t of st.nameTags.values()) if (t.visible) showTag(st, t, true);
    st.railZoomed(z);
    st.app.canvas.dataset.zones = st.zoomLabels.filter((l) => l.zone !== undefined && l.obj.visible).map((l) => l.zone).join("|");
  }
}

/** Hovering a utility tab names the utility its code stands for, in the door hint's style. */
export function tabHint(st: SceneState, model: Model, id: string, tab: Graphics, code: Text, x: number, y: number) {
  code.eventMode = "none";   // the code on top would otherwise take the hit and hand it to the machine
  const hint = new Container();
  const text = `${model.codes.get(id) ?? ""} ${model.label(id)}: used by many services, so no line is drawn`;
  const ht = new Text({ resolution: 2, text, style: label(11.5, "600", C.onInk) });
  hint.addChild(new Graphics().rect(x, y - 24, ht.width + 12, 20).fill(C.ink), ht);
  ht.position.set(x + 6, y - 21);
  hint.visible = false;
  hint.label = `utility-hint:${id}`;
  st.layers.tags.addChild(hint);   // above lines, their count tags and neighbouring machines
  tab.eventMode = "static";
  tab.on("pointerover", () => { hint.visible = true; });
  tab.on("pointerout", () => { hint.visible = false; });
}

/** A name without the dotted prefix every item on this floor shares (`com.acme.common.db` → `db`). */
export function shortName(st: SceneState, model: Model, id: string): string {
  return shownName(model, id, st.sharedPrefix);
}

/** The factory's sub line (factory/subline.ts, pure so the map audit reads the same words). */
export function factorySub(st: SceneState, model: Model, m: Machine): string {
  return factorySubOf(model, st.bundles, m);
}
