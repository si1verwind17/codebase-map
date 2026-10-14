import copy

from meaning_fixture import MEANING

from vizcode import structure
from vizcode.assemble import assemble
from vizcode.roles import family, group_children


def built(repo, meaning=MEANING):
    return assemble(structure.build(repo, "docs/viz-code"), copy.deepcopy(meaning))


def test_package_roles_on_fixture(shop_repo):
    roles = {n["id"]: n.get("role") for n in built(shop_repo)["nodes"] if n["kind"] == "package"}
    assert roles["worker::worker/"] == "entry"                 # FastAPI routes
    assert roles["shop::io.demo.shop.api/"] == "entry"         # tapir routes
    assert roles["shop::io.demo.shop.repo/"] == "storage"      # Quill + SQL
    assert roles["worker::worker.util/"] == "logic"            # plain functions are not data
    assert roles["scripts::scripts/"] == "storage"             # psycopg import


def test_role_override_from_meaning(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["roles"] = {"worker::worker.util/": {"role": "model", "why": "formatting helpers only"}}
    node = next(n for n in built(shop_repo, meaning)["nodes"] if n["id"] == "worker::worker.util/")
    assert node["role"] == "model" and node["role_why"] == "formatting helpers only"


def test_family_names():
    assert [family(n) for n in ("Pricing13", "DiscountRuleV4", "PricingParams", "pricing.py", "Main$")] == \
        ["Pricing", "DiscountRule", "Pricing", "pricing", "Main"]


def test_grouping_a_crowded_floor():
    by_id = {f"c{i}": {"id": f"c{i}", "kind": "class", "name": n} for i, n in enumerate(
        [f"Exposure{k}" for k in range(1, 14)] + [f"Lots{k}" for k in range(1, 4)] +
        [f"Thing{k}Params" for k in range(5)] + [f"Unique{chr(65 + k)}x" for k in range(12)])}
    methods = {k: (0 if "Params" in v["name"] else 3) for k, v in by_id.items()}
    items, groups = group_children("pkg", sorted(by_id), by_id, methods)
    labels = sorted(g["label"] for g in groups)
    assert "data ×5" in labels and "Exposure ×13" in labels
    assert len(items) <= 24 and sum(len(g["members"]) for g in groups) + len(items) - len(groups) == len(by_id)
