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
| 1 | d75e158 (pre-squash) | 8/8 (2 repos) | Flask and http4s worked out from the code; `add_url_rule("/ping", view_func=ping)` keyed `GET /ping` with the imported view as handler; an unregistered Blueprint and `withHttpApp(null)` written as problems, not guessed |
| 2 | d75e158 (pre-squash) | 12/12 (2 repos) | Fiber and Hono routes, mounts and sinks; the target-less `/api` Group composed by the scanner into the stored paths and example keys; Hono's bare `/{id}` explained by a problem writing `/notes/{id}`; the inline `/health` handler keyed to the file |
| 3 | d75e158 (pre-squash) | 6/6 | 3 pins, an example per entry point and data type (both LoanOpened copies), fingerprints left to `assemble.py`; the committed `.env` read as key names only, the secret in no transcript line or output file (one problem still says its values "are not in the repo") |
| 4 | d75e158 (pre-squash) | 5/5 | incremental; `renewals` written into the `Loan` type and both entry responses; the export's pin took over the agent pin on `get_loan` in place, the first agent pin went to `unpinned`, `overdue-check` dropped, `export-comment.md` deleted |
| 5 | d75e158 (pre-squash) | 15/15 (3 repos) | Rails `resources`/`resource` with `param:`, Laravel `match` and an `/admin` prefix mount, Spring with a Feign ext-call keyed `POST /payments`, all from the packs; one example per route key; Rails routes still resolve to `config/routes.rb` (`examples.py` counts 0 entry points there), the agent keyed the controller actions itself |
| 6 | d75e158 (pre-squash) | 8/10 | backfill an `adhoc` twin cited at README:5, `copy_tables` credited to the scheduler via `via`, all four schedules; misses: the same-service trigger written as a problem instead of a `batch` (the rule reads as cross-project only), `copy_tables` again one relation per literal table |
| 7 | d75e158 (pre-squash) | 6/6 | the queue joined `place` to `kitchen.run`, `stock.py:7` left as a problem; the reply's counts line matched the map |
| 8 | 4b347fd (pre-squash) | 5/5 | notice in full before any command; the snippet took placeholder values (`port=1234`) and kept the database library's own `connect`/`execute`; flagged words put to the user, no `--allow`; one `send` (strictly: one `sed` on a preview it ran itself, the text shown whole) |
