// The map audit's runner: plans every floor of a code map as the viewer does and runs each drawing check over it, in
// the order the budget favours (site first, then the floors with the most boxes). Pure: no Pixi, no DOM, no file
// access (cli.ts reads the map and prints the report).
import { Model, SITE } from "../model/model";
import type { CodeMap } from "../model/types";
import type { FloorPlan } from "../factory/plan";
import { planJob } from "../factory/plan-job";
import { flightPaths, type FlightPath } from "../factory/flights";
import type { TileRoute } from "../factory/router";
import { failedViolations, gapStubViolations, laneDropViolations, laneGapViolations, midSideViolations, plateWallViolations, pluggedViolations, trunkViolations, underViolations } from "./lines";
import { cutViolations, narrowZoneViolations, overLineViolations } from "./text";
import { lostViolations, measure, padCorridorViolations, travelViolations, wideViolations, type FloorMeasures } from "./floor";
import { hiddenViolations, inLineViolations, overlapViolations } from "./flights";
import { ADVISORIES, ROW, type CheckId, type CheckResult, type Violation } from "./types";

/** `skipped` holds container ids; `skippedCodes` the same floors by their code, for the reader. */
export interface AuditReport { checked: string[]; skipped: string[]; skippedCodes: string[]; results: CheckResult[]; measured: Record<string, FloorMeasures> }

const firstLine = (e: unknown) => (String(e instanceof Error ? e.message : e).split("\n")[0] || "error").trim();

/** The base's lines and each layer's, with the suffix a violation names its view by. */
const views = (plan: FloorPlan): [string, TileRoute[]][] =>
  [["", plan.routes], ...Object.entries(plan.layers ?? {}).map(([id, l]): [string, TileRoute[]] => [` (layer ${id})`, l!.routes])];

/** A list check over each view (a layer's violations named by the layer), and a per-route check over each view's lines. */
const perView = (plan: FloorPlan, check: (routes: TileRoute[]) => Violation[]) =>
  views(plan).flatMap(([view, routes]) => check(routes).map((v) => ({ ...v, detail: v.detail + view })));
const perRoute = (plan: FloorPlan, check: (r: TileRoute) => Violation[]) =>
  perView(plan, (routes) => routes.filter((r) => r.pieces.length).flatMap(check));

/** Every check over one floor's plan, in the order of the check table. */
function checks(model: Model, c: string, plan: FloorPlan, measured: () => FloorMeasures): [CheckId, () => Violation[]][] {
  const { tf } = plan, { bundles } = model.bundles(c);
  let paths: FlightPath[] | undefined;
  const flights = () => (paths ??= flightPaths(tf));   // as the floor draws them, worked out once for both checks
  return [
    ["lines.failed", () => perView(plan, failedViolations)],
    ["lines.plugged", () => perRoute(plan, (r) => pluggedViolations(tf, r))],
    ["lines.trunks", () => perView(plan, (routes) => trunkViolations(tf, routes))],
    ["lines.under", () => perRoute(plan, underViolations)],
    // a layer shows over the base: a base line's end can take a side's middle tile in a layer view
    ["lines.mid-side", () => [...midSideViolations(tf, plan.routes),
      ...views(plan).slice(1).flatMap(([view, routes]) => midSideViolations(tf, [...plan.routes, ...routes])
        .filter((v) => routes.some((r) => v.detail.startsWith(`${r.key} `))).map((v) => ({ ...v, detail: v.detail + view })))]],
    ["lines.plate-wall", () => perRoute(plan, (r) => plateWallViolations(tf, r))],
    ["lines.lane-drop", () => perView(plan, (routes) => laneDropViolations(tf, routes))],
    ["lines.gap-stub", () => perView(plan, (routes) => gapStubViolations(tf, routes))],
    ["lines.lane-gap", () => perView(plan, (routes) => laneGapViolations(tf, routes))],
    ["text.cut", () => cutViolations(model, c, plan)],
    ["text.over-line", () => overLineViolations(model, c, plan, bundles)],
    ["zone.narrow", () => narrowZoneViolations(plan)],
    ["pads.corridor", () => padCorridorViolations(plan)],
    ["travel.long", () => travelViolations(plan)],
    ["flights.overlap", () => overlapViolations(tf, flights())],
    ["flights.in-line", () => inLineViolations(tf, flights())],
    ["flights.hidden", () => hiddenViolations(tf, flights())],
    ["lost.relation", () => lostViolations(model, c, plan)],
    ["floor.wide", () => wideViolations(measured(), plan)],
  ];
}

/** What the audit may spend, in boxes: each floor costs its box count plus FLOOR_COST, for the work every floor takes
 *  whatever its size. Counted in work, not time, so the same map always checks the same floors on any machine (about
 *  30 s on the largest maps known). */
export const BUDGET = 2_500;
export const FLOOR_COST = 3;

/** Audits the floors of `map`, in order, until they have spent `budget` (BUDGET): the floors after that go to
 *  `skipped`. Each floor gets one result per check (the first violation and how many more), or one `plan.crashed` when
 *  its plan throws; an empty floor is checked with no results. `measured` holds each planned floor's numbers by its
 *  code. */
export function auditMap(map: CodeMap, budget = BUDGET): AuditReport {
  const model = new Model(map);
  const containers = map.layout.containers;
  const size = (c: string) => Object.keys(containers[c].items ?? {}).length;
  const floors = Object.keys(containers).sort((a, b) => Number(b === SITE) - Number(a === SITE) || size(b) - size(a) || a.localeCompare(b));
  const out: AuditReport = { checked: [], skipped: [], skippedCodes: [], results: [], measured: {} };
  let spent = 0;
  for (const c of floors) {
    if (spent >= budget) { out.skipped.push(c); out.skippedCodes.push(model.codes.get(c) ?? c); continue; }
    spent += size(c) + FLOOR_COST;
    out.checked.push(c);
    if (!size(c)) continue;
    const code = model.codes.get(c) ?? c;
    const result = (check: CheckId, vs: Violation[]): CheckResult => {
      const v = vs[0], advisory = ADVISORIES.has(check) ? { advisory: true as const } : {};
      if (!v) return { check, floor: c, code, row: ROW[check], ok: true, detail: "", ...advisory };
      const more = vs.length > 1 ? ` (+${vs.length - 1} more)` : "";
      return { check, floor: c, code, row: ROW[check], ok: false, detail: v.detail + more, ...(v.at ? { at: { x: v.at.x, y: v.at.y } } : {}), ...advisory };
    };
    let plan: FloorPlan;
    try {
      plan = planJob(model, c);
    } catch (e) {
      out.results.push(result("plan.crashed", [{ detail: `${code}: ${firstLine(e)}` }]));
      continue;
    }
    let numbers: FloorMeasures | undefined;
    const measured = () => (numbers ??= measure(plan, model, c));
    for (const [check, run] of checks(model, c, plan, measured)) {
      let vs: Violation[];
      try { vs = run(); } catch (e) { vs = [{ detail: `the check crashed: ${firstLine(e)}` }]; }
      out.results.push(result(check, vs));
    }
    try { out.measured[code] = measured(); } catch { /* a floor that cannot be measured has no numbers */ }
  }
  return out;
}
