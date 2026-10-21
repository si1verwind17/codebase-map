// Planning the nearby floors while the viewer is idle, so descending (or rising) finds its plan already cached.
// `nextFloors` orders what to plan; `createRunner` plans one floor per idle slice through an injected scheduler.
import { SITE, type Model } from "../model/model";

/** How many of a floor's child floors are planned ahead: a big floor opens dozens, and each plan costs memory and worker
 *  time the reader may never use. */
export const MAX_NEARBY = 8;

/** The floors one step from `container`, nearest first: the floor of the selected machine (if it opens one), then up to
 *  `limit` floors of the machines on this floor that open one (the same test App's `go` applies: `model.floor`), in
 *  machine order, then the parent floor. */
export function nextFloors(model: Model, container: string, selected?: string, limit = MAX_NEARBY): string[] {
  const out: string[] = [];
  const add = (c: string | undefined) => { if (c && c !== container && model.floor(c) && !out.includes(c)) out.push(c); };
  const items = Object.keys(model.floor(container)?.items ?? {});
  if (selected && items.includes(selected)) add(selected);
  const first = out.length;
  for (const id of items) { if (out.length - first >= limit) break; add(id); }
  if (container !== SITE) { const p = model.path(container); add(p[p.length - 2]); }
  return out;
}

/** What an idle callback is given: how long the browser expects to stay idle. */
export type Deadline = { timeRemaining(): number };
/** Runs `schedule(slice)` once per step; it returns a way to cancel. */
export type Scheduler = (slice: (deadline?: Deadline) => void) => () => void;

/** requestIdleCallback where the browser has it, with no timeout: a plan waits for real idle time, never forced into a
 *  busy frame (a floor change that needs one asks the planner itself). A 50 ms timer where it does not. */
export const idleScheduler: Scheduler = (slice) => {
  if (typeof requestIdleCallback === "function") {
    const h = requestIdleCallback(slice);
    return () => cancelIdleCallback(h);
  }
  const h = setTimeout(slice, 50);
  return () => clearTimeout(h);
};

export interface Runner {
  /** Replace the queue (a new floor, model or selection); the old one is dropped. */
  start(containers: string[]): void;
  /** Drop the queue. */
  stop(): void;
  /** Floors still waiting, the one being planned included. */
  readonly pending: number;
}

/** One `plan` per slice, nearest first, skipping floors `planned` already holds. A plan that answers with a promise (the
 *  worker's) is awaited before the next slice, so one floor at most is ever being planned. A slice plans nothing, and
 *  is scheduled again, while `busy` (a floor move is animating) or when its idle time has run out. `warm`, when given,
 *  readies the page's side of a planned floor (true when it had work to do): the slice after a plan answers warms that
 *  floor, and a queued floor already planned is warmed in the slice that reaches it; one floor per slice either way. */
export function createRunner(o: { schedule: Scheduler; busy: () => boolean; planned: (c: string) => boolean; plan: (c: string) => void | Promise<unknown>; warm?: (c: string) => boolean; onSettled?: () => void }): Runner {
  let queue: string[] = [];
  let warmNext: string | null = null;   // the floor whose plan just answered: the next slice warms it
  let cancel: (() => void) | null = null;
  let live = 0;   // bumped by every start/stop: a slice scheduled before that (a scheduler whose cancel came too late) does nothing
  let running = false;   // start was called and stop was not since
  let flying = false;    // a plan is in flight: the next slice is scheduled when it ends
  const next = (mine: number) => {
    if (queue.length || warmNext !== null) cancel = o.schedule((d) => slice(mine, d));
    else o.onSettled?.();
  };
  const slice = (mine: number, deadline?: Deadline) => {
    if (mine !== live) return;
    cancel = null;
    if (flying) return;
    if (o.busy() || (deadline && !(deadline.timeRemaining() > 0))) { cancel = o.schedule((d) => slice(mine, d)); return; }
    if (warmNext !== null) { const w = warmNext; warmNext = null; o.warm?.(w); next(mine); return; }
    let c = queue.shift();
    while (c !== undefined && o.planned(c)) {
      if (o.warm?.(c)) { next(mine); return; }
      c = queue.shift();
    }
    const job = c === undefined ? undefined : o.plan(c);
    if (job) {
      flying = true;
      const done = () => { flying = false; if (running) next(live); };
      job.then(() => { if (running && o.warm) warmNext = c!; done(); }, done);
      return;
    }
    next(mine);
  };
  const stop = () => { live++; running = false; cancel?.(); cancel = null; queue = []; warmNext = null; };
  return {
    start(containers) {
      stop();
      running = true;
      queue = [...containers];
      if (flying) return;   // the plan in flight schedules the first slice when it ends
      if (queue.length) { const mine = live; cancel = o.schedule((d) => slice(mine, d)); } else o.onSettled?.();
    },
    stop,
    get pending() { return queue.length + (flying ? 1 : 0) + (warmNext !== null ? 1 : 0); },
  };
}
