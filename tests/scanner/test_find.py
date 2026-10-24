import extract
import find


def test_find_prints_ids_with_signatures(shop_repo, capsys):
    extract.main([str(shop_repo)])
    capsys.readouterr()
    structure = shop_repo / "docs" / "viz-code" / "structure.json"
    assert find.main([str(structure), "Job#store", "--kind", "method"]) == 0
    assert capsys.readouterr().out == \
        "worker::worker.main.Job#store/3  worker/main.py:26  (conn, *args, **kw) -> None\n"
    assert find.main([str(structure), "nothing-like-this"]) == 1


def test_the_node_named_like_the_text_comes_before_the_limit(tmp_path, capsys):
    import json
    nodes = [{"id": f"m::a.Dispatcher{i}Helper", "kind": "class", "name": f"Dispatcher{i}Helper"} for i in range(40)]
    nodes.append({"id": "m::a.Dispatcher", "kind": "class", "name": "Dispatcher"})
    (tmp_path / "s.json").write_text(json.dumps({"nodes": nodes}))
    assert find.main([str(tmp_path / "s.json"), "Dispatcher", "--limit", "3"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("m::a.Dispatcher  ") and out[-1] == "... 38 more"
