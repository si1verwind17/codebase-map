// The words under a machine's name on the factory floor (its sub line), from the model and the floor's bundles alone:
// pure, so the drawing (floor/labels.ts) and the map audit read the same words. No Pixi here.
import type { Bundle, Model } from "../model/model";
import type { Machine } from "../route/types";
import { splitEndpoint } from "../floor/names";

/** The factory's sub line: the shape and the role tag already say the kind and role, so only the count of what is inside. */
export function factorySubOf(model: Model, floorBundles: Bundle[], m: Pick<Machine, "id" | "kind">): string {
  if (["datastore", "external", "table", "method"].includes(m.kind)) return subline(model, floorBundles, m);
  const real = model.twinOf(m.id) ?? m.id;
  const n = m.kind === "group" ? (model.groups.get(m.id)?.members.length ?? 0) : model.map.nodes.filter((x) => x.parent === real).length;
  return n ? `${n} inside` : "";
}

function subline(model: Model, floorBundles: Bundle[], m: Pick<Machine, "id" | "kind">): string {
  const real = model.twinOf(m.id) ?? m.id;   // a twin describes the package it stands for
  const n = model.nodes.get(real);
  if (m.kind === "datastore") {
    const tables = model.map.nodes.filter((x) => x.parent === m.id).length;
    const bundles = floorBundles.filter((b) => b.a === m.id || b.b === m.id);
    const reads = bundles.filter((b) => b.kinds["db-read"]).length, writes = bundles.filter((b) => b.kinds["db-write"]).length;
    return `${tables} tables · R ${reads} · W ${writes}`;
  }
  if (m.kind === "group") return `${model.groups.get(m.id)?.members.length ?? 0} inside · open`;
  if (m.kind === "table") {
    const a = model.tableAccess(m.id);
    return [a.writers.length ? `W ${a.writers.join(" ")}` : "", a.readers.length ? `R ${a.readers.join(" ")}` : ""].filter(Boolean).join(" · ") || "no access found";
  }
  if (m.kind === "method") return n?.signature ? `(${n.signature.params.map((p) => p.name).join(", ")})` : "";
  if (m.kind === "external") return ["external", splitEndpoint(model.label(m.id)).endpoint].filter(Boolean).join(" · ");
  const children = model.map.nodes.filter((x) => x.parent === real).length;
  const role = n?.role ? `${n.role} · ` : "";
  return `${role}${m.kind}${children ? ` · ${children} inside` : ""}`;
}
