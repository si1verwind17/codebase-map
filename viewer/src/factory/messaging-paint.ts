// src/factory/messaging-paint.ts
// Painting messaging (spec §5, mock factory-transport.html panels 1 and 2): landing pads, receiving docks, the queue's
// waiting stack, the dead-letter hub's red marks, dotted flight paths, and the plates, tags and signs placed for them
// in flights.ts. Geometry comes from pads.ts and flights.ts; this file only draws.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import { C, F, FONT } from "../floor/palette";
import type { Pt } from "../route/types";
import type { ReplicaTag } from "../floor/movers";
import { dockFace, flightKey, isReplicaTag, type FlightPath, type MessagingLabels, type Placed } from "./flights";
import { PLATE_FONT } from "./fit";
import type { Stack, TileFloor } from "./layout";
import { padMark, type Dock, type Pad } from "./pads";
import { T, type Box } from "./tiles";

const KEY = { width: 1.2, color: C.ink };
const style = (size: number, fill: number) => new TextStyle({ fontFamily: FONT, fontSize: size, fontWeight: "700", fill });

/** A landing pad: a mark on its machine's roof, bottom row (`padMark`): a keylined green-soft square with an H; a
 *  failure pad's H is red (red drones leave it). */
export function paintPad(g: Graphics, p: Pad) {
  const { x, y, w } = padMark(p), a = x + w * 0.28, b = x + w * 0.72, t = y + w * 0.22, u = y + w * 0.78;
  g.rect(x, y, w, w).fill(F.hub).stroke(KEY);
  g.moveTo(a, t).lineTo(a, u).moveTo(b, t).lineTo(b, u).moveTo(a, y + w / 2).lineTo(b, y + w / 2);
  g.stroke({ width: 1.8, color: p.role === "failure" ? C.red : C.green });
}

/** A receiving dock (a push subscription's, or an inbound webhook's): yellow, keylined, with hazard stripes across its
 *  length (past `skip` px of words). */
export function paintDock(g: Graphics, d: Pick<Dock, "x" | "y" | "w" | "h">, skip = 0) {
  const x = d.x * T, y = d.y * T, w = d.w * T, h = d.h * T;
  g.rect(x + 1, y + 1, w - 2, h - 2).fill(C.yellow).stroke(KEY);
  // `skip`: px at a level dock's start its face's words take; the stripes run in the rest
  if (w >= h) for (let i = 0; i < Math.floor((w - skip - 8) / 11); i++) g.moveTo(x + skip + 4 + i * 11, y + h - 3).lineTo(x + skip + 10 + i * 11, y + 3);
  else for (let i = 0; i < Math.floor((h - 8) / 11); i++) g.moveTo(x + 3, y + 4 + i * 11 + 6).lineTo(x + w - 3, y + 4 + i * 11);
  g.stroke({ width: 1.6, color: C.ink });
}

/** A queue hub's waiting stack: three small keylined crates in its reserved tile. */
export function paintStack(g: Graphics, s: Stack) {
  const x = s.x * T, y = s.y * T;
  for (let i = 0; i < 3; i++) g.rect(x + 4, y + T - 3 - (i + 1) * 7, 16, 6).fill(C.yellow).stroke({ width: 1, color: C.ink });
}

/** A dead-letter hub: a red band across its top and its tower (a door's corner marker) red. */
export function paintDeadHub(g: Graphics, b: Box) {
  const x = b.x * T, y = b.y * T, W = b.w * T;
  g.rect(x, y, W, 4).fill(C.red);
  if (b.foot === "hub") g.circle(x + W / 2, y + 14, 6).fill(C.red).stroke({ width: 1, color: C.ink });
  else g.rect(x + W - 16, y + 8, 10, 10).fill(C.red).stroke({ width: 1, color: C.ink });
}

/** Dots along a polyline, spaced along its true (Euclidean) length. */
export function dots(g: Graphics, pts: Pt[], on: number, off: number) {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i], len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    for (let d = 0; d < len; d += on + off) {
      const e = Math.min(len, d + on);
      g.moveTo(a.x + ((b.x - a.x) * d) / len, a.y + ((b.y - a.y) * d) / len).lineTo(a.x + ((b.x - a.x) * e) / len, a.y + ((b.y - a.y) * e) / len);
    }
  }
}

/** A flight's dotted path: green, red for a failure. */
export function paintFlight(g: Graphics, f: FlightPath) {
  dots(g, f.points, 2, 6);
  g.stroke({ width: 3, color: f.dead ? C.red : C.green, cap: "round" });
}

/** A label box: `fill` behind, an optional keyline, the text centred. Returns the outer container (the drone toggle's)
 *  and the inner one (the zoom rule's), so each switch owns its own `visible`. */
export function labelBox(p: Placed, size: number, fill: number, ink: number, edge?: number): { outer: Container; inner: Container } {
  const outer = new Container(), inner = new Container();
  const bg = new Graphics().rect(p.x, p.y, p.w, p.h).fill(fill);
  if (edge !== undefined) bg.stroke({ width: 1, color: edge });
  const t = new Text({ resolution: 2, text: p.text, style: style(size, ink) });
  t.anchor.set(0.5);
  t.position.set(p.x + p.w / 2, p.y + p.h / 2);
  const room = p.w - 6;   // never turned: every word reads left to right
  if (t.width > room) t.scale.set(room / t.width);   // the estimate is generous; never spill out of the box
  inner.addChild(bg, t);
  outer.addChild(inner);
  return { outer, inner };
}

/** A flight's plate: paper, edged and lettered in the flight's ink. */
export const plateView = (p: Placed, dead: boolean, size: number) => labelBox(p, size, C.paper, dead ? C.red : C.green, dead ? C.red : C.green);
/** A consumer's tag under its machine (`group notifier · 2 replicas`): paper on ink, as the mock's badge. */
export const tagView = (p: Placed, size: number) => labelBox(p, size, C.ink, C.paper);
/** A receiving dock's sign (`POST /path` or `push`, a webhook's route): ink on the dock's yellow, keylined. */
export const signView = (p: Placed, size: number) => labelBox(p, size, C.yellow, C.ink, C.ink);

/** The scene's layers and view maps `paintMessaging` draws into and registers with. */
export interface MessagingViews {
  lines: Container;                        // docks, signs and plates (a pad whose machine has no view)
  tags: Container;                         // a tag whose machine has no view
  machineViews: Map<string, Container>;    // stacks, dead-letter marks and tags belong to their machine's view
  lineViews: Map<string, Container[]>;     // fade with their flight's bundle, by its key
  droneViews: Map<string, Container[]>;    // what the drone toggle hides, by bundle key
  dronePaths: boolean;                     // the toggle's state now
  smalls: { objs: Container[]; size: number }[];   // the 9 px rule: hidden when too small, and in codes mode
  replicaTags: Map<string, ReplicaTag>;    // `N replicas` tags by their `tagKey`: they pulse as crates land
}

/** Pads, docks, waiting stacks, dead-letter marks, then the labels placed for them (flights.ts `messagingLabels`):
 *  consumer tags, dock signs, plates. Docks, signs and plates fade with their flight's bundle; pads, stacks, marks and
 *  tags belong to their machine's view. A floor with no hub draws nothing. */
export function paintMessaging(tf: TileFloor, flights: FlightPath[], labels: MessagingLabels, v: MessagingViews) {
  const land = tf.landing;
  if (!land) return;
  const join = (m: Map<string, Container[]>, key: string, c: Container) => m.set(key, [...(m.get(key) ?? []), c]);
  // a pad is a mark on its machine's roof: it is drawn over the roof and fades with the machine
  for (const p of land.pads) { const g = new Graphics(); paintPad(g, p); const m = v.machineViews.get(p.machine); if (m) m.addChild(g); else { v.lines.addChild(g); join(v.lineViews, flightKey(p.machine, p.item), g); } }
  for (const d of land.docks) { const g = new Graphics(); paintDock(g, d); v.lines.addChild(g); join(v.lineViews, flightKey(d.machine, d.item), g); }
  for (const s of land.stacks) { const m = v.machineViews.get(s.item); if (m) { const g = new Graphics(); paintStack(g, s); m.addChild(g); } }
  for (const h of land.messaging.airfields.flatMap((a) => a.hubs)) if (h.dlqOf) {
    const m = v.machineViews.get(h.item), b = tf.boxes.get(h.item);
    if (m && b) { const g = new Graphics(); paintDeadHub(g, b); m.addChild(g); }
  }
  for (const t of labels.tags) {
    const { outer, inner } = tagView(t, PLATE_FONT);
    (v.machineViews.get(t.machine) ?? v.tags).addChild(outer);
    v.smalls.push({ objs: [inner], size: PLATE_FONT });
    const text = inner.children.find((c): c is Text => c instanceof Text);
    if (text && isReplicaTag(t.text)) v.replicaTags.set(t.key, { box: t, text, base: t.text, shown: () => inner.visible && outer.visible });
  }
  for (const s of labels.signs) {
    const { outer, inner } = signView(s, 10);
    v.lines.addChild(outer);
    join(v.lineViews, s.key, outer);
    v.smalls.push({ objs: [inner], size: 10 });
  }
  for (const p of labels.plates) {
    const { outer, inner } = plateView(p, !!flights[p.of!]?.dead, PLATE_FONT);
    v.lines.addChild(outer);
    join(v.lineViews, p.key, outer);
    join(v.droneViews, p.key, outer);   // the drone toggle hides plates with their paths
    outer.visible = v.dronePaths;
    v.smalls.push({ objs: [inner], size: PLATE_FONT });
  }
}

/** A hover list's card, in one style for every hover list (rail signs and platforms, docks, trunks): paper words on an
 *  ink box, padded 6 by 3. It replaces what `tip` held; `corner` places the box's top-left from its size. */
export function fillCard(tip: Container, words: string, corner: (w: number, h: number) => { x: number; y: number }): { w: number; h: number } {
  for (const c of tip.removeChildren()) c.destroy();
  const t = new Text({ resolution: 2, text: words, style: new TextStyle({ fontFamily: FONT, fontSize: 11.5, fontWeight: "600", fill: C.paper, lineHeight: 15.5 }) });
  const w = t.width + 12, h = t.height + 6, at = corner(w, h);
  t.position.set(at.x + 6, at.y + 3);
  tip.addChild(new Graphics().rect(at.x, at.y, w, h).fill(C.ink), t);
  return { w, h };
}
/** A hover card's scale at world zoom `z`: never drawn under its 11.5 px words' readable size on screen. */
export const cardScale = (z: number) => Math.max(1, 12 / (11.5 * z));

/** The scene's layers and view maps `paintWebhooks` draws into and registers with. */
export interface WebhookViews {
  lines: Container;                        // a dock whose machine has no view
  tags: Container;                         // the hover list
  machineViews: Map<string, Container>;    // a dock and its words belong to their service's view: they fade and light with it
  smalls: { objs: Container[]; size: number }[];   // the 9 px rule: hidden when too small, and in codes mode
  docks: { machine: string; objs: Container[] }[];   // each dock's views, for the lit check (tests read it)
  zoom(): number;                          // the world's scale now: the hover list is sized to stay readable
  /** A hover list shown (its text, and how to hide it: the scene hides it on a camera move) or hidden (null). */
  tip(text: string | null, hide: () => void): void;
}

/** Inbound webhook docks (pads.ts `webhookDocks`): the push dock's art against their service, drawn with it, their face's
 *  words (flights.ts `dockFace`) on the dock itself, the stripes in the rest. A dock whose face does not read every route
 *  whole (an upright dock, `webhook`, a method alone, `+N`) lists every route on hover, in the rail signs' style (ink,
 *  paper words), above the dock. */
export function paintWebhooks(tf: TileFloor, v: WebhookViews) {
  if (!tf.webhooks?.length) return;
  const tip = new Container();
  tip.visible = false;
  tip.label = "webhook-tip";
  v.tags.addChild(tip);
  for (const d of tf.webhooks) {
    const face = dockFace(d), parent = v.machineViews.get(d.machine) ?? v.lines;
    const g = new Graphics();
    g.label = `webhook-dock:${d.machine}`;
    paintDock(g, d, face ? face.w + 3 : 0);
    parent.addChild(g);
    const objs: Container[] = [g];
    if (face) {
      const { outer, inner } = signView(face, 10);
      parent.addChild(outer);
      v.smalls.push({ objs: [inner], size: 10 });
      objs.push(outer);
    }
    v.docks.push({ machine: d.machine, objs });
    if (d.signs.length === 1 && d.face === d.signs[0]) continue;
    const words = d.signs.join("\n");
    const hide = () => { tip.visible = false; v.tip(null, hide); };
    for (const o of objs) {
      o.eventMode = "static";
      o.on("pointerover", () => {
        fillCard(tip, words, (_, h) => ({ x: 0, y: -h }));
        tip.position.set(d.x * T, d.y * T - 4);
        tip.scale.set(cardScale(v.zoom()));
        tip.visible = true;
        v.tip(words, hide);
      });
      o.on("pointerout", hide);
    }
  }
}
