#!/usr/bin/env python3
"""Release the plugin: bump the version in .claude-plugin/marketplace.json (both fields), commit, tag vX.Y.Z on that
commit, and with --push push main and the tag and create the GitHub release (gh, notes generated). Run on a clean main
after the change is squash-merged. Without --push it stops before anything leaves the machine; run it again with --push
to finish (a bump already committed and tagged at HEAD is not made twice). Stdlib only.

    tools/release.py 1.1.2 "doors lead to the door back"
    tools/release.py 1.1.2 "doors lead to the door back" --push
"""
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
VERSION = re.compile(r'("version":\s*")(\d+\.\d+\.\d+)(")')


def versions(text: str) -> list[str]:
    return [m.group(2) for m in VERSION.finditer(text)]


def bump(text: str, new: str) -> str:
    """Every version field set to `new`; the fields must agree and `new` must be higher."""
    found = set(versions(text))
    if len(found) != 1:
        raise ValueError(f"marketplace.json versions disagree or are missing: {sorted(found)}")
    old = found.pop()
    if tuple(map(int, new.split("."))) <= tuple(map(int, old.split("."))):
        raise ValueError(f"{new} is not above the current {old}")
    return VERSION.sub(lambda m: m.group(1) + new + m.group(3), text)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def run(*cmd: str) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="X.Y.Z")
    ap.add_argument("summary", help='what the release brings, for the commit "codebase-map X.Y.Z: <summary>"')
    ap.add_argument("--push", action="store_true", help="push main and the tag, and create the GitHub release")
    a = ap.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a.version):
        sys.exit(f"version must be X.Y.Z, not {a.version!r}")
    tag = f"v{a.version}"
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        sys.exit("release from main: squash-merge the branch first")
    if git("status", "--porcelain"):
        sys.exit("the working tree is not clean")

    text = MARKETPLACE.read_text()
    done = git("tag", "--list", tag) == tag and git("rev-list", "-n1", tag) == git("rev-parse", "HEAD") \
        and set(versions(text)) == {a.version}
    if not done:
        if git("tag", "--list", tag):
            sys.exit(f"{tag} already exists on another commit")
        try:
            MARKETPLACE.write_text(bump(text, a.version))
        except ValueError as e:
            sys.exit(str(e))
        run("git", "add", str(MARKETPLACE.relative_to(ROOT)))
        run("git", "commit", "-q", "-m", f"codebase-map {a.version}: {a.summary}")
        run("git", "tag", tag)
    else:
        print(f"{tag} is already committed and tagged at HEAD")

    if not a.push:
        print(f"\nNothing pushed. To publish: tools/release.py {a.version} {a.summary!r} --push")
        return 0
    run("git", "push", "origin", "main")
    run("git", "push", "origin", tag)
    run("gh", "release", "create", tag, "--title", tag, "--generate-notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
