"""Final-review fixes of the new languages: per-file crash guard, Rust src/bin, non-empty Stack prefixes,
BOM build files, posix paths, root node_modules, Rust `Self::`, Python's own name scope."""
import json
import re
from pathlib import Path

from conftest import with_stack

from vizcode import stack, structure
from vizcode.assemble import assemble


def unrec(s) -> set[tuple[str, str]]:
    return {(u["lang"], u["prefix"]) for u in s["stack"]["unrecognised"]}


# --- 1. a crash on one file never stops a scan ------------------------------------------------------------

class Boom:
    def parse(self, *a, **k):
        raise ValueError("bad tree " + "x" * 300)


def test_a_parser_crash_skips_the_file_and_the_scan_goes_on(make_repo, monkeypatch):
    repo = make_repo({"go.mod": "module shop\n", "a.go": "package shop\nfunc A() {}\n",
                      "app/__init__.py": "", "app/x.py": "def f():\n    pass\n"})
    monkeypatch.setitem(structure.LANGS, ".go", ("go", Boom()))
    s = structure.build(repo, "docs/viz-code")
    assert "a.go" not in s["files"] and "app/x.py" in s["files"]
    skip = next(x for x in s["skipped"] if x["file"] == "a.go")
    assert skip["reason"].startswith("parser failed: ValueError: bad tree") and len(skip["reason"]) == 200
    assert "a.go" in structure.summary_md(s).split("Skipped files:", 1)[1]


def test_a_pattern_crash_skips_the_file_too(make_repo, monkeypatch):
    repo = make_repo({"go.mod": "module shop\n", "a.go": "package shop\nfunc A() {}\n", "b.go": "package shop\n"})

    def boom(st, lang, data, r, module, imports):
        if r["nodes"]:
            raise KeyError("k")
        return []
    monkeypatch.setattr(structure, "_pattern_tables", boom)
    s = structure.build(repo, "docs/viz-code")
    assert list(s["files"]) == ["b.go"]
    assert {"file": "a.go", "reason": "parser failed: KeyError: 'k'"} in s["skipped"]


# --- 2. Cargo's extra binaries ----------------------------------------------------------------------------

def test_rust_src_bin_is_scanned(make_repo):
    s = structure.build(make_repo({"Cargo.toml": '[package]\nname = "a"\n', "src/bin/server.rs": "fn main() {}\n",
                                   "crates/api/Cargo.toml": '[package]\nname = "api"\n',
                                   "crates/api/src/bin/worker.rs": "fn main() {}\n",
                                   "tools/bin/x.go": "package x\n", "bin/y.ts": "export const y = 1\n"}))
    assert {"src/bin/server.rs", "crates/api/src/bin/worker.rs"} <= set(s["files"])
    assert {"tools/bin/x.go", "bin/y.ts"} <= set(s["excluded"])


# --- 3. every Stack prefix names something and can be cleared ---------------------------------------------

def test_prefix_drops_a_leading_separator():
    assert stack._prefix("rust", "::serde::Deserialize") == "serde"
    assert stack._prefix("php", "\\Foo\\Bar\\Baz") == "Foo\\Bar"
    assert stack._prefix("rust", "tokio::sync") == "tokio"


MIXED = {
    "Cargo.toml": '[package]\nname = "a"\n',
    "src/main.rs": "use ::dashmap::DashMap;\nuse ::smallvec::SmallVec;\nuse tokio::sync;\nfn main() {}\n",
    "web/package.json": "{}",
    "web/main.ts": "import x from '/src/main'\nimport y from '/vendor.js'\nimport z from 'lodash/fp'\n"
                   "import w from '@scope/pkg/x'\nexport const a = 1\n",
    "go.mod": "module shop\n",
    "x.go": 'package shop\nimport "github.com/jackc/pgx/v5"\n',
    "composer.json": "{}",
    "A.php": "<?php\nnamespace App;\nuse \\Brick\\Math\\X;\nclass A {}\n",
    "Gemfile": "",
    "a.rb": "require 'sidekiq/web'\n",
}


def test_absolute_ts_import_is_the_repos_own(make_repo):
    s = structure.build(make_repo(MIXED), "docs/viz-code")
    got = unrec(s)
    assert ("rust", "dashmap") in got and ("rust", "smallvec") in got
    assert not any(p in ("", "src", "vendor.js") or p.startswith("/") for _, p in got), got


def test_every_listed_prefix_clears_its_line_when_ignored(make_repo):
    repo = make_repo(MIXED)
    s = structure.build(repo, "docs/viz-code")
    listed = s["stack"]["unrecognised"]
    assert listed and all(u["prefix"] for u in listed)
    by_lang: dict[str, list[str]] = {}
    for u in listed:
        by_lang.setdefault(u["lang"], []).append(u["prefix"])
    with_stack(repo, "".join(f"{lang}:\n  ignore: {json.dumps(ps)}\n" for lang, ps in by_lang.items()))
    assert structure.build(repo, "docs/viz-code")["stack"]["unrecognised"] == []


# --- 4. Windows: BOM build files, posix paths -------------------------------------------------------------

def test_bom_package_json_and_go_mod(tmp_path):
    from vizcode.modules import detect_modules, names_from_build_files
    bom = b"\xef\xbb\xbf"
    (tmp_path / "packages/a").mkdir(parents=True)
    (tmp_path / "package.json").write_bytes(bom + json.dumps({"workspaces": ["packages/*"]}).encode())
    (tmp_path / "packages/a/x.ts").write_bytes(b"")
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc/go.mod").write_bytes(bom + b"module example.com/svc\n")
    (tmp_path / "svc/m.go").write_bytes(b"")
    modules, fm, _ = detect_modules(tmp_path, ["packages/a/x.ts", "svc/m.go"])
    assert fm["packages/a/x.ts"] == "mod:packages/a"
    assert names_from_build_files(tmp_path, modules)["mod:svc"] == "example.com/svc"


def test_relative_paths_are_posix():
    src = (Path(structure.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"str\(\w+\.relative_to\(", src)
    assert src.count(".relative_to(root).as_posix()") >= 2
    assert "Path(f).parent.as_posix()" in src


# --- 5. root node_modules ---------------------------------------------------------------------------------

def test_root_node_modules_excluded():
    assert structure.excluded("node_modules/react/index.js", structure.DEFAULT_EXCLUDES)
    assert structure.excluded("web/node_modules/react/index.js", structure.DEFAULT_EXCLUDES)
    assert structure.excluded("node_modules/x.py", structure.DEFAULT_EXCLUDES)   # vendored, in every language
    assert not structure.excluded("build/x.py", structure.DEFAULT_EXCLUDES)   # a Python package may be named build


# --- 7. Rust `Self::` -------------------------------------------------------------------------------------

def test_rust_self_path_is_the_callers_own_type(make_repo):
    repo = make_repo({"Cargo.toml": '[package]\nname = "a"\n',
                      "lib.rs": "struct A;\nimpl A {\n  fn find() {}\n  fn save(&self) { Self::find() }\n}\n"
                                "struct B;\nimpl B {\n  fn find() {}\n}\n"})
    s = structure.build(repo, "docs/viz-code")
    meaning = {"nodes": [{"id": "svc:a", "kind": "service", "name": "a", "modules": ["."],
                          "evidence": [{"file": "lib.rs", "line": 1}]}]}
    got = {(r["from"].split("::", 1)[1], r["to"].split("::", 1)[1], r["confidence"])
           for r in assemble(s, meaning)["relations"] if r["kind"] == "calls"}
    assert got == {("lib.A#save/0", "lib.A#find/0", "confirmed")}, got


# --- 8. Python's names stay out of the JVM languages' scope -----------------------------------------------

def test_python_folders_do_not_hide_java_libraries(make_repo):
    s = structure.build(make_repo({
        "py/io/__init__.py": "", "py/io/x.py": "import org.thing\n", "py/org/__init__.py": "",
        "svc/pom.xml": "<project/>",
        "svc/src/main/java/a/A.java": "package a;\nimport io.netty.Bootstrap;\nimport org.apache.commons.Lang;\n"
                                      "class A {}\n",
    }), "docs/viz-code")
    got = unrec(s)
    assert ("java", "io.netty") in got and ("java", "org.apache") in got, got
    assert not any(lang == "python" for lang, _ in got), got
