// Who plans the floors the scene has not shown yet: a layout worker, so a busy floor's ~1 s of planning never freezes the
// page, or the main thread where there is no worker. Node-safe: the worker itself is spawned by spawn-plan-worker.ts,
// which only App imports, so node tests and the audit never load it.
import type { Model } from "../model/model";
import type { FloorPlan } from "../factory/plan";
import { planJob, type PlanReply, type PlanRequest } from "../factory/plan-job";

export interface Planner {
  /** Where plans are made now: "main" from the start without a worker, or since the worker failed. */
  readonly where: "worker" | "main";
  /** Floor `container`'s plan. `urgent`: the reader waits on it (a floor change), so it goes before queued floors. */
  plan(container: string, urgent?: boolean): Promise<FloorPlan>;
  /** Stop: the worker ends, and a job still waiting never answers with a plan (it rejects). */
  dispose(): void;
}

/** A worker job unanswered this long, while the reader waits on it, is planned on the main thread too: a worker that
 *  hangs never holds a floor change for good. */
export const URGENT_WAIT_MS = 5000;

const disposed = () => new Error("planner disposed");

/** Plans on the main thread, each in its own macrotask, so a caller that awaits it lets a frame in first. */
export function mainPlanner(model: Model): Planner {
  let live = true;
  return {
    where: "main",
    plan(container) {
      return new Promise((resolve, reject) => setTimeout(() => {
        if (!live) { reject(disposed()); return; }
        try { resolve(planJob(model, container)); } catch (e) { reject(e); }
      }, 0));
    },
    dispose() { live = false; },
  };
}

type Job = { id: number; container: string; urgent: boolean; settled: boolean; main?: boolean; timer?: ReturnType<typeof setTimeout>;
  waiters: { resolve: (p: FloorPlan) => void; reject: (e: unknown) => void }[] };

/** Plans in a worker (`spawn`), sent the map's `text` once (it keeps no reference to it). The queue stays here, one job
 *  in the worker at a time, so an urgent job only ever waits for the one in flight; jobs for the same floor are one
 *  job. A worker that fails (an `error` or `messageerror` event, or no worker at all) hands every job still open, and
 *  every later one, to `fallback`. */
export function workerPlanner(model: Model, text: string, spawn: () => Worker, fallback: Planner = mainPlanner(model)): Planner {
  let where: "worker" | "main" = "worker";
  let worker: Worker | null = null;
  let live = true;
  let seq = 0;
  let flying: Job | null = null;
  const queue: Job[] = [];

  const settle = (job: Job, plan: FloorPlan | null, error?: unknown) => {
    if (job.settled) return;
    job.settled = true;
    clearTimeout(job.timer);
    const i = queue.indexOf(job);
    if (i >= 0) queue.splice(i, 1);
    for (const w of job.waiters) if (plan) w.resolve(plan); else w.reject(error);
  };
  /** `job` planned by the fallback instead (the worker failed, answered with an error, or kept the reader waiting). */
  const onMain = (job: Job) => {
    if (job.main) return;   // already handed over (the backstop, then a worker failure): planned there once
    job.main = true;
    fallback.plan(job.container, job.urgent).then((p) => settle(job, p), (e) => settle(job, null, e));
  };

  const pump = () => {
    if (!worker || flying) return;
    let next = queue.shift();
    while (next?.settled) next = queue.shift();
    if (!next) return;
    flying = next;
    worker.postMessage({ kind: "plan", id: next.id, container: next.container } satisfies PlanRequest);
  };

  const fail = () => {
    if (where === "main") return;
    where = "main";
    worker?.terminate();
    worker = null;
    const open = [...(flying ? [flying] : []), ...queue];
    flying = null;
    queue.length = 0;
    for (const job of open) if (!job.settled) onMain(job);
  };

  try {
    worker = spawn();
    worker.addEventListener("message", (e: MessageEvent<PlanReply>) => {
      if (!live) return;
      const r = e.data, job = flying;
      if (!job) return;
      if (r?.id !== job.id) { fail(); return; }   // an answer to nothing asked: the worker is not the one we know
      flying = null;
      if ("plan" in r) settle(job, r.plan); else if (!job.settled) onMain(job);
      pump();
    });
    worker.addEventListener("error", fail);
    worker.addEventListener("messageerror", fail);
    worker.postMessage({ kind: "map", text } satisfies PlanRequest);
  } catch {
    fail();
  }

  return {
    get where() { return where; },
    plan(container, urgent = false) {
      if (!live) return Promise.reject(disposed());
      if (where === "main") return fallback.plan(container, urgent);
      let job = flying?.container === container && !flying.settled ? flying : queue.find((j) => j.container === container);
      if (!job) { job = { id: ++seq, container, urgent: false, settled: false, waiters: [] }; queue.push(job); }
      const out = new Promise<FloorPlan>((resolve, reject) => job.waiters.push({ resolve, reject }));
      if (urgent && !job.urgent) {
        job.urgent = true;
        const i = queue.indexOf(job);
        if (i > 0) { queue.splice(i, 1); queue.unshift(job); }
        const j = job;
        j.timer = setTimeout(() => { if (!j.settled && live) onMain(j); }, URGENT_WAIT_MS);
      }
      pump();
      return out;
    },
    dispose() {
      if (!live) return;
      live = false;
      worker?.terminate();
      worker = null;
      fallback.dispose();
      const open = [...(flying ? [flying] : []), ...queue];
      flying = null;
      queue.length = 0;
      for (const job of open) settle(job, null, disposed());
    },
  };
}
