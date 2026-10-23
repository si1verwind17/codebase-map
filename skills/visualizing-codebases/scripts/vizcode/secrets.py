"""Config file lines with every value that may be a credential hidden, for reading config without printing a
secret (SKILL.md § Never read secrets).

A value is hidden when its key names a credential (CREDENTIAL_KEY), when it looks like one by itself (a token
prefix, a long random string, a PEM block), or, for the user and password of a URL or a connection string's
password field, inside an otherwise readable value (a DSN keeps its host and database). A multi-line value of a credential key (YAML `|`, a PEM block) is hidden line by line, and a comment that
names a credential is hidden whole. Everything else stays: hosts, paths, ports, crons, service names."""
from __future__ import annotations

import re

HIDDEN = "<hidden>"
# a key whose value is a credential; the last segment of a dotted or nested key is what counts
CREDENTIAL_KEY = re.compile(
    r"(?i)(pass(word|wd|phrase)?|pwd|secret|token|api[-_]?key|apikey|private[-_]?key|credential|auth[-_]?key|"
    r"access[-_]?key|signing[-_]?key|encryption[-_]?key|salt|cookie[-_]?key|"
    r"session[-_]?key|license[-_]?key|webhook[-_]?key)")
# a key that ends saying what kind of setting it is, not a credential: `accessTokenUri`, `password_min_length`
SETTING_KEY = re.compile(r"(?i)(ur[il]|host|endpoint|path|name|type|file|enabled|expir\w*|ttl|timeout|length|"
                         r"header|policy|mode|scope|issuer|audience|algorithm|prefix|location|provider)s?$")
# `key: value`, `key = value`, `KEY=value`, `- KEY=value`, `"key": value`, `export KEY=value`
KEY_VALUE = re.compile(r"""^(\s*(?:-\s+)?(?:export\s+)?["']?)([A-Za-z_][\w.\-\[\]]*)(["']?\s*[:=]\s*)(.*)$""")
USERINFO = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")
# a connection string's own password field (`Server=db;Password=x`, `password=x host=db`)
CONN_PASSWORD = re.compile(r"(?i)\b(password|pwd)\s*=\s*[^;\s\"']*")
# a value that is a secret by its shape: a provider token prefix, a JWT, or a long random-looking string
SECRET_VALUE = re.compile(
    r"^[\"']?(?:(?:sk|pk|rk)_(?:live|test)_\w+|gh[pousr]_\w{20,}|xox[abpr]-[\w-]+|AKIA[0-9A-Z]{16}|eyJ[\w-]+\.[\w-]+"
    r"|(?=[A-Za-z0-9+/_=-]*\d)(?=[A-Za-z0-9+/_=-]*[A-Za-z])[A-Za-z0-9+/_=-]{32,})[\"',]?$")
PEM_BEGIN, PEM_END = re.compile(r"-----BEGIN [A-Z ]+-----"), re.compile(r"-----END [A-Z ]+-----")
COMMENT = re.compile(r"^\s*(#|//|;)")
BLOCK = re.compile(r"^[|>][-+]?\d*\s*$")   # a YAML block scalar indicator


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def mask(text: str) -> list[tuple[int, str]]:
    """(line number, line) for each line of a config file, credentials hidden."""
    out: list[tuple[int, str]] = []
    block_over = -1    # a hidden multi-line value: lines indented deeper than this stay hidden
    in_pem = False
    for no, line in enumerate(text.splitlines(), 1):
        lead = line[:_indent(line)]
        if in_pem:
            out.append((no, lead + HIDDEN))
            in_pem = not PEM_END.search(line)
            continue
        if block_over >= 0:
            if line.strip() and _indent(line) > block_over:
                out.append((no, lead + HIDDEN))
                continue
            block_over = -1
        if COMMENT.match(line):
            hide = CREDENTIAL_KEY.search(line) or any(SECRET_VALUE.match(w) for w in line.split())
            out.append((no, lead + COMMENT.match(line).group(1) + " " + HIDDEN if hide else line))
            continue
        if PEM_BEGIN.search(line):
            m = KEY_VALUE.match(line)
            out.append((no, m.group(1) + m.group(2) + m.group(3) + HIDDEN if m else lead + HIDDEN))
            in_pem = not PEM_END.search(line)
            continue
        m = KEY_VALUE.match(line)
        if not m or not m.group(4).strip():
            out.append((no, line))
            continue
        head, key, value = m.group(1) + m.group(2) + m.group(3), m.group(2), m.group(4)
        last = re.split(r"[.\[\]]", key.strip("[]"))[-1] or key
        if (CREDENTIAL_KEY.search(last) and not SETTING_KEY.search(last)) or SECRET_VALUE.match(value.strip()):
            out.append((no, head + HIDDEN + ("," if value.rstrip().endswith(",") else "")))
            if BLOCK.match(value.strip()):
                block_over = _indent(line)
            continue
        out.append((no, head + CONN_PASSWORD.sub(lambda m: m.group(1) + "=" + HIDDEN, USERINFO.sub(HIDDEN, value))))
    return out
