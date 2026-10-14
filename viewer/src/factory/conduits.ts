// Floor 0 only: the optional code-dependency overlay (spec §8 Libraries). Each `uses-code` pair on the
// site is a thin conduit of fine slate dots, straight from the user's roof centre to the used box's centre (a library on
// the shelf, or another service). It is drawn under the machines, so only the gap between the two boxes shows. It is not
// a line: never routed, never lit, never selected, and it carries nothing. It also never runs over a word: where it would
// cross a floor label (a zone or lane name, under the conduits), it breaks off around the label's largest box.
import type { Graphics } from "pixi.js";
import type { Bundle, Model } from "../model/model";
import { SITE } from "../model/model";
import { C } from "../floor/palette";
import type { Machine } from "../route/types";
import type { PxRect } from "./clear";

type Pt = { x: number; y: number };

export interface Conduit {
  key: string;
  /** the item that imports the code */
  user: string;
  /** the library (or service) whose code it imports */
  used: string;
  points: [Pt, Pt];
}

/** The site's bundles that carry a `uses-code` relation: one conduit each while the overlay is on. The floor's routed
 *  lines (plain `bundles(SITE)`) never carry them. */
const codeBundles = (model: Model): Bundle[] =>
  model.bundles(SITE, { codeLinks: true }).bundles.filter((b) => b.relations.some((x) => x.kind === "uses-code"));

/** How many conduits F0 has to draw: the Code links toggle and its legend entry show only when there is one. */
export const codeLinkCount = (model: Model): number => codeBundles(model).length;

/** The conduits on `container`'s floor: none unless `on` and the floor is the site. `machines`: the floor's boxes in
 *  world px (toGeometry). */
export function codeConduits(model: Model, container: string, machines: ReadonlyMap<string, Pick<Machine, "x" | "y" | "w" | "h">>, on: boolean): Conduit[] {
  if (!on || container !== SITE) return [];
  const out: Conduit[] = [];
  for (const b of codeBundles(model)) {
    const r = b.relations.find((x) => x.kind === "uses-code")!;
    const user = model.liftTo(container, r.from) === b.a ? b.a : b.b, used = user === b.a ? b.b : b.a;
    const u = machines.get(user), v = machines.get(used);
    if (!u || !v) continue;
    out.push({ key: b.key, user, used, points: [{ x: u.x + u.w / 2, y: u.y + u.h / 2 }, { x: v.x + v.w / 2, y: v.y + v.h / 2 }] });
  }
  return out;
}

/** Fine round dots: 1.5 px across at a 3.5 px pitch in world size. The implements link is 3 px ink dots at a 6.5 px
 *  pitch, so the two read apart by size, spacing and colour. Zoomed out, a dot never renders under 1.5 px across or
 *  closer than 4 px to the next (MIN_D, MIN_PITCH on screen): the conduits stay visible at Fit. */
const R = 0.75, PITCH = 3.5, PAD = 2;
export const MIN_D = 1.5, MIN_PITCH = 4;

/** `zoom`: the world's scale, which sets the floor on the dots' on-screen size and spacing. */
export function conduitDots([a, b]: Pt[], blocked: PxRect[] = [], zoom = 1): { r: number; pitch: number; dots: Pt[] } {
  const r = Math.max(R, MIN_D / 2 / zoom), pitch = Math.max(PITCH, MIN_PITCH / zoom);
  const len = Math.hypot(b.x - a.x, b.y - a.y);
  const dots: Pt[] = [];
  const free = (p: Pt) => !blocked.some((q) => p.x >= q.x0 - PAD && p.x <= q.x1 + PAD && p.y >= q.y0 - PAD && p.y <= q.y1 + PAD);
  for (let d = 0; d <= len; d += pitch) {
    const p = { x: a.x + ((b.x - a.x) * d) / (len || 1), y: a.y + ((b.y - a.y) * d) / (len || 1) };
    if (free(p)) dots.push(p);
  }
  return { r, pitch, dots };
}

/** `blocked`: the floor labels' boxes, which the conduit breaks off around. Redrawn as the zoom moves (see `zoom`). */
export function paintConduit(g: Graphics, c: Pick<Conduit, "points">, blocked: PxRect[] = [], zoom = 1) {
  const { r, dots } = conduitDots(c.points, blocked, zoom);
  g.clear();
  for (const p of dots) g.circle(p.x, p.y, r);
  g.fill(C.slate);
}
