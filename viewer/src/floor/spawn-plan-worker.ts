// The one module that imports the layout worker: inlined into the page (`?worker&inline`), so the single-file viewer
// opened from file:// needs no second file. Only App imports this; node tests and the audit plan without it.
import PlanWorker from "./plan.worker?worker&inline";

export const spawnPlanWorker = (): Worker => new PlanWorker();
