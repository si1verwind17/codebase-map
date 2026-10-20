// Factory drawing: the tile floor's grid, zones and lanes, implements links, belts, pipes, rails and flight paths with
// their hit lines, the machines painted on the grid, the messaging labels and the rail yards.
import { Container, Graphics, Rectangle, Text } from "pixi.js";
import type { Bundle, Model } from "../model/model";
import { SITE } from "../model/model";
import type { FloorGeometry } from "../route/types";
import { crossings } from "./lane";
import { C, PICKED_RING } from "./palette";
import type { TileFloor } from "../factory/layout";
import { freeBand, paintBox, storeLegend, type Store } from "../factory/machines";
import { factoryOps, type Op as FactoryOp, paintHousing, paintInferred, paintPiece, paintPlate, paintRailTile, paintTile } from "../factory/pieces";
import { BADGE_FONT, Clearance, badgeSize, layerTileRects, placeBadges, type BadgeSpot } from "../factory/clear";
import { paintGrid, paintLane, paintZone } from "../factory/ground";
import type { TileRoute } from "../factory/router";
import { paintImplements } from "../factory/implements";
import { coveredKeys, flightPaths, legendKinds, messagingLabels, messagingObstacles, type FlightPath } from "../factory/flights";
import { paintFlight, paintMessaging, paintWebhooks } from "../factory/messaging-paint";
import { padReserve } from "../factory/pads";
import { paintRails } from "../factory/rail-paint";
import { railLabels, railLegend } from "../factory/rail-place";
import type { FloorPlan, LayerLines, SceneState } from "./state";
import type { FloorLayer, LayerId } from "../model/layers";
import { dashed, drawDoor, drawFrame, KEYLINE, stroke } from "./draw";
import { factorySub, label, nameTag, shortName, tabHint } from "./labels";
import { wireDoor, wireMachine } from "./wiring";
import { trunkHover } from "./trunk-hover";

/** `restyle`: the scene's emphasis pass, which a click on a door runs (wiring.ts). */
export function drawFactory(st: SceneState, model: Model, geo: FloorGeometry, tf: TileFloor, restyle: () => void) {
  const routes = st.routes as TileRoute[];
  /** A datastore box's store kind (on an inside floor its box is the store's door, under the store's own id). */
  const storeOf = (b: { id: string; kind: string }): Store | undefined =>
    b.kind === "datastore" ? model.nodes.get(st.doors.get(b.id)?.anchor ?? b.id)?.store : undefined;
  if (st.container !== SITE) drawFrame(st, model, geo);
  st.layers.lanes.addChild(paintGrid(tf.cols, tf.rows));
  // messaging: each event relation a flight carries is drawn as that flight's path from its pad or dock, not as the
  // old machine→hub drone route; labels keep off the paths, not off the routes they replace
  // worked out once per plan (as the plan is): later draws of the floor reuse them
  const plan = st.plans.get(st.container);
  let msg = plan?.tf === tf ? plan.msg : undefined;
  if (!msg) {
    const flights = flightPaths(tf), covered = coveredKeys(flights, st.bundles);
    msg = { flights, covered, obstacles: messagingObstacles(tf, routes, flights, covered) };   // exactly floorObstacles on a floor with no hub
    if (plan?.tf === tf) plan.msg = msg;
  }
  st.flights = msg.flights;
  st.covered = msg.covered;
  const clear = new Clearance(msg.obstacles, tf.cols + 8);
  for (const z of tf.zones) st.layers.lanes.addChild(paintZone(z, clear, st.zoomLabels));
  for (const l of tf.lanes) {
    const name = tf.boxes.has(l.id) && model.kindOf(l.id) !== "datastore" ? shortName(st, model, l.id) : l.label;
    st.layers.lanes.addChild(paintLane(l, name, crossings(routes, (l.y + 1.5) * 24, 36), st.zoomLabels));
  }
  // trait ↔ implementation first: a straight dotted line beneath every belt and pipe and under the machines,
  // not a belt (the drone toggle leaves it alone)
  st.implLinks = model.implementLinks(st.container).filter((l) => geo.machines.has(l.trait) && geo.machines.has(l.impl));
  for (const l of st.implLinks) {
    const g = new Graphics();
    g.label = `implements:${l.key}`;
    paintImplements(g, geo.machines.get(l.trait)!, geo.machines.get(l.impl)!);
    st.layers.lines.addChild(g);
    st.implViews.set(l.key, g);
  }
  // a rail with no batch bundle of its own (a station's stand-in, `rail:` key) resolves to its shell in tf.rails
  const bundleOf = (r: TileRoute) => st.bundles.find((b) => b.key === r.key) ?? tf.rails!.shells.find((b) => b.key === r.key)!;
  for (const f of st.flights) addFlight(st, f);   // under every belt, as drone routes are
  // a tile two or more lines share lists them on hover; ends are named as their boxes are (short code and name)
  const end = (id: string) => {
    const anchor = st.doors.get(id)?.anchor, shows = anchor && model.doorShows(st.container, anchor);
    return { code: model.codes.get(shows || id) ?? "", name: shows ? model.label(shows) : shortName(st, model, id) };
  };
  paintLines(st, routes, bundleOf, trunkHover(st, routes, bundleOf, end), st.layers.lines, st.lineViews, tf.cols);
  // each extra layer's lines (spec §15), painted as the base's are, in its own container above them: hidden until shown
  st.layerViews.clear();
  const layers = plan?.tf === tf ? plan.layers : undefined;
  for (const [id, l] of Object.entries(layers ?? {}) as [LayerId, { routes: TileRoute[] }][]) {
    const bundles = st.layered.filter((b) => b.layer === id), of = (r: TileRoute) => bundles.find((b) => b.key === r.key)!;
    const box = new Container(), lineViews = new Map<string, Container[]>();
    box.label = `layer:${id}`;
    box.visible = false;
    st.layers.layered.addChild(box);
    const ops = paintLines(st, l.routes, of, trunkHover(st, l.routes, of, end), box, lineViews, tf.cols);
    st.layerViews.set(id, { box, lineViews, routes: l.routes, bundles, lines: layerLines(l.routes, bundles, ops) });
  }
  st.chimneys = [];
  st.windows.clear();
  const badges = model.badges(st.container);
  for (const m of geo.machines.values()) {
    const box = tf.boxes.get(m.id)!;
    if (box.foot === "door") { drawDoor(st, model, m, restyle); continue; }
    const real = model.twinOf(m.id) ?? m.id;
    const p = paintBox(box, {
      code: model.codes.get(m.kind === "door" ? st.doors.get(m.id)!.anchor : m.id) ?? "",
      name: m.kind === "door" ? model.label(st.doors.get(m.id)!.anchor) : shortName(st, model, m.id),
      sub: m.kind === "door" ? "" : factorySub(st, model, m),
      params: m.kind === "method" ? model.nodes.get(real)?.signature?.params.map((q) => q.name) : undefined,
      tag: box.foot === "package" ? model.nodes.get(real)?.role : undefined,
      reserve: padReserve(tf.landing?.pads.filter((q) => q.machine === m.id).length ?? 0),
      store: storeOf(box),
    });
    if (p.chimney) st.chimneys.push({ id: m.id, ...p.chimney });
    if (p.lit && p.dark) st.windows.set(m.id, { lit: p.lit, dark: p.dark });
    st.codeParts.push({ names: p.names, big: p.big, smalls: p.smalls });
    st.minName = Math.min(st.minName, p.nameSize);
    const hl = new Graphics().rect(m.x - 5, m.y - 5, m.w + 10, m.h + 10).stroke(PICKED_RING);
    if (m.kind !== "door") {   // utilities this machine uses: their codes on keylined tabs above the roof, left of the chimney
      let bx = m.x + m.w - (p.chimney ? 30 : 4);
      for (const b of badges.get(m.id) ?? []) {
        const t = new Text({ resolution: 2, text: model.codes.get(b) ?? "", style: label(11, "700") });
        bx -= t.width + 8;
        const tab = new Graphics().rect(bx, m.y - 19, t.width + 8, 16).fill(C.paper).stroke(KEYLINE);
        p.view.addChild(tab, t);
        tabHint(st, model, b, tab, t, bx, m.y - 19);
        p.smalls.push({ objs: [tab, t], size: 11 });   // hidden in codes mode, and when too small to read
        t.position.set(bx + 4, m.y - 18);
        bx -= 4;
      }
    }
    if (m.kind === "door") wireDoor(st, model, m, p.view, hl, restyle);   // an installed library: double-click goes to it
    else wireMachine(st, m, p.view, hl, nameTag(st, model, m));
  }
  // messaging labels take the room left (a tag with no clear room under its machine goes inside it, between the name
  // and the sub line: an estimated band); placed on the first draw, after the zone names, clear of every layer's lines
  // too, so a plate reads in each layer view
  for (const r of layerTileRects(plan?.tf === tf ? plan.layers : undefined)) clear.add(r);
  if (tf.landing) {
    const band = (id: string) => { const b = tf.boxes.get(id); return b ? freeBand(b, shortName(st, model, id)) : undefined; };
    msg.labels ??= messagingLabels(model, tf, msg.flights, clear, band);
    paintMessaging(tf, msg.flights, msg.labels, {
      lines: st.layers.lines, tags: st.layers.tags, machineViews: st.machineViews, lineViews: st.lineViews,
      droneViews: st.droneViews, dronePaths: st.dronePaths, smalls: st.msgSmalls, replicaTags: st.replicaTags,
    });
  }
  // inbound webhooks: each service's receiving dock, its words on its face, drawn with the service
  if (tf.webhooks) {
    paintWebhooks(tf, {
      lines: st.layers.lines, tags: st.layers.tags, machineViews: st.machineViews, smalls: st.msgSmalls, docks: st.webhookDocks, zoom: () => st.world.scale.x,
      tip: (t, hide) => {
        if (t === null) { delete st.app.canvas.dataset.dockTip; st.dockTip.shownAt = null; return; }
        st.app.canvas.dataset.dockTip = t;
        st.dockTip = { hide, shownAt: [st.world.x, st.world.y, st.world.scale.x] };
      },
    });
  }
  if (msg.legend === undefined) msg.legend = legendKinds(tf, msg.flights);
  st.events.messaging?.(msg.legend ?? null);
  // rails: yards, platforms, stations and signs, their labels in the room the messaging labels left (placed once)
  if (tf.rails && plan?.tf === tf) {
    plan.rail ??= railLabels(model, st.container, tf, clear);
    const done = paintRails(model, st.container, tf, routes, plan.rail, {
      lines: st.layers.lines, tags: st.layers.tags, lineViews: st.lineViews, smalls: st.msgSmalls,
      select: (key) => st.events.select({ type: "bundle", key }), zoom: () => st.world.scale.x,
      tip: (t) => { if (t === null) delete st.app.canvas.dataset.railTip; else st.app.canvas.dataset.railTip = t; },
    });
    st.railExtra = done.extra;
    st.trainPaths = done.trainPaths;
    st.railZoomed = done.zoomed;
  }
  st.events.rails?.(railLegend(tf));
  st.events.storage?.(storeLegend(tf.boxes.values(), storeOf));
  // `used by N` badges take the room the labels left, beside their machines (placed once per plan, as the labels are).
  // Each opens its item's layer
  const shown = st.floorLayers.filter((l) => l.usedBy > 0 && geo.machines.has(l.item) && st.machineViews.has(l.item));
  const sized = shown.map((l) => ({ l, ...badgeView(l) }));
  const same = plan?.tf === tf ? plan : undefined;
  const spots = placeBadges(sized.map((b) => ({ id: b.l.item, m: geo.machines.get(b.l.item)!, w: b.w, h: b.h })), clear, layerTileRects(same?.layers), same ? (same.badges ??= new Map()) : undefined);
  for (const { l, w, h, t } of sized) st.machineViews.get(l.item)!.addChild(usedByBadge(st, l, spots.get(l.item)!, w, h, t));
  st.smoke = deco();
  st.layers.tags.addChild(st.smoke);
}

/** A badge's text, and the size its spot is planned for (`badgeSize`, an estimate never smaller than the drawn box). */
function badgeView(layer: FloorLayer) {
  const t = new Text({ resolution: 2, text: `used by ${layer.usedBy}`, style: label(BADGE_FONT, "700", C.paper) });
  return { t, ...badgeSize(layer.usedBy) };
}
/** A heavily used item's `used by N` badge (spec §15): paper on ink, as the factory's tags, beside its box where the
 *  floor is clear (clear.ts `planBadge`; kept in the plan). It keeps a readable size as the floor zooms out, as far as
 *  its clear room allows (`zoomBadges`). A tap or click, or Enter on its button once Tab has made the canvas
 *  keyboard-reachable (Pixi's accessibility layer), opens its item's layer. */
function usedByBadge(st: SceneState, layer: FloorLayer, spot: BadgeSpot, pw: number, h: number, t: Text): Container {
  const n = layer.usedBy;
  // the container's origin is the anchor: scaling it grows the badge away from the box (inside its planned box, `pw` wide)
  const w = Math.min(pw, Math.ceil(t.width) + 8), x = spot.ox * w, y = spot.oy * h;
  const c = new Container();
  c.label = `used-by:${layer.id}`;
  c.position.set(spot.ax, spot.ay);
  c.addChild(new Graphics().rect(x, y, w, h).fill(C.ink), t);
  t.position.set(x + 4, y + (h - t.height) / 2);
  c.hitArea = new Rectangle(x, y, w, h);
  c.eventMode = "static";
  c.cursor = "pointer";
  c.accessible = true;
  c.accessibleType = "button";
  c.accessibleTitle = c.accessibleHint = `used by ${n}: show ${layer.name}`;
  c.on("pointertap", (e) => { e.stopPropagation(); st.events.openLayer?.(layer.id); });
  st.usedBadges.push({ view: c, maxK: spot.maxK });
  return c;
}
/** The badge's text renders at least this many screen px while its clear room allows: zoomed out, it is scaled up
 *  about its anchor, up to its spot's `maxK`. */
export const BADGE_MIN_PX = 10;

/** Scale every `used by N` badge for zoom `z`; tests read the smallest text size as drawn (`data-badge-px`). */
export function zoomBadges(st: SceneState, z: number) {
  let px = Infinity;
  for (const b of st.usedBadges) {
    const k = Math.min(b.maxK, Math.max(1, BADGE_MIN_PX / (BADGE_FONT * z)));
    b.view.scale.set(k);
    px = Math.min(px, BADGE_FONT * z * k);
  }
  if (st.usedBadges.length) st.app.canvas.dataset.badgePx = px.toFixed(1);
  else delete st.app.canvas.dataset.badgePx;
}

/** Belts, pipes, rails, taps and drone routes with their hit lines, then every housing, junction plate and inferred ring,
 *  into `into`, each view registered by its bundle key in `views`: the base's lines, or one extra layer's. Returns the
 *  paint ops (the legend reads a layer's plates from them). */
function paintLines(st: SceneState, routes: TileRoute[], bundleOf: (r: TileRoute) => Bundle, hover: (hit: Graphics) => void,
  into: Container, views: Map<string, Container[]>, cols: number): FactoryOp[] {
  // taps first, then rails, belts and pipes on top (the underground order, spec §4)
  const order = { tapR: 0, tapW: 0, tapRW: 0, drone: 1, rail: 2, belt: 3, pipe: 4 };
  const idx = routes.map((_, i) => i).sort((p, q) => order[routes[p].kind] - order[routes[q].kind]);
  const ops = factoryOps(routes.map((r) => { const b = bundleOf(r); return { pieces: r.pieces, kind: r.kind, failed: r.failed, both: r.both, inferred: b.inferred === b.relations.length && b.relations.length > 0 }; }), cols, idx);
  for (const i of idx) {
    if (st.covered.has(routes[i].key)) continue;   // drawn as its flights
    const r = routes[i], b = bundleOf(r), g = deco();
    if (r.kind === "drone") dashed(g, r.points, 2, 6, { width: 3, color: C.green, cap: "round" });
    else if (r.failed) dashed(g, r.points, 6, 5, { width: 3, color: C.red });   // could not be routed: still shown, still selectable
    else for (const o of ops) if (o.layer === "body" && o.ri === i) paintPiece(g, o.p, r.kind, r.both);
    if (b.inferred === b.relations.length && b.relations.length) g.label = "inferred";
    addTileLine(st, r, b, g, hover, into, views);
  }
  // then every housing, every junction plate and every inferred ring: no line's body can cover an underground housing
  const extra = new Map<string, Graphics>();   // one Graphics per layer and route, created in paint order
  const gOf = (layer: string, ri: number) => {
    const k = layer + ri;
    let g = extra.get(k);
    if (!g) { g = deco(); extra.set(k, g); into.addChild(g); views.get(routes[ri].key)?.push(g); }
    return g;
  };
  for (const o of ops) {
    if (o.layer === "tile") {   // a shared belt tile: one composed body, lit with every route on it
      const g = deco();
      paintTile(g, o.tile!);
      into.addChild(g);
      for (const h of o.holders!) views.get(routes[h].key)?.push(g);
    } else if (o.layer === "rail") {   // a rail junction: straight and curve on one tile, lit with every rail on it
      const g = deco();
      paintRailTile(g, o.rails!);
      into.addChild(g);
      for (const h of o.holders!) views.get(routes[h].key)?.push(g);
    } else if (o.layer === "housing") paintHousing(gOf("housing", o.ri), o.p, routes[o.ri].kind, o.both);
    else if (o.layer === "plate") {   // a junction plate is the tile's, not one line's: every route on top there fades with its own selection
      const g = deco();
      paintPlate(g, o.p);
      into.addChild(g);
      for (const h of o.holders!) views.get(routes[h].key)?.push(g);
    } else if (o.layer === "inferred") paintInferred(gOf("inferred", o.ri), o.p);
  }
  return ops;
}

/** The line kinds a layer draws (the legend's line rows while it shows). */
function layerLines(routes: TileRoute[], bundles: Bundle[], ops: FactoryOp[]): LayerLines {
  const out: LayerLines = {};
  for (const r of routes) {
    if (r.failed) out.failed = true;
    else if (r.kind === "belt" || r.kind === "pipe" || r.kind === "rail" || r.kind === "drone") out[r.kind] = true;
    else out.tap = true;
    if (r.pieces.some((p) => p.under)) out.under = true;
    if (r.both) out.both = true;
  }
  if (bundles.some((b) => b.inferred === b.relations.length && b.relations.length > 0)) out.inferred = true;
  if (ops.some((o) => o.layer === "plate")) out.plate = true;
  return out;
}

/** A line's painted body, a shared tile's body, a junction plate, a housing, an inferred ring, the smoke: drawn above
 *  other lines' hit areas, they take no click, so a press on a trunk tile or a plate reaches the topmost line's hit area
 *  beneath and selects that line, as a press on its own tile does. */
const deco = () => { const g = new Graphics(); g.eventMode = "none"; return g; };

/** One flight's dotted path and its hit line. It is its bundle's line: selection, fading and the drone toggle reach it. */
function addFlight(st: SceneState, f: FlightPath) {
  const g = deco();
  g.label = `flight:${f.flight}:${f.key}`;
  paintFlight(g, f);
  const hit = new Graphics();
  stroke(hit, f.points, { width: 16, color: 0xffffff, alpha: 0.001 }, false);
  hit.eventMode = "static";
  hit.cursor = "pointer";
  hit.on("pointertap", (e) => { e.stopPropagation(); st.events.select({ type: "bundle", key: f.key }); });
  st.layers.lines.addChild(g, hit);
  st.lineViews.set(f.key, [...(st.lineViews.get(f.key) ?? []), g]);
  st.droneViews.set(f.key, [...(st.droneViews.get(f.key) ?? []), g, hit]);
  g.visible = hit.visible = st.dronePaths;
}

function addTileLine(st: SceneState, r: TileRoute, b: Bundle, g: Graphics, hover: (hit: Graphics) => void, into: Container, views: Map<string, Container[]>) {
  const hit = new Graphics();
  if (r.pieces.length) for (const p of r.pieces) if (!p.under) hit.rect(p.x * 24, p.y * 24, 24, 24);
  if (r.pieces.length) hit.fill({ color: 0xffffff, alpha: 0.001 });
  else stroke(hit, r.points, { width: 16, color: 0xffffff, alpha: 0.001 }, false);
  hit.eventMode = "static";
  hit.cursor = "pointer";   // a stand-in rail (`rail:` key, a shell of tf.rails) is selected like any line
  hit.on("pointertap", (e) => { e.stopPropagation(); st.events.select({ type: "bundle", key: b.key }); });
  if (r.kind !== "drone") hover(hit);   // a tile it shares with another line shows the trunk card
  into.addChild(g, hit);
  // appended: a bundle only partly carried by flights keeps its old route beside the flights already registered
  views.set(b.key, [...(views.get(b.key) ?? []), g]);
  if (r.kind === "drone") { st.droneViews.set(b.key, [...(st.droneViews.get(b.key) ?? []), g, hit]); g.visible = hit.visible = st.dronePaths; }
}
