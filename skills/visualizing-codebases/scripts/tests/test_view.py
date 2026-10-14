import json

import assemble as assemble_cli
import extract
import view
from vizcode import readme
from meaning_fixture import MEANING

VIEWER = '<html><body><script id="code-map" type="application/json">/*CODE_MAP*/</script></body></html>'


def test_render_inlines_and_escapes_script_end():
    page, inlined = view.render('{"a": "</script><b>"}', VIEWER)
    assert inlined and "\\u003c/script>" in page and "</script><b>" not in page.split("/*")[0]
    assert page.count('<script id="code-map"') == 1


def test_render_leaves_big_maps_for_the_file_picker():
    page, inlined = view.render("x" * (view.INLINE_LIMIT + 1), VIEWER)
    assert not inlined and view.MARKER in page


def test_render_refuses_a_viewer_without_marker():
    try:
        view.render("{}", "<html></html>")
    except ValueError as e:
        assert "marker" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_view_cli_writes_index_html(shop_repo, tmp_path, monkeypatch, capsys):
    built = tmp_path / "viewer.html"
    built.write_text(VIEWER)
    monkeypatch.setattr(view, "VIEWER", built)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    assert view.main([str(shop_repo)]) == 0
    page = (out / "index.html").read_text()
    assert json.loads(page.split('application/json">')[1].split("</script>")[0])["meta"]["repo"] == "demo"
    ignored = (out / ".gitignore").read_text().split()
    assert "index.html" in ignored and "export-comment.md" in ignored
    assert "field-guide.html" in ignored


def test_view_cli_without_a_map(shop_repo, capsys):
    assert view.main([str(shop_repo)]) == 2
    assert "run assemble.py first" in capsys.readouterr().err


def test_assemble_writes_the_viewer_page_too(shop_repo, tmp_path, monkeypatch):
    """Benchmark 2026-10-04: 3/3 runs stopped after assemble.py and never ran view.py, so no index.html."""
    built = tmp_path / "viewer.html"
    built.write_text(VIEWER)
    monkeypatch.setattr(view, "VIEWER", built)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    page = (out / "index.html").read_text()
    assert '"repo": "demo"' in page or '"repo":"demo"' in page


def test_failed_assemble_writes_no_page(shop_repo, tmp_path, monkeypatch):
    built = tmp_path / "viewer.html"
    built.write_text(VIEWER)
    monkeypatch.setattr(view, "VIEWER", built)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps({**MEANING, "pins": [{"id": "x", "title": "x", "start": "svc:x", "direction": "sideways", "by": "agent"}]}))
    assert assemble_cli.main([str(shop_repo)]) == 1
    assert not (out / "index.html").exists()


def test_render_survives_comment_open_before_script():
    """`<!--<script` inside a JSON string switched the HTML parser to double-escaped state: blank page."""
    page, inlined = view.render('{"summary": "<!--<script> x", "b": "</script>"}', VIEWER)
    body = page.split('application/json">')[1].split("</script>")[0]
    assert "<" not in body
    assert json.loads(body)["summary"] == "<!--<script> x"


def test_assemble_without_a_viewer_keeps_the_map_and_says_so(shop_repo, tmp_path, monkeypatch, capsys):
    """A missing viewer is not a meaning.json error: exit 3, map written, the message names the page."""
    monkeypatch.setattr(view, "VIEWER", tmp_path / "missing.html")
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 3
    assert (out / "code-map.json").exists()
    assert "index.html not written" in capsys.readouterr().err


def test_view_copies_the_field_guide_beside_the_page(shop_repo, tmp_path, monkeypatch, capsys):
    built, guide = tmp_path / "viewer.html", tmp_path / "field-guide.html"
    built.write_text(VIEWER)
    guide.write_text("<html>guide</html>")
    monkeypatch.setattr(view, "VIEWER", built)
    monkeypatch.setattr(view, "GUIDE", guide)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0   # assemble goes through view.write_page
    assert (out / "field-guide.html").read_text() == "<html>guide</html>"
    guide.write_text("<html>newer</html>")
    assert view.main([str(shop_repo)]) == 0
    assert (out / "field-guide.html").read_text() == "<html>newer</html>"
    assert "not found" not in capsys.readouterr().out


def test_view_without_the_guide_still_writes_the_page(shop_repo, tmp_path, monkeypatch, capsys):
    built = tmp_path / "viewer.html"
    built.write_text(VIEWER)
    monkeypatch.setattr(view, "VIEWER", built)
    monkeypatch.setattr(view, "GUIDE", tmp_path / "missing" / "field-guide.html")
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    assert (out / "index.html").exists() and not (out / "field-guide.html").exists()
    said = capsys.readouterr().out
    assert said.count("field guide not found") == 1


def test_view_survives_a_guide_that_cannot_be_copied(shop_repo, tmp_path, monkeypatch, capsys):
    built, guide = tmp_path / "viewer.html", tmp_path / "field-guide.html"
    built.write_text(VIEWER)
    guide.write_text("<html>guide</html>")
    monkeypatch.setattr(view, "VIEWER", built)
    monkeypatch.setattr(view, "GUIDE", guide)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    (out / "field-guide.html").unlink()
    real = view.with_header

    def boom(page, file):
        if file == "field-guide.html":
            raise PermissionError("denied")
        return real(page, file)
    monkeypatch.setattr(view, "with_header", boom)
    capsys.readouterr()
    assert view.main([str(shop_repo)]) == 0
    assert "field guide not copied: denied" in capsys.readouterr().out
    assert (out / "index.html").exists()


def test_pages_carry_the_header_as_first_child_of_head(shop_repo, tmp_path, monkeypatch):
    built, guide = tmp_path / "viewer.html", tmp_path / "field-guide.html"
    built.write_text("<!doctype html><html><head>\n<meta charset=utf-8></head>" + VIEWER[6:])
    guide.write_text("<!doctype html><html><head>\n<title>g</title></head><body></body></html>")
    monkeypatch.setattr(view, "VIEWER", built)
    monkeypatch.setattr(view, "GUIDE", guide)
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    for name in ("index.html", "field-guide.html"):
        page = (out / name).read_text()
        assert page.split("<head>\n", 1)[1].startswith(readme.header(name) + "\n"), name
        assert page.count("Generated by the visualizing-codebases skill") == 1
