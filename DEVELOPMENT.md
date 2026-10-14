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

## Publishing

GitHub Pages deploys from the `pages` workflow (Settings → Pages → Source: GitHub Actions). It publishes the field
guide at `/` and the demo map at `/demo/`.
