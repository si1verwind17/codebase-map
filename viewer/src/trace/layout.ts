// Where the trace pane draws what reach.ts found: one box per service or library (tables, topics,
// externals and datastores alone), columns by hop distance (upstream left, the focus's box in column 0, downstream
// right), a call within a box going down and a hop to another box going sideways. Rows in a box are a call tree: depth
// first in call order, each row indented by its call depth, a call an elbow from the caller's trunk into the callee
// (callers of the focus mirrored above it). Arrows are orthogonal (the booklet's lines), each crossing a gap in its own
// lane. Pure: positions in px.
import type { Model } from "../model/model";
import { ownerOf, type Edge, type EdgeKind, type TraceGraph } from "./graph";
import { reach, type Fold, type Reached, type TraceState } from "./reach";
import { CONTAINERS, type SeedRule } from "./entries";

export const BOX_W = 260;
export const ROW_H = 40;
export const HEAD_H = 28;
export const BOX_PAD = 6;
export const COL_GAP = 120;
export const BOX_GAP = 20;
export const MARGIN = 16;
/** The strip inside a box's left edge where calls within the box run down. */
export const GUTTER = 14;
/** A row's indent per call level inside its box, and the levels shown (deeper rows stay at the last). */
export const INDENT = 14;
export const INDENT_LEVELS = 4;
/** Where the second, third… arrow into one row in a box meets it, off the row's middle (each its own elbow). */
const INTO = [0, -8, 8, -16, 16];
const LANE = 7;
const LANES = Math.floor((COL_GAP - 20) / LANE);

export interface Row {
  id: string;                 // the reached id (a node id, or `fold:<library>|<side>`)
  node: string;
  kind: Reached["kind"];
  label: string;
  sub: string;                // second line: keys arriving here, then the data in and back
  focus: boolean;
  side: Reached["side"];
  hop: number;
  more: number;
  folds: Fold[];
  loops: string[];
  members: string[];
  calls: number;
  /** call depth in its box (0: its first row of a chain) and the indent it is drawn at (capped) */
  depth: number;
  indent: number;
  x: number;
  y: number;
}

export interface Box {
  key: string;                // `${owner}@${col}`
  owner: string;
  title: string;
  code: string;
  kind: string;
  col: number;
  rows: Row[];
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Arrow {
  id: string;
  from: string;               // row ids
  to: string;
  edge: Edge;
  kind: EdgeKind;
  dashed: boolean;            // inferred
  path: string;               // SVG path, orthogonal
  hit: string;                // where a click picks it: in a box its own elbow into the row, else the whole path
  title: string;              // what the arrow carries, in words
}

export interface TraceView {
  state: TraceState;
  boxes: Box[];
  arrows: Arrow[];
  rows: Map<string, Row>;
  /** every map node the pane shows (a library fold: the library), for the floor */
  nodes: string[];
  methods: number;
  /** what the trace starts from: the seed rule, every seed, the seeds shown (fewer while folded) */
  start: { rule: SeedRule; total: number; shown: number };
  width: number;
  height: number;
}

/** Return types that carry nothing back. */
const VOID = new Set(["None", "Unit", "void", "Void", "()", "Nothing", "undefined", "null", "nil", "NoReturn", "Task", "ValueTask"]);
const WRAPPERS = /^(?:Promise|Task|ValueTask|ZIO|RIO|URIO|UIO|IO|Future|Mono|CompletableFuture|Awaitable)[<\[](.*)[>\]]$/;
/** The last top-level type argument (`R,Throwable,Unit` -> `Unit`; `String,Map[K,V]` -> `Map[K,V]`). */
function lastArg(args: string): string {
  let depth = 0, start = 0;
  for (let i = 0; i < args.length; i++) {
    const c = args[i];
    if (c === "<" || c === "[" || c === "(") depth++;
    else if (c === ">" || c === "]" || c === ")") depth--;
    else if (c === "," && depth === 0) start = i + 1;
  }
  return args.slice(start);
}
/** True when a return type carries nothing back, also under an async wrapper (`Promise<void>`, `Task[Unit]`). */
function isVoid(returns: string): boolean {
  let t = returns.replace(/\s+/g, "");
  for (let m = WRAPPERS.exec(t); m; m = WRAPPERS.exec(t)) t = lastArg(m[1]);
  return VOID.has(t);
}
/** Relation kinds whose key is shown where they arrive. */
const KEYED = new Set<EdgeKind>(["request", "event", "stream", "batch", "ext-call"]);

/** The data an arrow into method `id` carries: its parameter types going in, its return type coming back
 *  (`Reservation →  ← ChargeId`); a parameter with no declared type shows its name. Empty for a non-method. */
export function dataText(model: Model, id: string): string {
  const sig = model.nodes.get(id)?.signature;
  if (!sig) return "";
  const ins = sig.params.map((p) => p.type ?? p.name).join(", ");
  const back = sig.returns && !isVoid(sig.returns) ? `← ${sig.returns}` : "";
  return [ins ? `${ins} →` : "", back].filter(Boolean).join("  ");
}

/** A row's name: `Class.method` for a method in a class, the node's name otherwise; a fold says how many calls. */
export function rowLabel(model: Model, r: Pick<Reached, "kind" | "node" | "calls">): string {
  if (r.kind === "library") return `${model.label(r.node)} · ${r.calls} ${r.calls === 1 ? "call" : "calls"}`;
  const n = model.nodes.get(r.node);
  if (!n) return r.node;
  if (n.kind !== "method") return model.label(r.node);
  const p = n.parent ? model.nodes.get(n.parent) : undefined;
  return p?.kind === "class" ? `${p.name}.${n.name}` : n.name;
}

/** A trace's title (the pane's header): the focus's own row label (`Class.method`); a line by its title; a focus that is
 *  no row of its own (a datastore, a container: its seeds are the rows) by the name its box shows (`Model.itemName`). */
export function traceTitle(model: Model, view: Pick<TraceView, "rows" | "state">): string {
  const st = view.state;
  if (st.line) return st.line.title;
  const own = view.rows.get(st.focus)?.label;
  if (own) return own;
  return model.nodes.get(st.focus)?.kind === "method" ? rowLabel(model, { kind: "node", node: st.focus, calls: 0 }) : model.itemName(st.focus);
}

const SEED_WORDS: Record<SeedRule, [string, string] | null> = {
  self: null, container: null, tables: ["table", "tables"], "entry points": ["entry point", "entry points"],
  "boundary methods": ["boundary method", "boundary methods"], ends: ["end", "ends"],
};

/** What the trace starts from, after its title (spec A6): the focus's kind and its seed count ("service · 2 entry
 *  points", "line · 2 ends"); a container with neither entry points nor boundary methods its kind alone; a focus that
 *  starts at itself null. */
export function startText(model: Model, view: Pick<TraceView, "state" | "start">): string | null {
  const { rule, total } = view.start;
  if (rule === "self") return null;
  const kind = view.state.line ? "line" : model.kindOf(view.state.focus);
  const w = SEED_WORDS[rule];
  return w ? `${kind} · ${total} ${total === 1 ? w[0] : w[1]}` : kind;
}

/** A node's names down its parent chain from the top, joined " / " ("notifier / app / main.py"). */
export function qualifiedName(model: Model, id: string): string {
  const names: string[] = [];
  const seen = new Set<string>();
  for (let n = model.nodes.get(id); n && !seen.has(n.id); n = n.parent ? model.nodes.get(n.parent) : undefined) {
    seen.add(n.id);
    names.unshift(n.name);
  }
  return names.join(" / ");
}

/** The name a new pin of this trace offers (spec A6, ruling R10): a service, library, package, file or class by its
 *  qualified name; anything else by its title. */
export function pinStartName(model: Model, view: Pick<TraceView, "rows" | "state">): string {
  const f = view.state.focus;
  return !view.state.line && model.nodes.has(f) && CONTAINERS.has(model.kindOf(f)) ? qualifiedName(model, f) : traceTitle(model, view);
}

/** An arrow in words, for its tooltip and the detail panel. */
export function arrowTitle(model: Model, e: Edge): string {
  const kind = e.kind === "implements" ? "implemented by" : e.kind;
  const data = e.kind === "calls" || e.kind === "request" ? dataText(model, e.to) : "";
  const where = e.file ? `${e.file}${e.line ? ":" + e.line : ""}` : "";
  return [kind, e.key ?? "", data, e.kind === "implements" ? "" : e.confirmed ? "confirmed" : "inferred", where].filter(Boolean).join(" · ");
}

export function layoutTrace(model: Model, graph: TraceGraph, st: TraceState): TraceView {
  const set = reach(model, graph, st);
  const col = new Map<string, number>();
  for (const r of set.reached.values()) {
    if (!r.parent) { col.set(r.id, 0); continue; }
    const p = set.reached.get(r.parent)!;
    const same = r.kind !== "library" && ownerOf(model, r.node) === ownerOf(model, p.node);
    col.set(r.id, col.get(r.parent)! + (same ? 0 : (r.side as number)));
  }
  const keysIn = new Map<string, string[]>();
  for (const h of set.hops)
    if (KEYED.has(h.edge.kind) && h.edge.key) {
      const list = keysIn.get(h.to) ?? [];
      if (!list.includes(h.edge.key)) list.push(h.edge.key);
      keysIn.set(h.to, list);
    }

  // boxes and their rows
  const boxes = new Map<string, Box>();
  const rows = new Map<string, Row>();
  const seeds = new Set(set.seeds);
  for (const r of set.reached.values()) {
    const owner = r.kind === "library" ? r.node : ownerOf(model, r.node);
    const c = col.get(r.id)!;
    const key = `${owner}@${c}`;
    let box = boxes.get(key);
    if (!box) {
      box = { key, owner, title: model.label(owner), code: model.codes.get(owner) ?? "", kind: model.kindOf(owner), col: c, rows: [], x: 0, y: 0, w: BOX_W, h: 0 };
      boxes.set(key, box);
    }
    const keys = (keysIn.get(r.id) ?? []).join(" · ");
    const sub = r.kind === "gap" ? "entry method not known"
      : r.kind === "library" ? r.members.map((m) => model.nodes.get(m)?.name ?? m).join(", ")
      : model.nodes.get(r.node)?.kind === "method" ? [keys, dataText(model, r.node)].filter(Boolean).join(" · ")
      : keys || model.kindOf(r.node);
    const row: Row = { id: r.id, node: r.node, kind: r.kind, label: rowLabel(model, r), sub, focus: seeds.has(r.id), side: r.side, hop: r.hop,
      more: r.more, folds: r.folds, loops: r.loops, members: r.members, calls: r.calls, depth: 0, indent: 0, x: 0, y: 0 };
    box.rows.push(row);
    rows.set(r.id, row);
  }
  const orderOf = new Map([...set.reached.values()].map((r) => [r.id, r.order]));
  const rank = (r: Row) => (r.side as number) * r.hop;
  const parentIn = (r: Row, b: Box) => { const p = set.reached.get(r.id)!.parent; return p && b.rows.some((x) => x.id === p) ? p : null; };
  // upstream rows first, then the seed with downstream rows depth-first: a callee's own callees in this box follow it
  // before its next sibling; upstream mirrored, each caller's own callers just above it (farthest chains first)
  for (const b of boxes.values()) {
    const upAll = b.rows.filter((r) => r.side === -1).sort((p, q) => orderOf.get(p.id)! - orderOf.get(q.id)!);
    const upIds = new Set(upAll.map((r) => r.id));
    const callers = new Map<string, Row[]>();
    const upRoots: Row[] = [];
    for (const r of upAll) {
      const p = set.reached.get(r.id)!.parent;
      if (p && upIds.has(p)) callers.set(p, [...(callers.get(p) ?? []), r]);
      else upRoots.push(r);
    }
    upRoots.sort((p, q) => rank(p) - rank(q) || orderOf.get(p.id)! - orderOf.get(q.id)!);
    const up: Row[] = [];
    const mirror = (r: Row) => { for (const k of callers.get(r.id) ?? []) mirror(k); up.push(r); };
    for (const r of upRoots) mirror(r);
    const rest = b.rows.filter((r) => r.side !== -1).sort((p, q) => orderOf.get(p.id)! - orderOf.get(q.id)!);
    const inRest = new Set(rest.map((r) => r.id));
    const kids = new Map<string, Row[]>();
    const roots: Row[] = [];
    for (const r of rest) {
      const p = set.reached.get(r.id)!.parent;
      if (p && inRest.has(p)) kids.set(p, [...(kids.get(p) ?? []), r]);
      else roots.push(r);
    }
    roots.sort((p, q) => p.hop - q.hop || orderOf.get(p.id)! - orderOf.get(q.id)!);
    const out: Row[] = [];
    const walk = (r: Row) => { out.push(r); for (const k of kids.get(r.id) ?? []) walk(k); };
    for (const r of roots) walk(r);
    b.rows = [...up, ...out];
    // call depth: one more than the row it was reached from, when that row is in this box (rest first: the seed is the
    // root its callers hang from)
    const depth = (r: Row): number => { const p = parentIn(r, b); return p ? depth(rows.get(p)!) + 1 : 0; };
    for (const r of b.rows) { r.depth = depth(r); r.indent = Math.min(r.depth, INDENT_LEVELS) * INDENT; }
  }

  // columns: upstream left, downstream right; in a column, boxes in reach order
  const cols = [...new Set([...boxes.values()].map((b) => b.col))].sort((a, b) => a - b);
  const minCol = cols[0] ?? 0;
  const colX = (c: number) => MARGIN + (c - minCol) * (BOX_W + COL_GAP);
  let height = 0;
  for (const c of cols) {
    const inCol = [...boxes.values()].filter((b) => b.col === c)
      .sort((p, q) => Math.min(...p.rows.map((r) => orderOf.get(r.id)!)) - Math.min(...q.rows.map((r) => orderOf.get(r.id)!)));
    let y = MARGIN;
    for (const b of inCol) {
      b.x = colX(c);
      b.y = y;
      b.h = HEAD_H + b.rows.length * ROW_H + BOX_PAD;
      b.rows.forEach((r, i) => { r.x = b.x; r.y = b.y + HEAD_H + i * ROW_H; });
      y += b.h + BOX_GAP;
    }
    height = Math.max(height, y - BOX_GAP + MARGIN);
  }
  const width = cols.length ? MARGIN * 2 + cols.length * BOX_W + (cols.length - 1) * COL_GAP : 0;

  // arrows: within a box down the gutter; across a gap in a lane of their own
  const boxOf = new Map<string, Box>();
  for (const b of boxes.values()) for (const r of b.rows) boxOf.set(r.id, b);
  const lanes = new Map<number, number>();
  const lane = (gap: number) => { const k = lanes.get(gap) ?? 0; lanes.set(gap, k + 1); return 10 + (k % LANES) * LANE; };
  const sideLanes = new Map<number, number>();    // same-column hops between boxes: lanes of their own beside the box edge
  const sideLane = (c: number) => { const k = sideLanes.get(c) ?? 0; sideLanes.set(c, k + 1); return 2 + (k % 3) * 3; };
  // hops within a box: an elbow from the trunk of the row nearer the tree's root (less indented; the edge's start when
  // level) into the other row; the elbow is the arrow's own: a second arrow into one row meets it off the middle
  const trunkX = (b: Box, r: Row) => b.x + GUTTER / 2 + r.indent;
  const rowLeft = (b: Box, r: Row) => b.x + GUTTER + r.indent;
  const incoming = new Map<string, number>();
  const treeHop = (h: { from: string; to: string }) => set.reached.get(h.to)?.parent === h.from || set.reached.get(h.from)?.parent === h.to;
  let channels = 0;
  let lowest = height;
  /** A horizontal run below every box of the columns strictly between, so a long arrow goes round them. */
  const channelY = (lo: number, hi: number) => {
    let bottom = 0;
    for (const bx of boxes.values()) if (bx.col > lo && bx.col < hi) bottom = Math.max(bottom, bx.y + bx.h);
    const y = bottom + 8 + (channels++ % LANES) * LANE;
    lowest = Math.max(lowest, y + MARGIN);
    return y;
  };
  const gapEnd = (c: number) => colX(c) + BOX_W;  // x where the gap right of column c starts
  // tree hops first, so a row's own elbow is the one at its middle
  const hops = [...set.hops].sort((p, q) => Number(treeHop(q)) - Number(treeHop(p)) || rows.get(p.to)!.y - rows.get(q.to)!.y || rows.get(p.from)!.y - rows.get(q.from)!.y);
  const arrows: Arrow[] = hops.map((h) => {
    const a = rows.get(h.from)!, b = rows.get(h.to)!;
    const ba = boxOf.get(h.from)!, bb = boxOf.get(h.to)!;
    const ya = a.y + ROW_H / 2, yb = b.y + ROW_H / 2;
    let path: string, hit: string | null = null;
    if (ba === bb) {
      const tree = set.reached.get(h.to)?.parent === h.from ? a : set.reached.get(h.from)?.parent === h.to ? b : a.indent <= b.indent ? a : b;
      const leaf = tree === a ? b : a;
      const k = incoming.get(leaf.id) ?? 0;
      incoming.set(leaf.id, k + 1);
      const x = trunkX(ba, tree), y = leaf.y + ROW_H / 2 + INTO[k % INTO.length];
      const edge = leaf.y > tree.y ? tree.y + ROW_H - 6 : tree.y + 6;
      hit = `M ${x} ${y} H ${rowLeft(ba, leaf)}`;
      path = tree === a ? `M ${x} ${edge} V ${y} H ${rowLeft(ba, leaf)}` : `M ${rowLeft(ba, leaf)} ${y} H ${x} V ${edge}`;
    } else if (ba.col + 1 === bb.col) {
      const x1 = ba.x + BOX_W, mx = x1 + lane(ba.col);
      path = `M ${x1} ${ya} H ${mx} V ${yb} H ${bb.x}`;
    } else if (ba.col < bb.col) {
      const y = channelY(ba.col, bb.col);
      path = `M ${ba.x + BOX_W} ${ya} H ${gapEnd(ba.col) + lane(ba.col)} V ${y} H ${gapEnd(bb.col - 1) + lane(bb.col - 1)} V ${yb} H ${bb.x}`;
    } else if (ba.col === bb.col + 1) {
      const mx = gapEnd(bb.col) + COL_GAP - lane(bb.col);
      path = `M ${ba.x} ${ya} H ${mx} V ${yb} H ${bb.x + BOX_W}`;
    } else if (ba.col > bb.col) {
      const y = channelY(bb.col, ba.col);
      path = `M ${ba.x} ${ya} H ${gapEnd(ba.col - 1) + COL_GAP - lane(ba.col - 1)} V ${y} H ${gapEnd(bb.col) + COL_GAP - lane(bb.col)} V ${yb} H ${bb.x + BOX_W}`;
    } else {
      const x1 = ba.x + BOX_W;
      path = `M ${x1} ${ya} H ${x1 + sideLane(ba.col)} V ${yb} H ${bb.x + BOX_W}`;
    }
    return { id: `${h.from}>${h.to}>${h.edge.kind}>${h.edge.key ?? ""}`, from: h.from, to: h.to, edge: h.edge, kind: h.edge.kind,
      dashed: !h.edge.confirmed, path, hit: hit ?? path, title: arrowTitle(model, h.edge) };
  });

  const ordered = [...boxes.values()].sort((p, q) => p.col - q.col || p.y - q.y);
  const nodes = [...new Set([...rows.values()].map((r) => r.node))];
  const methods = [...rows.values()].filter((r) => r.kind === "node" && model.nodes.get(r.node)?.kind === "method").length;
  return { state: st, boxes: ordered, arrows, rows, nodes, methods, start: { ...set.start, shown: set.seeds.length }, width, height: lowest };
}
