import { describe, expect, it } from "vitest";
import { textOverlaps, type Word } from "./text-overlaps";

const w = (t: string, x: number, y: number, ww: number, h: number, more: Partial<Word> = {}): Word => ({ t, x, y, w: ww, h, ...more });

describe("textOverlaps", () => {
  it("finds two words that overlap, and not two that touch within the tolerance", () => {
    expect(textOverlaps([w("a", 0, 0, 20, 10), w("b", 10, 5, 20, 10)], {}, 1).found).toEqual(['"a" over "b"']);
    expect(textOverlaps([w("a", 0, 0, 20, 10), w("b", 19.5, 0, 20, 10)], {}, 1).found).toEqual([]);   // 0.5 px: antialiasing
    expect(textOverlaps([w("a", 0, 0, 20, 10), w("b", 0, 10, 20, 10)], {}, 1).found).toEqual([]);     // edge to edge
  });

  it("finds a word over another line's tile; a word over its own line's tile counts as an excused hit", () => {
    const tiles = { L: ["1,0"], M: ["3,3"] };
    expect(textOverlaps([w("x\ny", 20, 2, 10, 10)], tiles, 1)).toEqual({ found: ['"x/y" over line L'], ownHits: 0, ownNear: 0 });
    expect(textOverlaps([w("sign", 20, 2, 10, 10, { line: ["L"] })], tiles, 1)).toEqual({ found: [], ownHits: 1, ownNear: 1 });
    expect(textOverlaps([w("near", 0, 0, 24.5, 10)], tiles, 1).found).toEqual([]);   // reaches the tile by under 1 px
  });

  it("counts a line's own word within a tile of it, and not one further off", () => {
    const tiles = { L: ["1,0"] };
    expect(textOverlaps([w("code", 50, 2, 10, 10, { line: ["L"] })], tiles, 1)).toEqual({ found: [], ownHits: 0, ownNear: 1 });
    expect(textOverlaps([w("code", 80, 2, 10, 10, { line: ["L"] })], tiles, 1)).toEqual({ found: [], ownHits: 0, ownNear: 0 });
    expect(textOverlaps([w("code", 50, 2, 10, 10, { line: ["M"] })], tiles, 1).ownNear).toBe(0);
  });

  it("finds a word over a dotted path, not one beside it, and excuses its own line's word", () => {
    const paths = { P: [[0, 0, 100, 100]] };
    expect(textOverlaps([w("on", 40, 40, 20, 10)], {}, 1, paths).found).toEqual(['"on" over line P']);
    // tolerance: a word's box shrinks by tol and the path grows by PATH_HALF (2), so a word within 2 - tol = 1 px of the path touches
    const h = { H: [[0, 0, 100, 0]] }, v = { V: [[0, 0, 0, 100]] };   // horizontal and vertical segments (the p === 0 branch)
    expect(textOverlaps([w("far", 40, 10.9, 20, 10)], {}, 1, h).found, "well off").toEqual([]);
    expect(textOverlaps([w("in", 40, 0.9, 20, 10)], {}, 1, h).found, "0.9 px below the line: inside").toEqual(['"in" over line H']);
    expect(textOverlaps([w("out", 40, 1.1, 20, 10)], {}, 1, h).found, "1.1 px below: outside").toEqual([]);
    expect(textOverlaps([w("in", 0.9, 40, 10, 20)], {}, 1, v).found).toEqual(['"in" over line V']);
    expect(textOverlaps([w("out", 1.1, 40, 10, 20)], {}, 1, v).found).toEqual([]);
    expect(textOverlaps([w("by", 60, 20, 20, 10)], {}, 1, paths).found).toEqual([]);                    // well off the diagonal
    expect(textOverlaps([w("own", 40, 40, 20, 10, { line: ["P"] })], {}, 1, paths).found).toEqual([]);
    expect(textOverlaps([w("cut", 40, 40, 20, 10)], {}, 1, { P: [[0, 0, 30, 30], [70, 70, 100, 100]] }).found).toEqual([]);   // a building stands over the middle
  });

  it("skips cards", () => {
    expect(textOverlaps([w("a", 0, 0, 20, 10), w("tag", 0, 0, 20, 10, { card: true })], { L: ["0,0"] }, 1).found).toEqual(['"a" over line L']);
  });
});
