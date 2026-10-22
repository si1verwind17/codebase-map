// The map audit's shared shapes: check ids, the audit-row each belongs to, and what a check reports.
export type CheckId = "lines.failed" | "lines.plugged" | "lines.trunks" | "lines.under" | "lines.mid-side"
  | "lines.plate-wall" | "lines.lane-drop" | "lines.gap-stub" | "lines.lane-gap" | "text.cut" | "text.over-line" | "zone.narrow" | "pads.corridor" | "travel.long"
  | "flights.overlap" | "flights.in-line" | "flights.hidden" | "lost.relation" | "floor.wide" | "plan.crashed";

/** The row of the owner's audit each check comes from. */
export const ROW: Record<CheckId, string> = { "lines.failed": "9", "lines.plugged": "9", "lines.trunks": "9",
  "lines.under": "2", "lines.mid-side": "13", "lines.plate-wall": "30",
  "lines.lane-drop": "—", "lines.gap-stub": "—", "lines.lane-gap": "—", "text.cut": "5", "text.over-line": "7, 8, 45",
  "zone.narrow": "26", "pads.corridor": "32", "travel.long": "25",
  "flights.overlap": "—", "flights.in-line": "—", "flights.hidden": "—", "lost.relation": "40", "floor.wide": "46", "plan.crashed": "—" };

/** Advisory checks: what they find is a look that is known and kept for now, not a map limit. audit.py lists it in
 *  audit.md under "Drawing advisories"; it never counts as a limit, nor changes the summary line. */
export const ADVISORIES: ReadonlySet<CheckId> = new Set<CheckId>(["flights.in-line", "flights.hidden"]);

/** One broken rule: what is wrong, and where on the floor (tile coordinates) when it has a spot. */
export interface Violation { detail: string; at?: { x: number; y: number } }

/** `advisory`: the check is one of ADVISORIES (on every result of it, passed or not). */
export interface CheckResult { check: CheckId; floor: string; code: string; row: string; ok: boolean; detail: string; at?: { x: number; y: number }; advisory?: true }
