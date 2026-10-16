import json
import urllib.parse

import pytest

import extract
import feedback
from conftest import ROOT
from helpers import scan

GENERIC = "# A route built from nested objects was missed\n\nA route whose path is built from nested objects is not drawn.\n"


@pytest.fixture
def mapped(shop_repo):
    scan(shop_repo)
    return shop_repo, shop_repo / "docs" / "viz-code"


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(feedback.webbrowser, "open", lambda url: urls.append(url) or True)
    return urls


def draft(out, text=GENERIC):
    out.mkdir(parents=True, exist_ok=True)
    (out / "feedback.md").write_text(text)


def digest_of(capsys):
    return next(ln.split()[1] for ln in capsys.readouterr().out.splitlines() if ln.startswith("Digest: "))


def test_facts_hold_no_name_from_the_map(mapped):
    repo, out = mapped
    draft(out)
    title, _, body = feedback.compose(out)
    assert feedback.leaks(title, body, feedback.private_terms(repo, out)[0], set()) == []   # the facts alone
    cmap = json.loads((out / "code-map.json").read_text())
    for n in cmap["nodes"]:
        if n["kind"] in ("service", "class", "table"):
            assert n["name"] not in body, n["name"]
    for path in cmap["files"]:
        assert path not in body
    assert "- nodes: " in body and "- relations: " in body and "- content warnings: " in body


def test_preview_flags_a_name_from_the_map(mapped, capsys):
    repo, out = mapped
    draft(out, "# PgOrderRepo is missing\n\nIts table write is not drawn.\n")
    assert feedback.main(["preview", str(repo)]) == 1
    printed = capsys.readouterr().out
    assert "- pgorderrepo (from " in printed and "\nTitle: [feedback] PgOrderRepo is missing\n" in printed


def test_whole_identifiers_are_matched(mapped):
    repo, out = mapped
    terms, _ = feedback.private_terms(repo, out)
    hits = dict(feedback.leaks("t", "the orders_table key and io.demo.shop.repo package", terms, set()))
    assert "io.demo.shop.repo" in hits


@pytest.mark.parametrize("said", ["the pg order repo writes", "Pg Order Repo", "pg-order repo"])
def test_a_name_split_into_words_is_matched(mapped, said):
    terms, _ = feedback.private_terms(*mapped)
    assert [w for w, _ in feedback.leaks("t", said, terms, set())] == ["order repo", "pg order repo"]


def test_an_allowed_phrase_passes(mapped):
    terms, _ = feedback.private_terms(*mapped)
    assert feedback.leaks("t", "Pg Order Repo", terms, {"pg order repo", "order repo"}) == []


def test_common_words_are_listed_but_do_not_block(mapped, capsys):
    repo, out = mapped
    terms, common = feedback.private_terms(repo, out)
    assert "orders" in common and "orders" not in terms
    draft(out, "# Orders are missing\n\nA route on orders is not drawn.\n")
    assert feedback.main(["preview", str(repo)]) == 0
    printed = capsys.readouterr().out
    assert "Common words that are also names" in printed and "- orders (from " in printed


def test_names_in_any_script_are_matched(tmp_path):
    out = tmp_path / "docs" / "viz-code"
    out.mkdir(parents=True)
    (out / "code-map.json").write_text(json.dumps({"nodes": [{"id": "svc:x", "name": "บริการชำระเงิน"}]}))
    terms, _ = feedback.private_terms(tmp_path, out)
    assert feedback.leaks("t", "ใน บริการชำระเงิน มีปัญหา", terms, set()) == [("บริการชำระเงิน", "บริการชำระเงิน")]


def test_allow_passes_a_word_the_user_accepted(mapped, capsys):
    repo, out = mapped
    draft(out, "# PgOrderRepo is missing\n\nIts table write is not drawn.\n")
    assert feedback.main(["preview", str(repo), "--allow", "PgOrderRepo"]) == 0


def test_send_needs_the_digest_of_the_previewed_text(mapped, capsys, opened):
    repo, out = mapped
    draft(out)
    assert feedback.main(["preview", str(repo)]) == 0
    d = digest_of(capsys)
    assert feedback.main(["send", str(repo)]) == 1
    draft(out, GENERIC + "One more line.\n")
    assert feedback.main(["send", str(repo), "--digest", d]) == 1
    assert opened == []
    draft(out)
    assert feedback.main(["send", str(repo), "--digest", d]) == 0
    q = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)
    assert opened[0].startswith(feedback.ISSUES + "?")
    assert q["template"] == ["send-feedback.yml"]
    assert q["title"] == ["[feedback] A route built from nested objects was missed"]
    assert q["report"] == ["A route whose path is built from nested objects is not drawn."]
    assert q["facts"][0].startswith("- skill: scanner ")


def test_the_form_has_the_fields_the_link_fills():
    form = (ROOT / ".github" / "ISSUE_TEMPLATE" / feedback.TEMPLATE).read_text()
    assert "labels: [skill-feedback]" in form
    for fid, label in feedback.FIELDS:
        assert f"id: {fid}\n" in form and f"label: {label}\n" in form


def test_send_refuses_a_name_from_the_map(mapped, capsys, opened):
    repo, out = mapped
    draft(out, "# PgOrderRepo is missing\n\nIts table write is not drawn.\n")
    feedback.main(["preview", str(repo)])
    assert feedback.main(["send", str(repo), "--digest", digest_of(capsys)]) == 1
    assert opened == []


def test_too_long_is_refused(mapped, capsys, opened):
    repo, out = mapped
    draft(out, "# Long\n\n" + "word " * 3000)
    assert feedback.main(["preview", str(repo)]) == 1
    assert feedback.main(["send", str(repo), "--digest", digest_of(capsys)]) == 1
    assert opened == []


def test_without_a_scan_nothing_goes(shop_repo, capsys):
    draft(shop_repo / "docs" / "viz-code")
    assert feedback.main(["preview", str(shop_repo)]) == 2
    assert "no scan in " in capsys.readouterr().err


def test_with_a_scan_and_no_map_only_versions_and_scan_counts_go(shop_repo):
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    draft(out)
    _, _, body = feedback.compose(out)
    assert "- map: none yet (scanned, not assembled)" in body and "- skill: scanner " in body


def test_committed_paths_and_scanner_facts_are_names(shop_repo):
    extract.main([str(shop_repo)])
    terms, _ = feedback.private_terms(shop_repo, shop_repo / "docs" / "viz-code")
    assert "shop/src/main/scala/io/demo/shop/repo/orderrepo.scala" in terms   # a committed path
    assert "pgorderrepo" in terms and "orders_table" in terms   # a class and a config key, before any map


def test_the_facts_are_not_checked(mapped, capsys):
    repo, out = mapped
    draft(out, "# Something was missed\n\nSomething is not drawn.\n")
    assert feedback.main(["preview", str(repo)]) == 0
    printed = capsys.readouterr().out
    assert "Common words" not in printed and "- relations: " in printed


@pytest.mark.parametrize("text", ["", "no title\n\ntext", "# Title only\n"])
def test_a_draft_needs_a_title_and_text(mapped, text, capsys):
    repo, out = mapped
    draft(out, text)
    assert feedback.main(["preview", str(repo)]) == 2


def test_missing_draft(mapped, capsys):
    assert feedback.main(["preview", str(mapped[0])]) == 2
    assert "feedback.md not found" in capsys.readouterr().err


def test_words_of_library_calls_do_not_block(tmp_path):
    out = tmp_path / "docs" / "viz-code"
    out.mkdir(parents=True)
    (out / "structure.json").write_text(json.dumps({"facts": {"a.py": {
        "calls": [{"callee": "conn.execute"}], "sql": [{"writes": ["acme_ledger"]}]}}}))
    terms, common = feedback.private_terms(tmp_path, out)
    assert "execute" in common and "execute" not in terms
    assert "acme_ledger" in terms and "ledger" in terms
