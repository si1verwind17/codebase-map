# Sending feedback

Read this when the user asks to send feedback on the skill: `send-feedback` after the skill's name, or in plain
words ("report this to the skill's maintainers"). Never start it yourself. `REPO`, `OUT`, `SKILL_DIR` and `PY` are
as in `SKILL.md`. It needs a scan in `OUT` (`structure.json` from step 1 at least): the text is checked against
the repository's names, and without a scan there is nothing to check against.

The feedback becomes a public GitHub issue. The user decides twice: first whether to go on, then on the exact text.
Nothing is posted by you: the last step opens GitHub's new-issue form, filled in, and the user submits it there.

1. **Say what will happen, before writing anything.** Tell the user, in these points:
   - **Where:** a new issue on https://github.com/si1verwind17/codebase-map, read by its maintainers to improve
     the skill.
   - **Your account:** it is posted from your own GitHub account, under your name, so anyone reading it sees who
     sent it and can link it to your employer.
   - **Public:** anyone can read it. Deleting it later does not undo copies already made.
   - **Your review:** a check catches names from this repository's map, but not every private detail (a
     customer's name, the business domain, logic a snippet shows). You read the whole text before it goes, and
     you are the last check.
   - **What goes in:** a title and a description you write together, in general terms; then map facts that
     `feedback.py` adds: the skill's versions, the operating system, the Python version, whether Node is
     installed, counts (files, modules, nodes and relations by kind, pins, examples, warnings by id, drawing check
     results), the languages, and the names of the skill's own patterns that matched.
   - **What never goes in:** code, file paths, the names of services, classes, methods, tables, topics, fields or
     config keys, example values, the repository's name or address, and the text of `map-notes.md`, `problems` or
     the audit's messages.
   - **How it is sent:** you open a filled-in form in their browser; it is posted only when they press Submit
     there.

   Ask whether to go on. On anything but yes, stop.
2. **Draft `OUT/feedback.md`:** a `# title` line, then what happened, what they expected, and how the code
   involved is shaped. Read that code first (and what `summary.md` says of it): the shape you describe must be the
   one in the code, with its real mechanism — a decorator, a base class, a registration call, the database call —
   never a guess. Describe the shape, never the code: "a consumer registered through a factory method is
   missing", not the class's name. Technical words (`decorator`, `INSERT`, the database library's name) are not
   private; names from the repository are. When the shape needs code, write a minimal made-up snippet in the same language
   with placeholder names and values (`Foo`, `handle`, `items`, `8080`, `"key"`): no port, number, string key or
   URL from the repository. Leave out the business domain, and anything the user calls confidential.
3. **Check it:** `$PY SKILL_DIR/scripts/feedback.py preview REPO --out-dir OUT`. It prints the whole issue,
   then the words that match a name from this repository's map (it exits 1 while any remain), then common words
   that are also names in the map (never blocking). Rewrite each matching word and preview again. A matching word
   that is a library's own call (its connect, execute, a decorator) is described in words ("the database library's
   connect and execute calls"), never renamed to a call the library does not have. After two
   rewrites with words still matching, stop rewriting: show the user those words and ask. A word stays only when
   the user, shown it, says it may go: add `--allow WORD` for it (the words as printed). Never allow one yourself.
4. **Show the issue and ask.** Paste the preview output from `Title:` to the end into your reply as a code block,
   unchanged and in full: never retype, reformat, summarise or cut it (no `head` or `sed` on the preview). When you
   ask again and the digest is one whose full text you already showed, you may say so instead ("the same text as
   above, digest …"); any other text is shown in full. Say the text above the `---` line is exactly what the form
   will hold, public and under their account, and point to any common words listed below it. Ask them to read all of it for anything private, then: "Open this as a GitHub issue?"
   Only a yes to this text counts: not the yes from step 1, not a yes to an earlier draft. After any change, go
   back to step 3.
5. **Open the form:** `$PY SKILL_DIR/scripts/feedback.py send REPO --out-dir OUT --digest DIGEST`, with the
   digest of the preview the user said yes to and the same `--allow` words. It refuses any other text. Never open
   or post the issue any other way (`gh`, a link you build, an API): when `send` refuses, fix the cause and go back
   to step 3. Tell the user the form is open, filled in, and that nothing is posted until they press Submit; they
   can still edit it there or close the tab. If no browser opened, give them the link it printed.

`OUT/feedback.md` is a working file, never committed. The `.gitignore` that `assemble.py` writes keeps it out of git;
before the first `assemble.py` there is none, so do not tell the user git ignores it.
