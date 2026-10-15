# Meaning-rules changes

Only changes that can make facts on an existing map wrong or incomplete go here: a meaning rule in SKILL.md, or a new kind of fact to look for. Viewer, scanner and schema changes do not (the page refresh and the full rescan cover them).
Bump `RULES_VERSION` in `scripts/vizcode/__init__.py` with each new section; prune old sections from the bottom when the file passes about 10. The oldest section left is the floor: a map older than it gets a full meaning re-check.

## Rules 2 — 2026-10-15
- In-process queues (SKILL.md § In-process queues): where a trace stops at a put on a queue, channel or hub that a background task drains, add the `in-process-queue` node and its `hand-off` relations; clear each `queue.missing` warning.

## Rules 1 — 2026-10-13
- Baseline: nothing to re-check.
