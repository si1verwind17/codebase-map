"""Pins (format.md § Pins): the slug rule and the shape checks assemble.py makes before assembling."""
import pytest

from vizcode import pins


def pin(**over):
    return {"id": "driver-reserves-a-bay", "title": "driver reserves a bay", "start": "svc:x",
            "direction": "downstream", "by": "agent", **over}


@pytest.mark.parametrize("title, want", [
    ("driver reserves a bay, billing charges it", "driver-reserves-a-bay-billing-charges-it"),
    ("Stripe  payment / result", "stripe-payment-result"),
    ("v2 → orders", "v2-orders"),
    ("???", "pin"),
])
def test_slug(title, want):
    assert pins.slug(title) == want


def test_valid_pins_pass():
    assert pins.errors({"pins": [pin(), pin(id="driver-reserves-a-bay-2", by="user", direction="both")],
                        "unpinned": ["old-pin"]}) == []


def test_missing_fields_are_named():
    assert pins.errors({"pins": [{"id": "a", "title": "a"}]}) == ["pin 1: missing start, direction, by"]
    assert pins.errors({"pins": ["a"]}) == ["pin 1: must be an object {id, title, start, direction, by}"]


def test_direction_and_by_are_checked():
    errs = pins.errors({"pins": [pin(direction="sideways", by="robot")]})
    assert errs == ["pin driver-reserves-a-bay: direction 'sideways' is not one of downstream, upstream, both",
                    "pin driver-reserves-a-bay: by 'robot' is not agent or user"]


def test_an_id_that_is_not_a_slug_gets_the_slug_suggested():
    (err,) = pins.errors({"pins": [pin(id="Driver Reserves")]})
    assert err.startswith("pin Driver Reserves: id is not the slug of its title — use 'driver-reserves-a-bay'")


def test_an_id_that_is_a_slug_of_another_title_is_refused():
    (err,) = pins.errors({"pins": [pin(id="driver-reserves")]})
    assert err.startswith("pin driver-reserves: id is not the slug of its title — use 'driver-reserves-a-bay'")


def test_a_numbered_suffix_is_accepted():
    assert pins.errors({"pins": [pin(id="driver-reserves-a-bay-2")]}) == []


def test_duplicate_ids_are_refused():
    (err,) = pins.errors({"pins": [pin(), pin()]})
    assert err.startswith("pin driver-reserves-a-bay: duplicate id (pins 1 and 2)")


def test_a_retired_id_is_refused():
    (err,) = pins.errors({"pins": [pin(by="user")], "unpinned": ["driver-reserves-a-bay"]})
    assert err.startswith("pin driver-reserves-a-bay: the id is in unpinned")
    assert "next free suffix" in err


def test_unpinned_holds_ids():
    assert pins.errors({"pins": [], "unpinned": ["ok", 3, ""]}) == [
        "unpinned 2: must be a pin id (a string)", "unpinned 3: must be a pin id (a string)"]


def test_a_pin_may_start_at_any_node_kind_the_viewer_traces_and_no_other():
    kinds = ["method", "table", "topic", "in-process-queue", "external", "datastore", "service", "library", "package", "file", "class"]
    cmap = {"nodes": [{"id": f"n:{k}", "kind": k} for k in kinds] + [{"id": "n:widget", "kind": "widget"}],
            "pins": [pin(id=f"p-{k}", start=f"n:{k}") for k in kinds]
            + [pin(id="w", start="n:widget"), pin(id="gone", start="n:gone")]}
    assert pins.start_errors(cmap) == [
        "pin w: start n:widget is a widget, which the viewer cannot trace from — start at a method, table, topic, "
        "in-process-queue, external, datastore, service, library, package, file or class"]
