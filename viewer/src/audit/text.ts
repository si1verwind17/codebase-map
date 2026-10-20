// The text and zone checks of the map audit: names, sub lines and signatures cut from the front; labels the plan places
// over a line tile or a machine box, in the base and in each layer view; zones narrower than their label. Each is pure
// and returns its violations ([] when the rule holds). No Pixi here: the words and spots come from the same functions
// the drawing uses (fit.ts, subline.ts, clear.ts, flights.ts, rail-place.ts), never from a copy.
import type { Bundle, Model } from "../model/model";
import type { FloorPlan } from "../factory/plan";
import type { TileRoute } from "../factory/router";
import type { Box } from "../factory/tiles";
import { T } from "../factory/tiles";
import { chestFit, fitLine, fitName, fitSignature, freeBand, nameSpec } from "../factory/fit";
import { boxNameFit, nameContext } from "../factory/boxname";
import { factorySubOf } from "../factory/subline";
import { padReserve } from "../factory/pads";
import { floorPrefix, shownName } from "../floor/names";
import { Clearance, badgeBox, badgeSize, labelBox, layerTileRects, placeBadges, planZoneLabel, type BadgeSpot, type PxRect } from "../factory/clear";
import { coveredKeys, flightPaths, messagingLabels, messagingObstacles, type FlightPath, type MessagingLabels } from "../factory/flights";
import { railLabels, type RailLabels } from "../factory/rail-place";
import { floorLayers } from "../model/layers";
import type { Violation } from "./types";

/** The fitting functions the drawing uses; a test may pass others to prove the check sees a cut. */
export const FITS = { name: fitName, line: fitLine, signature: fitSignature, chest: chestFit };
export type Fits = { name: (name: string, width: number, max: number, sizes?: number[]) => { lines: string[]; size: number };
  line: typeof fitLine; signature: typeof fitSignature; chest: typeof chestFit };

/** A plan as the viewer keeps it: the planner's output, and, once drawn, the messaging, rail labels and badge spots. */
export type AuditPlan = FloorPlan & {
  msg?: { flights: FlightPath[]; covered: Set<string>; obstacles: PxRect[]; labels?: MessagingLabels };
  rail?: RailLabels;
  badges?: Map<string, BadgeSpot>;
};

const tileAt = (px: number, py: number) => ({ x: Math.floor(px / T), y: Math.floor(py / T) });
const cut = (s: string) => s.startsWith("…");
// a role tag's width, estimated as plates are (0.56 em a letter at 9.5 px): the sub line stops short of it
const tagWidth = (tag: string) => Math.ceil(tag.length * 9.5 * 0.56);

/** Every machine name, sub line and signature on the floor as the drawing fits it (factory-draw.ts, machines.ts
 *  `paintBox`, draw.ts `drawDoor`), reported when a shown line starts with "…": cut from the front. The sub line's width
 *  takes the role tag's estimated width (the drawing measures it); a front cut does not depend on the width. */
export function cutViolations(model: Model, container: string, plan: FloorPlan, fit: Fits = FITS): Violation[] {
  const { tf } = plan, out: Violation[] = [];
  const { bundles, doors } = model.bundles(container);
  const ctx = nameContext(model, container, tf.boxes.values(), doors);
  const report = (what: string, b: Box, lines: string[], px: number, py: number) => {
    const bad = lines.find(cut);
    if (bad !== undefined) out.push({ detail: `${what} of ${b.id} cut: '${bad}'`, at: tileAt(px, py) });
  };
  for (const b of tf.boxes.values()) {
    const x = b.x * T, y = b.y * T, W = b.w * T, H = b.h * T;
    const f = boxNameFit(model, ctx, b, fit);   // the name and fit the drawing uses (boxname.ts)
    if (b.foot === "door") {   // drawDoor: code and name relative to the floors above, from 19 px down
      report("name", b, f.lines, x + (ctx.doorOf.get(b.id)!.side === "out" ? 8 : 28), y + 19);
      continue;
    }
    const real = model.twinOf(b.id) ?? b.id;
    const spec = nameSpec(b);
    report("name", b, f.lines, x + spec.ix, spec.top);
    const sub = b.kind === "door" ? "" : factorySubOf(model, bundles, b);
    const params = b.kind === "method" ? model.nodes.get(real)?.signature?.params.map((q) => q.name) : undefined;
    if (!(sub || params) || ["installed", "hub", "rack", "chest"].includes(b.foot)) continue;
    const tag = b.foot === "package" ? model.nodes.get(real)?.role : undefined;
    const reserve = padReserve(tf.landing?.pads.filter((q) => q.machine === b.id).length ?? 0);
    const subW = W - spec.ix - 8 - (tag ? reserve + tagWidth(tag) + 6 : reserve);
    const top = y + H - 17;
    if (spec.top + f.lines.length * (f.size + 2) > top) continue;   // not drawn: the name takes its room
    if (params) report("signature", b, [fit.signature(params, subW)], x + spec.ix, top);
    else report("sub line", b, [fit.line(sub, subW, [11, 10]).text], x + spec.ix, top);
  }
  return out;
}

const hit = (a: PxRect, b: PxRect) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
const LINE_WORD: Record<string, string> = { tapR: "tap", tapW: "tap", tapRW: "tap" };

/** A label the plan places: what it is called in a violation, its boxes (at scale 1 and at its largest scale), and the
 *  machine it may stand inside (a consumer tag in its machine's free band). */
interface Label { what: string; boxes: PxRect[]; inside?: string }

/** The labels the plan places, as factory-draw.ts places them and in its order (each joins the floor's clear room, so
 *  the order decides the spots): the zone names, the messaging labels, the rail labels (placed only so the badges see
 *  the room they take: not checked here), then the `used by N` badges, beside their machines, clear of every layer's
 *  lines. Lane labels are not checked: the drawing sizes them from the measured text (ground.ts `paintLane`), so the
 *  plan has no spot for them, and an estimate could report a false overlap or miss a real one. */
export function labelRects(model: Model, container: string, plan: AuditPlan, bundles: Bundle[]): Label[] {
  const { tf, routes } = plan;
  let msg = plan.msg;
  if (!msg) {
    const flights = flightPaths(tf), covered = coveredKeys(flights, bundles);
    msg = { flights, covered, obstacles: messagingObstacles(tf, routes, flights, covered) };
  }
  const clear = new Clearance(msg.obstacles, tf.cols + 8);
  const out: Label[] = [];
  for (const z of tf.zones) {
    const p = planZoneLabel({ ...z, name: z.name.toUpperCase() }, clear);
    out.push({ what: `zone '${z.name}' label`, boxes: [labelBox(p, 1), labelBox(p, p.maxK)] });
  }
  for (const r of layerTileRects(plan.layers)) clear.add(r);   // as factory-draw.ts: labels keep off every layer's lines
  if (tf.landing) {
    const prefix = floorPrefix(model, [...tf.boxes.values()].filter((b) => b.kind !== "door").map((b) => b.id));
    const band = (id: string) => { const b = tf.boxes.get(id); return b ? freeBand(b, shownName(model, id, prefix)) : undefined; };
    const labels = msg.labels ?? messagingLabels(model, tf, msg.flights, clear, band);
    const box = (l: { x: number; y: number; w: number; h: number }) => ({ x0: l.x, y0: l.y, x1: l.x + l.w, y1: l.y + l.h });
    for (const t of labels.tags) out.push({ what: `tag '${t.text}'`, boxes: [box(t)], ...(t.inside ? { inside: t.machine } : {}) });
    for (const s of labels.signs) out.push({ what: `sign '${s.text}'`, boxes: [box(s)] });
    for (const p of labels.plates) out.push({ what: `plate '${p.text}'`, boxes: [box(p)] });
  }
  if (tf.rails && !plan.rail) railLabels(model, container, tf, clear);
  const items = floorLayers(model, container).filter((l) => l.usedBy > 0 && tf.boxes.has(l.item)).map((l) => {
    const q = tf.boxes.get(l.item)!;
    return { id: l.item, usedBy: l.usedBy, m: { x: q.x * T, y: q.y * T, w: q.w * T, h: q.h * T }, ...badgeSize(l.usedBy) };
  });
  const spots = placeBadges(items, clear, layerTileRects(plan.layers), plan.badges ? new Map(plan.badges) : undefined);
  for (const i of items) {
    const s = spots.get(i.id)!;
    out.push({ what: `badge 'used by ${i.usedBy}'`, boxes: [badgeBox(s, 1), badgeBox(s, s.maxK)] });
  }
  return out;
}

/** Every label the plan places (`labelRects`) that overlaps a line tile on top or a machine box: in the base view
 *  against the base's lines, and in each layer view against that layer's lines (a layer shows over the base). A consumer
 *  tag placed inside its machine's free band is not over that machine. Flight paths are not tiles: a plate stands on its
 *  own flight by design. */
export function overLineViolations(model: Model, container: string, plan: AuditPlan, bundles: Bundle[]): Violation[] {
  const { tf } = plan;
  const tiles = (routes: TileRoute[]) => routes.flatMap((r) => r.pieces.filter((p) => !p.under)
    .map((p) => ({ word: LINE_WORD[r.kind] ?? r.kind, rect: { x0: p.x * T, y0: p.y * T, x1: (p.x + 1) * T, y1: (p.y + 1) * T } })));
  const views: [string, ReturnType<typeof tiles>][] = [["", tiles(plan.routes)],
    ...Object.entries(plan.layers ?? {}).map(([id, l]): [string, ReturnType<typeof tiles>] => [` (layer ${id})`, tiles(l!.routes)])];
  const boxes = [...tf.boxes.values()].map((b) => ({ id: b.id, rect: { x0: b.x * T, y0: b.y * T, x1: (b.x + b.w) * T, y1: (b.y + b.h) * T } }));
  const out: Violation[] = [];
  for (const l of labelRects(model, container, plan, bundles)) {
    const at = tileAt(l.boxes[0].x0, l.boxes[0].y0);
    const box = boxes.find((b) => b.id !== l.inside && l.boxes.some((r) => hit(r, b.rect)));
    if (box) out.push({ detail: `${l.what} over box ${box.id}`, at });
    for (const [view, ts] of views) {
      const t = ts.find((q) => l.boxes.some((r) => hit(r, q.rect)));
      if (t) out.push({ detail: `${l.what} over a ${t.word}${view}`, at });
    }
  }
  return out;
}

/** Every zone whose label has no spot inside it even on an empty floor (`planZoneLabel` with nothing in the way):
 *  narrower (or lower) than its label. */
export function narrowZoneViolations(plan: FloorPlan): Violation[] {
  const out: Violation[] = [];
  for (const z of plan.tf.zones) {
    const p = planZoneLabel({ ...z, name: z.name.toUpperCase() }, new Clearance([], plan.tf.cols + 8));
    if (p.clear) continue;
    const b = labelBox(p, 1);
    out.push({ detail: `zone '${z.name}' label does not fit (${z.w} ${z.w === 1 ? "tile" : "tiles"})`, at: tileAt(b.x0, b.y0) });
  }
  return out;
}
