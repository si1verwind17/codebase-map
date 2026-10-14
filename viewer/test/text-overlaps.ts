// The overlap rules of the e2e "no word sits on a line or on another word" check, pure so a unit test can prove them
// (test/text_overlaps.test.ts). Words and tiles come from the canvas (labels.ts `textsRead`, `linesRead`), in world px.

/** A word as `textsRead` writes it: its box in world px, the lines it fades with, and whether it is a card. */
export type Word = { t: string; x: number; y: number; w: number; h: number; line?: string[]; card?: true };

/** Half the width of a dotted flight, drone or conduit path, world px: a word is over it when it comes within this. */
export const PATH_HALF = 2;

/** Whether the segment (ax,ay)-(bx,by) touches the rectangle [x0,x1]x[y0,y1] (Liang-Barsky). */
function touches(ax: number, ay: number, bx: number, by: number, x0: number, y0: number, x1: number, y1: number): boolean {
  let t0 = 0, t1 = 1;
  const dx = bx - ax, dy = by - ay;
  for (const [p, q] of [[-dx, ax - x0], [dx, x1 - ax], [-dy, ay - y0], [dy, y1 - ay]]) {
    if (p === 0) { if (q < 0) return false; continue; }
    const r = q / p;
    if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
  }
  return true;
}

/** Every word over a line tile or over another word, by more than `tol` world px (1 screen px: antialiasing); how many
 *  tile hits the own-line exemption excused; and how many of a line's own words (a station's code, a platform's) stand
 *  within a tile of that line (a count above 0 proves words and tiles share coordinates). `paths`: dotted lines that are
 *  not tiles (flights, drone routes, conduits) by key, each a flat polyline `[x0, y0, x1, y1, ...]` in world px, already
 *  cut where a building stands over them; a word within PATH_HALF of one is over it (its own line's word is excused). */
export function textOverlaps(all: Word[], lineTiles: Record<string, string[]>, tol: number, paths: Record<string, number[][]> = {}, T = 24): { found: string[]; ownHits: number; ownNear: number } {
  const words = all.filter((w) => !w.card);   // exempt: a hover or selection card stands above everything on purpose, while asked for
  const tiles = new Map<string, string[]>();
  for (const [k, ts] of Object.entries(lineTiles)) for (const t of ts) tiles.set(t, [...(tiles.get(t) ?? []), k]);
  const name = (w: Word) => `"${w.t.replaceAll("\n", "/")}"`;
  const found: string[] = [];
  let ownHits = 0, ownNear = 0;
  // a machine's own art (roof, windows, pads, stacks) is neither a line nor a word, so a name over it needs no exemption
  for (const w of words) {
    const hit = new Set<string>();
    for (let tx = Math.floor((w.x + tol) / T); tx <= Math.floor((w.x + w.w - tol) / T); tx++)
      for (let ty = Math.floor((w.y + tol) / T); ty <= Math.floor((w.y + w.h - tol) / T); ty++)
        for (const k of tiles.get(`${tx},${ty}`) ?? []) {
          if (w.line?.includes(k)) ownHits++;   // exempt: a line's own sign or plate is drawn on that line
          else hit.add(k);
        }
    for (const [k, polys] of Object.entries(paths)) {
      if (hit.has(k) || w.line?.includes(k)) continue;
      const r = [w.x + tol - PATH_HALF, w.y + tol - PATH_HALF, w.x + w.w - tol + PATH_HALF, w.y + w.h - tol + PATH_HALF] as const;
      if (polys.some((q) => { for (let i = 0; i + 3 < q.length; i += 2) if (touches(q[i], q[i + 1], q[i + 2], q[i + 3], ...r)) return true; return false; })) hit.add(k);
    }
    for (const k of hit) found.push(`${name(w)} over line ${k}`);
    if (w.line) {
      let near = false;
      for (let tx = Math.floor(w.x / T) - 1; tx <= Math.floor((w.x + w.w) / T) + 1 && !near; tx++)
        for (let ty = Math.floor(w.y / T) - 1; ty <= Math.floor((w.y + w.h) / T) + 1 && !near; ty++)
          near = (tiles.get(`${tx},${ty}`) ?? []).some((k) => w.line!.includes(k));
      if (near) ownNear++;
    }
  }
  for (let i = 0; i < words.length; i++) for (let j = i + 1; j < words.length; j++) {
    const a = words[i], b = words[j];
    if (Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > tol && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > tol)
      found.push(`${name(a)} over ${name(b)}`);
  }
  return { found, ownHits, ownNear };
}
