// Selection and lighting: which lines carry moving parts, what is selected, and the emphasis pass (restyle) that fades
// everything else. Plain functions over the scene's state (state.ts).
import { Graphics, type Container } from "pixi.js";
import { C } from "./palette";
import { STEP } from "../factory/tiles";
import { paintGhost } from "../factory/pieces";
import type { TileRoute } from "../factory/router";
import { expandKeys, lineEnds, railLine as railLineOf, type RailLine, yardKey } from "../factory/rail-place";
import type { LayerLines, LayerView, SceneState, Target } from "./state";
import { peekKeys, type LayerId } from "../model/layers";
import { stroke } from "./draw";
import { showTag } from "./labels";
import { clearLayer } from "./clear";
import { SITE } from "../model/model";
import { codeConduits, paintConduit } from "../factory/conduits";

/** The keys of this floor's rails that a train runs (stand-in `rail:` keys among them), for the default lit set
 *  (floor/lit.ts). */
export function railKeys(st: SceneState): string[] {
  return st.trainPaths.map((p) => p.key);
}

/** Which bundles carry moving parts (App's `defaultLit` with nothing selected, a selection's lines otherwise).
 *  The scene rebuilds its movers after. */
export function light(st: SceneState, keys: Iterable<string>) {
  st.lit = new Set(expand(st, [...keys]));
}

export function select(st: SceneState, t: Target) {
  st.selected = t;
  st.trunkTip.hide();   // the trunk card goes on any selection change
  restyle(st);
}

export function applyDronePaths(st: SceneState) {
  const keys = selectedKeys(st);
  for (const [k, views] of st.droneViews) for (const v of views) v.visible = st.dronePaths || keys.has(k);
}

/** Base lines while an extra layer shows (spec §15: a very faint background beneath it, the mock's 12%). */
export const BASE_FADE = 0.12;

/** Show an extra layer of this floor (`id`), or the base (null; also for an id this floor does not have): the layer's
 *  lines at full strength on top, every base line at BASE_FADE, every building as it was. The selection fade composes
 *  with it. The scene rebuilds its movers after (moving parts run on the shown layer's lines only). */
export function setLayer(st: SceneState, id: LayerId | null) {
  st.layer = id !== null && st.layerViews.has(id) ? id : null;
  st.layers.lines.interactiveChildren = st.layer === null;   // the faint background takes no click and shows no card
  st.trunkTip.hide();
  restyle(st);
}

/** The layer lines a node selected on the base peeks (model/layers.ts `peekKeys`): none while a layer shows or for a
 *  bundle selection. */
function peeked(st: SceneState): Map<LayerId, Set<string>> {
  const sel = st.selected;
  return st.layer === null && sel?.type === "node" ? peekKeys(st.layered, st.floorLayers.map((l) => l.id), sel.id) : new Map();
}

/** How many layer line keys the selection peeks (the canvas's `data-peek`). */
export function peekCount(st: SceneState): number {
  let n = 0;
  for (const keys of peeked(st).values()) n += keys.size;
  return n;
}

/** Each layer view's visibility from the shown layer and the selection: the shown layer whole; a layer holding peeked
 *  lines only those (a view shared by several lines shows while any of them is peeked, at full strength, taking no click);
 *  every other layer hidden with all its line views visible again, so a later `setLayer` shows it whole. */
function layerVisibility(st: SceneState) {
  const peek = peeked(st);
  for (const [id, v] of st.layerViews) {
    const keys = peek.get(id), mine = new Set<Container>();
    for (const k of keys ?? []) for (const c of v.lineViews.get(k) ?? []) mine.add(c);
    v.box.visible = id === st.layer || !!keys;
    v.box.interactiveChildren = !keys;
    for (const views of v.lineViews.values()) for (const c of views) { c.visible = !keys || mine.has(c); if (id !== st.layer) c.alpha = 1; }
  }
}

/** The line kinds the shown layer draws (the legend's line rows), null on the base. */
export function layerLines(st: SceneState): LayerLines | null {
  if (st.layer === null) return null;
  return st.layerViews.get(st.layer)?.lines ?? {};
}

/** The shown layer's routes and lines (none on the base). */
function shownLayer(st: SceneState): LayerView | undefined {
  return st.layer === null ? undefined : st.layerViews.get(st.layer);
}

/** On F0: draw the code-dependency conduits while the overlay is on, drop them while it is off (and on any
 *  other floor, so none leak there). Tests read their count as `data-conduits`. */
export function applyCodeLinks(st: SceneState) {
  const on = st.codeLinks && !!st.tf && !!st.model && !!st.geo && st.container === SITE;
  if (!on) {
    if (st.conduits.length) { clearLayer(st.layers.conduits); st.conduits = []; }
    delete st.app.canvas.dataset.conduits;
    delete st.app.canvas.dataset.conduitsLit;
    return;
  }
  if (!st.conduits.length) {
    // the zone and lane names lie under the conduits: each breaks off around their box at the largest scale they take
    st.conduitBlocked = st.zoomLabels.map(({ obj, maxK }) => {
      const b = obj.getLocalBounds();
      return { x0: obj.x + b.minX * maxK, y0: obj.y + b.minY * maxK, x1: obj.x + b.maxX * maxK, y1: obj.y + b.maxY * maxK };
    });
    st.conduitZoom = st.world.scale.x;
    for (const c of codeConduits(st.model!, st.container, st.geo!.machines, true)) {
      const g = new Graphics();
      g.label = `conduit:${c.key}`;
      paintConduit(g, c, st.conduitBlocked, st.conduitZoom);
      st.layers.conduits.addChild(g);
      st.conduits.push({ user: c.user, used: c.used, g, points: c.points });
    }
  }
  fadeConduits(st);
  st.app.canvas.dataset.conduits = String(st.conduits.length);
}

/** The zoom moved: repaint the conduits once it has moved more than 2%, so their dots keep a readable size on screen. */
export function zoomConduits(st: SceneState) {
  const z = st.world.scale.x;
  if (!st.conduits.length || Math.abs(Math.log(z / (st.conduitZoom || z))) <= 0.02) return;
  st.conduitZoom = z;
  for (const c of st.conduits) paintConduit(c.g, c, st.conduitBlocked, z);
}

/** A conduit not touching the selected machine fades as other lines do; any other selection fades them all. */
function fadeConduits(st: SceneState) {
  const sel = st.selected;
  for (const c of st.conduits) c.g.alpha = !sel || (sel.type === "node" && (sel.id === c.user || sel.id === c.used)) ? 1 : 0.25;
  if (st.conduits.length) st.app.canvas.dataset.conduitsLit = String(st.conduits.filter((c) => c.g.alpha === 1).length);   // tests read it
  else delete st.app.canvas.dataset.conduitsLit;
}

/** Emphasis only: views are built once per floor, so clicks never land on rebuilt objects. */
export function restyle(st: SceneState) {
  const sel = st.selected;
  const keys = selectedKeys(st);
  layerVisibility(st);
  const lit = new Set<Container>();   // a view shared by several lines (a junction plate) stays lit while any of them is selected
  const shown = shownLayer(st);
  for (const m of [st.lineViews, shown?.lineViews ?? new Map<string, Container[]>()]) for (const [k, views] of m) if (keys.has(k)) for (const v of views) lit.add(v);
  // the selection fade is the only greyed look (an inferred factory line has a dashed edge instead); while a layer shows,
  // every base line is also at BASE_FADE and the selection fades within the layer, but a selected box's own base lines
  // (belts, pipes, rails with their station and platform, drones, taps) come up to full strength with its layer lines
  // (spec §15, revised after the demo)
  const base = st.layer === null ? 1 : BASE_FADE;
  // a running trace (spec §3.2) decides the fade: the items it passes through and the lines between them stay at full
  // strength, the rest fade as a selection fades them; a selected item keeps its ring and its own lines
  const traced = st.traced;
  const onTrace = (k: string) => !!traced && endsOf(st, k).every((e) => traced.has(e));
  for (const [k, views] of st.lineViews) for (const v of views) {
    const mine = !!sel && lit.has(v);              // a selected item's own line
    const kept = traced ? onTrace(k) : !sel;        // on the trace; with no trace, nothing selected
    v.alpha = mine ? 1 : (kept ? 1 : 0.25) * base;
  }
  // the shown layer's lines fade the same way, with no base fade beneath them
  if (shown) for (const [k, views] of shown.lineViews) for (const v of views) {
    const kept = traced ? onTrace(k) : !sel;
    v.alpha = (sel && lit.has(v)) || kept ? 1 : 0.25;
  }
  for (const [k, g] of st.implViews) g.alpha = (sel?.type === "node" && k.split("|").includes(sel.id) ? 1 : sel ? 0.25 : 1) * base;
  for (const [id, v] of st.machineViews) {
    const related = sel?.type === "node" && (sel.id === id || touches(st, sel.id, id) || implementsLink(st, sel.id, id));
    const inBundle = sel?.type === "bundle" && endsOf(st, sel.key).includes(id);
    const selectedHere = sel?.type === "node" && sel.id === id;
    v.alpha = (traced ? !traced.has(id) && !selectedHere : sel && !related && !inBundle) ? 0.38 : 1;
    st.highlights.get(id)!.visible = selectedHere || st.traceMarked.has(id);
    st.hoverRings.get(id)!.visible = st.traceHover === id;
    const tab = st.openTabs.get(id);
    if (tab) tab.visible = sel?.type === "node" && sel.id === id;
    const hint = st.doorHints.get(id);
    if (hint && !(sel?.type === "node" && sel.id === id)) hint.visible = false;
    const nt = st.nameTags.get(id);
    if (nt) showTag(st, nt, sel?.type === "node" && sel.id === id);
  }
  // tests read it: each webhook dock and its words, lit (full alpha down to the world) or faded, as `machine:lit|faded`
  if (st.webhookDocks.length) st.app.canvas.dataset.docks = st.webhookDocks.map((d) => {
    const alpha = (c: Container) => { let a = 1; for (let p: Container | null = c; p && p !== st.world; p = p.parent) a *= p.alpha; return a; };
    return `${d.machine}:${d.objs.every((o) => alpha(o) === 1) ? "lit" : "faded"}`;
  }).join(" ");
  else delete st.app.canvas.dataset.docks;
  applyDronePaths(st);
  fadeConduits(st);
  // tests read them: the machines a trace keeps at full strength, the one a pane row's hover rings and the ones the
  // trace marks
  const ds = st.app.canvas.dataset;
  if (traced) ds.traced = String([...st.machineViews.keys()].filter((id) => traced.has(id)).length); else delete ds.traced;
  if (st.traceHover && st.machineViews.has(st.traceHover)) ds.traceHover = st.traceHover; else delete ds.traceHover;
  const marked = [...st.machineViews.keys()].filter((id) => st.traceMarked.has(id)).sort();
  if (marked.length) ds.traceMarked = marked.join(" "); else delete ds.traceMarked;
  const o = st.layers.overlay.clear();
  if (!st.tf) for (const r of st.routes) if (keys.has(r.key)) stroke(o, r.points, { width: 2, color: C.select, alpha: 0.9 }, false);
  if (st.tf) {
    // while a layer shows, only its own selected lines are outlined: a base outline would lie over the layer
    if (st.layer === null) for (const f of st.flights) if (keys.has(f.key)) stroke(o, f.points, { width: 2, color: C.select, alpha: 0.9 }, false);
    // on the base a selected box's peeked layer routes are outlined with its base routes
    const peek = peeked(st), outlined = st.layer === null
      ? [...(st.routes as TileRoute[]), ...[...peek].flatMap(([id, ks]) => (st.layerViews.get(id)?.routes ?? []).filter((r) => ks.has(r.key)))]
      : (shown?.routes ?? []);
    for (const r of outlined) if (keys.has(r.key) && !st.covered.has(r.key)) {
      if (!r.pieces.length) stroke(o, r.points, { width: 2, color: C.select, alpha: 0.9 }, false);   // drone / failed: no tiles
      for (const p of [...(st.railExtra.get(r.key) ?? []), ...r.pieces]) {   // a rail: its yard link and siding too
        if (p.under) { paintGhost(o, p); continue; }
        const cx = p.x * 24 + 12, cy = p.y * 24 + 12;   // solid highlight only over the above-ground tiles
        o.moveTo(cx - STEP[p.in][0] * 12, cy - STEP[p.in][1] * 12).lineTo(cx, cy).lineTo(cx + STEP[p.out][0] * 12, cy + STEP[p.out][1] * 12);
      }
      o.stroke({ width: 2, color: C.select, alpha: 0.9 });
    }
    st.idle = new Set(sel || traced ? [...st.machineViews].filter(([, v]) => v.alpha < 1).map(([id]) => id) : []);
    for (const [id, w] of st.windows) { w.lit.visible = !st.idle.has(id); w.dark.visible = st.idle.has(id); }
  }
}

/** The extra layer to open for node `id`: undefined when it has any base line on this floor (a line, a stand-in rail,
 *  a yard) or no layer line; else the first layer in list order (`floorLayers`) holding one of its lines. */
export function layerOnlyOf(st: SceneState, id: string): LayerId | undefined {
  const r = st.tf?.rails;
  const base = [...st.bundles, ...(r?.shells ?? [])].some((b) => b.a === id || b.b === id) || (r?.yards ?? []).some((y) => y.machine === id);
  if (base) return undefined;
  return st.floorLayers.find((l) => st.layerViews.get(l.id)?.bundles.some((b) => b.a === id || b.b === id))?.id;
}

/** True when closing layer `layer` would leave `t` with no visible line: a node with no base line and a line in the
 *  layer, or a line of the layer itself. */
export function liveOnlyIn(st: SceneState, t: Target, layer: LayerId): boolean {
  if (t?.type === "bundle") return st.layerViews.get(layer)?.bundles.some((b) => b.key === t.key) ?? false;
  if (t?.type !== "node") return false;
  const r = st.tf?.rails;
  const base = [...st.bundles, ...(r?.shells ?? [])].some((b) => b.a === t.id || b.b === t.id) || (r?.yards ?? []).some((y) => y.machine === t.id);
  return !base && (st.layerViews.get(layer)?.bundles.some((b) => b.a === t.id || b.b === t.id) ?? false);
}

/** A machine's lines on this floor, its lines in every extra layer among them (they light and move once their layer
 *  shows; on the base nothing draws them). */
export function bundleKeysOf(st: SceneState, id: string): string[] {
  const r = st.tf?.rails;   // a machine's stand-in rails and the yards against it are its lines too
  const keys = [...st.bundles, ...(r?.shells ?? []), ...st.layered].filter((b) => b.a === id || b.b === id).map((b) => b.key)
    .concat((r?.yards ?? []).filter((y) => y.machine === id).map((y) => yardKey(y.source)));
  return [...new Set(keys)];   // a line in two layers once
}

/** A stand-in rail (`rail:` key) or a yard (`yard:<source>`) as the inspector shows it. */
export function railLine(st: SceneState, key: string): RailLine | undefined {
  return st.tf && st.model ? railLineOf(st.model, st.tf, key) : undefined;
}
/** Keys as the views know them (a yard's brings every rail of the yard), selected now. */
function expand(st: SceneState, keys: string[]): string[] {
  return st.tf ? expandKeys(st.tf, keys) : keys;
}
function selectedKeys(st: SceneState): Set<string> {
  const sel = st.selected;
  return new Set(expand(st, sel?.type === "bundle" ? [sel.key] : sel?.type === "node" ? bundleKeysOf(st, sel.id) : []));
}
/** The machines a selected line touches (a yard's: its machine and every destination). */
function endsOf(st: SceneState, key: string): string[] {
  return (st.tf && st.model && lineEnds(st.model, st.tf, key)) || key.split("|");
}

function touches(st: SceneState, a: string, b: string) {
  return [...st.bundles, ...(st.tf?.rails?.shells ?? []), ...(st.layer === null ? st.layered : shownLayer(st)?.bundles ?? [])].some((x) => (x.a === a && x.b === b) || (x.a === b && x.b === a));
}

/** `a` and `b` are a trait and its implementation, linked on this floor. */
export function implementsLink(st: SceneState, a: string, b: string) {
  return st.implLinks.some((l) => (l.trait === a && l.impl === b) || (l.trait === b && l.impl === a));
}
