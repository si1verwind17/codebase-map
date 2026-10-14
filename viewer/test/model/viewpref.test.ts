import { describe, expect, it } from "vitest";
import { loadRailFolds, saveRailFolds, loadCodeLinks, loadDronePaths, saveCodeLinks, saveDronePaths } from "../../src/ui/viewpref";

const memory = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };
const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };

describe("drone paths preference", () => {
  it("is on by default and remembers the choice", () => {
    const s = memory();
    expect(loadDronePaths(s)).toBe(true);
    saveDronePaths(s, false);
    expect(loadDronePaths(s)).toBe(false);
    expect(s.getItem("code-map.drone-paths")).toBe("off");
    saveDronePaths(s, true);
    expect(loadDronePaths(s)).toBe(true);
  });

  it("falls back to on when storage is missing or blocked", () => {
    expect(loadDronePaths(null)).toBe(true);
    expect(loadDronePaths(broken)).toBe(true);
    expect(() => saveDronePaths(broken, false)).not.toThrow();
  });
});

describe("code links preference", () => {
  it("is off by default and remembers the choice", () => {
    const s = memory();
    expect(loadCodeLinks(s)).toBe(false);
    saveCodeLinks(s, true);
    expect(loadCodeLinks(s)).toBe(true);
    expect(s.getItem("code-map.code-links")).toBe("on");
    saveCodeLinks(s, false);
    expect(loadCodeLinks(s)).toBe(false);
  });

  it("falls back to off when storage is missing or blocked", () => {
    expect(loadCodeLinks(null)).toBe(false);
    expect(loadCodeLinks(broken)).toBe(false);
    expect(() => saveCodeLinks(broken, true)).not.toThrow();
  });
});

describe("rail folds", () => {
  it("start all open and remember the folded sections", () => {
    const s = memory();
    expect(loadRailFolds(s)).toEqual(new Set());
    saveRailFolds(s, new Set(["pins", "floor"]));
    expect(s.getItem("code-map.rail-folded")).toBe("floor,pins");
    expect(loadRailFolds(s)).toEqual(new Set(["floor", "pins"]));
    saveRailFolds(s, new Set());
    expect(loadRailFolds(s)).toEqual(new Set());
  });

  it("ignore junk in storage", () => {
    const s = memory();
    s.setItem("code-map.rail-folded", "pins,nope,,find");
    expect(loadRailFolds(s)).toEqual(new Set(["find", "pins"]));
  });

  it("are all open when storage is missing or blocked, and saving there does not throw", () => {
    expect(loadRailFolds(null)).toEqual(new Set());
    expect(loadRailFolds(broken)).toEqual(new Set());
    expect(() => saveRailFolds(broken, new Set(["find"]))).not.toThrow();
  });
});
