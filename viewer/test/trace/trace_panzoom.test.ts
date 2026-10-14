import { describe, expect, it } from "vitest";
import { clampZoom, fitZoom, intoView, isDrag, wheelZoom, zoomAbout } from "../../src/trace/panzoom";

describe("the trace pane's pan and zoom", () => {
  it("clamps the zoom to 50–200 %", () => {
    expect(clampZoom(0.1)).toBe(0.5);
    expect(clampZoom(3)).toBe(2);
    expect(clampZoom(1.3)).toBe(1.3);
  });

  it("zooms ×1.1 per 100 px wheel notch, smoothly for a pinch's small steps, within the limits", () => {
    expect(wheelZoom(1, -100)).toBeCloseTo(1.1, 10);
    expect(wheelZoom(1, 100)).toBeCloseTo(1 / 1.1, 10);
    expect(wheelZoom(1, -10)).toBeCloseTo(1.1 ** 0.1, 10);
    expect(wheelZoom(2, -100)).toBe(2);
    expect(wheelZoom(0.5, 100)).toBe(0.5);
  });

  it("zooms about the pointer: the sheet point under it stays put", () => {
    const v = zoomAbout({ k: 1, left: 100, top: 50 }, 2, 200, 100);
    expect(v).toEqual({ k: 2, left: 400, top: 200 });
    expect((v.left + 200) / v.k).toBe(300);   // was (100 + 200) / 1
    expect(zoomAbout({ k: 1, left: 0, top: 0 }, 5, 0, 0).k).toBe(2);
  });

  it("fits: the largest zoom up to 100 % that shows the whole sheet, never below 50 %", () => {
    expect(fitZoom(400, 300, 1000, 800)).toBe(1);
    expect(fitZoom(1600, 300, 1000, 800)).toBe(0.625);
    expect(fitZoom(2000, 400, 1000, 400)).toBe(0.5);
    expect(fitZoom(4000, 300, 1000, 800)).toBe(0.5);
    expect(fitZoom(0, 0, 1000, 800)).toBe(1);
  });

  it("brings a row into view only on the axis where it is out of view", () => {
    expect(intoView({ x: 16, y: 44, w: 260, h: 40 }, 1, 1000, 400)).toEqual({ left: 0, top: 0 });
    expect(intoView({ x: 1500, y: 100, w: 260, h: 40 }, 1, 1000, 400)).toEqual({ left: 1130, top: 0 });
    expect(intoView({ x: 16, y: 600, w: 260, h: 40 }, 1, 1000, 400)).toEqual({ left: 0, top: 420 });
  });

  it("a press becomes a drag after 4 px", () => {
    expect(isDrag(3, 0)).toBe(false);
    expect(isDrag(0, 4)).toBe(true);
    expect(isDrag(3, 3)).toBe(true);
  });
});
