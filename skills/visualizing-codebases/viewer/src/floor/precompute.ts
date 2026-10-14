// Planning the nearby floors while the viewer is idle, so descending (or rising) finds its plan already cached.
// `nextFloors` orders what to plan; `createRunner` plans one floor per idle slice through an injected scheduler.
import { SITE, type Model } from "../model/model";

/** The floors one step from `container`, nearest first: the floor of the selected machine (if it opens one), then the
 *  floors of the machines on this floor that open one (the same test App's `go` applies: `model.floor`), in machine
 *  order, then the parent floor. */
export function nextFloors(model: Model, container: string, selected?: string): string[] {
  const out: string[] = [];
  const add = (c: string | undefined) => { if (c && c !== container && model.floor(c) && !out.includes(c)) out.push(c); };
  const items = Object.keys(model.floor(container)?.items ?? {});
  if (selected && items.includes(selected)) add(selected);
  for (const id of items) add(id);
  if (container !== SITE) { const p = model.path(container); add(p[p.length - 2]); }
  return out;
}

/** Runs `schedule(slice)` once per step; it returns a way to cancel. */
export type Scheduler = (slice: () => void) => () => void;

/** requestIdleCallback with a timeout, where the browser has it; a 50 ms timer where it does not. */
export const idleScheduler: Scheduler = (slice) => {
  if (typeof requestIdleCallback === "function") {
    const h = requestIdleCallback(slice, { timeout: 1000 });
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
  /** Floors still waiting. */
  readonly pending: number;
}

/** One `plan` per slice, nearest first, skipping floors `planned` already holds. While `busy` (a floor move
 *  is animating) a slice plans nothing and is scheduled again. */
export function createRunner(o: { schedule: Scheduler; busy: () => boolean; planned: (c: string) => boolean; plan: (c: string) => void; onSettled?: () => void }): Runner {
  let queue: string[] = [];
  let cancel: (() => void) | null = null;
  let live = 0;   // bumped by every start/stop: a slice scheduled before that (a scheduler whose cancel came too late) does nothing
  const slice = (mine = live) => {
    if (mine !== live) return;
    cancel = null;
    if (o.busy()) { cancel = o.schedule(() => slice(mine)); return; }
    let next = queue.shift();
    while (next !== undefined && o.planned(next)) next = queue.shift();
    if (next !== undefined) o.plan(next);
    if (queue.length) cancel = o.schedule(() => slice(mine));
    else o.onSettled?.();
  };
  const stop = () => { live++; cancel?.(); cancel = null; queue = []; };
  return {
    start(containers) {
      stop();
      queue = [...containers];
      if (queue.length) { const mine = live; cancel = o.schedule(() => slice(mine)); } else o.onSettled?.();
    },
    stop,
    get pending() { return queue.length; },
  };
}
