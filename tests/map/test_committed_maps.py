"""The committed viewer fixture and demo map must stay valid under mapcheck."""
from pathlib import Path
import json

import pytest

from vizcode import mapcheck

SKILL = Path(__file__).resolve().parents[2]
MAPS = [SKILL / "viewer/test/fixtures/shop.code-map.json",
        SKILL / "demo/parking-city/docs/viz-code/code-map.json"]


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.name if "demo" not in str(p) else "demo")
def test_committed_map_is_valid(path):
    assert mapcheck.check(json.loads(path.read_text())) == []


def test_the_demo_page_is_built_from_the_current_viewer_and_map():
    """The demo's index.html is committed as a showcase (and published on the site): it must be what view.py
    writes today. After a viewer or demo-map change: `view.py demo/parking-city`."""
    import view
    out = SKILL / "demo/parking-city/docs/viz-code"
    page, _ = view.render((out / "code-map.json").read_text(encoding="utf-8"), view.VIEWER.read_text(encoding="utf-8"))
    assert (out / "index.html").read_text(encoding="utf-8") == view.with_header(page, "index.html"), \
        "demo/parking-city/docs/viz-code/index.html is stale: run scripts/view.py demo/parking-city"
