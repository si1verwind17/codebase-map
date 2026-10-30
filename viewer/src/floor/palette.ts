// The Instruction Booklet palette, light by default, with an evening (dark) variant. Colour always has a job, and never
// carries a kind alone. The theme is read once at load: the floor bakes colours into its drawing, so a switch reloads.

/** The theme the viewer opens in: the reader's saved choice, else light. */
export const THEME: "light" | "dark" = (() => {
  try { return globalThis.localStorage?.getItem("viz-theme") === "dark" ? "dark" : "light"; } catch { return "light"; }
})();
const DARK = THEME === "dark";

export const C = DARK ? {
  page: 0x181c22,        // the floor at night
  pageDeep: 0x1f242b,
  ink: 0x0c0e12,         // the darkest value: tabs, chimneys, flags
  edge: 0x4a535e,        // keylines: a rim one step lighter than the face, never a dark gap
  paper: 0x2a3038,       // machine faces, one step up from the floor
  text: 0xdde4ec,        // words on a face
  onInk: 0xdde4ec,       // words on an ink tab
  shade: 0x0f1216,       // flat-shaded side of a module
  red: 0xd95a52,         // writes, alerts
  yellow: 0xd9b43a,      // outside world
  blue: 0x3f80d8,        // streams
  green: 0x4fa75a,       // events
  slate: 0x8d98a5,       // reads, secondary
  steel: 0x343d48,       // warehouses, lanes
  shelf: 0x262c34,       // libraries, data shelves
  amber: 0xc8962e,       // trains (batch)
  purple: 0xa57fe0,      // a line drawn straight: the router found no room for it
  select: 0x69b1ff,
} : {
  page: 0xe3ecf3,
  pageDeep: 0xd3dfe9,
  ink: 0x1b1d21,
  edge: 0x1b1d21,        // keylines are ink on the booklet page
  paper: 0xffffff,
  text: 0x1b1d21,
  onInk: 0xffffff,
  shade: 0xc4d1dc,       // flat-shaded side of a module
  red: 0xd01012,         // writes, alerts
  yellow: 0xf5cd2f,      // outside world
  blue: 0x0055bf,        // streams
  green: 0x237841,       // events
  slate: 0x5c6b78,       // reads, secondary
  steel: 0xc9d8e6,       // warehouses, lanes
  shelf: 0xf2f5f8,       // libraries, data shelves
  amber: 0x7a5c00,       // trains (batch)
  purple: 0x8a3ab9,      // a line drawn straight: the router found no room for it
  select: 0x0055bf,
};

/** The picked mark round a machine (a selection, the trace's focus and pointed row): the blue keyline. */
export const PICKED_RING = { width: 3, color: C.select };
/** A trace pane row's hover on the floor: a thinner ring just outside the picked mark (a pointer, not a pick). */
export const HOVER_RING = { width: 1.5, color: C.text };

export const CSS = Object.fromEntries(Object.entries(C).map(([k, v]) => [k, "#" + v.toString(16).padStart(6, "0")])) as Record<keyof typeof C, string>;

export const FONT = "Archivo, system-ui, sans-serif";

/** On the dark floor a belt is bounded by light guard rails, so the dark band never reads as a slot in the floor. */
export const BELT_GUARDS = DARK;
/** Belt body, treads and chevrons, pipe casings and tile clamps, faint rules and zone edges, lit windows, the split line of
 *  a two-way belt, an inferred line's ring, a door's dashed edge. */
export const F = DARK
  ? { guard: 0x5f6975, belt: 0x0e1014, casing: 0x2f363f, clamp: 0x4a535e, tread: 0x1f242b, rule: 0x2b323b, lit: 0xbcb08a,
      chev: 0x8a95a2, split: 0x46505c, hub: 0x1f2e27, crate: 0x3a434e, amberSoft: 0x3a3122, guess: 0x8d98a5, door: 0x8d98a5 }
  : { guard: 0x1b1d21, belt: 0x1b1d21, casing: 0x1b1d21, clamp: 0x1b1d21, tread: 0x3a3e45, rule: 0xb8c6d2, lit: 0xfff1b8,
      chev: 0xffffff, split: 0x5b6470, hub: 0xd4ead9, crate: 0xe8eef3, amberSoft: 0xefe3bf, guess: 0xffffff, door: 0x1b1d21 };
