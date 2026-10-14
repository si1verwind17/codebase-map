"""Read committed code only: the stamped commit and an exported copy of its tree."""
from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def head_commit(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def commit_exists(repo: Path, sha: str) -> bool:
    r = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                       capture_output=True)
    return r.returncode == 0


def project_root(repo: Path) -> str | None:
    """The scanned folder's path relative to the git top level ('a/b'), or None at the top.
    Map paths, git diff and evidence are all taken relative to the scanned folder."""
    prefix = _git(repo, "rev-parse", "--show-prefix").strip().strip("/")
    return prefix or None


def require_committed(repo: Path, commit: str) -> None:
    """A subfolder is scanned as committed at HEAD; refuse one HEAD does not contain."""
    if not _git(repo, "ls-tree", "--name-only", commit).strip():
        raise GitError(f"{repo} has no files committed at {commit[:12]}: commit the folder first")


def rel_out_dir(repo: Path, out_dir: str) -> str:
    """The output directory as a clean path relative to the repo root; it must be inside the repo."""
    root = repo.resolve()
    target = Path(out_dir) if Path(out_dir).is_absolute() else root / out_dir
    try:
        rel = target.resolve().relative_to(root)
    except ValueError:
        raise ValueError(f"--out-dir must be inside the repository ({root}); got {out_dir}") from None
    if str(rel) == ".":
        raise ValueError("--out-dir must be a subdirectory of the repository, not its root")
    return rel.as_posix()


def export_tree(repo: Path, commit: str, dest: Path) -> list[str]:
    """Extract the committed tree into dest and return members that were not extracted.
    Never reads the working directory, so uncommitted edits by anyone else cannot leak
    into the scan. Run from a subfolder, git archive exports just that subtree, rooted at dest. Links pointing
    outside the tree are dropped, not fatal."""
    dropped: list[str] = []

    def safe(member, path):
        try:
            return tarfile.data_filter(member, path)
        except tarfile.FilterError:
            dropped.append(member.name)
            return None

    proc = subprocess.Popen(["git", "-C", str(repo), "archive", "--format=tar", commit],
                            stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            tar.extractall(dest, filter=safe)
    except tarfile.ReadError:
        pass   # git printed no archive: reported below
    if proc.wait() != 0:
        raise GitError(f"git archive {commit[:12]} failed: is the folder committed at HEAD?")
    return dropped


def changed_files(repo: Path, old: str, new: str) -> list[dict]:
    """Files changed between two commits under repo (the whole tree, or its subfolder, paths
    relative to repo); renames carry old_path."""
    out = []
    for line in _git(repo, "diff", "--relative", "--name-status", "-M", old, new).splitlines():
        parts = line.split("\t")
        status = parts[0][0]
        if status == "R":
            out.append({"status": "R", "old_path": parts[1], "path": parts[2]})
        else:
            out.append({"status": status, "path": parts[1]})
    return out
