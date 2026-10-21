// The layout worker's client (floor/planner.ts) against a fake Worker that answers through planWorkerState in a
// microtask, as the real worker does in its own thread: the queue, urgent jobs, merged jobs, the main-thread fallback
// on a worker error, the urgent backstop and dispose.
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { Model, SITE } from "../../src/model/model";
import type { CodeMap } from "../../src/model/types";
import { planJob, planWorkerState, type PlanRequest } from "../../src/factory/plan-job";
import { mainPlanner, URGENT_WAIT_MS, workerPlanner } from "../../src/floor/planner";
import { nextFloors } from "../../src/floor/precompute";
import { camera, stepTween } from "../../src/floor/camera";
import type { SceneState } from "../../src/floor/state";

const text = readFileSync(new URL("../../../demo/parking-city/docs/viz-code/code-map.json", import.meta.url), "utf8");
const demo = new Model(JSON.parse(text) as CodeMap);
const [A, B, C, D] = nextFloors(demo, SITE);

/** A Worker stand-in: records what it is sent; answers through planWorkerState in a microtask unless `hold` is set
 *  (then `release()` answers the oldest held request). */
class FakeWorker extends EventTarget {
  readonly sent: PlanRequest[] = [];
  readonly held: PlanRequest[] = [];
  terminated = false;
  hold = false;
  private st = planWorkerState();
  postMessage(msg: PlanRequest) {
    this.sent.push(msg);
    if (this.hold && msg.kind === "plan") { this.held.push(msg); return; }
    queueMicrotask(() => this.answer(msg));
  }
  release() { const m = this.held.shift(); if (m) this.answer(m); }
  private answer(msg: PlanRequest) {
    const r = this.st.handle(msg);
    if (r) this.dispatchEvent(new MessageEvent("message", { data: structuredClone(r) }));
  }
  terminate() { this.terminated = true; }
}

const plans = (w: FakeWorker) => w.sent.filter((m) => m.kind === "plan").map((m) => (m as { container: string }).container);
const flush = () => new Promise<void>((r) => setTimeout(r, 0));

afterEach(() => { vi.useRealTimers(); });

describe("workerPlanner", () => {
  it("sends the map once, keeps one job in the worker, and answers each with planJob's plan", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    expect(p.where).toBe("worker");
    const a = p.plan(A), b = p.plan(B);
    expect(w.sent.filter((m) => m.kind === "map")).toHaveLength(1);
    expect(plans(w), "one job in flight").toEqual([A]);
    w.release();
    expect(await a).toEqual(planJob(demo, A));
    expect(plans(w)).toEqual([A, B]);
    w.release();
    expect(await b).toEqual(planJob(demo, B));
  });

  it("puts an urgent job before the queued ones", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    void p.plan(A); void p.plan(B); void p.plan(C);
    const d = p.plan(D, true);
    w.release();
    await flush();
    expect(plans(w), "the urgent job right after the one in flight").toEqual([A, D]);
    w.release();
    expect(await d).toEqual(planJob(demo, D));
    w.release(); w.release();
    await flush();
    expect(plans(w)).toEqual([A, D, B, C]);
  });

  it("makes duplicate asks one job", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    const a1 = p.plan(A), b1 = p.plan(B), a2 = p.plan(A), b2 = p.plan(B, true);
    w.release(); await flush(); w.release();
    const [x1, y1, x2, y2] = await Promise.all([a1, b1, a2, b2]);
    expect(x1).toBe(x2);
    expect(y1).toBe(y2);
    expect(plans(w)).toEqual([A, B]);
  });

  it("on a worker error plans on the main thread from then on, outstanding jobs included", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    const a = p.plan(A), b = p.plan(B);
    w.dispatchEvent(new Event("error"));
    expect(p.where).toBe("main");
    expect(w.terminated).toBe(true);
    expect(await a).toEqual(planJob(demo, A));
    expect(await b).toEqual(planJob(demo, B));
    expect(await p.plan(C)).toEqual(planJob(demo, C));
    expect(plans(w)).toEqual([A]);
  });

  it("falls back on messageerror, and when the worker cannot be made", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    const a = p.plan(A);
    w.dispatchEvent(new Event("messageerror"));
    expect(p.where).toBe("main");
    expect(await a).toEqual(planJob(demo, A));
    const q = workerPlanner(demo, text, () => { throw new Error("no worker here"); });
    expect(q.where).toBe("main");
    expect(await q.plan(B)).toEqual(planJob(demo, B));
  });

  it("plans a job the worker answers with an error on the main thread", async () => {
    const w = new FakeWorker();
    const p = workerPlanner(demo, "{", () => w as unknown as Worker, mainPlanner(demo));   // the worker cannot read this map
    expect(await p.plan(A)).toEqual(planJob(demo, A));
    expect(p.where, "an answered error is not a broken worker").toBe("worker");
  });

  it("plans an urgent job unanswered after URGENT_WAIT_MS on the main thread too; the first answer wins", async () => {
    vi.useFakeTimers();
    const w = new FakeWorker();
    w.hold = true;
    const fallback = mainPlanner(demo), spy = vi.spyOn(fallback, "plan");
    const p = workerPlanner(demo, text, () => w as unknown as Worker, fallback);
    const a = p.plan(A, true);
    let got: unknown;
    void a.then((x) => { got = x; });
    await vi.advanceTimersByTimeAsync(URGENT_WAIT_MS - 1);
    expect(spy).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(spy).toHaveBeenCalledWith(A, true);
    await vi.advanceTimersByTimeAsync(1);   // the fallback's own macrotask
    expect(got).toEqual(planJob(demo, A));
    const first = got;
    w.release();   // the worker answers late: ignored
    await vi.advanceTimersByTimeAsync(1);
    expect(got).toBe(first);
    expect(p.where).toBe("worker");
  });

  it("merges an urgent ask into the job in flight: one job, its backstop armed", async () => {
    vi.useFakeTimers();
    const w = new FakeWorker();
    w.hold = true;
    const fallback = mainPlanner(demo), spy = vi.spyOn(fallback, "plan");
    const p = workerPlanner(demo, text, () => w as unknown as Worker, fallback);
    const a = p.plan(A), b = p.plan(B), a2 = p.plan(A, true);
    expect(plans(w)).toEqual([A]);
    await vi.advanceTimersByTimeAsync(URGENT_WAIT_MS);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(A, true);
    await vi.advanceTimersByTimeAsync(1);
    expect(await a2).toBe(await a);
    w.release();   // the worker answers A late; B goes next
    await vi.advanceTimersByTimeAsync(1);
    expect(plans(w)).toEqual([A, B]);
    w.release();
    expect(await b).toEqual(planJob(demo, B));
  });

  it("an error after the backstop fired plans that floor on the main thread once", async () => {
    vi.useFakeTimers();
    const w = new FakeWorker();
    w.hold = true;
    const fallback = mainPlanner(demo), spy = vi.spyOn(fallback, "plan");
    const p = workerPlanner(demo, text, () => w as unknown as Worker, fallback);
    const a = p.plan(A, true), b = p.plan(B);
    await vi.advanceTimersByTimeAsync(URGENT_WAIT_MS);
    expect(spy).toHaveBeenCalledTimes(1);
    w.dispatchEvent(new Event("error"));   // before the backstop's own plan has answered
    await vi.advanceTimersByTimeAsync(1);
    expect(spy.mock.calls.map((c) => c[0])).toEqual([A, B]);
    expect(await a).toEqual(planJob(demo, A));
    expect(await b).toEqual(planJob(demo, B));
  });

  it("a reply to a job not in flight falls back rather than stalling the queue", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    const a = p.plan(A), b = p.plan(B);
    w.dispatchEvent(new MessageEvent("message", { data: { id: 999, container: A, error: "stray" } }));
    expect(p.where).toBe("main");
    expect(await a).toEqual(planJob(demo, A));
    expect(await b).toEqual(planJob(demo, B));
  });

  it("after dispose terminates the worker, ignores late replies and rejects open jobs", async () => {
    const w = new FakeWorker();
    w.hold = true;
    const p = workerPlanner(demo, text, () => w as unknown as Worker);
    const a = p.plan(A), b = p.plan(B);
    p.dispose();
    expect(w.terminated).toBe(true);
    w.release();
    await expect(a).rejects.toThrow();
    await expect(b).rejects.toThrow();
    await expect(p.plan(C)).rejects.toThrow();
    expect(plans(w)).toEqual([A]);
  });
});

describe("mainPlanner", () => {
  it("plans in a macrotask of its own", async () => {
    const p = mainPlanner(demo);
    let done = false;
    const a = p.plan(A).then((x) => { done = true; return x; });
    await Promise.resolve();
    expect(done).toBe(false);
    expect(await a).toEqual(planJob(demo, A));
    expect(p.where).toBe("main");
  });
});

describe("the camera while a floor change waits on its plan", () => {
  it("a camera ease ending meanwhile leaves data-camera at moving", () => {
    const dataset: Record<string, string> = {};
    const st = { app: { canvas: { dataset } }, world: { position: { set() {} }, scale: { set() {} }, x: 0, y: 0 }, planWaits: 1,
      tween: { from: [0, 0, 1], to: [10, 10, 2], t: 0, ms: 100 } } as unknown as SceneState;
    dataset.camera = "moving";
    stepTween(st, 200);
    expect(st.tween).toBeNull();
    expect(dataset.camera).toBe("moving");
    camera(st, 0, 0, 1, false);
    expect(dataset.camera).toBe("moving");
    st.planWaits = 0;
    camera(st, 0, 0, 1, false);
    expect(dataset.camera).toBe("idle");
  });
});
