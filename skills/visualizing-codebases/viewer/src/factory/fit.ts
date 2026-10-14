// Text inside machines: the largest size whose wrapped lines fit; never cut from the front.
import { nameLines } from "../floor/names";
import { FOOT, T, type Box } from "./tiles";

export const PLATE_FONT = 10.5;
export const PLATE_H = 17;
/** A label's width at `size`, estimated (never measured, so placement cannot depend on font loading): Archivo bold
 *  averages under 0.56 em a letter on these words (measured: "group notifier ×2" is 82 px at 10.5, estimated 100),
 *  plus 4 px padding a side. The drawn text is centred in it and shrunk in the rare case it is wider. */
export const plateW = (text: string, size = PLATE_FONT) => Math.ceil(text.length * size * 0.56) + 8;

const CHAR = 0.56;   // average glyph width as a fraction of the font size (the same estimate nameLines wraps by)
export const fits = (s: string, width: number, size: number) => s.length * size * CHAR <= width;

/** Does every break in `lines` (from nameLines) fall between words: after a separator or a space, or before "(" or a
 *  camelCase capital, never inside a word ("reservatio" / "n-events")? A line not found in `name` counts as not clean. */
export function cleanBreaks(name: string, lines: string[]): boolean {
  let at = 0;
  for (const l of lines.slice(0, -1)) {
    const i = name.indexOf(l, at);
    if (i < 0) return false;
    at = i + l.length;
    const a = name[at - 1], b = name.slice(at).trimStart()[0];
    if (!(/[-_./ ]/.test(a) || name[at] === " " || b === "(" || (/[a-z0-9]/.test(a) && /[A-Z]/.test(b)))) return false;
  }
  return true;
}

/** A name in up to `max` lines: the largest size that wraps whole; if that wrap breaks inside a word, one size smaller
 *  when that breaks between words (never more: the floor's smallest name sets its codes switch). If even the smallest
 *  size does not wrap whole, the front is kept and the last line ends with "…" (a name is never cut from the front). */
export function fitName(name: string, width: number, max: number, sizes = [14, 13, 12, 11, 10]): { lines: string[]; size: number } {
  const at = (size: number) => { const lines = nameLines(name, width, size, max); return lines[lines.length - 1].startsWith("…") ? undefined : { lines, size }; };
  const i = sizes.findIndex((size) => at(size));
  if (i >= 0) {
    const whole = at(sizes[i])!;
    if (cleanBreaks(name, whole.lines) || i + 1 >= sizes.length) return whole;
    const next = at(sizes[i + 1]);
    return next && cleanBreaks(name, next.lines) ? next : whole;
  }
  const size = sizes[sizes.length - 1];
  const per = Math.max(4, Math.floor(width / (size * CHAR)));
  const lines = nameLines(name, width, size, max + 8).slice(0, max);   // wrap fully, keep the first lines
  const last = lines.length - 1;
  lines[last] = lines[last].slice(0, per - 1).trimEnd() + "…";
  return { lines, size };
}

/** One line of text, never starting with "…": the largest size that fits; else, for a path, leading segments are dropped
 *  ("GET /v1/orders/{id}" → "GET /orders/{id}"); else the end is cut. */
export function fitLine(text: string, width: number, sizes = [11, 10]): { text: string; size: number } {
  for (const size of sizes) if (fits(text, width, size)) return { text, size };
  const size = sizes[sizes.length - 1];
  const at = text.includes(" · ") ? text.lastIndexOf(" · ") + 3 : 0;   // the endpoint is the last part
  const head = text.slice(0, at), tail = text.slice(at);
  const verb = /^[A-Z]+ (?=\/)/.exec(tail)?.[0] ?? "";
  const path = tail.slice(verb.length);
  if (path.includes("/")) {
    const segs = path.split("/").filter(Boolean);
    const lead = path.startsWith("/") ? "/" : "";
    for (let i = 1; i < segs.length; i++) {
      const cand = head + verb + lead + segs.slice(i).join("/");
      if (fits(cand, width, size)) return { text: cand, size };
    }
  }
  const per = Math.max(4, Math.floor(width / (size * CHAR)));
  return { text: text.length > per ? text.slice(0, per - 1).trimEnd() + "…" : text, size };
}

/** A method's parameters for a sub line at 10 px: "(a, b, c)", else "(a, b, …)" with as many leading ones as fit, else "(n params)". */
export function fitSignature(params: string[], width: number): string {
  const full = `(${params.join(", ")})`;
  if (fits(full, width, 10)) return full;
  for (let k = params.length - 1; k >= 1; k--) {
    const cut = `(${params.slice(0, k).join(", ")}, …)`;
    if (fits(cut, width, 10)) return cut;
  }
  return `(${params.length} ${params.length === 1 ? "param" : "params"})`;
}

/** Is `lines` the whole of `name`: nothing cut, no "…", each break after a hyphen, an underscore or a dot? */
export const shownWhole = (name: string, lines: string[]): boolean =>
  lines.join("") === name && !lines.some((l) => l.includes("…")) && lines.slice(0, -1).every((l) => /[-_.]$/.test(l));

/** A cache chest's name room, in px from the box's edges: under the code tab and the lid strap (`top`), above the lower
 *  strap (`bottom`), `inset` narrower than the box, at the machine name sizes, on up to two lines. */
export const CHEST_NAME = { top: 20, bottom: 8, inset: 12, ix: 6, maxLines: 2, sizes: [14, 13, 12, 11, 10] };

/** The chest name in a `w`×`h`-tile chest: the largest size at which it shows whole and fits the name room; undefined
 *  when it does not at any size. The painter draws exactly this. */
export function chestFit(name: string, w: number, h: number): { lines: string[]; size: number } | undefined {
  const { top, bottom, inset, maxLines, sizes } = CHEST_NAME;
  for (const size of sizes) {
    const lines = nameLines(name, w * T - inset, size, maxLines);
    if (shownWhole(name, lines) && top + lines.length * (size + 2) <= h * T - bottom) return { lines, size };
  }
  return undefined;
}

/** A cache chest's footprint: the narrowest (then the shortest) from FOOT.chest up to a lane-end store box (FOOT.warehouse)
 *  that shows its name whole; narrow first, since a chest stands in a corridor between machines. Undefined when even the
 *  lane-end box cannot: the cache keeps its lane. */
export function chestSize(name: string): [number, number] | undefined {
  const [w0, h0] = FOOT.chest, [w1, h1] = FOOT.warehouse;
  for (let w = w0; w <= w1; w++) for (let h = h0; h <= h1; h++) if (chestFit(name, w, h)) return [w, h];
  return undefined;
}

/** Where a box's name goes, by footprint (world px): its top, the width it wraps in, its lines and sizes, its left inset. */
export function nameSpec(b: Box): { top: number; w: number; maxLines: number; sizes: number[]; ix: number } {
  const y = b.y * T, W = b.w * T;
  const base = { top: y + 20, w: W - 14, maxLines: 2, sizes: [14, 13, 12, 11, 10], ix: 7 };
  switch (b.foot) {
    case "service": return { ...base, top: y + 58 };
    case "package": return { ...base, top: y + 22 };
    case "dock": return { ...base, ix: 14, top: y + 50, w: W - 20 };
    case "rack": return { ...base, top: y + 36, sizes: [13, 12, 11, 10] };
    case "installed": return { ...base, top: y + 44, w: W - 12, maxLines: 4, sizes: [12, 11, 10], ix: 6 };
    case "warehouse": return { ...base, top: y + 22, maxLines: 1 };
    // a hub: the name may run to the right keyline (the width estimate is generous), so a hyphenated word like
    // `reservation-` still fits whole at 10 px and breaks after its hyphen, not inside the word
    // no slack left: the estimated right edge is the keyline, so a wide-glyph name (ORDER_EVENTS) can cross it by a few px
    case "hub": return { ...base, top: y + 26, w: W - 4, ix: 4, sizes: [11, 10, 9] };
    // a chest: its whole name on up to two lines between its straps (fit.ts chestFit; the layout sized the chest for it)
    case "chest": return { ...base, top: y + CHEST_NAME.top, w: W - CHEST_NAME.inset, ix: CHEST_NAME.ix, maxLines: CHEST_NAME.maxLines, sizes: CHEST_NAME.sizes };
    default: return base;
  }
}

/** The free band inside a service or package between its fitted name and its sub line (world px), where a consumer's tag
 *  may sit; estimated from the name fit, never measured. Undefined for other footprints. */
export function freeBand(b: Box, name: string): { x0: number; y0: number; x1: number; y1: number } | undefined {
  if (b.foot !== "service" && b.foot !== "package") return undefined;
  const spec = nameSpec(b), fit = fitName(name, spec.w, spec.maxLines, spec.sizes);
  return { x0: b.x * T + 5, y0: spec.top + fit.lines.length * (fit.size + 2) + 3, x1: (b.x + b.w) * T - 5, y1: (b.y + b.h) * T - 19 };
}

// The names/codes switch (pure here so the map audit reads it; machines.ts re-exports it).
/** The smallest a machine or door name renders on screen before the floor switches to codes: 9 px held two wheel notches
 *  further out (the owner: names were still readable there). One notch is x e^-0.2 (deltaY 100, exp(-deltaY / 500)),
 *  so 9 x e^-0.4, about 6 px. Sub lines, tags and plates keep their own 9 px rule (`subShown`). */
export const NAME_MIN_PX = 9 * Math.exp(-0.4);
/** Zoom under which a name of `minName` px would render under NAME_MIN_PX: the floor shows codes instead. One switch for
 *  the whole floor, from the smallest name drawn on it (14 px names alone would switch at about 6/14). */
export const codeZoom = (minName: number) => NAME_MIN_PX / minName;
/** Hysteresis half-width: codes appear under CODE_ZOOM - BAND and names return over CODE_ZOOM + BAND. */
export const CODE_BAND = 0.04;
/** Is the floor in codes mode at zoom `z`, given its mode before and its smallest name (hysteresis around `codeZoom`)? */
export const codesMode = (z: number, was: boolean, minName: number) => z < codeZoom(minName) + (was ? CODE_BAND : -CODE_BAND);
