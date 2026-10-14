// The name each box shows and how the drawing fits it: one copy for the drawing (machines.ts `paintBox`, draw.ts
// `drawDoor`) and the map audit (text.ts `cutViolations`, floor.ts `minNameSize`). Pure: no Pixi.
import type { Door, Model } from "../model/model";
import { chestFit, fitName, nameSpec } from "./fit";
import { doorName, floorPrefix, shownName } from "../floor/names";
import { T, type Box } from "./tiles";

type Fitted = { lines: string[]; size: number };
/** The name-fitting functions the drawing uses; the audit's tests pass others to prove a check sees a cut. */
export interface NameFits { name: (name: string, width: number, max: number, sizes?: number[]) => Fitted; chest: (name: string, w: number, h: number) => Fitted | undefined }
export const NAME_FITS: NameFits = { name: fitName, chest: chestFit };

/** A door's words: its anchor's code, then the anchor's name relative to the floors above (`above`, their labels). */
export const doorWords = (model: Model, anchor: string, above: string[]) =>
  `${model.codes.get(anchor) ?? ""} ${doorName(model.label(anchor), above)}`;

/** A 7-tile door's name (`drawDoor`): wrapped by its width `w` px less 34, 2 lines down to 10 px. */
export const fitDoorName = (words: string, w: number, fits: NameFits = NAME_FITS): Fitted =>
  fits.name(words, w - 34, 2, [12.5, 12, 11, 10]);

/** A machine's name (`paintBox`): a chest's own fit when it has one, else the footprint's name spec. */
export function fitMachineName(b: Box, name: string, fits: NameFits = NAME_FITS): Fitted {
  const spec = nameSpec(b);
  return (b.foot === "chest" ? fits.chest(name, b.w, b.h) : undefined) ?? fits.name(name, spec.w, spec.maxLines, spec.sizes);
}

/** What naming a floor's boxes needs: its doors by id, the dotted prefix its machines share (the scene's
 *  `sharedPrefix`), and the labels of the floors above (a door's name is relative to them). */
export interface NameContext { doorOf: Map<string, Door>; prefix: string; above: string[] }
export function nameContext(model: Model, container: string, boxes: Iterable<Box>, doors: Door[]): NameContext {
  return {
    doorOf: new Map(doors.map((d) => [d.id, d])),
    prefix: floorPrefix(model, [...boxes].filter((b) => b.kind !== "door").map((b) => b.id)),
    above: model.path(container).map((c) => model.label(c)),
  };
}

/** The name a box shows and its fit, as factory-draw.ts draws it: a door-footprint box its door's words (`drawDoor`); a
 *  door box on another footprint its anchor's label; a machine its shown name (`paintBox`). */
export function boxNameFit(model: Model, ctx: NameContext, b: Box, fits: NameFits = NAME_FITS): Fitted & { door: boolean } {
  if (b.foot === "door") return { ...fitDoorName(doorWords(model, ctx.doorOf.get(b.id)!.anchor, ctx.above), b.w * T, fits), door: true };
  const door = b.kind === "door" ? ctx.doorOf.get(b.id) : undefined;
  return { ...fitMachineName(b, door ? model.label(door.anchor) : shownName(model, b.id, ctx.prefix), fits), door: false };
}
