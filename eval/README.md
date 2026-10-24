# Evaluations: visualizing-codebases

The scenarios here run the skill arm only (skill loaded), one rep each (a
run costs ~150k tokens), Sonnet, graded by an independent judge against the
checks below. A control arm (skill NOT loaded; its prompt must explicitly
forbid loading any skill, per the writing-skills protocol) is optional; when
one runs, it runs as below.

**Control arm gets the output contract**, not the method: a copy of
`format.md` and `scripts/schema/code-map.schema.json` in `<workdir>/contract/`,
and no scripts. Every run's output is checked with the skill's
`scripts/validate.py` (the judge runs it).

**Prompt** (verbatim, with the fixture's path; skill arm prepends "Before
starting, read `<skill path>/SKILL.md` and follow it as authoritative for how
you work."; control arm prepends "Do not load or read any skill, SKILL.md, or
convention guide from the environment." and appends "The output format is
specified in <workdir>/contract/."):

> Map the repository at `<repo path>` for a code-map viewer: its
> services, how they interact, what they read and write, where to start
> reading, and example data for what comes in. Write the result to
> `docs/viz-code/code-map.json` in that repo. Do not commit. When done,
> reply with ONLY the path you wrote and one line of counts.

## Scenarios

One file each in [`scenarios/`](scenarios/): its fixture, prompt and checks.

| Scenario | What it tests |
|---|---|
| [Scenario 1](scenarios/1-unknown-stack.md) | unknown stack (skill arm only) |
| [Scenario 2](scenarios/2-unknown-framework.md) | unknown framework in a new language (skill arm only) |
| [Scenario 3](scenarios/3-first-scan-pins-examples.md) | pins and examples on a first scan (skill arm only) |
| [Scenario 4](scenarios/4-rescan-viewer-pins.md) | a rescan with a changed type and pins from the viewer (skill arm only) |
| [Scenario 5](scenarios/5-known-packs.md) | packs that know the stack (skill arm only) |
| [Scenario 6](scenarios/6-airflow-etl.md) | an Airflow ETL repo (skill arm only) |
| [Scenario 7](scenarios/7-in-process-queue.md) | an in-process queue between a route and a background worker (skill arm only) |
| [Scenario 8](scenarios/8-send-feedback.md) | send feedback: the notice, no names in the issue, a yes to the exact text (skill arm only; one headless session per user turn) |

## Editing this skill

A meaning-rule change that can alter facts on existing maps → add a section to [`CHANGES.md`](../skills/visualizing-codebases/CHANGES.md) and bump `RULES_VERSION` (see that file).

## Pending validation

- Pack entries replaced by name in `stack.yaml`: no scenario yet.
- `ext.missing` cleared by a `problems` entry, and example keys under a mount: the rule is in SKILL.md; no scenario
  exercises it on purpose yet.
- Actor and sharded-entity messages as `request`s (SKILL.md § Matching interactions): no scenario yet.

## Latest results

Each scenario's latest run. `Skill@` is the commit whose skill content was evaluated. Sonnet runs, each graded
by an independent judge on Opus.

| Scenario | Skill@ | Result | Notes |
|---|---|---|---|
| 1 | 3daac3d | 8/8 (2 repos) | Quart (3 `stack.yaml` patterns: `route`, verb decorator, `add_url_rule` with a `handler` group → the named view `ping`) and http4s (one `Root` segments pattern) worked out from the code; Celery `event`, marshmallow/io.circe ignored, both summaries "nothing unrecognised" |
| 2 | 3daac3d | 12/12 (2 repos) | Fiber (route plus `Group` mount) and Hono (route, an inline-handler pattern, `.route` mount) written to `stack.yaml` in one pass; `/api` composed into the stored paths, `/notes → notes` composed in the problem text (examples keyed `/{id}`); `/health` → `get_health`; pgx `items` and ioredis `note:{id}` on their handlers |
| 3 | 3daac3d | 6/6 | 3 pins incl. the consumer `main/0` (direction both), every entry and data type with an example, fingerprints left to `assemble.py`; compose file only through `config.py`, `.env` as key names, neither secret in transcript or outputs; reply pasted the exact counts line |
| 4 | f4a05f2¹ | 5/5 | incremental from a 0.13.0/rules-6 map; `Loan` and both entry responses rewritten with `renewals`, map at HEAD, nothing stale; the export pin took over the agent pin on `get_loan` as `by: user`, the first agent pin went to `unpinned`, `overdue-check` dropped, `export-comment.md` deleted; clean run, 7 tool calls |
| 5 | 3daac3d | 15/15 (3 repos) | Rails (11 routes, `param:`/`except:`/singular `resource`), Laravel (`Route::match` → PUT+PATCH on `update`, `/admin` composed and listed as a mount) and Spring (Feign as an inferred ext-call keyed by its config address `payments.url`, no `/payments` route) from the packs, no `stack.yaml`; one example per key; `catalog_books` defined on Book |
| 6 | 3daac3d | 10/10 | scheduler from compose:2, backfill twin under `adhoc` at README:4; `copy_tables` as wildcard `table shop.*` with `via` and the three tables; trigger keyed `task copy_customers`; four schedules; GCS ext-call; `chunked` ×3. One uncounted slip: the warehouse write cites `replicate.py:13`, the line before its `to_sql` |
| 7 | 3daac3d | 6/6 | `tickets` queue at `main.py:12` joins `place` to `kitchen.run` with two confirmed hand-offs; `create_task` kept as a `start → run` call; the trace reaches the `tickets` table and `ticket-ready`; `stock.py:7` a problem, no `queue.missing` |
| 8 | 2f1d235 | 5/5 | notice in full before any command; the snippet took placeholder names (`rpclib`, `Rpc("some.topic")`, `Foo`) and the text kept the unfinished meaning pass in view; flagged `ledger`/`zentrova` put to the user, no `--allow`; every shown preview byte-identical to its output; one `send` with the last shown digest |

¹ Run on the skill one round of fixes before f4a05f2 (rescan logic unchanged since; not rerun since, as its
fixture holds a map made by an older skill).
