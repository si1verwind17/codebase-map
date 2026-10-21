// The hidden-tab pause (visibility.ts): the ticker stops while the page is hidden and starts again when it shows, so
// motion never jumps to catch up on its return.
import { describe, expect, it } from "vitest";
import { pauseWhenHidden, type VisibilitySource } from "../../src/floor/visibility";

/** A document whose visibility the test sets, and a ticker that counts its calls. */
function fakes(state: DocumentVisibilityState = "visible") {
  const listeners = new Set<() => void>();
  const doc = {
    visibilityState: state,
    addEventListener: (_t: "visibilitychange", f: () => void) => { listeners.add(f); },
    removeEventListener: (_t: "visibilitychange", f: () => void) => { listeners.delete(f); },
  };
  const calls: string[] = [];
  const ticker = { start: () => calls.push("start"), stop: () => calls.push("stop") };
  const set = (s: DocumentVisibilityState) => { doc.visibilityState = s; for (const f of [...listeners]) f(); };
  return { doc: doc as VisibilitySource, ticker, calls, set, listeners };
}

describe("pauseWhenHidden", () => {
  it("stops the ticker once when the page hides and starts it once when it shows", () => {
    const f = fakes();
    pauseWhenHidden(f.doc, f.ticker);
    expect(f.calls).toEqual([]);
    f.set("hidden");
    expect(f.calls).toEqual(["stop"]);
    f.set("visible");
    expect(f.calls).toEqual(["stop", "start"]);
  });

  it("stops at once when the page is already hidden at install", () => {
    const f = fakes("hidden");
    pauseWhenHidden(f.doc, f.ticker);
    expect(f.calls).toEqual(["stop"]);
    f.set("visible");
    expect(f.calls).toEqual(["stop", "start"]);
  });

  it("repeated events in the same state make no extra calls", () => {
    const f = fakes();
    pauseWhenHidden(f.doc, f.ticker);
    f.set("visible");
    f.set("hidden");
    f.set("hidden");
    f.set("visible");
    f.set("visible");
    expect(f.calls).toEqual(["stop", "start"]);
  });

  it("after the undo no event reaches the ticker and the listener is gone", () => {
    const f = fakes();
    const undo = pauseWhenHidden(f.doc, f.ticker);
    undo();
    expect(f.listeners.size).toBe(0);
    f.set("hidden");
    f.set("visible");
    expect(f.calls).toEqual([]);
  });
});
