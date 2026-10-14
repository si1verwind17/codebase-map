// src/factory/rail-place.ts
// Where batch rails are painted (spec §6, mock factory-transport.html Batch, factory-more.html §5), pure: the parts of
// each rail yard (platform strips, the parked train's strip, the rail from each platform to the exit it leaves by), the station sidings,
// the train paths Task 4 runs, the sign text and station labels placed in clear room, the hover lists, and the legend
// kinds. rail-paint.ts draws from this; nothing here draws.
import type { Model } from "../model/model";
import type { Relation } from "../model/types";
import type { Pt } from "../route/types";
import { platformOf, rate, runsPerDay, summarise, type Job, type Platform, type Yard } from "./batch";
import type { Clearance, PxRect } from "./clear";
import { placeBeside, type Placed } from "./flights";
import { plateW, PLATE_FONT, PLATE_H } from "./fit";
import type { TileFloor } from "./layout";
import { piecesToPoints, type TileRoute } from "./router";
import { exits, stationId, yardId, type StationBox, type YardBox } from "./yards";
import { STEP, T, type Dir, type Piece } from "./tiles";

/** One train's track, for Task 4: `points` (world px) run from its platform's strip, through the yard to the exit its
 *  rail leaves by, along the rail (underground runs included) and through the station to its buffer stop. `key` is the
 *  rail's route key (a batch bundle's, or a stand-in's `rail:` key), `platform` its `platformId`, `station` its
 *  `stationId`; `runsPerDay` is its platform's (null: no known schedule, on demand). */
export interface TrainPath { key: string; points: Pt[]; platform: string; station: string; source: string; dest: string; runsPerDay: number | null }

export const platformId = (source: string, dest: string) => `platform:${source}>${dest}`;
/** The key a yard is selected by (and its views fade with): its rails' ends grouped as in the router. */
export const yardKey = (source: string) => yardId(source);
export const isYardKey = (key: string) => key.startsWith("yard:");

const piece = (x: number, y: number, inn: Dir, out: Dir): Piece => ({ x, y, in: inn, out, under: false, hoodBefore: false, hoodAfter: false });
const dirOf = (a: { x: number; y: number }, b: { x: number; y: number }): Dir => (b.x > a.x ? "e" : b.x < a.x ? "w" : b.y > a.y ? "s" : "n");

/** The rail inside a yard for platform `i`: from its platform tile to the tile before the exit its rail leaves by
 *  (`first`, the route's first piece; its own exit when the rail does not ride a trunk), along the yard's row ends, then
 *  out. On a ladder it runs straight on from its platform tile into the throat, where one switch turns it along the
 *  throat to its exit row. Every tile travels `out` where it meets the platform strip and the exit. */
export function yardLink(y: YardBox, i: number, first?: Piece): Piece[] {
  const own = y.platforms[i];
  const [sx, sy] = STEP[y.out];
  const throat = y.ladder ? { x: own.x + sx, y: own.y } : own;
  const to = first ? { x: first.x - sx, y: first.y - sy } : throat;
  const tiles: { x: number; y: number }[] = y.ladder ? [{ x: own.x, y: own.y }, throat] : [{ x: own.x, y: own.y }];
  while (tiles[tiles.length - 1].x !== to.x || tiles[tiles.length - 1].y !== to.y) {
    const t = tiles[tiles.length - 1];
    tiles.push({ x: t.x + Math.sign(to.x - t.x), y: t.y + Math.sign(to.y - t.y) });
    if (tiles.length > y.w + y.h) break;   // a first piece off the yard's far edge: never loop
  }
  return tiles.map((t, k) => piece(t.x, t.y, k ? dirOf(tiles[k - 1], t) : y.out, k < tiles.length - 1 ? dirOf(t, tiles[k + 1]) : y.out));
}

/** A station's siding: its rail runs on from the entry into the strip, along the wall, to the far end (the buffer). */
export function sidingPieces(s: StationBox): Piece[] {
  const d = s.entry.d, n = s.w * s.h, out: Piece[] = [];
  for (let k = 1; k <= n; k++) out.push(piece(s.entry.x + STEP[d][0] * k, s.entry.y + STEP[d][1] * k, d, d));
  return out;
}

/** Every rail on the floor with the pieces painted beside its route: the yard link and the siding. A yard-less rail (its
 *  scheduler off the floor, `door` set) has no yard and an empty link: its train starts at the door. */
export interface RailTrack { key: string; yard?: YardBox; door?: string; index: number; station: StationBox; link: Piece[]; siding: Piece[]; route?: TileRoute }

/** The rails, in yard and platform order, then the yard-less ones. A rail whose first piece is on none of its yard's
 *  exits (its link would be cut short) is recorded in `tf.rails.unplaced` (`link: true`): every real floor keeps it empty. */
export function railTracks(tf: TileFloor, routes: TileRoute[]): RailTrack[] {
  const r = tf.rails;
  if (!r) return [];
  const byKey = new Map(routes.map((q) => [q.key, q]));
  const out: RailTrack[] = [];
  for (const y of r.yards) y.platforms.forEach((p, index) => {
    const station = r.stations.find((s) => !s.door && s.source === y.source && s.dest === p.dest);
    if (!station) return;
    const route = byKey.get(station.track);
    const first = route && !route.failed ? route.pieces[0] : undefined;
    if (first && !exits(y).some((e) => e.x === first.x && e.y === first.y)
      && !r.unplaced.some((u) => u.link && u.source === y.source && u.dest === p.dest)) r.unplaced.push({ source: y.source, dest: p.dest, link: true });
    out.push({ key: station.track, yard: y, index, station, link: yardLink(y, index, first), siding: sidingPieces(station), route });
  });
  for (const station of r.stations) if (station.door)
    out.push({ key: station.track, door: station.door, index: -1, station, link: [], siding: sidingPieces(station), route: byKey.get(station.track) });
  return out;
}

/** Task 4's train paths: one per rail that routed; a yard-less one starts at its door's edge. */
export function trainPaths(tf: TileFloor, routes: TileRoute[]): TrainPath[] {
  const yards = tf.rails?.batch.yards ?? [];
  return railTracks(tf, routes).filter((t) => t.route && !t.route.failed && t.route.pieces.length).map((t) => {
    const source = t.yard?.source ?? t.door!;
    const plat = t.station.platform ?? yards.find((q) => q.source === source)?.platforms.find((p) => p.dest === t.station.dest);
    return {
      key: t.key, points: piecesToPoints([...t.link, ...t.route!.pieces, ...t.siding]),
      platform: platformId(source, t.station.dest), station: stationId(t.station),
      source, dest: t.station.dest, runsPerDay: plat?.runsPerDay ?? null,
    };
  });
}

/** The parts of a yard in world px: no header, no caption. Each platform is a row, its strip covering the row but the
 *  platform tile at its `out` end, where its rail runs; every word on it reads left to right. A yard with no platform
 *  is a strip where a train stands parked (`parked`: the tiles but the sign's, a locomotive and one wagon on a rail). */
export interface YardParts { strips: { dest: string; r: PxRect }[]; parked: PxRect | null; signInside: boolean }

export function yardParts(y: YardBox): YardParts {
  const x0 = y.x * T, y0 = y.y * T, x1 = (y.x + y.w) * T;
  const signInside = !!y.sign && y.sign.x >= y.x && y.sign.x < y.x + y.w && y.sign.y >= y.y && y.sign.y < y.y + y.h;
  // the machine's drop shadow (SHADOW px right and down) falls on a yard against its e or s side: strips keep past it
  // (a free yard stands against no machine)
  const left = y.side === "e" && !y.free ? 8 : 3, top = y.side === "s" ? 6 : 4;
  const strips = y.platforms.map((p, i) => {
    const tx = p.x * T, ty = p.y * T, t = i === 0 ? top : 4;
    return { dest: p.dest, r: y.out === "w" ? { x0: tx + T + 2, y0: ty + t, x1: x1 - 3, y1: ty + T - 4 } : { x0: x0 + left, y0: ty + t, x1: tx - 2, y1: ty + T - 4 } };
  });
  const parked = y.platforms.length ? null : { x0, y0, x1: signInside ? x1 - T : x1, y1: y0 + T };
  return { strips, parked, signInside };
}

/** A box's short code on its own floor: the code without the floor's own code in front (`S7·P1·F11` on S7·P1 reads
 *  `F11`); a door wears its anchor's. */
export function shortCode(model: Model, container: string, id: string): string {
  const code = model.codes.get(id.startsWith("door:") ? id.slice(5) : id) ?? "";
  const own = model.codes.get(container);
  return own && code.startsWith(own + "·") ? code.slice(own.length + 1) : code;
}

/** One job in a hover list: `job — schedule (runs/day)`; a job with no schedule reads `on demand`. */
export function jobLine(j: Job): string {
  const when = summarise([j]);
  let runs = 0, known = false;
  for (const s of j.schedule ?? []) { const n = runsPerDay(s); if (n !== null) { runs += n; known = true; } }
  const r = known ? rate(runs) : null;
  return r && r !== when ? `${j.job} — ${when} (${r})` : `${j.job} — ${when}`;
}

const MAX_LINES = 24;   // a list longer than this says how many more (no demo yard comes near)
const list = (title: string, jobs: Job[]) => {
  const lines = jobs.slice(0, MAX_LINES).map(jobLine);
  if (jobs.length > MAX_LINES) lines.push(`… ${jobs.length - MAX_LINES} more`);
  return [title, ...lines].join("\n");
};

/** The sign's hover: every job of the yard, its own first, then each platform's. */
export function signList(model: Model, y: Yard): string {
  return list(`${model.label(y.source)} · ${y.sign}`, [...y.selfJobs, ...y.platforms.flatMap((p) => p.jobs)]);
}
/** A platform's (or its station's) hover: its own jobs. */
export function platformList(model: Model, p: Platform): string {
  return list(`${p.jobs.length} job${p.jobs.length === 1 ? "" : "s"} → ${model.label(p.dest.startsWith("door:") ? p.dest.slice(5) : p.dest)}`, p.jobs);
}

/** The labels placed for the rails: the sign's summary beside its clock tile, and a station's source code beside it. */
export interface RailLabels { signs: (Placed & { source: string })[]; stations: (Placed & { station: string })[] }

export const STATION_FONT = 10;

/** Placed after the zone names and messaging labels, into the same clear room (`clear`): each sign's text beside its
 *  tile (right, left, below, above), then each station's label on its open side (away from the wall), never over a
 *  line, a machine or another label. A sign with no room shows its text on hover only; a station with no room has no
 *  label. Deterministic: yards and stations in their order. */
export function railLabels(model: Model, container: string, tf: TileFloor, clear: Clearance): RailLabels {
  const r = tf.rails;
  if (!r) return { signs: [], stations: [] };
  const bounds: PxRect = { x0: 0, y0: 0, x1: tf.cols * T, y1: tf.rows * T };
  const signs: RailLabels["signs"] = [];
  for (const y of r.yards) {
    if (!y.sign) continue;
    const text = r.batch.yards.find((q) => q.source === y.source)!.sign;
    const got = [text, ...signLines(text)].reduce<Placed | undefined>((done, t) => done ?? placeBox(yardKey(y.source), t, signSpots(y, t), clear, bounds), undefined);
    if (got) signs.push({ ...got, source: y.source });
  }
  const stations: RailLabels["stations"] = [];
  // a source label tells stations apart only when they come from more than one place (yard sources and doors)
  if (new Set(r.stations.map((s) => s.source)).size > 1) for (const s of r.stations) {
    // the yard's machine: the scheduler, or on an inner floor the door its jobs come in by (never the floor's own code)
    const yard = r.yards.find((y) => y.source === s.source);
    const text = shortCode(model, container, yard?.machine ?? s.source);
    if (!text) continue;
    const w = plateW(text, STATION_FONT), x0 = s.x * T, y0 = s.y * T, x1 = (s.x + s.w) * T, y1 = (s.y + s.h) * T;
    const cx = (x0 + x1) / 2 - w / 2, cy = (y0 + y1) / 2 - PLATE_H / 2;
    const spots = { n: [{ x: cx, y: y0 - 3 - PLATE_H }], s: [{ x: cx, y: y1 + 3 }], w: [{ x: x0 - 3 - w, y: cy }], e: [{ x: x1 + 3, y: cy }] }[s.side];
    const got = placeBeside(s.track, text, spots, clear, bounds, STATION_FONT, w);
    if (got) stations.push({ ...got, station: stationId(s) });
  }
  return { signs, stations };
}

/** A sign's text on two lines when one does not fit: split before its ` + ` tail, else at its ` · `, else at its last
 *  space (`daily` over `01:00`). */
export function signLines(text: string): string[] {
  const plus = text.indexOf(" + "), dot = text.indexOf(" · "), sp = text.lastIndexOf(" ");
  if (plus > 0) return [`${text.slice(0, plus)}\n${text.slice(plus + 1)}`];
  if (dot > 0) return [`${text.slice(0, dot)}\n${text.slice(dot + 3)}`];
  if (sp > 0) return [`${text.slice(0, sp)}\n${text.slice(sp + 1)}`];
  return [];
}

/** A label's box for `text` (one or more lines) at PLATE_FONT: as wide as its longest line, a plate tall per line. */
export const boxSize = (text: string, size = PLATE_FONT) => {
  const lines = text.split("\n");
  return { w: Math.max(...lines.map((l) => plateW(l, size))), h: PLATE_H + (lines.length - 1) * (size + 3) };
};

/** Spots for a sign's text: beside its tile (right, left), under and over it, then under and over its yard. */
function signSpots(y: YardBox, text: string): { x: number; y: number }[] {
  const { w, h } = boxSize(text), s = y.sign!;
  const x0 = s.x * T, y0 = s.y * T, mid = y0 + (T - h) / 2;
  const yx0 = y.x * T, yx1 = (y.x + y.w) * T, yy0 = y.y * T, yy1 = (y.y + y.h) * T;
  return [
    { x: x0 + T + 3, y: mid }, { x: x0 - 3 - w, y: mid },
    { x: x0, y: y0 + T + 3 }, { x: x0 + T - w, y: y0 + T + 3 }, { x: x0, y: y0 - 3 - h }, { x: x0 + T - w, y: y0 - 3 - h },
    { x: yx0 + 8, y: yy1 + 3 }, { x: yx1 - w, y: yy1 + 3 }, { x: yx0 + 8, y: yy0 - 3 - h }, { x: yx1 - w, y: yy0 - 3 - h },
  ];
}

/** `placeBeside` for a label of one or more lines: the first spot clear of `clear` and inside `bounds` wins and joins it. */
function placeBox(key: string, text: string, spots: { x: number; y: number }[], clear: Clearance, bounds: PxRect): Placed | undefined {
  const { w, h } = boxSize(text);
  for (const s of spots) {
    const box = { x0: Math.round(s.x), y0: Math.round(s.y), x1: Math.round(s.x) + w, y1: Math.round(s.y) + h };
    if (box.x0 < bounds.x0 || box.y0 < bounds.y0 || box.x1 > bounds.x1 || box.y1 > bounds.y1 || !clear.free(box)) continue;
    clear.add(box);
    return { key, text, x: box.x0, y: box.y0, w, h };
  }
  return undefined;
}

/** Which rail parts one floor has, for the legend's plain entries; null on a floor with no yard. */
export interface RailLegend { yard?: true; station?: true; sign?: true; train?: true }
/** The rail parts a floor shows, for the legend: a yard, a station (and so a train: every station has its rail),
 *  a schedule sign. Null on a floor with no rails. */
export function railLegend(tf: TileFloor): RailLegend | null {
  const r = tf.rails;
  if (!r?.yards.length && !r?.stations.length) return null;
  return {
    ...(r.yards.length ? { yard: true as const } : {}), ...(r.stations.length ? { station: true as const, train: true as const } : {}),
    ...(r.yards.some((y) => y.sign) ? { sign: true as const } : {}),
  };
}

/** The rails a yard's selection lights: the tracks of its stations. */
export function yardTracks(tf: TileFloor, source: string): string[] {
  return (tf.rails?.stations ?? []).filter((s) => s.source === source).map((s) => s.track);
}

/** Keys as the views know them: a yard's key brings every rail of the yard. */
export function expandKeys(tf: TileFloor, keys: string[]): string[] {
  return keys.flatMap((k) => (isYardKey(k) ? [k, ...yardTracks(tf, k.slice(5))] : [k]));
}

/** A stand-in rail (`rail:` key) or a yard (`yard:<source>`) as the inspector shows it: its ends, title, sub line and
 *  relations (a yard's: every job it schedules). Undefined for any other key. */
export interface RailLine { a: string; b: string; title: string; sub: string; relations: Relation[];
  /** its jobs as the hover lists read them (`job — schedule (runs/day)`): the inspector's keyboard route to a sign's list */
  jobs: string[] }
export function railLine(model: Model, tf: TileFloor, key: string): RailLine | undefined {
  const r = tf.rails;
  if (!r) return undefined;
  const name = (id: string) => model.label(id.startsWith("door:") ? id.slice(5) : id);
  const shell = r.shells.find((b) => b.key === key);
  if (shell) return { a: shell.a, b: shell.b, title: `${name(shell.a)} → ${name(shell.b)}`, sub: "batch rail", relations: shell.relations,
    jobs: platformOf(shell.b, shell.relations).jobs.map(jobLine) };
  const y = isYardKey(key) ? r.batch.yards.find((q) => yardKey(q.source) === key) : undefined;
  if (!y) return undefined;
  const rel = new Map(model.map.relations.map((q) => [q.id, q]));
  const jobs = [...y.selfJobs, ...y.platforms.flatMap((p) => p.jobs)];
  return { a: y.source, b: y.source, title: `Rail yard · ${name(y.source)}`, sub: y.sign, relations: jobs.map((j) => rel.get(j.relation)!).filter(Boolean), jobs: jobs.map(jobLine) };
}

/** The machines a stand-in rail or a yard touches (a yard: its machine and every destination); undefined for a bundle. */
export function lineEnds(model: Model, tf: TileFloor, key: string): string[] | undefined {
  const y = isYardKey(key) ? tf.rails?.yards.find((q) => yardKey(q.source) === key) : undefined;
  if (y) return [...(y.machine ? [y.machine] : []), ...y.platforms.map((p) => p.dest)];
  const line = railLine(model, tf, key);
  return line ? [line.a, line.b] : undefined;
}
