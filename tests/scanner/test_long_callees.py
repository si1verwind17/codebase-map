"""A long callee (a fluent chain, long arguments) keeps the called name at its end and that name's line."""
from vizcode import calls, ids
from vizcode.adapters import CALLEE_MAX, callee_text, generic, python as py, scala
from vizcode.adapters.langs import SPECS

STEPS = "".join(f'\n      .step{i}("a fairly long literal argument number {i}", options)' for i in range(8))


def _last(res, name):
    return next(c for c in res["calls"] if calls.callee_parts(c["callee"])[-1:] == [name])


def test_callee_text_keeps_short_text_and_the_name_of_long_text():
    assert callee_text("repo.find") == "repo.find"
    long = "builder" + "".join(f'.step{i}("{"x" * 30}")' for i in range(8)) + ".send"
    out = callee_text(long)
    assert len(out) <= CALLEE_MAX
    assert calls.callee_parts(out)[-1] == "send"
    assert calls.callee_parts(out)[0] == "builder"          # emptied arguments were enough: the receiver stays
    many = "x" + "".join(f".s{i}()" for i in range(60)) + ".send"
    cut = callee_text(many)
    assert len(cut) <= CALLEE_MAX and calls.callee_parts(cut)[-1] == "send"
    assert calls.callee_parts(cut)[0] == "?"                 # a cut head is an untrusted receiver


def test_java_chain_names_its_last_call_on_its_line():
    src = "class R {\n  void configure() {\n    from(\"in\")" + STEPS + "\n      .send(\"out\");\n  }\n}\n"
    res = generic.parse(src.encode(), "svc/R.java", {"id": "mod:svc", "path": "svc", "lang": "java", "build": "dir"},
                        ids.IdRegistry(), spec=SPECS["java"])
    send = _last(res, "send")
    assert send["line"] == src[:src.index(".send")].count("\n") + 1
    assert send["args"] == 1


def test_scala_chain_names_its_last_call_on_its_line():
    src = "object R {\n  def run() =\n    client" + STEPS + "\n      .send(\"out\")\n}\n"
    res = scala.parse(src.encode(), "svc/src/main/scala/R.scala", {"id": "mod:svc", "path": "svc", "lang": "scala"},
                      ids.IdRegistry())
    send = _last(res, "send")
    assert send["line"] == src[:src.index(".send")].count("\n") + 1


def test_python_chain_names_its_last_call_on_its_line():
    src = "def run():\n    return (client" + STEPS.replace("options", "opts") + "\n      .send('out'))\n"
    res = py.parse(src.encode(), "svc/r.py", {"id": "mod:svc", "path": "svc", "lang": "python", "build": "dir"}, ids.IdRegistry())
    send = _last(res, "send")
    assert send["line"] == src[:src.index(".send")].count("\n") + 1
