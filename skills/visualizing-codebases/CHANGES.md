# Meaning-rules changes

Only changes that can make facts on an existing map wrong or incomplete go here: a meaning rule in SKILL.md, or a new kind of fact to look for. Viewer, scanner and schema changes do not (the page refresh and the full rescan cover them).
Bump `RULES_VERSION` in `scripts/vizcode/__init__.py` with each new section; prune old sections from the bottom when the file passes about 10. The oldest section left is the floor: a map older than it gets a full meaning re-check.

## Rules 5 — 2026-10-21
- Job triggers (SKILL.md § Deployables, not folders): a job that triggers a job of its own service is a `batch` relation too, from the calling job's method to the target task method, keyed `task <name>`; turn a `problems` entry that records such a trigger into that relation.
- Generic jobs (SKILL.md § Matching interactions): a job whose tables come from its inputs is one relation per direction with a wildcard key and the concrete tables in `tables`, also when every caller passes literal tables; merge relations written one per table into that one.

## Rules 4 — 2026-10-21
- Route keys (SKILL.md § Stack): a path parameter is written `{name}` whatever the framework writes around it (`{id:int}`, `{id?}`, `{*id}`, `:id(\d+)` → `{id}`), and a route's path already holds the prefix of a mount in its own file that the scanner joined (`composed onto N routes` in `summary.md`): rewrite `request` keys and example keys that spell a route otherwise.
- Route handlers (SKILL.md step 5): a route whose handler is a file or the function that registers it (`route.file-handler`, `route.setup-handler`) gets its real handler from a `stack.yaml` handler group, or a `problems` entry saying why there is none.
- Deployables (SKILL.md § Deployables, not folders): a deployable in a language the scanner does not read is a `service`, not an `ext:` placeholder (clear each `deployable.unscanned`); deployables come from whatever runs things (manifests, charts, app-host code, a `Procfile`, a worker command); a gateway's config-declared route is a `request` from the gateway service; a store or service chosen per deployment is `deployment_dependent` with every alternative listed.
- Queues in a store or a job system (SKILL.md § Queues in a store or a job system): a list or stream in a datastore, a job queue or a table used as a queue is a `topic` backed by that store; a job queue's events are keyed `job <name>` on both sides.

## Rules 3 — 2026-10-20
- A call's direction (SKILL.md § data): a `request` now defaults to `data: forward`, and a `request` or `ext-call` set to `both` because of what the call returns goes back to `forward` (the `data.two-way-call` warning lists them). Only a flow both ways is two-way, as a `bidirectional` stream.

## Rules 2 — 2026-10-15
- In-process queues (SKILL.md § In-process queues): where a trace stops at a put on a queue, channel or hub that a background task drains, add the `in-process-queue` node and its `hand-off` relations; clear each `queue.missing` warning.
- Actor and entity messages (SKILL.md § Matching interactions): where a trace stops at a send to an actor or sharded entity, add the `request` to the handler it dispatches to.

## Rules 1 — 2026-10-13
- Baseline: nothing to re-check.
