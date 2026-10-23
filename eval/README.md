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
- Config read through `config.py`: Scenario 3's fixture has no literal compose value, so a raw read still passes
  its secrets check; the rerun of 2026-10-23 added `POSTGRES_PASSWORD` by hand. Put one in the fixture.

## Latest results

Each scenario's latest run. `Skill@` is the commit whose skill content was evaluated. Sonnet runs, each graded
by an independent judge on Opus.

| Scenario | Skill@ | Result | Notes |
|---|---|---|---|
| 1 | f4a05f2¹ | 8/8 (2 repos) | Flask and http4s worked out from the code; `add_url_rule("/ping", view_func=ping)` keyed `GET /ping` with the named view as handler; Celery `imports` event, marshmallow/io.circe ignored; the unregistered Blueprint, the out-of-repo Celery broker and the injected Transactor written as problems, not guessed |
| 2 | f4a05f2¹ | 12/12 (2 repos) | Fiber and Hono written to stack.yaml from the code in one pass each; the target-less `/api` Group composed by the scanner into the stored paths and example keys; the inline `/health` handler keyed to the file; Hono's `/notes → notes` mount listed, its routes kept as `/{id}` with matching example keys and no problem needed; pgx `items` and ioredis `note:{id}` attached to their handlers |
| 3 | f4a05f2 | 6/6 | 3 pins, an example for every entry point and data type, fingerprints left to `assemble.py`; `.env` never opened, the compose file (with a literal `POSTGRES_PASSWORD` added for this run) read only through `config.py`, its value hidden; neither secret in any transcript line or output file; config read from the working tree, not `--commit`; the consumer entry keyed on `main/0` (the subscribe loop), where the previous run used `handle/1` |
| 4 | f4a05f2¹ | 5/5 | incremental from a 0.13.0/rules-6 map; `Loan` and both entry responses rewritten with `renewals`, map at HEAD, nothing stale; the export pin took over the agent pin on `get_loan` as `by: user`, the first agent pin went to `unpinned`, `overdue-check` dropped, `export-comment.md` deleted; clean run, 7 tool calls |
| 5 | f4a05f2 | 15/15 (3 repos) | Rails `resources`/`resource` with `param:`, Laravel `match` with the `/admin` prefix composed into `DELETE /admin/products/{id}`, Spring with a Feign ext-call keyed `POST /payments`, all from the packs, one example per route key; the Feign interface's `@PostMapping` is no route-looking line (an earlier run flagged it: fixed), so orders' Stack reads `nothing unrecognised` |
| 6 | f4a05f2 | 10/10 | `copy_tables` as wildcard `table shop.*` reads and writes from each DAG method with `via`, the three literal tables split across the two (earlier runs: one relation per direction from the service; SKILL.md leaves it open); trigger a `batch` keyed `task copy_customers`; backfill an `adhoc` twin at README:5, all four schedules; the DSN read through `config.py`, so every warehouse link is `confirmed` |
| 7 | f4a05f2¹ | 6/6 | the `tickets` queue cited at `main.py:12` joined `place` to `kitchen.run` with confirmed hand-offs (main.py:25; main.py:19 + kitchen.py:22), `create_task` kept as a `start → run` call; `stock.py:7` left as a problem, no `queue.missing`; the reply's counts line matched the map |
| 8 | 2f1d235 | 5/5 | notice in full before any command; the snippet took placeholder names (`rpclib`, `Rpc("some.topic")`, `Foo`) and the text kept the unfinished meaning pass in view; flagged `ledger`/`zentrova` put to the user, no `--allow`; every shown preview byte-identical to its output; one `send` with the last shown digest |

¹ Run on the same changes one round of fixes earlier: before `config.py --commit`, the DSN rule and the Feign
fix, which these scenarios do not exercise.
