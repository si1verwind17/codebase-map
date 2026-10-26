"""Whether an in-process queue creation site can be a hand-off: the repo's code puts items on the queue and takes
them off. A queue the code never fills (only a library puts on it, as with OS signals), never drains, or only
inspects or administers (reads its size, clears it) is none. Judged from the creating method's text for a queue
bound to a local name, and from the call chained onto a creation (`X.new(name).size`); a field, a queue built
outside a method, one handed on without a name, and one a stack.yaml pattern found (the agent confirmed it) are kept.
"""
from __future__ import annotations

import re

from . import stack

PUT = {"put", "put_nowait", "putasync", "push", "send", "send_nowait", "sendasync", "try_send", "trysend", "offer",
       "offerall", "add", "tryadd", "enqueue", "enq", "emit", "tryemit", "publish", "write", "writeasync", "trywrite",
       "post"}
TAKE = {"get", "get_nowait", "getasync", "pop", "shift", "deq", "dequeue", "trydequeue", "take", "takeall",
        "trytake", "poll", "recv", "try_recv", "recv_async", "blocking_recv", "receive", "tryreceive",
        "receiveasflow", "consumeeach", "collect", "on", "once", "addlistener", "subscribe", "read", "readasync",
        "tryread", "readallasync", "getconsumingenumerable", "drainto", "iter", "try_iter"}
# the name a creation is bound to, just before it: `q = `, `q := `, `val q: Queue[Int] = `, `q <- `, `let (tx, rx) = `
BINDING = re.compile(r"(?:\(\s*(?:mut\s+)?(\w+)\s*,\s*(?:mut\s+)?(\w+)\s*\)|(?<![\w.@$>:])(\$?[A-Za-z_]\w*))"
                     r"\s*(?::(?![:=])[^=]*?)?\s*(?::=|=(?![=>])|<-)\s*(?:new\s+|await\s+)?(?:\w+(?:::|\.))*$")
CALL_HEAD = re.compile(r"([A-Za-z_][\w.:]*)\s*$")
KEYWORDS = {"if", "for", "while", "switch", "return", "go", "await", "case", "select", "range", "elif", "unless"}


def _binding(prefix: str) -> list[str]:
    m = BINDING.search(prefix)
    if not m:
        return []
    return [n for n in m.groups() if n]


def _callee(text: str, at: int) -> str | None:
    """The called name around position `at` when it is an argument of a call (`signal.Notify(c, …)`), else None."""
    depth = 0
    for i in range(at - 1, max(-1, at - 400), -1):
        ch = text[i]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth == 0:
                if ch != "(":
                    return None
                m = CALL_HEAD.search(text, 0, i)
                return m.group(1) if m and m.group(1) not in KEYWORDS else None
            depth -= 1
        elif ch in ";\n" and depth == 0:
            return None
    return None


def _after_args(text: str) -> int:
    """Where `text` continues after the creation's own argument groups (`(8)`, `[Int](8)`)."""
    i = 0
    while (m := re.match(r"\s*[(\[]", text[i:])) is not None:
        depth, j = 0, i + m.end() - 1
        while j < len(text):
            depth += 1 if text[j] in "([" else -1 if text[j] in ")]" else 0
            if depth == 0:
                break
            j += 1
        i = j + 1
    return min(i, len(text))


def site_use(src: str, line: int, regex: re.Pattern, spans: list[tuple[int, int, str]], within: str) -> dict | None:
    """How the code uses the queue created on `line`: put and take seen, and the calls it is passed to (`None` for a
    use that is no call argument: returned, stored, assigned). A creation chained into one call without arguments
    (`X.new(name).size`) is used only for that call. None when the site is not judged."""
    lines = src.split("\n")
    text = lines[line - 1] if line <= len(lines) else ""
    if (m := regex.search(text)) is None:
        return None
    rest = text[m.end():]
    chained = re.match(r"\s*\??\.\s*(\w+)(?:\s*\(\s*\))?(?![\w(\[{.]|\s*[.({\[]|\s*do\b|\s*=)", rest[_after_args(rest):])
    if chained and not chained.group(1).lower().startswith("to"):   # `toX` converts it, the result is handed on
        word = chained.group(1).lower()
        return {"put": word in PUT, "take": word in TAKE, "passed": []}
    span = next((s for s in spans if s[2] == within and s[0] <= line <= s[1]), None)
    names = _binding(text[:m.start()])
    if span is None or not names:
        return None
    body = "\n".join([rest] + lines[line:span[1]])
    use = {"put": False, "take": False, "passed": []}
    for name in names:
        n = re.escape(name)
        for occ in re.finditer(rf"(?<![\w.$@>]){n}\b", body):
            before, after = body[:occ.start()], body[occ.end():]
            chain = re.match(r"(?:\s*\??\.\s*\w+)+", after)
            if re.search(r"(?:<-|\b(?:range|in))\s*$", before):
                use["take"] = True
            elif re.match(r"\s*(?:<-|<<)", after):
                use["put"] = True
            elif chain:
                words = {w.lower() for w in re.findall(r"\w+", chain.group(0))}
                use["put"] |= bool(words & PUT)
                use["take"] |= bool(words & TAKE)
            elif not re.match(r"\s*(?:=(?!=)|:=|\[)", after):
                use["passed"].append(_callee(body, occ.start()))
    return use


def _bound(imp: dict, sep: str) -> set[str]:
    """The names an import binds in the file: its alias, the names it brings in, its first and last segments."""
    parts = [p for p in re.split(r"/|\.|::|\\", imp["target"]) if p]
    return {imp.get("as"), *(imp.get("names") or []), *(imp.get("renames") or {}).values(), *parts[:1], *parts[-1:]}


def _outside(callee: str | None, imports: list[dict], internal: set[str], lang: str) -> bool:
    """A call of a library the file imports (`signal.Notify`): what it does with the queue is no repo code."""
    if callee is None or not re.search(r"\.|::", callee):
        return False
    head = re.split(r"\.|::", callee)[0]
    sep = stack.sep(lang)
    return any(head in _bound(i, sep) for i in imports if not i["relative"]
               and not any(stack.prefix_match(p, i["target"], sep) for p in internal))


def handled(queues: list[dict], imports: list[dict], internal: set[str], lang: str) -> list[dict]:
    """The creation sites that can be hand-offs, without their `use`: one is dropped when no repo code can put on it
    or none can take from it. Passing the queue to the repo's own code (or anywhere unknown) counts as both."""
    out = []
    for q in queues:
        use = q.pop("use", None)
        if use is not None:
            on = any(not _outside(c, imports, internal, lang) for c in use["passed"])
            if not ((use["put"] or on) and (use["take"] or on)):
                continue
        out.append(q)
    return out
