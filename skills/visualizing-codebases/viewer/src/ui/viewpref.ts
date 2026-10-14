// What the reader chose to show, kept per browser. Storage can be missing or throw (private windows):
// then the choice lasts for this visit only.

const DRONES = "code-map.drone-paths";

/** Drone paths are shown unless the reader hid them; blocked storage means shown. */
export function loadDronePaths(store: Pick<Storage, "getItem"> | null): boolean {
  try { return store?.getItem(DRONES) !== "off"; } catch { return true; }
}

export function saveDronePaths(store: Pick<Storage, "setItem"> | null, on: boolean): void {
  try { store?.setItem(DRONES, on ? "on" : "off"); } catch { /* blocked: keep it for this visit */ }
}

const CODE_LINKS = "code-map.code-links";

/** The F0 code-dependency conduits are hidden unless the reader showed them; blocked storage means hidden. */
export function loadCodeLinks(store: Pick<Storage, "getItem"> | null): boolean {
  try { return store?.getItem(CODE_LINKS) === "on"; } catch { return false; }
}

export function saveCodeLinks(store: Pick<Storage, "setItem"> | null, on: boolean): void {
  try { store?.setItem(CODE_LINKS, on ? "on" : "off"); } catch { /* blocked: keep it for this visit */ }
}

const SPLIT = "code-map.trace-split";
/** The trace pane's share of the window's height: at first, and its bounds while the divider is dragged. */
export const SPLIT_DEFAULT = 0.45, SPLIT_MIN = 0.2, SPLIT_MAX = 0.8;

export const clampSplit = (f: number): number => Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, f));

/** Where the reader left the divider; blocked or missing storage (or junk in it) means the default. */
export function loadSplit(store: Pick<Storage, "getItem"> | null): number {
  try {
    const v = Number(store?.getItem(SPLIT) ?? "");
    return v >= SPLIT_MIN && v <= SPLIT_MAX ? v : SPLIT_DEFAULT;
  } catch { return SPLIT_DEFAULT; }
}

export function saveSplit(store: Pick<Storage, "setItem"> | null, f: number): void {
  if (!Number.isFinite(f)) return;
  try { store?.setItem(SPLIT, String(clampSplit(f))); } catch { /* blocked: keep it for this visit */ }
}

const RAIL = "code-map.rail-folded";
/** The rail's foldable sections (spec S8), in rail order. */
export type RailSection = "find" | "floor" | "pins";
const SECTIONS: readonly RailSection[] = ["find", "floor", "pins"];

/** The sections the reader folded; blocked or missing storage (or junk in it) means all open. */
export function loadRailFolds(store: Pick<Storage, "getItem"> | null): Set<RailSection> {
  try {
    const kept = (store?.getItem(RAIL) ?? "").split(",");
    return new Set(SECTIONS.filter((s) => kept.includes(s)));
  } catch { return new Set(); }
}

export function saveRailFolds(store: Pick<Storage, "setItem"> | null, folded: ReadonlySet<RailSection>): void {
  try { store?.setItem(RAIL, SECTIONS.filter((s) => folded.has(s)).join(",")); } catch { /* blocked: keep it for this visit */ }
}
