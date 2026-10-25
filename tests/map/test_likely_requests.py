"""summary.md § Likely requests pairs client calls with the repo routes and rpc servers they likely reach, and the
audit's `request.unmatched` names a paired call whose method starts no request."""
from vizcode import mapcheck, structure

FILES = {
    "package.json": '{"name": "web"}\n',
    "web/api.ts": "import axios from 'axios'\n\nexport function cart(id: string) {\n  return axios.get('/api/cart/' + id)\n}\n"
                  "export function ping() {\n  return axios.get('/elsewhere/x')\n}\n",
    "cart/requirements.txt": "flask\n", "cart/app/__init__.py": "",
    "cart/app/views.py": "from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.route('/cart/<cid>')\ndef show(cid):\n"
                         "    return cid\n",
}


def test_a_client_call_is_paired_with_the_route_it_reaches_by_suffix(make_repo):
    s = structure.build(make_repo(FILES))
    md = structure.summary_md(s)
    section = md.split("## Likely requests — ", 1)[1].split("\n## ", 1)[0]
    assert section.startswith("1\n")
    assert "- GET /api/cart/{id} ← " in section and "→ `GET /cart/{cid}` → cart/app::app.views#show/1" in section
    assert "by suffix" in section and "/elsewhere/x" not in section


def test_request_unmatched_until_a_request_starts_at_the_caller(make_repo):
    s = structure.build(make_repo(FILES))
    md = structure.summary_md(s)
    caller = next(c["in"] for c in s["facts"]["web/api.ts"]["clients"] if c["path"].startswith("/api/cart"))
    cmap = {"nodes": [], "relations": [], "problems": []}
    assert [w["node"] for w in mapcheck.warnings(cmap, md) if w["id"] == "request.unmatched"] == [caller]
    cmap["relations"] = [{"kind": "request", "from": caller, "to": "cart/app::app.views#show/1"}]
    assert [w for w in mapcheck.warnings(cmap, md) if w["id"] == "request.unmatched"] == []
    cmap = {"nodes": [], "relations": [], "problems": [{"text": f"{caller} only runs in tests"}]}
    assert [w for w in mapcheck.warnings(cmap, md) if w["id"] == "request.unmatched"] == []


def test_a_star_segment_matches_one_segment():
    assert structure._reaches(structure._route_shape("/owners/{ownerId}/pets/{petId}"),
                              structure._route_shape("/owners/*/pets/{petId}")) == "exact"
    assert structure._reaches(structure._route_shape("/owners/7/x/pets/{petId}"),
                              structure._route_shape("/owners/*/pets/{petId}")) is None
