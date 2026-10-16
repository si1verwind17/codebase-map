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
| 1 | 5008e58 | 8/8 (2 repos) | Flask and http4s worked out from the code; each route pattern matched only route lines |
| 2 | 5008e58 | 12/12 (2 repos) | Fiber and Hono routes, mounts and sinks; the Reported check graded from `stack.yaml` |
| 3 | 5008e58 | 4/5 | 3 pins, an example per entry point and data type, fingerprints left to `assemble.py`; the reply's "4 relations" counted only the runtime ones of 8 |
| 4 | 24fc1e0 | 5/5 | `renewals` written into the stale examples once `stale.json` named it (`value_lacks`); two runs before that change cleared the flags unchanged (3/5) |
| 5 | 5008e58 | 15/15 (3 repos) | Rails `resources`, Laravel without a `use`, Spring with a Feign client; library's `PUT /members/{member_no}` got no relation (check 4 covers shop and orders) |
| 6 | 5008e58 | 6/10, 9/10 (2 runs) | run to run variance: `main`'s skill scored 8/10 on the same fixture; misses: `common` not a library (so no `via`), the trigger, the wildcard key; both runs cite the backfill's README line one line early |
| 7 | 5008e58 | 6/6 | the queue joined `place` to `cook` (the method that handles each ticket); `stock.py`'s local queue left as a problem |
| 8 | d67f9ff | 5/5 | run on the branch before the squash (the form fields and the re-ask wording came after it); graded with check 3 as now written (strictly, 4/5: turn 4 asked again naming the digest of the text shown in full at turn 2). Earlier runs on the branch: 4/5 retyped and summarised previews, then 4/5 described a register call instead of the decorator; the procedure now asks for the code to be read and the preview pasted whole. Each run said the scan had no map yet, and one offered to finish the run first |
