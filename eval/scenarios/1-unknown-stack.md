# Scenario 1: unknown stack (skill arm only)

Can the agent work out a stack the packs do not know, from the code alone?

**Fixture:** two temp repos built from `tests/conftest.py` (at the repo root): `FLASK`
(as `shopfront`) and `HTTP4S` (as `users-service`), each `git init` + one
commit, **without** a `stack.yaml` (a one-off script under the scratch
directory imports the constants and writes them, as the `make_repo` fixture
does). Do not give the agent `FLASK_STACK` or `HTTP4S_STACK`.

**Prompt:** the shared one in [`eval/README.md`](../README.md), once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Stack resolved:** after the run, `summary.md` reads
   `## Stack — nothing unrecognised`.
2. **Routes found:** every route of the fixture test is in `structure.json`
   (method, path, handler): Flask, the 6 of `test_flask_routes_with_stack`
   (`GET`/`DELETE /users/{id}`, `POST /users`, `GET /users`, `GET /health`,
   `GET /ping`; its handler may be the file, or the view a `view_func` names);
   http4s, the 2 of `test_http4s_with_stack` (`GET /users/{id}`, `POST /users`).
3. **Honest groups:** no pattern matches a non-route line; Celery is in
   `imports` (`event`), `marshmallow` / `io.circe` in `ignore`, never the
   reverse.
4. **Reported:** `stack.yaml` holds the entries the run added and the transcript's last summary names any Stack
   line left unresolved (the prompt limits the reply to a path and counts, so grade this from the files).

A miss is a SKILL.md wording fix, not a test change.
