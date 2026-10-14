// src/factory/rail-paint.ts
// Painting batch rails (spec §6, mock factory-transport.html Batch and factory-more.html §5): rail yards with their
// platform strips (or a parked train, a yard with no platform), the rail from each platform out of the yard, station
// sidings with a signal and a buffer stop, schedule signs, and the hover lists of signs, platforms, stations and yards.
// No part carries a caption naming its kind, and no word is turned: everything reads left to right. Geometry comes
// from yards.ts and rail-place.ts; this file only draws and wires the views the scene hands it.
import { Container, Graphics, Text, TextStyle } from "pixi.js";
import { drawTrain } from "../floor/movers";
import { C, F, FONT } from "../floor/palette";
import type { Model } from "../model/model";
import { cardScale, fillCard, labelBox } from "./messaging-paint";
import { paintRailTile } from "./pieces";
import {
  platformList, railTracks, shortCode, signList, STATION_FONT, trainPaths, yardKey, yardParts,
  type RailLabels, type RailTrack, type TrainPath,
} from "./rail-place";
import { PLATE_FONT } from "./fit";
import type { TileFloor } from "./layout";
import type { TileRoute } from "./router";
import { T, type Piece } from "./tiles";
import type { StationBox } from "./yards";

const KEY = { width: 1.4, color: C.ink };
const LABEL = 10;   // platform codes and badges, px: they follow the 9 px rule
const text = (s: string, size: number, fill: number) =>
  new Text({ resolution: 2, text: s, style: new TextStyle({ fontFamily: FONT, fontSize: size, fontWeight: "700", fill, lineHeight: size + 4 }) });

type Side = "above" | "right" | "left" | "below";

/** The scene's layers and view maps `paintRails` draws into and registers with. */
export interface RailViews {
  lines: Container;                        // yards, stations, signs and the labels placed for them
  tags: Container;                         // the hover list
  lineViews: Map<string, Container[]>;     // fade with their rails' keys (a yard with every rail of its own, and its key)
  smalls: { objs: Container[]; size: number }[];   // the 9 px rule: hidden when too small, and in codes mode
  select(key: string): void;               // a tap: a rail's key, or a yard's (`yard:<source>`)
  zoom(): number;                          // the world's scale now: the hover list grows to stay readable
  tip(text: string | null): void;          // a hover list shown (its text) or hidden
}

/** What the scene keeps from the paint: the pieces painted beside each rail's route (its yard link and its siding: the
 *  selection highlight covers them too) and Task 4's train paths. */
export interface PaintedRails { extra: Map<string, Piece[]>; trainPaths: TrainPath[]; tracks: RailTrack[];
  /** the zoom moved: a hover list on show keeps its readable size */ zoomed(z: number): void }

/** Yards, platforms, the rails inside yards, stations, signs and their labels; every view registered under its rails'
 *  keys so selection, the fade and the lit rule reach it. A floor with no yard draws nothing. */
export function paintRails(model: Model, container: string, tf: TileFloor, routes: TileRoute[], labels: RailLabels, v: RailViews): PaintedRails {
  const r = tf.rails;
  const extra = new Map<string, Piece[]>();
  if (!r) return { extra, trainPaths: [], tracks: [], zoomed: () => {} };
  const join = (key: string, c: Container) => v.lineViews.set(key, [...(v.lineViews.get(key) ?? []), c]);
  const tracks = railTracks(tf, routes);
  for (const t of tracks) extra.set(t.key, [...t.link, ...t.siding]);

  // the hover list: one, in the door hint's style (ink, paper words), standing above what is hovered
  const tip = new Container();
  tip.visible = false;
  tip.label = "rail-tip";
  v.tags.addChild(tip);
  /** The list with its box's corner at (x, y): grown up from it (`above`), or down and right (`right`, `below`), or down
   *  and left (`left`): a yard's list stands beside the yard, off its sign. */
  const show = (words: string, x: number, y: number, side: Side = "above") => {
    fillCard(tip, words, (w, h) => ({ x: side === "left" ? -w : 0, y: side === "above" ? -h : 0 }));
    tip.position.set(x, side === "above" ? y - 4 : y);
    tip.visible = true;
    zoomed(v.zoom());
    v.tip(words);
  };
  const hide = () => { tip.visible = false; v.tip(null); };
  const zoomed = (z: number) => { if (tip.visible) tip.scale.set(cardScale(z)); };
  const wire = (c: Container, key: string, words: () => string, at: { x: number; y: number; side?: Side }) => {
    c.eventMode = "static";
    c.cursor = "pointer";
    c.on("pointerover", () => show(words(), at.x, at.y, at.side));
    c.on("pointerout", hide);
    c.on("pointertap", (e) => { e.stopPropagation(); v.select(key); show(words(), at.x, at.y, at.side); });
  };

  for (const y of r.yards) {
    const sched = r.batch.yards.find((q) => q.source === y.source)!;
    const mine = tracks.filter((t) => t.yard === y), keys = [yardKey(y.source), ...mine.map((t) => t.key)];
    const parts = yardParts(y);
    const x0 = y.x * T, y0 = y.y * T, W = y.w * T, H = y.h * T;
    // the yard: an amber block, keylined, with no caption: its rows (or its parked train) say what it is; hovering it
    // lists every job of the yard, a tap selects every rail of the yard
    const body = new Container();
    const g = new Graphics().rect(x0, y0, W, H).fill(F.amberSoft).stroke(KEY);
    body.addChild(g);
    // a yard with no platform: a rail along its strip and a train standing on it, a locomotive and one wagon
    if (parts.parked) {
      const p = parts.parked, n = Math.round((p.x1 - p.x0) / T), row = Math.round(p.y0 / T), tx = Math.round(p.x0 / T);
      const rail = new Graphics();
      for (let i = 0; i < n; i++) paintRailTile(rail, [{ x: tx + i, y: row, in: "e", out: "e", under: false, hoodBefore: false, hoodAfter: false }]);
      const cy = p.y0 + T / 2, cx = (p.x0 + p.x1) / 2;
      drawTrain(rail, { key: yardKey(y.source), moving: false, atYard: true, cars: [
        { x: cx + 11, y: cy, horizontal: true, loco: true, loaded: false }, { x: cx - 11, y: cy, horizontal: true, loco: false, loaded: true },
      ] });
      body.addChild(rail);
    }
    v.lines.addChild(body);
    for (const k of keys) join(k, body);
    // the yard's list stands beside the yard, away from its machine
    const beside = { e: { x: x0 + W + 4, y: y0, side: "right" }, w: { x: x0 - 4, y: y0, side: "left" }, s: { x: x0, y: y0 + H + 4, side: "below" }, n: { x: x0, y: y0 - 4, side: "above" } }[y.side] as { x: number; y: number; side: Side };
    wire(body, yardKey(y.source), () => signList(model, sched), beside);

    // one strip per platform: the destination's short code and a job-count badge; a tap selects its rail
    for (const s of parts.strips) {
      const t = mine.find((q) => q.station.dest === s.dest), plat = sched.platforms.find((p) => p.dest === s.dest)!;
      const key = t?.key ?? yardKey(y.source);
      const L = s.r.x1 - s.r.x0, D = s.r.y1 - s.r.y0;
      const strip = new Container(), bg = new Graphics().rect(0, 0, L, D).fill(C.paper).stroke({ width: 1, color: C.ink });
      const inner = new Container();
      const badge = text(`×${plat.jobs.length}`, LABEL, C.paper), bw = badge.width + 6;
      const bb = new Graphics().rect(L - bw - 2, 2, bw, D - 4).fill(C.ink);
      badge.position.set(L - bw + 1, (D - badge.height) / 2);
      const code = text(shortCode(model, container, s.dest), LABEL, C.ink);
      const room = L - bw - 8;
      if (code.width > room) code.scale.set(room / code.width);
      code.position.set(3, (D - code.height * code.scale.y) / 2);
      inner.addChild(badge, code);
      strip.addChild(bg, bb, inner);   // the ink badge stays when the words are too small: the strip reads as a count marker
      strip.position.set(s.r.x0, s.r.y0);
      v.lines.addChild(strip);
      v.smalls.push({ objs: [inner], size: LABEL });
      join(key, strip);
      wire(bg, key, () => platformList(model, plat), { x: s.r.x0, y: s.r.y0 });
    }

    // the rail inside the yard, from each platform to the exit it leaves by: one tile at a time, a tile several rails
    // share (a rider passing another platform) painted once with all of them and lit with any; on a ladder each run of
    // the throat (the rails leaving by one exit) is one rail, its switches' curves over its ties, lit with any of them
    const throatX = y.ladder ? y.platforms[0].x + (y.out === "e" ? 1 : -1) : NaN;
    const tiles = new Map<string, { ps: Piece[]; keys: string[] }>();
    for (const t of mine) for (const p of t.link) {
      const k = p.x === throatX ? `run:${y.ladder![t.index]}` : `${p.x},${p.y}`, e = tiles.get(k) ?? tiles.set(k, { ps: [], keys: [] }).get(k)!;
      if (!e.keys.includes(t.key)) e.keys.push(t.key);
      if (!e.ps.some((q) => q.x === p.x && q.y === p.y && q.in === p.in && q.out === p.out)) e.ps.push(p);
    }
    for (const e of tiles.values()) {
      const lg = new Graphics();
      paintRailTile(lg, e.ps);
      v.lines.addChild(lg);
      for (const k of e.keys) join(k, lg);
    }

    // the sign: a clock on its tile; its summary beside it where there was room; hover or tap lists every job
    if (y.sign) {
      const sx = y.sign.x * T, sy = y.sign.y * T;
      const sg = new Graphics().rect(sx + 1, sy + 1, T - 2, T - 2).fill(C.paper).stroke({ width: 1.2, color: C.ink });
      sg.circle(sx + T / 2, sy + T / 2, 7.5).stroke({ width: 1.4, color: C.ink });
      sg.moveTo(sx + T / 2, sy + T / 2 - 5).lineTo(sx + T / 2, sy + T / 2).lineTo(sx + T / 2 + 4, sy + T / 2).stroke({ width: 1.4, color: C.ink });
      sg.label = `sign:${y.source}`;
      v.lines.addChild(sg);
      for (const k of keys) join(k, sg);
      wire(sg, yardKey(y.source), () => signList(model, sched), { x: sx, y: sy });
      for (const p of labels.signs.filter((q) => q.source === y.source)) {
        const { outer, inner } = labelBox(p, PLATE_FONT, C.paper, C.ink, C.ink);
        v.lines.addChild(outer);
        for (const k of keys) join(k, outer);
        v.smalls.push({ objs: [inner], size: PLATE_FONT });
        wire(outer, yardKey(y.source), () => signList(model, sched), { x: p.x, y: p.y });
      }
    }
  }

  // stations: a platform strip along the destination's wall, the siding through it to a buffer stop, a signal at the
  // end the train comes in by; its source's code beside it where there was room
  for (const t of tracks) {
    const s = t.station, plat = s.platform ?? r.batch.yards.find((q) => q.source === s.source)!.platforms.find((p) => p.dest === s.dest)!;
    const sv = new Container(), g = new Graphics();
    paintStation(g, s, t.siding);
    sv.addChild(g);
    v.lines.addChild(sv);
    join(t.key, sv);
    wire(g, t.key, () => platformList(model, plat), { x: s.x * T, y: s.y * T });
    for (const p of labels.stations.filter((q) => q.key === t.key)) {
      const { outer, inner } = labelBox(p, STATION_FONT, C.paper, C.ink, C.ink);
      v.lines.addChild(outer);
      join(t.key, outer);
      v.smalls.push({ objs: [inner], size: STATION_FONT });
    }
  }
  return { extra, trainPaths: trainPaths(tf, routes), tracks, zoomed };
}

/** A station: the strip (amber-soft, keylined) with the siding's rails over it, an ink buffer stop across the far end, and a
 *  green signal on the open side of the end the rail comes in by. */
export function paintStation(g: Graphics, s: StationBox, siding: Piece[]) {
  const x0 = s.x * T, y0 = s.y * T, w = s.w * T, h = s.h * T;
  g.rect(x0, y0, w, h).fill(F.amberSoft).stroke({ width: 1.2, color: C.ink });
  for (const p of siding) paintRailTile(g, [p]);
  const last = siding[siding.length - 1], first = siding[0];
  if (!last || !first) return;
  const d = s.entry.d, horiz = d === "e" || d === "w";
  // the buffer stop: across the track at the far edge of the last tile
  const bx = last.x * T + (d === "e" ? T - 4 : 0), by = last.y * T + (d === "s" ? T - 4 : 0);
  if (horiz) g.rect(bx, last.y * T + 4, 4, T - 8); else g.rect(last.x * T + 4, by, T - 8, 4);
  g.fill(C.ink);
  // the signal: on the open side (away from the wall), at the entry end
  const open: Record<string, [number, number]> = { n: [0, -1], s: [0, 1], w: [-1, 0], e: [1, 0] };
  const [ox, oy] = open[s.side];
  const cx = first.x * T + T / 2 + ox * 8 + (horiz ? (d === "e" ? -6 : 6) : 0), cy = first.y * T + T / 2 + oy * 8 + (horiz ? 0 : d === "s" ? -6 : 6);
  g.circle(cx, cy, 3).fill(C.green).stroke({ width: 1, color: C.ink });
}
