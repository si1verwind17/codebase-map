"""The synthetic big map the viewer is profiled on: valid, deterministic, and as busy where it counts as the maps
that showed the lag (a few range-group floors with thousands of relations inside)."""
import json
import os
import statistics

import pytest

import big_map
from vizcode import mapcheck


def test_small_map_passes_mapcheck():
    assert mapcheck.check(big_map.build(scale=0.02)) == []


def test_is_deterministic():
    a, b = big_map.build(scale=0.02), big_map.build(scale=0.02)
    assert json.dumps(a, indent=1) == json.dumps(b, indent=1)


def test_has_busy_floors():
    cmap = big_map.build(scale=0.05)
    inside = big_map.relations_inside(cmap)
    floors = sorted(inside.values())
    busiest = big_map.busiest_floor(cmap)
    assert inside[busiest] >= 10 * statistics.median(floors)
    floor = cmap["layout"]["containers"][busiest]
    assert busiest in cmap["layout"]["containers"]["svc:api"]["items"] or busiest.startswith("grp:svc:api")
    assert floor["items"] and (busiest.startswith("grp:") or busiest.endswith("/"))   # a group or a package floor


@pytest.mark.skipif(os.environ.get("VIZ_PERF") != "1", reason="the full-size map takes a while; VIZ_PERF=1 runs it")
def test_full_size_meets_targets():
    s = big_map.stats(big_map.build())
    assert 14_000 <= s["nodes"] <= 16_000
    assert 11_000 <= s["relations"] <= 13_000
    assert s["floors"] >= 3_000
    assert sum(1 for _, n in s["busiest"] if n >= 2_000) >= 3
