// The floor under everything: the tile grid, zones with their names in a clear corner, database lanes.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import { C, F, FONT } from "../floor/palette";
import { Clearance, LANE_FONT, laneLabelPlan, planZoneLabel, ZONE_FONT } from "./clear";
import type { TileLane, Zone } from "./layout";
import { LANE_H, T } from "./tiles";
import { IN_PROCESS } from "./messaging";

/** A floor label that keeps a readable size: scaled up about its anchor until it renders `MIN_PX` tall on screen, up to what
 *  its spot can hold (`maxK`), and hidden when even that is too small. `size` is its font size in world px. */
export interface ZoomLabel { obj: Container; size: number; maxK: number; /** a zone's name, for the shown-names count */ zone?: string }
export const MIN_PX = 9;
export function applyZoom(l: ZoomLabel, zoom: number) {
  const k = Math.min(l.maxK, Math.max(1, MIN_PX / (l.size * zoom)));
  l.obj.scale.set(k);
  l.obj.visible = l.size * zoom * k >= MIN_PX - 0.1;
}

const style = (size: number, fill: number) => new TextStyle({ fontFamily: FONT, fontSize: size, fontWeight: "700", fill });

export function paintGrid(cols: number, rows: number): Graphics {
  const g = new Graphics();
  for (let i = 0; i <= cols; i++) if (i % 5) g.moveTo(i * T, 0).lineTo(i * T, rows * T);
  for (let j = 0; j <= rows; j++) if (j % 5) g.moveTo(0, j * T).lineTo(cols * T, j * T);
  g.stroke({ width: 1, color: C.pageDeep, pixelLine: true });
  for (let i = 0; i <= cols; i += 5) g.moveTo(i * T, 0).lineTo(i * T, rows * T);
  for (let j = 0; j <= rows; j += 5) g.moveTo(0, j * T).lineTo(cols * T, j * T);
  g.stroke({ width: 1, color: F.rule, pixelLine: true });
  return g;
}

export function paintZone(z: Zone, clear: Clearance, labels: ZoomLabel[] = []): Container {
  const c = new Container();
  const g = new Graphics();
  const x = z.x * T, y = z.y * T, w = z.w * T, h = z.h * T;
  if (z.airfield && z.name === IN_PROCESS) {   // a service's own airfield: solid green edge (a broker's is dashed)
    g.rect(x, y, w, h).fill({ color: C.green, alpha: 0.05 }).stroke({ width: 1.5, color: C.green });
  } else if (z.airfield) {   // a broker's airfield: dashed green edge
    g.rect(x, y, w, h).fill({ color: C.green, alpha: 0.05 });
    for (let d = 0; d < w; d += 12) g.moveTo(x + d, y).lineTo(x + Math.min(w, d + 6), y).moveTo(x + d, y + h).lineTo(x + Math.min(w, d + 6), y + h);
    for (let d = 0; d < h; d += 12) g.moveTo(x, y + d).lineTo(x, y + Math.min(h, d + 6)).moveTo(x + w, y + d).lineTo(x + w, y + Math.min(h, d + 6));
    g.stroke({ width: 1.5, color: C.green });
  } else g.rect(x, y, w, h).fill({ color: C.slate, alpha: 0.07 }).stroke({ width: 1, color: F.rule });
  const t = new Text({ resolution: 2, text: z.name.toUpperCase(), style: style(ZONE_FONT, z.airfield ? C.green : C.slate) });
  // grows up and to the right from the label's bottom-left corner, into the clear room the plan found (see clear.ts)
  const plan = planZoneLabel({ ...z, name: z.name.toUpperCase() }, clear);
  const lab = new Container();
  lab.position.set(plan.ax, plan.ay);
  t.position.set(0, -t.height);
  lab.addChild(t);
  labels.push({ obj: lab, size: ZONE_FONT, maxK: plan.maxK, zone: z.name });
  c.addChild(g, lab);
  return c;
}

export function paintLane(l: TileLane, name: string, blocked: number[], labels: ZoomLabel[] = []): Container {
  const c = new Container();
  const x0 = l.x0 * T, x1 = l.x1 * T, y = l.y * T, h = LANE_H * T, cy = y + h / 2;
  const g = new Graphics().rect(x0, y, x1 - x0, h).fill(C.steel).stroke({ width: 1, color: C.edge });
  for (let x = x0 + 8; x < x1 - 8; x += 18) g.moveTo(x, cy).lineTo(Math.min(x + 10, x1 - 8), cy);   // dashed centre line
  g.stroke({ width: 2, color: C.slate });
  const t = new Text({ resolution: 2, text: name, style: style(LANE_FONT, C.text) });
  const plan = laneLabelPlan(l, t.width + 10, blocked);
  const lab = new Container();   // grows down and to the right from its top-left corner
  lab.position.set(plan.x, plan.y);
  t.position.set(5, 1);
  lab.addChild(new Graphics().rect(0, 0, plan.w, plan.h).fill(C.steel), t);
  labels.push({ obj: lab, size: LANE_FONT, maxK: plan.maxK });
  c.addChild(g, lab);
  return c;
}
