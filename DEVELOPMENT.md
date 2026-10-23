# Development

## Layout

| Path | What it is |
|---|---|
| `skills/visualizing-codebases/` | The skill as installed: `SKILL.md`, `format.md`, `references/` (detail a step of `SKILL.md` opens only when it applies), the scanner (`scripts/`) and the built viewer (`viewer/dist/`) |
| `viewer/` | The viewer's source (Svelte, PixiJS), its tests, and the field guide's source |
| `tests/` | The scanner's tests, grouped by area |
| `demo/parking-city/` | A fictional city parking network and its map, page included: a showcase for people. Agents never read it |
| `eval/` | Agent evaluations: the shared protocol, one file per scenario, the latest results |
| `docs/` | The field guide, and the README's pictures (`docs/images/`) |
| `tools/` | Repository scripts: `lint.py` (manifests and skill frontmatter), `release.py` (version bump, tag, release) |

## Set up

```
python3 -m venv .venv && .venv/bin/pip install -r skills/visualizing-codebases/scripts/requirements.txt
.venv/bin/python -m pytest -q tests
cd viewer && npm ci && npm run build && npx vitest run
```

Browser tests and the field guide build need a Chromium or Google Chrome: set `VIZ_CHROMIUM` to its
executable. Without it, the browser tests are skipped. Typical paths:

| System | `VIZ_CHROMIUM` |
|---|---|
| Linux | `/usr/bin/chromium` (or `/usr/bin/google-chrome`) |
| macOS | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| Windows | `C:\Program Files\Google\Chrome\Application\chrome.exe` |

The commands below write `VIZ_CHROMIUM=…` for that path.

## After a change

- **Viewer:** `npm run build` in `viewer/` writes `skills/visualizing-codebases/viewer/dist/`. Then rebuild:
  - the field guide: `VIZ_CHROMIUM=… npm run guide`, which writes `docs/field-guide.html`
  - the demo page: `.venv/bin/python skills/visualizing-codebases/scripts/view.py demo/parking-city`

  The tests fail when the audit build, the guide or the demo page are stale.
- **A meaning rule in SKILL.md** that can change facts on existing maps: add a section to
  [`CHANGES.md`](skills/visualizing-codebases/CHANGES.md) and bump `RULES_VERSION` (see that file).
- **Agent behaviour:** run the scenarios in [`eval/`](eval/README.md) that the change touches and update the
  latest results there.

## Profiling

How fast the viewer is on a big map: load, entering the busiest service, entering its busiest floor before it is laid
out, the script cost of each frame, and the heap. It runs on a synthetic map, `viewer/scripts/big_map.py`: one service
of 300 packages with three hot runs of packages whose range-group floors hold over 2,000 relations each (15k nodes,
12k relations, 3,341 floors, made by the skill's own `assemble`). The map is deterministic and written to the
gitignored `viewer/.profile/` on the first run (about 100 s), with the repo's `.venv` Python (`VIZ_PYTHON=…` for
another).

```
cd viewer && npm run build
VIZ_CHROMIUM=… npm run profile -- --runs 3                  # GPU drawing (Vulkan); --swiftshader on a machine without
                                                            # a GPU; --throttle 4 for a slow machine, --picker to open
                                                            # the map through the file input, --map P for another map,
                                                            # --cpuprofile DIR for profiles
node scripts/profile-top.mjs DIR/run1-coldEntry.cpuprofile  # where the time went
npx vitest bench --run test/perf --reporter=verbose          # the model and the floor planner alone, in node
```

`profile-top` names functions by source file and line when the profile was taken on a build with source maps:

```
npx vite build --sourcemap --minify false --outDir D
npm run profile -- --viewer D/index.html --cpuprofile DIR
node scripts/profile-top.mjs DIR/run1-coldEntry.cpuprofile --viewer D/index.html
```

`npm run profile` prints the median of each metric over the runs:

| Metric | What it measures | Baseline | Baseline, 4× throttle | After | After, 4× throttle |
|---|---|---|---|---|---|
| `firstFrameMs` | page start to the first floor drawn | 327 | 1,151 | 288 | 1,012 |
| `parseMs` | `JSON.parse` of the map | 28 | 100 | 28 | 99 |
| `enterService.longTaskSumMs` | long tasks from pressing Open on the service until its nearby floors are planned | 2,336 | 10,959 | 0 | 446 |
| `enterService.longTaskMaxMs` | the longest of them | 996 | 4,039 | 0 | 146 |
| `enterService.settleMs` | entering the service until no floor waits to be planned | 3,594 | 12,259 | 2,134 | 2,394 |
| `coldEntry.floorMs` | Open sub-assembly on the busiest floor, not yet laid out, until it shows | 985 | 3,998 | 596 | 739 |
| `coldEntry.longestTaskMs` | the longest task from that press until the camera rests | 1,008 | 4,079 | 55 | 205 |
| `frameJsMs.idle` | script ms per frame, the service floor at rest | 4.0 | 5.1 | 2.0 | 2.1 |
| `frameJsMs.pan` | script ms per frame while panning it | 4.3 | 6.2 | 3.7 | 4.1 |
| `heapMB.load` | JS heap after load (after GC) | 21.1 | 21.3 | 22.3 | 22.3 |
| `heapMB.session` | JS heap after the session (after GC) | 57.9 | 57.8 | 61.1 | 61.1 |
| `heapMB.worker` | the layout worker's heap (none before the worker) | — | — | 16.0 | 15.9 |

Baseline: 2026-10-21, commit `b3bf452`, a desktop with a GPU, median of 3 runs. The numbers depend on the machine:
compare a change only with a run of its base made on the same machine, back to back. The baseline model bench on the
same map (mean ms): `new Model` 4.7, `bundles` of the busiest floor 14.3 cold and 14.8 warm, `doorShows` over its 15
doors 370, `planFloor` cold 509, `relationsOf` the service 0.8, `methodsIn` the service 30.5, Find's seven keystrokes
of "account" 17.

After: 2026-10-21, with the big-map fixes released in 1.2.0, same machine, median of 3 runs. The model bench:
`new Model` 5.0, `bundles` cold 14.7 and warm under 0.001 (cached), `doorShows` over 15 doors 51, `planFloor` cold 509
(the planner itself was not touched), `relationsOf` 0.007, `methodsIn` 3.7, Find's seven keystrokes 4.8. `--picker`
gives the same within noise, except `firstFrameMs` 183 as the file path skips the inlined page. `frameJsMs` is noisy
(runs differ by up to 2× on the same code), so differences under about 1 ms there are inside the noise. The layout
worker's own heap (16 MB) comes on top of the main thread's. The model's indexes, and the bundles and door landings
warmed for the nearby floors, put the main thread about 1.2 MB above the baseline after load and 3.2 MB after the
session. `heapMB.session` is bounded, but the cache of 50 plans never evicts in this session (it visits fewer floors),
so that bound is the cache size, not something the profile shows.

What each fix bought, applied in this order (medians of 3):
- Layout in a Web Worker: the longest task on entering the service fell from 996 to 116 ms, on a cold floor from
  1,008 to 433 ms.
- Model caches and indexes: a cold floor took 999 → 634 ms to show, and its longest task fell from 433 to 90 ms.
- Moving parts and smoke in their own render groups: `frameJsMs` idle 5.3 → 2.0, pan 5.4 → 3.3 (measured back to
  back).
- Names, search and the trace graph on demand, a plan cache of 50, the map inlined minified: the big page
  13.0 → 10.0 MB, the demo page 5.9 % smaller.
- The page's own model warmed in idle time: the worker's model cannot share its caches, so each floor's bundles and
  door landings are worked out on the page too, one floor per idle slice after the worker plans it and while a floor
  change waits for its plan. Entering the service: longest task 90 → 0 (none over 50 ms); a cold floor 93 → 55 ms.
  The harness also changed here: it used to select the item and press Open in one task, which put the selection's
  ~20 ms into the entry; it now presses one task later, as a real click would.
`firstFrameMs` did not change by design (288 against 327 is within the run-to-run spread of this metric).

Known limit: the target was every long task under 50 ms on entry. Entering the service meets it at 1× (it misses at
4×, 146 ms). A cold floor misses it, 55 ms at 1× and 205 ms at 4×: what remains is the first draw of a 300-package
floor, about 40–45 ms (`paintLines` and building Pixi `Graphics`), with Pixi's first render of the new floor as a
separate task of similar size. Closing it is drawing work: drawing a floor's lines in slices, or fewer `Graphics`.

Two pixel guards go with it: `npm run shots:compare <dir>` (Still motion) and `node scripts/motion-shots.mjs`, the demo
with motion on at fixed moments of a fake clock (drones, trains and smoke), `--compare <dir>` exiting 1 on any
differing pixel. Make each baseline on the base commit first, after `npm run build`: `node scripts/shotset.mjs <dir>`
and `node scripts/motion-shots.mjs <dir>`.

## Workflow

1. **Branch.** Work on a feature branch off `main`; commit there.
2. **Test.** `.venv/bin/python -m pytest -q tests`, and in `viewer/`: `npm run check`, then
   `VIZ_CHROMIUM=… npx vitest run`. Rebuild what the change touches (see *After a change*): the tests fail on a
   stale build, guide or demo page.
3. **Eval** only when agent behaviour changes: `SKILL.md`, `format.md`, the scanner or its packs. A viewer-only
   change skips it.
4. **Merge.** Land the branch on `main` as one commit per independent change, each message saying what changed and
   why. Fold review fixes and other follow-ups into the change they fix. A branch with one change lands as one squashed
   commit; one with several (say, a worker and a cache) lands as several, so a later bisect or revert can single one
   out. Messages and docs name the change itself, never the branch or a plan's task numbers: neither outlives the
   merge. Delete the branch after checking it holds nothing the merge left out (`git diff <branch> main` is empty);
   it needs `git branch -D`, as the rebuilt commits do not mark it merged.
5. **Release.** On a clean `main`, bump the version by what the release brings (semver):

   ```
   tools/release.py 1.2.0 "what it brings"          # bumps marketplace.json, commits, tags v1.2.0; pushes nothing
   tools/release.py 1.2.0 "what it brings" --push   # then: pushes main and the tag, creates the GitHub release
   ```

   The version in `marketplace.json` is what installs pin to: Claude Code updates a plugin only when it changes.
   So a change that leaves the installed skill as it was (docs, tests, `tools/`, `eval/`, the demo) merges with
   no release.

## Publishing

GitHub Pages deploys from the `pages` workflow (Settings → Pages → Source: GitHub Actions). It publishes the field
guide at `/` and the demo map at `/demo/`.
