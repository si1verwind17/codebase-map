"""Call order (spec: traces §1.3): each `calls` relation carries the call site's line as evidence, so the viewer
can order a method's callees. One case per language: `run` calls `second` on line 3 and `first` on line 4."""
import pytest

from vizcode import structure
from vizcode.assemble import assemble

CASES = {
    "scala": ("build.sbt", 'lazy val app = (project in file("."))\n', "src/main/scala/a/O.scala",
              "package a\nobject O {\n  def run(): Unit = {\n    second()\n    first()\n  }\n"
              "  def first(): Unit = ()\n  def second(): Unit = ()\n}\n", 4, 5),
    "python": ("pyproject.toml", '[project]\nname = "app"\nversion = "0.1"\n', "app/o.py",
               "def run():\n    x = 1\n    second()\n    first()\n\n\ndef first():\n    pass\n\n\n"
               "def second():\n    pass\n", 3, 4),
    "java": ("pom.xml", "<project></project>\n", "src/main/java/a/O.java",
             "package a;\nclass O {\n  void run() {\n    second();\n    first();\n  }\n"
             "  void first() {}\n  void second() {}\n}\n", 4, 5),
    "kotlin": ("build.gradle.kts", "plugins {}\n", "src/main/kotlin/a/O.kt",
               "package a\n\nfun run() {\n  second()\n  first()\n}\n\nfun first() {}\n\nfun second() {}\n", 4, 5),
    "typescript": ("package.json", '{"name": "app"}\n', "src/o.ts",
                   "export function run(): void {\n  const x = 1;\n  second();\n  first();\n}\n"
                   "function first(): void {}\nfunction second(): void {}\n", 3, 4),
    "javascript": ("package.json", '{"name": "app"}\n', "src/o.js",
                   "export function run() {\n  const x = 1;\n  second();\n  first();\n}\n"
                   "function first() {}\nfunction second() {}\n", 3, 4),
    "go": ("go.mod", "module example.com/app\n\ngo 1.22\n", "o.go",
           "package main\n\nfunc run() {\n\tsecond()\n\tfirst()\n}\n\nfunc first() {}\n\nfunc second() {}\n", 4, 5),
    "csharp": ("App.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n", "O.cs",
               "namespace A;\nclass O {\n  public void Run() {\n    second();\n    first();\n  }\n"
               "  public void first() {}\n  public void second() {}\n}\n", 4, 5),
    "rust": ("Cargo.toml", "[package]\nname = \"app\"\nversion = \"0.1.0\"\n", "src/main.rs",
             "fn main() {}\nfn run() {\n    let x = 1;\n    second();\n    first();\n}\nfn first() {}\nfn second() {}\n",
             4, 5),
    "ruby": ("Gemfile", "source 'https://rubygems.org'\n", "lib/o.rb",
             "class O\n  def run\n    second()\n    first()\n  end\n\n  def first\n  end\n\n  def second\n  end\nend\n",
             3, 4),
    "php": ("composer.json", '{"name": "acme/app"}\n', "src/o.php",
            "<?php\nfunction run() {\n  $x = 1;\n  second();\n  first();\n}\nfunction first() {}\nfunction second() {}\n",
            4, 5),
}


@pytest.mark.parametrize("lang", sorted(CASES))
def test_calls_carry_the_call_line(make_repo, lang):
    build_file, build_text, rel, src, second_line, first_line = CASES[lang]
    s = structure.build(make_repo({build_file: build_text, rel: src}), "docs/viz-code")
    cmap = assemble(s, {})
    names = {n["id"]: n["name"] for n in cmap["nodes"]}
    callees = {names[r["to"]]: [e["line"] for e in r["evidence"]] for r in cmap["relations"]
               if r["kind"] == "calls" and names.get(r["from"]) in ("run", "Run")}
    assert callees == {"second": [second_line], "first": [first_line]}
    assert all(e["file"] == rel for r in cmap["relations"] if r["kind"] == "calls" for e in r["evidence"])
