# Scenario 4: a rescan with a changed type and pins from the viewer (skill arm only)

Does the agent rewrite stale examples and apply a `## Pins` export?

**Setup** (by the judge, on Scenario 3's repo after its run):

1. Commit the map as the agent left it (`git add -A && git commit -m map`; the working files stay ignored).
2. In the committed `docs/viz-code/code-map.json`, append a user pin to `pins`:
   `{"id": "overdue-check", "title": "overdue check", "start": "<the notices consumer's method id>", "direction": "upstream", "by": "user"}`;
   commit ("a user pin").
3. In `loans/loans/models.py` make `Loan.due_date` a `date` (`from datetime import date`; `due_date: date`) and add
   a field `renewals: int = 0` to `Loan`; commit ("due date is a date").
4. Write `docs/viz-code/export-comment.md` (not committed):

```
## Pins
- pin: member looks up a loan | start: <get_loan's method id> | direction: downstream
- unpin: <the id of the agent's first pin>
- unpin: overdue-check
```

**Prompt:** "Before starting, read `<skill path>/SKILL.md` and follow it as authoritative for how you work. Refresh
the code map of the repository at `<repo path>` (output `docs/viz-code`) for the latest commit. Do not commit."

**Checks** (PASS/FAIL):

1. **Stale found:** `stale.json` has mode `incremental` and `stale_examples` naming `Loan` and the entries of
   `open_loan` and `get_loan`.
2. **Rewritten:** `assemble.py` exited 0 (the map's commit is HEAD); `Loan`'s example value has a `renewals` number
   (the fingerprint alone would change on a flag clear); nothing in the map is `stale`.
3. **Pins applied:** a `by: user` pin `member-looks-up-a-loan` with that start and `downstream`, and no second pin
   with that start and direction (an agent pin there became the user's); the unpinned agent
   pin is gone from `pins` and listed in `unpinned`; `overdue-check` is gone and not in `unpinned`.
4. **Export handled:** `docs/viz-code/export-comment.md` is deleted.
5. **Reported:** the reply names each `## Pins` line as applied and the stale examples rewritten.

A miss is a SKILL.md wording fix, not a test change.
