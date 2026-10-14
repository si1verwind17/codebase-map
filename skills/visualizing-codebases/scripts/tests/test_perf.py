"""Extraction time on a generated 5,000-file TypeScript repo. Set VIZ_PERF=1 to run it."""
import os
import time

import pytest
from conftest import commit_all, git, write_files

from vizcode import structure

pytestmark = pytest.mark.skipif(os.environ.get("VIZ_PERF") != "1", reason="VIZ_PERF=1 not set")

FILES, PER_FOLDER = 5000, 50


def ts_file(i: int) -> str:
    """About 40 lines: two imports of earlier files, a class with methods calling them, a function."""
    folder = i // PER_FOLDER
    imports = "".join(f"import {{ Svc{j} }} from '../f{j // PER_FOLDER}/svc{j}';\n" for j in (i - 1, i - 7) if j >= 0)
    uses = "".join(f"    return new Svc{j}().run{j}(x) + 1;\n" for j in (i - 1,) if j >= 0) or "    return x;\n"
    body = "".join(f"  step{k}(x: number): number {{\n    return this.helper(x + {k});\n  }}\n\n" for k in range(6))
    return (f"// folder {folder}\nimport axios from 'axios';\n{imports}\n"
            f"export class Svc{i} {{\n  private base = process.env.SVC{i}_URL;\n\n"
            f"  run{i}(x: number): number {{\n{uses}  }}\n\n"
            f"  helper(x: number): number {{\n    return x * 2;\n  }}\n\n{body}"
            f"  async fetch(): Promise<void> {{\n    await axios.get(`${{this.base}}/items/{i}`);\n  }}\n}}\n\n"
            f"export const make{i} = (): Svc{i} => new Svc{i}();\n")


def test_five_thousand_typescript_files_under_a_minute(tmp_path):
    repo = tmp_path / "big"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    files = {"package.json": '{"name": "big"}\n'}
    files.update({f"src/f{i // PER_FOLDER}/svc{i}.ts": ts_file(i) for i in range(FILES)})
    write_files(repo, files)
    commit_all(repo, "init")
    t0 = time.time()
    s = structure.build(repo, "docs/viz-code")
    seconds = time.time() - t0
    print(f"\nstructure.build on {FILES} TypeScript files: {seconds:.1f} s")
    assert len(s["files"]) == FILES and s["stats"]["parse_errors"] == 0
    assert seconds < 60
