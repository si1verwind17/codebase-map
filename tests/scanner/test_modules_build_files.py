"""Modules from build files per ecosystem (packs/modules.yaml), build-output and test excludes, file suffixes."""
import json
from pathlib import Path

from conftest import write_files

from vizcode import calls, structure
from vizcode.modules import BUILD_FILES, ECOSYSTEMS, detect_modules
from vizcode.roles import family


def mods(tmp_path: Path, files: dict[str, str]) -> tuple[dict[str, tuple[str, str, str]], dict[str, str]]:
    """Write the files, detect modules over the source files: ({id: (path, lang, build)}, file -> module id)."""
    write_files(tmp_path, files)
    sources = sorted(f for f in files if Path(f).suffix in structure.LANGS
                     and not structure.excluded(f, structure.DEFAULT_EXCLUDES))
    modules, file_mod, _ = detect_modules(tmp_path, sources)
    return {m["id"]: (m["path"], m["lang"], m["build"]) for m in modules}, file_mod


def test_modules_yaml_lists_every_ecosystem():
    assert {e.build: (e.files, e.langs, e.members) for e in ECOSYSTEMS} == {
        "maven": (("pom.xml",), ("java", "kotlin"), "maven-modules"),
        "gradle": (("settings.gradle", "settings.gradle.kts"), ("java", "kotlin"), "gradle-include"),
        "npm": (("package.json", "pnpm-workspace.yaml"), ("typescript", "javascript"), "npm-workspaces"),
        "go": (("go.mod",), ("go",), "each-file"),
        "cargo": (("Cargo.toml",), ("rust",), "cargo-members"),
        "dotnet": (("*.csproj",), ("csharp",), "each-file"),
        "bundler": (("Gemfile",), ("ruby",), "each-file"),
        "composer": (("composer.json",), ("php",), "each-file"),
    }
    assert "pom.xml" in BUILD_FILES and "*.csproj" in BUILD_FILES


def test_maven_multi_module(tmp_path):
    m, fm = mods(tmp_path, {
        "pom.xml": "<project><modules>\n  <module>api</module>\n  <!-- <module>old</module> -->\n"
                   "  <module> core </module>\n  <module>svc</module>\n</modules></project>",
        "api/pom.xml": "<project/>", "core/pom.xml": "<project/>",     # svc has no pom: listed, still a module
        "api/src/main/java/a/A.java": "class A {}", "core/src/main/kotlin/b/B.kt": "class B",
        "svc/src/main/java/c/C.java": "class C {}", "old/src/O.java": "class O {}",
    })
    assert m == {"mod:.": (".", "java", "maven"), "mod:api": ("api", "java", "maven"),
                 "mod:core": ("core", "kotlin", "maven"), "mod:svc": ("svc", "java", "maven")}
    assert fm["old/src/O.java"] == "mod:."       # the root pom is the nearest build file


def test_gradle_settings_include(tmp_path):
    m, fm = mods(tmp_path, {
        "settings.gradle.kts": 'rootProject.name = "shop"\ninclude(":app", ":libs:util")\n'
                               '// include(":gone")\nincludeBuild("plugins")\n',
        "app/src/main/kotlin/X.kt": "class X", "libs/util/src/main/java/Y.java": "class Y {}",
        "tools/Z.java": "class Z {}", "plugins/P.java": "class P {}",
    })
    assert m == {"mod:.": (".", "java", "gradle"), "mod:app": ("app", "kotlin", "gradle"),
                 "mod:libs/util": ("libs/util", "java", "gradle")}
    assert fm["tools/Z.java"] == fm["plugins/P.java"] == "mod:."


def test_gradle_groovy_include(tmp_path):
    m, _ = mods(tmp_path, {"svc/settings.gradle": "include 'web', ':jobs:nightly',\n        'admin'\n",
                           "svc/web/W.java": "", "svc/jobs/nightly/N.java": "", "svc/admin/A.java": ""})
    assert set(m) == {"mod:svc/web", "mod:svc/jobs/nightly", "mod:svc/admin"}


def test_npm_workspaces_with_a_glob(tmp_path):
    m, fm = mods(tmp_path, {
        "package.json": json.dumps({"name": "root", "workspaces": ["packages/*"]}),
        "packages/a/package.json": "{}", "packages/a/src/x.ts": "", "packages/a/src/deep/y.ts": "",
        "packages/b/index.js": "",          # no package.json of its own: the glob makes it a module
        "tools/t.ts": "",
    })
    assert m == {"mod:.": (".", "typescript", "npm"), "mod:packages/a": ("packages/a", "typescript", "npm"),
                 "mod:packages/b": ("packages/b", "javascript", "npm")}
    assert fm["packages/a/src/deep/y.ts"] == "mod:packages/a"     # `*` is one folder, not `packages/a/src`
    assert fm["tools/t.ts"] == "mod:."


def test_npm_workspaces_object_form(tmp_path):
    m, _ = mods(tmp_path, {"package.json": json.dumps({"workspaces": {"packages": ["apps/web"]}}),
                           "apps/web/main.tsx": ""})
    assert set(m) == {"mod:apps/web"}


def test_pnpm_workspace(tmp_path):
    m, fm = mods(tmp_path, {
        "pnpm-workspace.yaml": "packages:\n  - 'apps/*'\n  - '!apps/skip'\n",
        "apps/web/main.ts": "", "apps/skip/s.ts": "", "lib/l.ts": "",
    })
    assert m == {"mod:.": (".", "typescript", "npm"), "mod:apps/web": ("apps/web", "typescript", "npm")}
    assert fm["apps/skip/s.ts"] == "mod:."


def test_go_mod_at_two_levels(tmp_path):
    m, fm = mods(tmp_path, {"go.mod": "module example.com/x\n", "main.go": "", "internal/x/y.go": "",
                            "tools/go.mod": "module example.com/tools\n", "tools/gen/g.go": ""})
    assert m == {"mod:.": (".", "go", "go"), "mod:tools": ("tools", "go", "go")}
    assert fm["internal/x/y.go"] == "mod:." and fm["tools/gen/g.go"] == "mod:tools"


def test_cargo_workspace(tmp_path):
    m, fm = mods(tmp_path, {
        "Cargo.toml": '[workspace]\nmembers = ["crates/*", "tools/cli"]\nexclude = ["crates/old"]\n',
        "crates/a/Cargo.toml": '[package]\nname = "a"\n', "crates/a/src/lib.rs": "",
        "crates/b/src/lib.rs": "", "crates/old/src/lib.rs": "", "tools/cli/src/main.rs": "",
    })
    assert m == {"mod:.": (".", "rust", "cargo"), "mod:tools/cli": ("tools/cli", "rust", "cargo"),
                 "mod:crates/a": ("crates/a", "rust", "cargo"), "mod:crates/b": ("crates/b", "rust", "cargo")}
    assert fm["crates/old/src/lib.rs"] == "mod:."


def test_broken_cargo_toml_is_still_a_module(tmp_path):
    m, _ = mods(tmp_path, {"Cargo.toml": "[workspace\nmembers = [", "src/lib.rs": ""})
    assert m == {"mod:.": (".", "rust", "cargo")}
    m, _ = mods(tmp_path / "odd", {"Cargo.toml": 'workspace = "x"\n', "package.json": "[1]", "a/x.ts": "",
                                   "src/lib.rs": ""})
    assert m == {"mod:.": (".", "rust", "cargo"), "mod:.#typescript": (".", "typescript", "npm")}


def test_two_csproj(tmp_path):
    m, fm = mods(tmp_path, {"src/Api/Api.csproj": "<Project/>", "src/Core/Core.csproj": "<Project/>",
                            "src/Api/Controllers/C.cs": "", "src/Core/D.cs": "", "Shop.sln": ""})
    assert m == {"mod:src/Api": ("src/Api", "csharp", "dotnet"), "mod:src/Core": ("src/Core", "csharp", "dotnet")}


def test_gemfile_and_composer_json(tmp_path):
    m, _ = mods(tmp_path, {"Gemfile": "source 'https://rubygems.org'\n", "app/models/x.rb": "",
                           "web/composer.json": "{}", "web/src/A.php": "", "cli/run.php": ""})
    assert m == {"mod:.": (".", "ruby", "bundler"), "mod:web": ("web", "php", "composer"),
                 "mod:cli": ("cli", "php", "dir")}


def test_build_files_claim_only_their_languages(tmp_path):
    """A package.json does not claim Python or Go files; Python keeps its own detection."""
    m, fm = mods(tmp_path, {"package.json": "{}", "go.mod": "module x\n", "svc/run.py": "", "svc/x.go": "",
                            "web/a.ts": ""})
    assert m == {"mod:.": (".", "go", "go"), "mod:.#typescript": (".", "typescript", "npm"),
                 "mod:svc": ("svc", "python", "python-scripts")}
    assert fm["svc/x.go"] == "mod:." and fm["web/a.ts"] == "mod:.#typescript"


def test_mixed_language_folder(tmp_path):
    """One module per language: the first language in sorted order takes `mod:<path>`, the others `#<lang>`;
    Python and Scala keep the id they always had."""
    m, fm = mods(tmp_path, {"svc/b.ts": "", "svc/a.go": "", "svc/c.rb": "", "svc/x/d.ts": ""})
    assert m == {"mod:svc": ("svc", "go", "dir"), "mod:svc#ruby": ("svc", "ruby", "dir"),
                 "mod:svc#typescript": ("svc", "typescript", "dir")}
    assert fm["svc/x/d.ts"] == "mod:svc#typescript"
    m, _ = mods(tmp_path / "py", {"job/run.py": "", "job/a.go": ""})
    assert m == {"mod:job": ("job", "python", "python-scripts"), "mod:job#go": ("job", "go", "dir")}
    m, _ = mods(tmp_path / "jvm", {"pom.xml": "<project/>", "src/A.java": "", "src/B.kt": ""})
    assert m == {"mod:.": (".", "java", "maven"), "mod:.#kotlin": (".", "kotlin", "maven")}


def test_min_js_and_bundles_excluded(make_repo):
    big = "// big\n" + "var x = 1;\n" * (600 * 1024 // 11)
    repo = make_repo({"web/ok.js": "function ok() {}\n", "dist/app.js": "function a() {}\n",
                      "web/dist/b.js": "function b() {}\n", "web/x.min.js": "function m() {}\n",
                      "web/big.js": big, "web/types.d.ts": "declare const x: number;\n",
                      "web/api_pb.ts": "export const y = 1;\n", "svc/api.pb.go": "package svc\n",
                      "svc/build/gen.go": "package gen\n", "svc/main.go": "package svc\n",
                      "lib/obj/o.cs": "class O {}", "lib/bin/b.cs": "class B {}", "app/vendor/v.php": "<?php\n",
                      "settings.gradle.kts": 'include(":a")\n', "a/build.gradle.kts": "plugins {}\n",
                      "bin/tool.py": "def main():\n    pass\n", "build/gen.py": "X = 1\n"})
    s = structure.build(repo)
    assert sorted(s["files"]) == ["bin/tool.py", "build/gen.py", "svc/api.pb.go", "svc/main.go", "web/api_pb.ts",
                                  "web/ok.js"]
    assert s["generated"] == ["svc/api.pb.go", "web/api_pb.ts"]   # scanned for data types and routes only
    assert {sk["file"] for sk in s["skipped"]} == {"web/big.js"}
    assert "dist/app.js" in s["excluded"] and "web/x.min.js" in s["excluded"]


def test_test_files_of_each_language_excluded(make_repo):
    repo = make_repo({"svc/FooTest.java": "class FooTest {}", "svc/Foo.java": "class Foo {}",
                      "svc/foo_test.go": "package svc\n", "svc/foo.go": "package svc\n",
                      "web/a.spec.ts": "", "web/a.test.tsx": "", "__tests__/b.ts": "", "web/__tests__/c.js": "",
                      "web/a.ts": "export const a = 1\n", "core/tests/it.rs": "", "core/src/lib.rs": "fn f() {}\n",
                      "app/spec/models/order_spec.rb": "", "spec/helper.rb": "", "app/x.rb": "class X; end\n",
                      "api/OrderTests.cs": "", "api/Order.cs": "class Order {}", "web/OrderTest.php": "",
                      "spec/conf.py": "X = 1\n"})
    s = structure.build(repo)
    assert sorted(s["files"]) == ["api/Order.cs", "app/x.rb", "core/src/lib.rs", "spec/conf.py", "svc/Foo.java",
                                  "svc/foo.go", "web/a.ts"]


def test_suffixes_stripped_for_families_and_receivers():
    assert family("OrderRepoV2.java") == "OrderRepo" and family("exposure.py") == "exposure"
    assert family("handler.ts") == "handler" and family("Repo.scala") == "Repo"
    nodes = {"f": {"id": "f", "name": "orders.go"}, "m": {"id": "m", "parent": "f"}}
    assert calls._owner_names(nodes["m"], nodes) == {"orders"}
