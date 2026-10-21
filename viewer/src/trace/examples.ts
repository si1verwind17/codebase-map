// Example values the agent wrote, the Swagger way: one per entry point (its request and response, or
// an event's payload) and one per data type. What the detail panel shows for a method or an arrow: the entry point's
// example if it is one, else the examples of the types its signature refers to; a type without one shows its fields.
// Always labelled as examples.
import type { Model } from "../model/model";
import { EXAMPLE_LABEL, type Field } from "../model/types";

export { EXAMPLE_LABEL };

export type ExampleBlock =
  | { kind: "entry"; title: string; request: unknown; response?: unknown }
  | { kind: "type"; title: string; cls: string; value: unknown }
  | { kind: "fields"; title: string; cls: string; fields: Field[] };

/** The examples for method `node`; `key` (an arrow's key) picks that entry when the method has several. */
export function examplesFor(model: Model, node: string, key?: string | null): ExampleBlock[] {
  const ex = model.map.examples;
  const entries = (ex?.entries ?? []).filter((e) => e.node === node);
  const keyed = key ? entries.filter((e) => e.key === key) : [];
  const chosen = keyed.length ? keyed : entries;
  if (chosen.length)
    return chosen.map((e) => ({ kind: "entry" as const, title: e.key, request: e.request, ...(e.response !== undefined ? { response: e.response } : {}) }));
  const sig = model.nodes.get(node)?.signature;
  const refs = [...new Set([...(sig?.params ?? []).flatMap((p) => p.refs ?? []), ...(sig?.returns_refs ?? [])])];
  return refs.flatMap((cls): ExampleBlock[] => {
    const t = ex?.types?.[cls];
    if (t) return [{ kind: "type", title: model.label(cls), cls, value: t.value }];
    const fields = model.nodes.get(cls)?.fields;
    return fields?.length ? [{ kind: "fields", title: model.label(cls), cls, fields }] : [];
  });
}

/** A value in full: JSON pretty-printed, even when the map stored it as a JSON string. */
export function pretty(v: unknown): string {
  if (v === undefined) return "—";
  if (typeof v === "string") {
    try { return JSON.stringify(JSON.parse(v), null, 2); } catch { return v; }
  }
  return JSON.stringify(v, null, 2);
}
