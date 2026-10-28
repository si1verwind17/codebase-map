# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's
[Report a vulnerability](https://github.com/si1verwind17/codebase-map/security/advisories/new) form, not in a public
issue. Say what is affected, how to reproduce it, and what an attacker gains.

## What is in scope

codebase-map reads repositories it did not write and draws them in a browser, so the content of a scanned repository
is untrusted input. In scope:

- **The viewer:** a map whose names, paths or comments run script or load remote content when the page is opened.
- **The scanner:** a scanned repository that makes the scripts in `skills/visualizing-codebases/scripts/` run its
  code, write outside the map's output, or read files beyond the repository.
- **The skill:** text in a scanned repository that steers the agent following `SKILL.md` into an action the skill
  does not ask for.

The demo under `demo/` is fictional and out of scope.
