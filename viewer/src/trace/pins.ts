// Pinned traces: the map's pins (the agent's and the user's) minus the ones unpinned here, plus the
// ones pinned here. Changes take effect at once, are kept in browser storage like comments (the page works without
// it), and go to the agent in export-comment.md under `## Pins`. A change the agent has applied (the next map carries
// it) is dropped from storage when the page loads that map.
import type { Store } from "../comments/comments";
import type { CodeMap, PinDirection, Pin } from "../model/types";

export const DIRECTIONS: readonly PinDirection[] = ["upstream", "both", "downstream"];

export interface ShownPin extends Pin {
  local: boolean;      // pinned here, not yet in the map
  missing: boolean;    // its start is not in this map
}

interface Local { added: Omit<Pin, "by">[]; removed: string[] }

/** A title as it goes out: one line, `|` replaced by `/` (the export's field separator). */
export const pinTitle = (title: string): string => title.replace(/\|/g, "/").replace(/\s+/g, " ").trim();

/** The title a new pin offers: the start's name alone (the rail shows the direction beside it); when a pin already
 *  has that title, the direction follows (" · downstream"), so two pins of one start differ. */
export const defaultTitle = (name: string, direction?: PinDirection, existing: readonly { title: string }[] = []): string => {
  const t = pinTitle(name);
  return direction && existing.some((p) => pinTitle(p.title) === t) ? `${t} · ${direction}` : t;
};

/** Plan 2's pin id rule (scripts/vizcode/pins.py `slug`): runs of lower-case letters and digits joined by `-`; `pin` when none. */
export const slug = (t: string): string => (t.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-") || "pin";

const isDirection = (d: unknown): d is PinDirection => typeof d === "string" && (DIRECTIONS as readonly string[]).includes(d);

export class Pins {
  private key: string;
  private local: Local = { added: [], removed: [] };

  constructor(private map: CodeMap, private has: (id: string) => boolean, private store: Store | null) {
    this.key = `viz-code:pins:${map.meta.repo}`;
    try {
      const raw = store?.getItem(this.key);
      const s = raw ? JSON.parse(raw) : null;
      if (s && typeof s === "object") {
        this.local.added = (Array.isArray(s.added) ? s.added : []).filter((a: Partial<Pin> | null) =>
          !!a && typeof a.id === "string" && typeof a.title === "string" && typeof a.start === "string" && isDirection(a.direction));
        this.local.removed = (Array.isArray(s.removed) ? s.removed : []).filter((x: unknown): x is string => typeof x === "string");
      }
    } catch {
      this.local = { added: [], removed: [] };
    }
    this.reconcile();
  }

  private mapPins(): Pin[] {
    return (Array.isArray(this.map.pins) ? this.map.pins : []).filter((p) => p && typeof p.id === "string" && typeof p.start === "string" && isDirection(p.direction));
  }

  /** Drop what the agent has applied: an addition the map now carries (same start, direction and title), a removal of
   *  a pin the map no longer has. */
  private reconcile() {
    const pins = this.mapPins(), ids = new Set(pins.map((p) => p.id));
    const before = JSON.stringify(this.local);
    const live = pins.filter((p) => !this.local.removed.includes(p.id));
    this.local.added = this.local.added.filter((a) => !live.some((p) => p.start === a.start && p.direction === a.direction && pinTitle(p.title) === pinTitle(a.title)));
    this.local.removed = this.local.removed.filter((id) => ids.has(id));
    if (JSON.stringify(this.local) !== before) this.save();
  }

  /** The pins the panel shows: the map's minus local removals, then local additions. */
  list(): ShownPin[] {
    const removed = new Set(this.local.removed);
    return [
      ...this.mapPins().filter((p) => !removed.has(p.id)).map((p) => ({ ...p, local: false, missing: !this.has(p.start) })),
      ...this.local.added.map((a) => ({ ...a, by: "user" as const, local: true, missing: !this.has(a.start) })),
    ];
  }

  /** The shown pin for this start and direction, if any. */
  find(start: string, direction: PinDirection): ShownPin | undefined {
    return this.list().find((p) => p.start === start && p.direction === direction);
  }

  add(title: string, start: string, direction: PinDirection, fallback?: string): ShownPin {
    const t = (title.replace(/\|/g, " ").trim() && pinTitle(title)) || pinTitle(fallback ?? "") || defaultTitle(start);
    const back = this.mapPins().find((p) => this.local.removed.includes(p.id) && p.start === start && p.direction === direction && pinTitle(p.title) === t);
    if (back) {                      // re-pinning what was unpinned here: restore it
      this.local.removed = this.local.removed.filter((id) => id !== back.id);
      this.save();
      return { ...back, local: false, missing: !this.has(start) };
    }
    const taken = new Set([...this.mapPins().map((p) => p.id), ...this.local.added.map((a) => a.id),
      ...(Array.isArray(this.map.unpinned) ? this.map.unpinned : [])]);
    let id = slug(t);
    for (let k = 2; taken.has(id); k++) id = `${slug(t)}-${k}`;
    const p = { id, title: t, start, direction };
    this.local.added.push(p);
    this.save();
    return { ...p, by: "user", local: true, missing: !this.has(start) };
  }

  /** Unpin: a pin made here is forgotten; a map pin is listed for the agent to remove. */
  remove(id: string): void {
    const i = this.local.added.findIndex((a) => a.id === id);
    if (i >= 0) this.local.added.splice(i, 1);
    else if (this.mapPins().some((p) => p.id === id) && !this.local.removed.includes(id)) this.local.removed.push(id);
    else return;
    this.save();
  }

  /** How many changes wait for the agent. */
  changes(): number {
    return this.local.added.length + this.local.removed.length;
  }

  clear(): void {
    this.local = { added: [], removed: [] };
    this.save();
  }

  /** The `## Pins` section of export-comment.md: `pin:` lines, then `unpin:` lines; "" with no change. */
  toMarkdown(): string {
    if (!this.changes()) return "";
    return [
      "## Pins",
      ...this.local.added.map((a) => `- pin: ${pinTitle(a.title)} | start: ${a.start} | direction: ${a.direction}`),
      ...this.local.removed.map((id) => `- unpin: ${id}`),
      "",
    ].join("\n");
  }

  private save() {
    try {
      this.store?.setItem(this.key, JSON.stringify(this.local));
    } catch {
      /* storage unavailable: pin changes live for this page only */
    }
  }
}
