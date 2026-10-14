// What a trace shows (spec §3.3, §3.5): from the focus, edges followed downstream and/or upstream, breadth first, two
// hops each way to start. A node's `+` adds one hop beyond it; more than FOLD_AT neighbours on a side show the total
// and the first FOLD_AT in call order until "show all"; calls into a shared library fold into one box per library and
// side until it is opened; an edge back to a node on the path that led here is a loop (↺), drawn once; a hop known only
// to a service (or library) ends there. Pure: the pane draws it (layout.ts).
import type { Model } from "../model/model";
import type { PinDirection } from "../model/types";
import { across, ownerOf, type Edge, type Side, type TraceGraph } from "./graph";
import { seedsFor, type LineStart, type SeedRule } from "./entries";

/** Hops each way a trace starts with. */
export const START_DEPTH = 2;
/** A side with more neighbours than this shows its total, then this many, then "show all". */
export const FOLD_AT = 5;

export interface TraceState {
  focus: string;
  direction: PinDirection;
  /** a line's trace (spec A5): the focus is `line:<key>` and the line's ends are the seeds */
  line?: LineStart;
  /** reached ids whose `+` was pressed: one more hop beyond each */
  expanded: ReadonlySet<string>;
  /** `${reached id}|${side}` whose "show all" was pressed */
  showAll: ReadonlySet<string>;
  /** library ids opened from their fold */
  libraries: ReadonlySet<string>;
}

export function initialState(focus: string, direction: PinDirection = "both", line?: LineStart): TraceState {
  return { focus, direction, ...(line ? { line } : {}), expanded: new Set(), showAll: new Set(), libraries: new Set() };
}

/** The `showAll` key of a start with more than FOLD_AT seeds (spec A3): every seed shown. */
export const ALL_SEEDS = "seeds";

export interface Fold { side: Side; total: number; word: string }

export interface Reached {
  id: string;                 // the node id, or `fold:<library id>|<side>` for a library fold
  node: string;               // the map node (the library for a fold)
  kind: "node" | "gap" | "library";
  side: 0 | Side;             // 0: a seed (the focus, a datastore's table, a container's entry point, a line's end)
  hop: number;                // edges from the focus (an `implements` step adds none)
  parent: string | null;      // the reached id it was reached from
  order: number;              // reach order: call order within a hop
  more: number;               // a frontier node: neighbours on its side not shown yet (its `+`); 0 otherwise
  folds: Fold[];              // sides whose neighbours are folded above FOLD_AT
  loops: string[];            // nodes on its own path it leads back to (↺)
  members: string[];          // a library fold: the library's methods it stands for
  calls: number;              // a library fold: the edges folded into it
}

/** One arrow between two reached ids, oriented as its edge (data from → to). */
export interface Hop { from: string; to: string; edge: Edge }

export interface TraceSet { reached: Map<string, Reached>; hops: Hop[]; seeds: string[]; start: { rule: SeedRule; total: number } }

const GAP = new Set(["service", "library", "class"]);

/** The word after a folded total: "12 callers". */
export function foldWord(edges: readonly Edge[], side: Side): string {
  if (edges.every((e) => e.kind === "calls")) return side === 1 ? "callees" : "callers";
  if (side === -1 && edges.every((e) => e.kind === "db-write")) return "writers";
  if (side === 1 && edges.every((e) => e.kind === "db-read")) return "readers";
  return side === 1 ? "downstream" : "upstream";
}

export function reach(model: Model, graph: TraceGraph, st: TraceState): TraceSet {
  const reached = new Map<string, Reached>();
  const hops: Hop[] = [];
  const hopKeys = new Set<string>();
  const budget = new Map<string, number>();
  const frontier: [string, Side][] = [];
  const queue: [string, Side][] = [];
  let order = 0;
  const start = seedsFor(model, st.focus, st.line);
  // a start with more than FOLD_AT seeds shows the first FOLD_AT until "show all" (spec A3, ruling R5)
  const seeds = start.ids.length > FOLD_AT && !st.showAll.has(ALL_SEEDS) ? start.ids.slice(0, FOLD_AT) : start.ids;
  const focusOwners = new Set(seeds.map((s) => ownerOf(model, s)));
  const sides: Side[] = st.direction === "both" ? [1, -1] : st.direction === "downstream" ? [1] : [-1];
  const make = (id: string, node: string, kind: Reached["kind"], side: 0 | Side, hop: number, parent: string | null): Reached =>
    ({ id, node, kind, side, hop, parent, order: order++, more: 0, folds: [], loops: [], members: [], calls: 0 });
  const addHop = (from: string, to: string, edge: Edge) => {
    const k = `${from}|${to}|${edge.kind}|${edge.key ?? ""}`;
    if (!hopKeys.has(k)) { hopKeys.add(k); hops.push({ from, to, edge }); }
  };
  const onPath = (anc: string, id: string) => {
    for (let cur: string | null = id; cur; cur = reached.get(cur)?.parent ?? null) if (cur === anc) return true;
    return false;
  };

  for (const s of seeds) {
    reached.set(s, make(s, s, "node", 0, 0, null));
    budget.set(s, START_DEPTH);
    for (const side of sides) queue.push([s, side]);
  }
  for (let qi = 0; qi < queue.length; qi++) {
    const [uid, side] = queue[qi];
    const u = reached.get(uid)!;
    const all = graph.next(u.node, side);
    if (!all.length) continue;
    let b = budget.get(uid) ?? 0;
    if (b === 0 && st.expanded.has(uid)) b = 1;
    // out of budget: only the zero-cost implementation steps are still followed; the rest is the frontier
    const edges = b === 0 ? all.filter((e) => e.kind === "implements") : all;
    if (b === 0 && edges.length < all.length) frontier.push([uid, side]);
    if (!edges.length) continue;
    // fold on distinct neighbours: the total is what "show all" can show; every edge to a shown neighbour is followed
    const neighbours = [...new Set(edges.map((e) => across(e, side)))];
    const folded = neighbours.length > FOLD_AT && !st.showAll.has(`${uid}|${side}`);
    if (folded) u.folds.push({ side, total: neighbours.length, word: foldWord(edges, side) });
    const keep = new Set(folded ? neighbours.slice(0, FOLD_AT) : neighbours);
    const touched = new Set<string>();
    const libraryOf = (v: string) => {
      const vn = model.nodes.get(v);
      const owner = ownerOf(model, v);
      return vn && !GAP.has(vn.kind) && model.nodes.get(owner)?.kind === "library" && !focusOwners.has(owner) && !st.libraries.has(owner) ? owner : null;
    };
    for (const e of edges) {
      const v = across(e, side);
      if (!keep.has(v)) {
        // a folded-away edge into a library whose fold is shown still counts in that fold
        const lib = libraryOf(v), f = lib ? reached.get(`fold:${lib}|${side}`) : undefined;
        if (f && touched.has(f.id)) { f.calls++; if (!f.members.includes(v)) f.members.push(v); }
        continue;
      }
      const known = reached.get(v);
      if (known) {
        if (v === uid || onPath(v, uid)) { if (!u.loops.includes(v)) u.loops.push(v); }
        else if (known.side === -side && onPath(uid, v)) { if (!known.loops.includes(uid)) known.loops.push(uid); }   // the far end of a cycle through the seed: marked there, not drawn twice
        else addHop(e.from, e.to, e);
        continue;
      }
      const owner = libraryOf(v);
      if (owner) {
        const fid = `fold:${owner}|${side}`;
        let f = reached.get(fid);
        if (!f) { f = make(fid, owner, "library", side, u.hop + 1, uid); reached.set(fid, f); }
        if (!f.members.includes(v)) f.members.push(v);
        f.calls++;
        touched.add(fid);
        addHop(side === 1 ? uid : fid, side === 1 ? fid : uid, e);
        continue;
      }
      const vn = model.nodes.get(v);
      const gap = !!vn && GAP.has(vn.kind);
      if (gap && v === st.focus && !st.line) continue;   // a container focus is not a gap row inside its own trace
      const step = e.kind === "implements" ? 0 : 1;
      reached.set(v, make(v, v, gap ? "gap" : "node", side, u.hop + step, uid));
      addHop(e.from, e.to, e);
      if (gap) continue;
      budget.set(v, b - step);
      queue.push([v, side]);
    }
  }
  for (const [uid, side] of frontier) {
    const u = reached.get(uid)!;
    u.more = new Set(graph.next(u.node, side).map((e) => across(e, side)).filter((v) => !reached.has(v))).size;
  }
  return { reached, hops, seeds, start: { rule: start.rule, total: start.ids.length } };
}
