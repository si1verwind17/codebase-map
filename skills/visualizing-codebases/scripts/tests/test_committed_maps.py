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
