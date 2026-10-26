from vizcode.layout.lanes import crossings, pick_lanes


def test_crossings_counts_proper_intersections_only():
    pos = {"a": (0, 0), "b": (2, 2), "c": (0, 2), "d": (2, 0), "e": (4, 0)}
    assert crossings(pos, [("a", "b"), ("c", "d")]) == 1          # an X
    assert crossings(pos, [("a", "b"), ("b", "e")]) == 0          # sharing an end is not a crossing


def _side_hub_floor():
    """A hub at the top right, called from the bottom row, with a chain of work in between: every belt to
    the hub cuts across the chain; taps down to a lane cut nothing."""
    pos = {"hub": (4, 0)}
    pos.update({f"c{k}": (k, 3) for k in range(4)})
    pos.update({f"r{k}": (k + 0.5, 1.5) for k in range(4)})
    edges = [(f"c{k}", "hub") for k in range(4)] + [(f"r{k}", f"r{k + 1}") for k in range(3)] + [("r0", "c0"), ("r3", "c3")]
    return pos, edges


def test_a_lane_that_would_add_crossings_is_refused():
    """A hub in the middle: its belts radiate without crossing, taps would cut the chain."""
    pos = {f"n{c}{r}": (c, r) for c in range(3) for r in range(3) if (c, r) != (1, 1)}
    pos["hub"] = (1, 1)
    edges = [(k, "hub") for k in pos if k != "hub"] + [("n00", "n22"), ("n20", "n02"), ("n10", "n12"), ("n01", "n21")]
    assert pick_lanes(pos, edges) == []


def test_a_busy_item_becomes_a_lane_when_that_clearly_cuts_crossings():
    pos, edges = _side_hub_floor()
    assert pick_lanes(pos, edges) == ["hub"]


def test_no_lane_when_it_would_not_help():
    pos = {"a": (0, 0), "b": (1, 0), "c": (2, 0), "hub": (3, 0)}
    edges = [("a", "hub"), ("b", "hub"), ("c", "hub")]              # all on one row: nothing crosses
    assert pick_lanes(pos, edges) == []


def test_at_most_two_lanes_and_sticky_ones_stay():
    pos, edges = _side_hub_floor()
    assert len(pick_lanes(pos, edges, cap=2)) <= 2
    pos2 = {"a": (0, 0), "b": (1, 0), "c": (2, 0), "hub": (3, 0)}
    edges2 = [("a", "hub"), ("b", "hub"), ("c", "hub")]
    assert pick_lanes(pos2, edges2, sticky={"hub"}) == ["hub"]      # kept from the last map while it still has callers


def test_layout_puts_a_picked_item_on_its_own_lane(shop_repo, monkeypatch):
    import copy
    from meaning_fixture import MEANING
    from vizcode.layout import layout as layout_mod
    from vizcode.map import mapcheck
    from vizcode.scan import structure
    from vizcode.map.assemble import assemble
    picked = []

    def fake_pick(pos, edges, sticky=frozenset(), cap=2, too_busy=None, eligible=None):
        if "shop::io.demo.shop.repo/" in pos:
            picked.append(True)
            return ["shop::io.demo.shop.repo/"]
        return []
    monkeypatch.setattr(layout_mod, "pick_lanes", fake_pick)
    meaning = copy.deepcopy(MEANING)
    meaning["roles"] = {"shop::io.demo.shop.repo/": {"role": "logic", "why": "test: keep it on the line"}}
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), meaning)
    floor = cmap["layout"]["containers"]["svc:shop"]
    assert picked and floor["items"]["shop::io.demo.shop.repo/"]["region"] == "lane"
    assert {"id": "shop::io.demo.shop.repo/", "row": 0} in floor["lanes"]
    assert mapcheck.check(cmap) == []


def test_a_lane_item_without_its_lane_is_refused(shop_repo):
    from meaning_fixture import MEANING
    import copy
    from vizcode.map import mapcheck
    from vizcode.scan import structure
    from vizcode.map.assemble import assemble
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    floor = cmap["layout"]["containers"]["svc:shop"]
    item = next(iter(floor["items"]))
    floor["items"][item] = {"region": "lane", "col": 0, "row": 7}
    assert any(item in e and "lane" in e for e in mapcheck.check(cmap))


def test_lanes_keep_their_order_and_rows_on_a_rescan():
    from vizcode.layout.layout import _lift_busy
    # two lanes, the busier one (zhub) sorting last: picked busiest-first, so sticky order must not re-sort
    pos = {"zhub": (6, 0), "ahub": (6, 1)}
    pos.update({f"c{k}": (k, 4) for k in range(5)})
    pos.update({f"d{k}": (k + 0.3, 5) for k in range(4)})
    pos.update({f"r{k}": (k + 0.5, 2.5) for k in range(5)})
    edges = [(f"c{k}", "zhub") for k in range(5)] + [(f"d{k}", "ahub") for k in range(4)] + \
        [(f"r{k}", f"r{k + 1}") for k in range(4)] + [("r0", "c0"), ("r4", "c4")]
    items = {k: {"region": "line", "col": c, "row": r} for k, (c, r) in pos.items()}
    first = _lift_busy(dict(items), edges, None, None)
    assert [l["id"] for l in first] == ["zhub", "ahub"]
    prev = {"lanes": first, "items": {l["id"]: {"region": "lane", "col": 0, "row": l["row"]} for l in first}}
    again_items = dict(items)
    again = _lift_busy(again_items, edges, prev, None)
    assert again == first
    for l in again:
        assert again_items[l["id"]]["row"] == l["row"]
