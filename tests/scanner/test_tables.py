"""The tables group of stack.yaml: find_tables, per-file facts, summary line, Stack report."""
import pytest
from conftest import with_stack

from vizcode import stack, structure

from helpers import write

# the stack.yaml mechanism alone: the packs' own routes and tables (Spring, JAX-RS, JPA, Quill, SQLAlchemy)
# would match these fixtures too
pytestmark = pytest.mark.usefixtures("packs_without_patterns")

QUILL = "scala:\n  tables:\n    - {name: quill-query, when: io.getquill, regex: 'query\\[(?P<table>\\w+)\\]'}\n"
JPA = ("java:\n  tables:\n    - {name: jpa-table, when: jakarta.persistence, "
       "regex: '@Table\\(\\s*name\\s*=\\s*\"(?P<table>[^\"]+)\"'}\n")
SQLA = "python:\n  tables:\n    - {name: sqla, when: sqlalchemy, regex: '__tablename__\\s*=\\s*\"(?P<table>\\w+)\"'}\n"


def test_find_tables_method_class_file(tmp_path):
    st = stack.load(write(tmp_path, "scala:\n  tables:\n    - {name: q, regex: 'query\\[(?P<table>\\w+)\\]'}\n"))
    src = "class R {\n  val a = query[Cls]\n  def m = query[Order]\n}\nval z = query[Top]\n"
    got = stack.find_tables(st, "scala", src, [], [(3, 3, "m")], [(1, 4, "R")], "file")
    assert [(t["table"], t["in"], t["kind"], t["line"], t["pattern"], t["source"]) for t in got] == [
        ("Cls", "R", "defined", 2, "q", "stack.yaml"), ("Order", "m", "access", 3, "q", "stack.yaml"),
        ("Top", "file", "access", 5, "q", "stack.yaml")]


def test_innermost_method_wins(tmp_path):
    st = stack.load(write(tmp_path, QUILL.replace("when: io.getquill, ", "")))
    got = stack.find_tables(st, "scala", "x\nquery[A]\n", [], [(1, 5, "outer"), (2, 3, "inner")], [], "f")
    assert got[0]["in"] == "inner"


def test_when_gating_uses_language_separator(tmp_path):
    st = stack.load(write(tmp_path, QUILL))
    assert stack.find_tables(st, "scala", "query[A]", ["io.getquill.jdbc"], [], [], "f") != []
    assert stack.find_tables(st, "scala", "query[A]", ["io.getquillx"], [], [], "f") == []
    assert stack.find_tables(st, "scala", "query[A]", [], [], [], "f") == []
    assert stack.find_tables(st, "python", "query[A]", ["io.getquill"], [], [], "f") == []
    st = stack.load(write(tmp_path, "rust:\n  tables:\n    - {name: d, when: diesel, regex: 'table!\\((?P<table>\\w+)'}\n"))
    assert stack.find_tables(st, "rust", "table!(users)", ["diesel::prelude"], [], [], "f")[0]["table"] == "users"


@pytest.mark.parametrize("text,expect", [
    ("java:\n  tables:\n    - {name: t, regex: 'x'}\n", "java.tables[0] (t): regex has no table group"),
    ("java:\n  tables:\n    - {regex: '(?P<table>x)'}\n", "java.tables[0]: missing name"),
    ("java:\n  tables:\n    - {name: t}\n", "java.tables[0] (t): missing regex"),
    ("java:\n  tables:\n    - {name: t, regex: '(', }\n", "regex does not compile"),
    ("java:\n  tables:\n    - {name: t, regex: '(?P<table>x)', path: literal}\n", "unknown key 'path'"),
    ("java:\n  tables:\n    - {name: t, regex: '(?P<table>x)', when: 3}\n", "when must be an import prefix"),
    ("java:\n  tables:\n    - {name: t, regex: '(?P<table>x)'}\n    - {name: t, regex: '(?P<table>y)'}\n",
     "java.tables[1] (t): duplicate table name"),
    ("java:\n  tables: [3]\n", "java.tables[0]: must be a mapping"),
])
def test_bad_table_entries(tmp_path, text, expect):
    with pytest.raises(stack.StackError) as e:
        stack.load(write(tmp_path, text))
    assert "stack.yaml: " in str(e.value) and expect in str(e.value)


def test_table_and_route_names_are_separate(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  routes:\n    - {name: x, path: literal, method: GET, regex: '(?P<path>/a)'}\n"
                          "  tables:\n    - {name: x, regex: '(?P<table>t)'}\n"))
    assert [p.name for p in st.patterns if p.lang == 'python'] == ['x']
    assert [p.name for p in st.tables] == ['x']


def test_prefix_match_single_colon_only():
    assert stack.prefix_match("node:", "node:fs", "/")
    assert not stack.prefix_match("std::", "std::io", "::")
    assert stack.prefix_match("std", "std::io", "::")


def test_load_strips_a_trailing_separator(tmp_path):
    st = stack.load(write(tmp_path, "rust:\n  ignore: ['std::']\n"
                                    "java:\n  imports:\n    - {prefix: 'java.', kind: sql-db}\n"
                                    "  tables:\n    - {name: t, when: 'jakarta.persistence.', regex: '(?P<table>x)'}\n"
                                    "typescript:\n  ignore: ['node:', '@aws-sdk/']\n"))
    assert "std" in st.ignore["rust"] and "std::" not in st.ignore["rust"]
    assert ("java", "sql-db", "stack.yaml") in st.imports["java"]
    assert next(p.when for p in st.tables if p.name == "t") == "jakarta.persistence"
    assert "node:" in st.ignore["typescript"] and "@aws-sdk" in st.ignore["typescript"]
    assert stack.covered(st, "rust", "std::io") and stack.covered(st, "typescript", "node:fs")


SCALA = {
    "build.sbt": 'lazy val shop = (project in file("shop"))\n',
    "shop/src/main/scala/io/demo/shop/OrderRepo.scala":
        "package io.demo.shop\n\nimport io.getquill.*\n\nclass OrderRepo {\n"
        "  def byId(id: String) = run(query[Order].filter(_.id == id))\n"
        "  def all = run(query[Item])\n}\n",
    "shop/src/main/scala/io/demo/shop/Other.scala":
        "package io.demo.shop\n\nobject Other { def q = query[Nope] }\n",
}
JAVA = {
    "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
    "src/main/java/io/demo/shop/Order.java":
        "package io.demo.shop;\n\nimport jakarta.persistence.Table;\n\n@Table(name = \"orders\")\npublic class Order {\n"
        "  int id;\n}\n",
}
PY = {
    "pyproject.toml": "[project]\nname = 'shop'\n",
    "shop/__init__.py": "",
    "shop/models.py": "from sqlalchemy import Column\n\n\nclass Order:\n    __tablename__ = \"orders\"\n",
}


def test_scala_quill_access_in_method(make_repo):
    repo = make_repo(SCALA)
    with_stack(repo, QUILL)
    s = structure.build(repo, "docs/viz-code")
    ts = s["facts"]["shop/src/main/scala/io/demo/shop/OrderRepo.scala"]["tables"]
    assert [(t["table"], t["kind"], t["line"]) for t in ts] == [("Order", "access", 6), ("Item", "access", 7)]
    assert "tables" not in s["facts"]["shop/src/main/scala/io/demo/shop/Other.scala"]
    md = structure.summary_md(s)
    line = next(x for x in md.splitlines() if x.startswith("- **tables (patterns):**"))
    f = "shop/src/main/scala/io/demo/shop/OrderRepo.scala"
    assert line == f"- **tables (patterns):** Item ({f}:7 in all); Order ({f}:6 in byId)"
    assert "Table patterns:\n- scala quill-query (stack.yaml): 2 tables in 1 file\n" in md


def test_java_jpa_defined_on_class(make_repo):
    repo = make_repo(JAVA)
    with_stack(repo, JPA)
    s = structure.build(repo, "docs/viz-code")
    ts = s["facts"]["src/main/java/io/demo/shop/Order.java"]["tables"]
    assert [(t["table"], t["kind"]) for t in ts] == [("orders", "defined")]
    assert ts[0]["in"].endswith("Order")
    md = structure.summary_md(s)
    line = next(x for x in md.splitlines() if x.startswith("- **tables (patterns):**"))
    assert line == "- **tables (patterns):** orders (src/main/java/io/demo/shop/Order.java:5 defined on Order)"


def test_python_sqlalchemy(make_repo):
    repo = make_repo(PY)
    with_stack(repo, SQLA)
    s = structure.build(repo, "docs/viz-code")
    ts = s["facts"]["shop/models.py"]["tables"]
    assert [(t["table"], t["kind"], t["pattern"]) for t in ts] == [("orders", "defined", "sqla")]


def test_zero_match_table_pattern_flagged(make_repo):
    repo = make_repo(PY)
    with_stack(repo, SQLA.replace("__tablename__", "__nomatch__"))
    s = structure.build(repo, "docs/viz-code")
    dead = next(p for p in s["stack"]["patterns"] if p["name"] == "sqla")
    assert dead["matches"] == 0 and dead["group"] == "tables" and dead["first_file"] == "shop/models.py:1"
    md = structure.summary_md(s)
    assert "1 pattern with no match" in md
    assert "Table patterns:\n- python sqla (stack.yaml): 0 matches — check the regex against shop/models.py:1\n" in md
    assert stack.count(s["stack"]) == 1


def test_no_tables_no_summary_line(make_repo):
    s = structure.build(make_repo(PY), "docs/viz-code")
    assert "tables (patterns)" not in structure.summary_md(s)
    assert "tables" not in s["facts"]["shop/models.py"]
