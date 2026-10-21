// The field guide (docs/field-guide.html, written by `npm run guide`): fresh against its inputs, small, a picture on
// every page but the last, no product names.
import { readFileSync, statSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { guideDigest } from "../../scripts/guide-inputs.mjs";

const GUIDE = new URL("../../../docs/field-guide.html", import.meta.url);
const html = readFileSync(GUIDE, "utf8");
const pages = [...html.matchAll(/<template class="page" data-title="([^"]*)"[^>]*>([\s\S]*?)<\/template>/g)].map((m) => ({ title: m[1], body: m[2] }));
const pictures = JSON.parse(html.match(/<script type="application\/json" id="pictures">([\s\S]*?)<\/script>/)![1]) as
  Record<string, { stills?: { src: string; density: number }[]; clip?: string }>;

describe("the field guide", () => {
  it("is fresh: built from the current example maps, page template and viewer", () => {
    const stamped = html.match(/<meta name="guide-inputs" content="([0-9a-f]*)">/)?.[1];
    expect(stamped, "docs/field-guide.html is stale: run `npm run build` then `npm run guide` in viewer/").toBe(guideDigest());
  });

  it("is at most 3 MB", () => {
    expect(statSync(GUIDE).size).toBeLessThanOrEqual(3 * 1024 * 1024);
  });

  it("has a rendered picture or clip on every page but the last", () => {
    expect(pages).toHaveLength(20);
    for (const p of pages.slice(0, -1)) {
      const name = p.body.match(/data-pic="([^"]+)"/)?.[1];
      expect(name, `${p.title}: a picture`).toBeTruthy();
      const pic = pictures[name!];
      const srcs = pic?.clip ? [pic.clip] : (pic?.stills ?? []).map((s) => s.src);
      expect(srcs.length, `${p.title}: picture ${name} is rendered`).toBeGreaterThan(0);
      for (const s of srcs) expect(s, `${p.title}: picture ${name} is inlined`).toMatch(/^data:(image\/png|video\/webm);base64,/);
    }
    expect(pages.at(-1)!.body).not.toMatch(/data-pic=/);
  });

  it("names no product", () => {
    const text = html.replace(/data:[a-z0-9/+-]+;base64,[A-Za-z0-9+/=]+/g, "");
    expect(text.match(/\b(airflow|flyte|kafka|rabbitmq|sqs|pub\/?sub|celery|stripe)\b/gi) ?? []).toEqual([]);
  });

  it("has no step-player page and no flow clip", () => {
    expect(pages.filter((p) => /walk|flow/i.test(p.title))).toEqual([]);
    expect(pictures.walk).toBeUndefined();
  });
});
