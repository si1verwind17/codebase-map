import { describe, expect, it } from "vitest";
import { C, HOVER_RING, PICKED_RING } from "../../src/floor/palette";

describe("the floor's rings", () => {
  it("the picked mark is the blue selection keyline; a pane row's hover is a thinner ink ring, never the same look", () => {
    expect(PICKED_RING.color).toBe(C.select);
    expect(HOVER_RING.color).toBe(C.ink);
    expect(HOVER_RING.color).not.toBe(PICKED_RING.color);
    expect(HOVER_RING.width).toBe(PICKED_RING.width / 2);
  });
});
