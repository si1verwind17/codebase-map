# Development

## Layout

| Path | What it is |
|---|---|
| `skills/visualizing-codebases/` | The skill as installed: `SKILL.md`, `format.md`, the scanner (`scripts/`) and the built viewer (`viewer/dist/`) |
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
gitignored `viewer/.profile/` on the first run (about 100 s).

```
cd viewer && npm run build
VIZ_CHROMIUM=… npm run profile -- --runs 3                  # GPU drawing; add --throttle 4 for a slow machine,
                                                            # --picker to open the map through the file input,
                                                            # --map P for another map, --cpuprofile DIR for profiles
node scripts/profile-top.mjs DIR/run1-coldEntry.cpuprofile  # where the time went (--viewer: a --sourcemap build)
npx vitest bench --run test/perf --reporter=verbose          # the model and the floor planner alone, in node
```

`npm run profile` prints the median of each metric over the runs:

| Metric | What it measures | Baseline | Baseline, 4× throttle | After |
|---|---|---|---|---|
| `firstFrameMs` | page start to the first floor drawn | 327 | 1,151 | — |
| `parseMs` | `JSON.parse` of the map | 28 | 100 | — |
| `enterService.longTaskSumMs` | long tasks from entering the service until its nearby floors are planned | 2,336 | 10,959 | — |
| `enterService.longTaskMaxMs` | the longest of them | 996 | 4,039 | — |
| `enterService.settleMs` | entering the service until no floor waits to be planned | 3,594 | 12,259 | — |
| `coldEntry.floorMs` | Open sub-assembly on the busiest floor, not yet laid out, until it shows | 985 | 3,998 | — |
| `coldEntry.longestTaskMs` | the longest task from that press until the camera rests | 1,008 | 4,079 | — |
| `frameJsMs.idle` | script ms per frame, the service floor at rest | 4.0 | 5.1 | — |
| `frameJsMs.pan` | script ms per frame while panning it | 4.3 | 6.2 | — |
| `heapMB.load` | JS heap after load (after GC) | 21.1 | 21.3 | — |
| `heapMB.session` | JS heap after the session (after GC) | 57.9 | 57.8 | — |
| `heapMB.worker` | a layout worker's heap (none yet) | — | — | — |

The model bench on the same map (mean ms): `new Model` 4.7, `bundles` of the busiest floor 14.3 cold and 14.8 warm,
`doorShows` over its 15 doors 370, `planFloor` cold 509, `relationsOf` the service 0.8, `methodsIn` the service 30.5,
Find's seven keystrokes of "account" 17.

Baseline: 2026-10-21, commit `b3bf452`, Intel i7-14700F, NVIDIA RTX 5070 (Chromium on Vulkan; median of 3 runs).

Two pixel guards go with it: `npm run shots:compare` (Still motion) and `node scripts/motion-shots.mjs`, the demo
with motion on at fixed moments of a fake clock (drones, trains and smoke), `--compare <baseline-dir>` exiting 1 on
any differing pixel.

## Workflow

1. **Branch.** Work on a feature branch off `main`; commit there.
2. **Test.** `.venv/bin/python -m pytest -q tests`, and in `viewer/`: `npm run check`, then
   `VIZ_CHROMIUM=… npx vitest run`. Rebuild what the change touches (see *After a change*): the tests fail on a
   stale build, guide or demo page.
3. **Eval** only when agent behaviour changes: `SKILL.md`, `format.md`, the scanner or its packs. A viewer-only
   change skips it.
4. **Merge.** Squash the branch into `main` as one commit whose message says what changed and why. Delete the
   branch after checking it holds nothing the squash left out (`git diff <branch> main` is empty); it needs
   `git branch -D`, as a squash does not mark it merged.
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
