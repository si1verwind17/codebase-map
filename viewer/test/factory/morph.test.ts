import { describe, expect, it } from "vitest";
import { ease, morphRect } from "../../src/floor/morph";

describe("box morph between floors", () => {
  const box = { x: 100, y: 200, w: 200, h: 80 };
  const page = { x: 20, y: 40, w: 1000, h: 700 };

  it("starts exactly on the box and ends exactly on the page", () => {
    expect(morphRect(box, page, 0)).toEqual(box);
    expect(morphRect(box, page, 1)).toEqual(page);
  });

  it("grows smoothly: every edge moves one way only", () => {
    let prev = morphRect(box, page, 0);
    for (let t = 0.1; t <= 1.0001; t += 0.1) {
      const r = morphRect(box, page, t);
      expect(r.x).toBeLessThanOrEqual(prev.x);
      expect(r.w).toBeGreaterThanOrEqual(prev.w);
      prev = r;
    }
  });

  it("eases in and out", () => {
    expect(ease(0)).toBe(0);
    expect(ease(1)).toBe(1);
    expect(ease(0.5)).toBeCloseTo(0.5);
    expect(ease(0.1)).toBeLessThan(0.1);   // slow start
    expect(ease(0.9)).toBeGreaterThan(0.9); // slow finish
  });
});
