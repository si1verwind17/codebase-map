// The trace's graph: the map's calls and runtime relations as directed edges, built once per map. A db-read
// is turned round (table → reader) so a table's upstream is its writers and its downstream its readers. A trait method
// also leads to its implementations' same-named methods (format.md: `calls` are drawn to the trait method), so a trace
// does not stop at a trait. `uses-code` is not part of a trace.
import type { Model } from "../model/model";
import type { Evidence, Relation, RelationKind } from "../model/types";

/** The relation kinds a trace follows. */
export const TRACE_KINDS: readonly RelationKind[] = ["calls", "request", "event", "stream", "batch", "db-read", "db-write", "ext-call", "hand-off"];

export type EdgeKind = RelationKind | "implements";

/** 1: downstream (edges followed forward), -1: upstream (followed backward). */
export type Side = 1 | -1;

export interface Edge {
  from: string;              // oriented as drawn: from → to
  to: string;
  kind: EdgeKind;
  key: string | null;
  confirmed: boolean;        // any relation behind it confirmed
  file: string;              // its first evidence (for `calls`: the caller's file), "" when none
  line: number;              // that evidence's line, 0 when none
  relations: Relation[];     // the map's relations behind it (none for `implements`)
}

/** Kinds that end a box of their own in the pane: every other node lives in its service's or library's box. */
const OWN_BOX = new Set(["service", "library", "table", "topic", "external", "datastore"]);

/** The box a node is drawn in: its service or library (the top of its parent chain), or itself for a table, topic,
 *  external, datastore, service or library. */
export function ownerOf(model: Model, id: string): string {
  const n = model.nodes.get(id);
  if (!n || OWN_BOX.has(n.kind)) return id;
  let cur = n;
  const seen = new Set<string>([cur.id]);
  while (cur.parent && model.nodes.has(cur.parent) && !seen.has(cur.parent)) {
    seen.add(cur.parent);
    cur = model.nodes.get(cur.parent)!;
  }
  return cur.id;
}

/** Edges in call order: by their first evidence (file, then line), then by their ends. */
export function edgeOrder(a: Edge, b: Edge): number {
  return a.file.localeCompare(b.file) || a.line - b.line || a.from.localeCompare(b.from) || a.to.localeCompare(b.to) || a.kind.localeCompare(b.kind);
}

function firstEvidence(evs: readonly Evidence[] | undefined): { file: string; line: number } {
  let best: { file: string; line: number } | null = null;
  for (const e of evs ?? []) {
    const c = { file: e.file ?? "", line: e.line ?? 0 };
    if (!best || c.file.localeCompare(best.file) < 0 || (c.file === best.file && c.line < best.line)) best = c;
  }
  return best ?? { file: "", line: 0 };
}

export class TraceGraph {
  private readonly fwd = new Map<string, Edge[]>();
  private readonly back = new Map<string, Edge[]>();

  constructor(readonly model: Model) {
    const byKey = new Map<string, Edge>();
    for (const r of model.map.relations) {
      if (!TRACE_KINDS.includes(r.kind)) continue;
      const [from, to] = r.kind === "db-read" ? [r.to, r.from] : [r.from, r.to];
      const k = `${r.kind}|${from}|${to}|${r.key ?? ""}`;
      const ev = firstEvidence(r.evidence);
      const e = byKey.get(k);
      if (!e) {
        byKey.set(k, { from, to, kind: r.kind, key: r.key ?? null, confirmed: r.confidence === "confirmed", file: ev.file, line: ev.line, relations: [r] });
        continue;
      }
      e.relations.push(r);
      if (r.confidence === "confirmed") e.confirmed = true;
      if (ev.file.localeCompare(e.file) < 0 || (ev.file === e.file && ev.line < e.line)) { e.file = ev.file; e.line = ev.line; }
    }
    // trait method -> implementations, by the scanner's fold rule (calls.py `_abstractions`): a method of a class
    // naming a supertype in `implements` folds to the same-named method of that supertype, or of the nearest class
    // above it that declares one, of the same arity, else of any arity when only one exists; chains reach the top.
    // The edge runs from the top method to each implementation.
    const methods = new Map<string, Map<string, string[]>>();
    for (const n of model.map.nodes) {
      if (n.kind !== "method" || !n.parent) continue;
      const byName = methods.get(n.parent) ?? new Map<string, string[]>();
      byName.set(n.name, [...(byName.get(n.name) ?? []), n.id]);
      methods.set(n.parent, byName);
    }
    const arity = (m: string) => m.slice(m.lastIndexOf("/") + 1);
    const declared = (sup: string, name: string): string[] => {
      const todo = [sup], seen = new Set<string>();
      while (todo.length) {
        const c = todo.shift()!;
        if (seen.has(c) || !model.nodes.has(c)) continue;
        seen.add(c);
        const found = methods.get(c)?.get(name);
        if (found?.length) return found;
        todo.push(...(model.nodes.get(c)!.implements ?? []));
      }
      return [];
    };
    const up = new Map<string, string>();
    for (const c of model.map.nodes) {
      for (const sup of c.implements ?? []) {
        for (const [name, mine] of methods.get(c.id) ?? []) {
          const theirs = declared(sup, name);
          for (const m of mine) {
            const sameArity = theirs.filter((t) => arity(t) === arity(m));
            const same = sameArity.length ? sameArity : theirs;
            if (same.length === 1 && !up.has(m)) up.set(m, same[0]);
          }
        }
      }
    }
    const top = (m: string): string => {
      const seen = new Set([m]);
      while (up.has(m) && !seen.has(up.get(m)!)) { m = up.get(m)!; seen.add(m); }
      return m;
    };
    for (const impl of up.keys()) {
      const t = top(impl), m = model.nodes.get(impl)!;   // `up` keys are map nodes
      const k = `implements|${t}|${impl}|`;
      if (!byKey.has(k)) byKey.set(k, { from: t, to: impl, kind: "implements", key: null, confirmed: true, file: m.file ?? "", line: m.line ?? 0, relations: [] });
    }
    const add = (m: Map<string, Edge[]>, id: string, e: Edge) => { const list = m.get(id); if (list) list.push(e); else m.set(id, [e]); };
    for (const e of byKey.values()) { add(this.fwd, e.from, e); add(this.back, e.to, e); }
    for (const list of [...this.fwd.values(), ...this.back.values()]) list.sort(edgeOrder);
  }

  /** The edges leaving `id` on `side` (downstream: out of it; upstream: into it), in call order. */
  next(id: string, side: Side): readonly Edge[] {
    return (side === 1 ? this.fwd : this.back).get(id) ?? [];
  }

  /** How many edges touch `id` either way. */
  degree(id: string): number {
    return this.next(id, 1).length + this.next(id, -1).length;
  }
}

/** The node an edge reaches from `side`'s end: its `to` downstream, its `from` upstream. */
export const across = (e: Edge, side: Side): string => (side === 1 ? e.to : e.from);
