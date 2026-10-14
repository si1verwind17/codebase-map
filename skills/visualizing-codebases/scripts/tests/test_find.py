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
