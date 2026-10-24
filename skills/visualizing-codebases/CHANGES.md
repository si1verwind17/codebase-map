# Meaning-rules changes

Only changes that can make facts on an existing map wrong or incomplete go here: a meaning rule in SKILL.md, or a new kind of fact to look for. Viewer, scanner and schema changes do not (the page refresh and the full rescan cover them).
Bump `RULES_VERSION` in `scripts/vizcode/__init__.py` with each new section; prune old sections from the bottom when the file passes about 10. The oldest section left is the floor: a map older than it gets a full meaning re-check.

## Rules 8 — 2026-10-24
- FastAPI prefixes (SKILL.md § Run, the structure pass's lists): the scanner joins `include_router` prefixes onto the included router's routes across files; rewrite `request` keys and example keys that spell such a route without them, and compose only the includes marked `not composed`.
- Flask routes (SKILL.md § Stack): the Python pack reads `route`, the verb decorators and `add_url_rule`; a `stack.yaml` Flask pattern now listed `duplicates` can go.
- Request objects (SKILL.md § Matching interactions): `http clients` also lists request descriptors (`{method, url}` objects) and calls on the app's own `*Client` class; match each to its route as a `request`, and drop hand-written requests the list now gives as facts.
- Job systems (SKILL.md § Queues, `references/interactions.md`): `summary.md` lists `jobs defined` and `jobs enqueued` for the packs' job systems (Celery, RQ, Dramatiq, Sidekiq/ActiveJob, Laravel queues, Bull, Hangfire, Spring); write the job-queue `event`s and schedules' `batch`es from those lines and check hand-written ones against them.
- Roles of one module (SKILL.md § Deployables, not folders): a package or jar run as several roles (web, worker, scheduler; master and workers) is one service per role, and a relation between two roles starts at the service of the role making it with `via` naming the shared method; move relations that start at a method under another role's service.
- Deployables (SKILL.md § Deployables, not folders): a deployable holding many unscanned files beside scanned ones is listed now (give it its service); one in a test, CI, docs or dev folder is no longer listed, and a service or `problems` entry written only to clear it can go.

## Rules 7 — 2026-10-24
- Outbound requests (SKILL.md § Matching interactions): `http clients` now lists calls through the code's own HTTP helpers and client calls with a path; match each to its route as a `request`, and drop hand-written requests the list now gives as facts.
- SQL kept outside the code (SKILL.md § Matching interactions): a mapper XML's statements are SQL facts of the interface methods they name, and § Tables defined in SQL files lists the tables `.sql` files create; attach their reads and writes.
- Inline handlers (`references/stack.md`): a route's lambda inside a function is its own handler node named after the route; move the route's examples and relations onto it.

## Rules 6 — 2026-10-23
- Tables by naming default (SKILL.md § Stack): each class the Stack section lists as entity-looking with no table takes its table from the ORM's naming default; write those tables and their reads and writes.
- Framework-implemented interfaces (SKILL.md § Run, the structure pass's lists): a repository's or declarative HTTP client's methods start the `db-read`/`db-write` or `request` relations; a call to a method only the library base supplies starts at the calling method. Move relations written elsewhere onto them.
- Base paths (SKILL.md § Run, `stack.yaml` `base_paths`): a path prefix only config sets goes into `base_paths` once per deployable folder; route keys, `request` keys and example keys carry it.
- Route styles (SKILL.md § Stack): each route-looking line with no route gets a route pattern, or a `problems` entry saying why it is none.

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
