// One floor's plan as a job, and the layout worker's side of it. Pure (no DOM, no pixi): the worker (floor/plan.worker.ts),
// the scene's main-thread fallback (floor/planner.ts) and the map audit all plan a floor through `planJob`, so the three
// can never lay a floor out differently.
import { Model } from "../model/model";
import type { CodeMap } from "../model/types";
import { planFloor, type FloorPlan } from "./plan";

/** Floor `container`'s plan: its bundles (`b`, when the caller has them already), then `planFloor` over them. */
export function planJob(model: Model, container: string, b = model.bundles(container)): FloorPlan {
  return planFloor(model, container, b.doors, b.bundles, b.layered);
}

/** What the page sends the worker: the map's text once, then one floor at a time. */
export type PlanRequest = { kind: "map"; text: string } | { kind: "plan"; id: number; container: string };
/** What the worker answers each `plan` with: the plan (structured-cloned on the way), or why there is none. */
export type PlanReply = { id: number; container: string; plan: FloorPlan } | { id: number; container: string; error: string };

/** The worker's state: the map's text until the first plan asks for it, then the Model built from it once. Answers
 *  every `plan` (an error reply, never a throw: a throw in a worker reaches the page as an `error` event, which the
 *  page takes as the worker being broken); `map` has no answer. */
export function planWorkerState(): { handle(msg: PlanRequest): PlanReply | null } {
  let text: string | null = null;
  let model: Model | null = null;
  return {
    handle(msg) {
      if (msg.kind === "map") { text = msg.text; model = null; return null; }
      const { id, container } = msg;
      try {
        if (!model) {
          if (text === null) throw new Error("no map yet");
          model = new Model(JSON.parse(text) as CodeMap);
          text = null;   // the Model holds what it needs
        }
        if (!model.floor(container)) throw new Error(`no floor ${container}`);
        return { id, container, plan: planJob(model, container) };
      } catch (e) {
        return { id, container, error: e instanceof Error ? e.message : String(e) };
      }
    },
  };
}
