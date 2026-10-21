// Painting machines: block buildings with a flat shade, their code on a tab and their name inside.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import { C, F, FONT } from "../floor/palette";
import { fitLine, fitSignature, fits, nameSpec } from "./fit";
import { fitMachineName } from "./boxname";
export { freeBand, nameSpec, NAME_MIN_PX, codeZoom, CODE_BAND, codesMode } from "./fit";
import { T, type Box } from "./tiles";

export interface Painted {
  view: Container; lit?: Graphics; dark?: Graphics; chimney?: { x: number; y: number };
  /** The name, sub line, role tag and code tab: hidden while the machine shows `big` instead (zoomed far out). */
  names: Container[];
  /** Small text (code tab, role tag, sub line) by font size: each group hides on its own whenever it would render under 9 px. */
  smalls: { objs: Container[]; size: number }[];
  /** The fitted size of the name, in world px: the floor's switch to codes is derived from the smallest one. */
  nameSize: number;
  /** The short code, large and centred on the roof; hidden until the floor is zoomed out. Stays inside the box. */
  big: Container;
}

/** Does a sub line of `size` px show at zoom `z`? Never in codes mode, and not while it would render under 9 px. */
export const subShown = (size: number, z: number, codes: boolean) => !codes && size * z >= 9 - 0.1;
/** The code's size in world px: about 13 px on screen at a 0.39 Fit, shrunk to stay inside a small box. */
export const CODE_FONT = 34;

const KEY = { width: 1.4, color: C.ink };
const text = (s: string, size: number, weight: "500" | "600" | "700", fill: number) =>
  new Text({ resolution: 2, text: s, style: new TextStyle({ fontFamily: FONT, fontSize: size, fontWeight: weight, fill, lineHeight: size + 2 }) });

/** The short code large and centred on a `W`×`H` box at (x, y), on a plate, shrunk to stay inside the box; hidden until asked. */
export function bigCode(code: string, x: number, y: number, W: number, H: number): Container {
  const out = new Container();
  const big = new Text({ resolution: 2, text: code, style: new TextStyle({ fontFamily: FONT, fontSize: CODE_FONT, fontWeight: "700", fill: C.ink }) });
  big.anchor.set(0.5);
  const room = Math.min((W - 12) / (big.width + 16), (H - 12) / (big.height + 8), 1);   // the padded plate must fit the box
  const plate = new Graphics().roundRect(-big.width / 2 - 8, -big.height / 2 - 4, big.width + 16, big.height + 8, 6).fill({ color: C.paper, alpha: 0.92 }).stroke({ width: 1.4, color: C.ink });
  out.addChild(plate, big);
  out.scale.set(room);
  out.position.set(x + W / 2, y + H / 2);
  out.visible = false;
  return out;
}

/** On-screen height of the big code at `zoom` in a `W`×`H` box (the test's readability measure). */
export function bigCodeHeight(W: number, H: number, zoom: number, chars = 2): number {
  const w = chars * CODE_FONT * 0.62, h = CODE_FONT * 1.2;   // glyph estimate: only the shrink to fit matters
  return h * Math.min((W - 12) / (w + 16), (H - 12) / (h + 8), 1) * zoom;
}

/** A door's words, world px (the scene draws them so): the TO/FROM head 5 px down, then up to two name lines from 19 px
 *  down at no more than 12.5 px (line height size + 2.5), `w - 34` wide, starting at `x` (past the arrow on an in-door).
 *  `band` is all the room they can take; flight paths keep out of it. */
export function doorText(r: { x: number; y: number; w: number; h: number }, side: "in" | "out"): { x: number; band: { x0: number; y0: number; x1: number; y1: number } } {
  const x = side === "out" ? r.x + 8 : r.x + 28;
  return { x, band: { x0: x, y0: r.y + 5, x1: x + r.w - 34, y1: r.y + 19 + 2 * (12.5 + 2.5) } };
}

/** `words.reserve`: px at the right of the bottom row kept for the machine's landing pads (pads.ts `padReserve`): the
 *  role tag stands left of them and the sub line stops short of both. */
export type Store = "database" | "cache" | "bucket" | "warehouse";

/** A datastore's art by what it stores: a database or a warehouse is today's warehouse, a cache a chest, a
 *  bucket a container yard; no `store` reads as a database. A cache chest beside its machine (the `chest` footprint) is
 *  always a cache. */
export const storeArt = (b: Box, store: Store | undefined): "warehouse" | "chest" | "yard" | undefined =>
  b.foot === "chest" ? "chest" : b.foot !== "warehouse" ? undefined : store === "cache" ? "chest" : store === "bucket" ? "yard" : "warehouse";

/** Which store art a floor shows, for the legend: each entry only when the floor has one; null when it has neither. */
export interface StoreLegend { cache?: true; bucket?: true }
export function storeLegend(boxes: Iterable<Box>, storeOf: (b: Box) => Store | undefined): StoreLegend | null {
  const out: StoreLegend = {};
  for (const b of boxes) {
    const art = storeArt(b, storeOf(b));
    if (art === "chest") out.cache = true;
    if (art === "yard") out.bucket = true;
  }
  return out.cache || out.bucket ? out : null;
}

const STORE_FACE = { warehouse: C.steel, chest: C.steel, yard: C.shelf };

/** A datastore box's own art inside its keylined face (`art` from storeArt): drawn within the box, so it keeps its footprint. */
export function paintStoreArt(g: Graphics, b: Box, art: "warehouse" | "chest" | "yard") {
  const x = b.x * T, y = b.y * T, W = b.w * T, H = b.h * T;
  if (art === "warehouse") {
    g.moveTo(x, y + 18).lineTo(x + W, y + 18).stroke({ width: 1, color: C.ink });
    for (let i = 0; i < 5; i++) g.rect(x + W - 82 + i * 15, y + 4, 12, 11).fill(F.crate).stroke({ width: 0.8, color: C.ink });
  } else if (art === "chest") {
    // two straps across the chest, the lid's under the code tab, and a latch on the lower one (a chest beside its machine
    // keeps its lower strap at its foot, under its name; a lane end's runs between its name and its sub line)
    const small = b.foot === "chest";
    const bands = small ? [y + 15, y + H - 5] : [y + 15, y + 44];   // the lower strap between the name and the sub line
    for (const by of bands) g.rect(x + 1, by, W - 2, small ? 3 : 4).fill(C.paper).stroke({ width: 0.8, color: C.ink });
    const [lw, lh] = small ? [6, 8] : [10, 11];
    // on the lower strap, at the right: clear of the name and the sub line, inside the box
    const lx = small ? x + W - 10 : x + W - 22, ly = small ? y + H - 9 : bands[1] + 2 - lh / 2;
    g.rect(lx, ly, lw, lh).fill(C.paper).stroke({ width: 1, color: C.ink });
    g.rect(lx + lw / 2 - 1, ly + lh / 2 - 1.5, 2, 3).fill(C.ink);   // keyhole
  } else {
    // a container yard: shipping containers stacked two and one on the ground line, their sides ribbed
    g.moveTo(x, y + 18).lineTo(x + W, y + 18).stroke({ width: 1, color: C.ink });
    const box = (cx: number, cy: number) => {
      g.rect(cx, cy, 30, 7).fill(F.crate).stroke({ width: 0.8, color: C.ink });
      for (let r = cx + 4; r < cx + 30; r += 4) g.moveTo(r, cy + 1.5).lineTo(r, cy + 5.5);
      g.stroke({ width: 0.7, color: C.slate });
    };
    box(x + W - 72, y + 10); box(x + W - 38, y + 10); box(x + W - 56, y + 3);
  }
}

export function paintBox(b: Box, words: { code: string; name: string; sub: string; tag?: string; params?: string[]; reserve?: number; store?: Store }): Painted {
  const x = b.x * T, y = b.y * T, W = b.w * T, H = b.h * T;
  const view = new Container();
  const g = new Graphics();
  const art = storeArt(b, words.store);
  const face = art ? STORE_FACE[art] : b.foot === "dock" ? C.yellow
    : b.foot === "rack" || b.foot === "installed" ? C.shelf : b.foot === "hub" ? F.hub : C.paper;
  g.rect(x + 5, y + 5, W, H).fill(C.shade).stroke({ width: 1, color: C.ink });
  g.rect(x, y, W, H).fill(face).stroke(KEY);
  view.addChild(g);
  const names: Container[] = [];
  const out: Painted = { view, names, big: new Container(), nameSize: 0, smalls: [] };
  const { top: nameTop, ix } = nameSpec(b);

  if (b.foot === "service" || b.foot === "package") {
    const base = b.foot === "service" ? 26 : 18, peak = b.foot === "service" ? 12 : 9;   // sawtooth roof
    const n = 5, step = W / n;
    for (let i = 0; i < n; i++) g.moveTo(x + i * step, y + base).lineTo(x + i * step + step * 0.72, y + peak).lineTo(x + (i + 1) * step, y + base);
    g.stroke(KEY);
    if (b.foot === "service") {
      g.rect(x + W - 22, y - 16, 11, 20).fill(C.ink);   // chimney
      out.chimney = { x: x + W - 16.5, y: y - 16 };
      const lit = new Graphics(), dark = new Graphics();
      for (let i = 0; i < 4; i++) {
        lit.rect(x + 12 + i * 26, y + 38, 16, 12).fill(F.lit).stroke({ width: 1, color: C.ink });
        dark.rect(x + 12 + i * 26, y + 38, 16, 12).fill(C.steel).stroke({ width: 1, color: C.ink });
      }
      dark.visible = false;
      view.addChild(lit, dark);
      out.lit = lit; out.dark = dark;
    }
  } else if (b.foot === "dock") {
    for (let i = 0; i < 8; i++) g.moveTo(x, y + 22 + i * 12).lineTo(x + 9, y + 13 + i * 12);   // hazard edge on the loading side
    g.stroke({ width: 2, color: C.ink });
    g.moveTo(x + W - 22, y + 10).lineTo(x + W - 22, y + 36).stroke({ width: 1.6, color: C.ink });
    g.poly([x + W - 22, y + 10, x + W - 8, y + 16, x + W - 22, y + 22]).fill(C.ink);   // flag
  } else if (b.foot === "rack") {
    g.moveTo(x + 6, y + 32).lineTo(x + W - 6, y + 32).stroke({ width: 2, color: F.rule });
    for (let i = 0; i < 5; i++) g.rect(x + 10 + i * 16, y + 21, 11, 10).fill(C.shade).stroke({ width: 0.8, color: C.ink });
  } else if (b.foot === "installed") {
    // a wall unit: the plug socket near the top, the name upright below it, wrapped at its parts
    g.rect(x + W / 2 - 11, y + 20, 22, 15).fill(C.ink);
    g.rect(x + W / 2 - 6, y + 24, 3, 7).fill(C.paper).rect(x + W / 2 + 3, y + 24, 3, 7).fill(C.paper);
  } else if (art) {
    paintStoreArt(g, b, art);
  } else if (b.foot === "hub") {
    for (const [px, py] of [[4, 4], [W - 14, 4]]) g.rect(x + px, y + py, 10, 10).fill(C.paper).stroke({ width: 1, color: C.ink });   // landing pads
    g.circle(x + W / 2, y + 14, 6).fill(C.green).stroke({ width: 1, color: C.ink });                                            // tower
  }

  if (b.foot !== "hub") {   // code tab
    const code = text(words.code, 10.5, "700", C.paper);
    const tab = new Graphics().rect(x, y, Math.max(24, code.width + 8), 15).fill(C.ink);
    code.position.set(x + 4, y + 1);
    view.addChild(tab, code);
    out.smalls.push({ objs: [tab, code], size: 10.5 });
  }
  const reserve = words.reserve ?? 0;
  let tagW = reserve;
  if (words.tag) {   // a package's role (entry, logic, outbound, model, storage)
    const t = text(words.tag, 9.5, "700", C.slate);
    t.position.set(x + W - reserve - t.width - 6, y + H - 15);
    tagW = reserve + t.width + 6;   // the sub line stops short of the tag (and the pads)
    view.addChild(t);
    out.smalls.push({ objs: [t], size: 9.5 });
  }
  const fit = fitMachineName(b, words.name);   // boxname.ts: the audit reads the same fit
  const name = text(fit.lines.join("\n"), fit.size, "700", C.ink);
  name.position.set(x + ix, nameTop);
  view.addChild(name);
  names.push(name);
  out.nameSize = fit.size;
  if ((words.sub || words.params) && b.foot !== "installed" && b.foot !== "hub" && b.foot !== "rack" && b.foot !== "chest") {
    const subW = W - ix - 8 - tagW;
    let sf: { text: string; size: number };
    if (words.params) {   // a method's signature: whole, or its leading parameters, or a count; never cut from the front
      const sig = fitSignature(words.params, subW);
      sf = { text: sig, size: fits(sig, subW, 11) ? 11 : 10 };
    } else sf = fitLine(words.sub, subW, [11, 10]);
    const sub = text(sf.text, sf.size, "500", b.foot === "dock" ? C.ink : C.slate);
    const top = y + H - 17;
    if (nameTop + fit.lines.length * (fit.size + 2) <= top) { sub.position.set(x + ix, top); view.addChild(sub); out.smalls.push({ objs: [sub], size: sf.size }); }
  }
  out.big = bigCode(words.code, x, y, W, H);
  view.addChild(out.big);
  return out;
}
