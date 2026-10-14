// The Instruction Booklet palette. Colour always has a job, and never carries a kind alone.
export const C = {
  page: 0xe3ecf3,
  pageDeep: 0xd3dfe9,
  ink: 0x1b1d21,
  paper: 0xffffff,
  shade: 0xc4d1dc,       // flat-shaded side of a module
  red: 0xd01012,         // writes, alerts
  yellow: 0xf5cd2f,      // outside world
  blue: 0x0055bf,        // streams
  green: 0x237841,       // events
  slate: 0x5c6b78,       // reads, secondary
  steel: 0xc9d8e6,       // warehouses, lanes
  shelf: 0xf2f5f8,       // libraries, data shelves
  amber: 0x7a5c00,       // trains (batch)
  select: 0x0055bf,
};

/** The picked mark round a machine (a selection, the trace's focus and pointed row): the blue keyline. */
export const PICKED_RING = { width: 3, color: C.select };
/** A trace pane row's hover on the floor: a thinner ink ring just outside the picked mark (a pointer, not a pick). */
export const HOVER_RING = { width: 1.5, color: C.ink };

export const CSS = Object.fromEntries(Object.entries(C).map(([k, v]) => [k, "#" + v.toString(16).padStart(6, "0")])) as Record<keyof typeof C, string>;

export const FONT = "Archivo, system-ui, sans-serif";

/** Belt treads, faint rules and zone edges, lit windows, the split line of a two-way belt. */
export const F = { tread: 0x3a3e45, rule: 0xb8c6d2, lit: 0xfff1b8, split: 0x5b6470, hub: 0xd4ead9, crate: 0xe8eef3,
  amberSoft: 0xefe3bf };   // rail yards and stations (the approved mock factory-transport.html's amberSoft)
