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
| 1 | 33e60cd | 8/8 (2 repos) | Flask and http4s worked out from the code; SKILL.md's worked `stack.yaml` uses other stacks, so nothing was copied |
| 2 | 33e60cd | 10/10 (2 repos) | Fiber and Hono routes, mounts and sinks; the Reported check graded from `stack.yaml` |
| 3 | 33e60cd | 5/5 | 3 pins, an example per entry point and data type, fingerprints left to `assemble.py` |
| 4 | 33e60cd | 5/5 | stale examples rewritten with the new field; the user's `pin:` converted the agent's identical pin |
| 5 | 33e60cd | 15/15 (3 repos) | Rails `resources`, Laravel without a `use`, Spring with a Feign client; an example per key |
| 6 | 33e60cd | 10/10 | Airflow DAGs under the scheduler, the hand-run backfill apart, the generic copy's tables, the trigger |
| 7 | 5008e58 | 6/6 | the queue joined `place` to `cook` (the method that handles each ticket); `stock.py`'s local queue left as a problem |
