// The picked mark (spec S5): one blue for what is picked in both panes, its pale wash readable under ink text, and
// never the outside world's yellow.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CSS } from "../../src/floor/palette";

const css = readFileSync(new URL("../../src/app.css", import.meta.url), "utf8");
const token = (name: string) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`))?.[1]?.toLowerCase();
function luminance(hex: string) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const contrast = (a: string, b: string) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

describe("the picked mark", () => {
  it("is the floor's selection blue", () => {
    expect(token("picked")).toBe(CSS.select);
  });

  it("has a wash that keeps ink text at 7:1 or more", () => {
    const wash = token("picked-wash")!;
    expect(wash).toMatch(/^#[0-9a-f]{6}$/);
    expect(contrast(wash, token("ink")!)).toBeGreaterThanOrEqual(7);
  });

  it("is never the outside world's yellow", () => {
    expect([token("picked"), token("picked-wash")]).not.toContain(token("yellow"));
  });
});
