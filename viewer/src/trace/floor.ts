// The trace on the floor (spec §3.2): the floor keeps its zoom; the items it shows that the trace passes through stay
// at full strength, and the lines between them carry the moving parts.
import { SITE, type Model } from "../model/model";
import type { Target } from "../floor/state";
import type { TraceState } from "./reach";

/** The items on floor `c` standing for the nodes a trace shows: each node lifted to the floor, or, on an inner floor,
 *  the door its line leaves by. */
export function traceItems(model: Model, c: string, nodes: readonly string[]): Set<string> {
  const out = new Set<string>();
  for (const id of nodes) {
    const item = model.liftTo(c, id);
    if (item) out.add(item);
    else if (c !== SITE && model.nodes.has(id)) out.add(model.doorId(model.anchorFor(c, id)));
  }
  return out;
}

/** The floor's lines (base and extra layers) whose two ends are both traced items, once each. */
export function traceKeys(model: Model, c: string, items: ReadonlySet<string>): string[] {
  const b = model.bundles(c);
  return [...new Set([...b.bundles, ...b.layered].filter((x) => items.has(x.a) && items.has(x.b)).map((x) => x.key))];
}

/** The one item on floor `c` that wears the picked mark for a trace (spec A1: blue is what you are looking at now): the
 *  node pointed at in the pane (the row whose detail is open) when there is one and it has a mark here, else the trace's focus, lifted to the
 *  floor as a hovered row is. A node with no item on this floor marks the door of this floor that leads toward it, when
 *  there is one ("it's that way"); else nothing. A line's trace (focus `line:<key>`) marks nothing until a row is
 *  pointed; a pointed row with no mark on this floor leaves the ring on the focus. [] or one id. */
export function traceMarks(model: Model, c: string, focus: string, point: string | null): string[] {
  const markOf = (id: string): string[] => {
    const item = model.liftTo(c, id);
    if (item) return [item];
    if (c === SITE || !model.nodes.has(id)) return [];
    const door = model.doorId(model.anchorFor(c, id));
    return model.bundles(c).doors.some((d) => d.id === door) ? [door] : [];
  };
  const pointed = markOf(point ?? focus);
  return pointed.length || point === null ? pointed : markOf(focus);   // a pointed row with no mark here leaves the ring on the focus
}

/** What the inspector shows while the trace pane is open (audit row 64): the item the blue mark is on, by traceMarks's
 *  choice — the pointed row's node (its detail is open) else the trace's focus — given as a pick without making one
 *  (S1: the floor selection stays empty). A pointed node is shown even where the ring stays on the focus (no mark for it
 *  on this floor): its detail is open, so it is what the reader is looking at. A line's trace shows its line while the
 *  shown floor can name it (`hasLine`), else the floor (null); a focus that is neither a map node nor a floor group, the
 *  floor. */
export function traceSubject(model: Model, st: Pick<TraceState, "focus" | "line">, point: string | null, hasLine: (key: string) => boolean): Target {
  if (point !== null && model.nodes.has(point)) return { type: "node", id: point };
  if (st.line) return hasLine(st.line.key) ? { type: "bundle", key: st.line.key } : null;
  return model.nodes.has(st.focus) || model.groups.has(st.focus) ? { type: "node", id: st.focus } : null;
}

/** Where node `id` is when its own floor is not floor `c` (spec S3): "on floor F2 · billing", named as the Floors list
 *  names it; null on its own floor or for a node not in the map. */
export function floorNote(model: Model, c: string, id: string): string | null {
  if (!model.nodes.has(id)) return null;
  const f = model.floorOf(id) ?? SITE;
  if (f === c) return null;
  return `on floor F${model.path(f).length - 1} · ${f === SITE ? "Whole system" : model.label(f)}`;
}

/** Whether pick `t` on floor `c` is the box the trace's focus is drawn as there (spec A4, ruling R8): the focus lifted to
 *  the floor — a method's service on F0, a container itself — or the focus itself (a twin as its package); for a line's
 *  trace, the same line. A click there keeps the trace as it is. */
export function ownBox(model: Model, c: string, st: Pick<TraceState, "focus" | "line">, t: NonNullable<Target>): boolean {
  if (t.type === "bundle") return !!st.line && st.line.key === t.key;
  return isFocus(model, st, t) || (!st.line && model.liftTo(c, st.focus) === t.id);
}

/** Whether pick `t` is the trace's focus itself (a twin as its package): a node picked by name (Find, a link) keeps the
 *  trace only then, so Find on the service that holds a method's trace traces the service. Never for a line's trace. */
export function isFocus(model: Model, st: Pick<TraceState, "focus" | "line">, t: NonNullable<Target>): boolean {
  return t.type === "node" && !st.line && (model.twinOf(t.id) ?? t.id) === st.focus;
}
