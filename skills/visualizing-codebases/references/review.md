# Review comments, pins from the viewer, map notes

Read this when `OUT/export-comment.md` or `OUT/map-notes.md` exists (SKILL.md § Run steps 2-3).

## Review comments

If `OUT/export-comment.md` exists, read it before anything else. It is review
feedback a person left on the map in the viewer: each block names a node or
the line between two nodes, its `file:line`, the map commit it was made on,
and what they want. Read the code a comment points at with
`git -C REPO show <map commit>:./<file>`. Act on every comment in the code,
say which ones you handled and which you could not (and why), and rescan so
the map matches the new code. Delete the file once the rescan has applied its
`## Pins` section (below), or as soon as you have read it when it has none. A
comment that questions the map rather than the code is answered in the map:
set the fact's `why` (and `deployment_dependent`) in `meaning.json`. Before
you reply, find every change you report in the rescanned `code-map.json`;
report only what is there. Why: the comment loop is how a reviewer steers an
agent without reading every file; a comment left unread, or a fix claimed but
not made, is a review that never happened.

A `## Pins` section, when present, holds the pins the user added and removed
in the viewer, one per line:

```
## Pins
- pin: <title> | start: <node id> | direction: <downstream|upstream|both>
- unpin: <pin id>
```

Apply each line to `meaning.json` whatever mode `diff.py` reports, `none`
included (after `diff.py` wrote it; on a full rescan, after you copied
`meaning.previous.json`), before you delete the file: a `pin:` line whose
start and direction match an agent pin turns that pin into the user's
(`by: user`, the line's title, its id that title as a slug); any other
`pin:` line becomes a `by: user` pin whose id is its title as a slug (the
next free `-2`, `-3` when the slug is taken, by a pin or in `unpinned`); an `unpin:` of an agent pin
deletes it and adds its id to `unpinned`; an `unpin:` of a user pin deletes
it; an `unpin:` naming no pin needs nothing. These lines change the map, not
the code. Report each line as applied.

## Map notes

`OUT/map-notes.md` is the user's standing notes on the map: committed, read
on every run, never edited by you. `export-comment.md` is different: it is
about the code and the pins, handled once, then deleted.

- Free-text notes: apply what the format can express — which deployables are
  services, excludes, a relation's `why` and `deployment_dependent`, a
  missing outside service. Anything else (a layout override) is "not
  supported yet". Name each note in the report as applied or not supported
  yet.
- Acceptances keep a map limit out of the count:
  `- accept <check id> <floor code or *>  — <reason>` (the reason is
  optional). `audit.md` prints the line to paste under each map limit.
