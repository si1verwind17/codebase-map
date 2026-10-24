"""TypeScript the grammar cannot parse (`export type * from`, object-type arguments before a tagged template) is
blanked before parsing, same length, so the file parses whole and every offset still points at the source."""
from vizcode import structure
from vizcode.adapters import generic


def test_the_forms_are_blanked_in_place():
    src = b"export type * from './t'\nconst Box = styled.div<{ a: number;\n  b?: string }>`\n  color: red;\n`\n"
    out = generic.parseable(src, "tsx")
    assert len(out) == len(src) and out.count(b"\n") == src.count(b"\n")
    assert b"type" not in out.split(b"\n")[0] and b"<{" not in out
    assert generic.parseable(src, "go") == src


def test_a_file_using_them_parses_whole(make_repo):
    files = {"package.json": '{"name": "ui"}\n',
             "src/Card.tsx": "export type * from './types'\n\nconst Title = styled.h2<{ big: boolean }>`\n"
                             "  font-size: ${(p) => (p.big ? 2 : 1)}em;\n`\n\nexport function Card() {\n"
                             "  return load()\n}\n\nfunction load() {\n  return 1\n}\n"}
    s = structure.build(make_repo(files))
    assert s["stats"]["parse_errors"] == 0
    assert [c["in"].rsplit("#", 1)[-1] for c in s["facts"]["src/Card.tsx"]["calls"] if c["callee"] == "load"] == ["Card/0"]


def test_stories_specs_mocks_and_browser_tests_are_excluded(make_repo):
    files = {"package.json": '{"name": "ui"}\n', "src/Card.tsx": "export const Card = () => 1\n",
             "src/Card.stories.tsx": "export default { title: 'Card' }\n", "src/api.mock.ts": "export const m = 1\n",
             "spec/fixtures/state.ts": "export const s = 1\n", "playwright/login.ts": "export const l = 1\n",
             "src/__mocks__/x.ts": "export const x = 1\n", "src/List.testHelpers.tsx": "export const h = 1\n"}
    s = structure.build(make_repo(files))
    assert sorted(s["files"]) == ["src/Card.tsx"]


def test_comparisons_are_never_blanked():
    for src in (b"for (let i = 0; i<arr.length; i++) {\n  if (arr[i] > `${limit}`) go()\n}\n",
                b"const v = a<b ? {k: 1} : c > `z`\n"):
        assert generic.parseable(src, "typescript") == src


def test_a_testnet_config_is_app_code(make_repo):
    s = structure.build(make_repo({"package.json": '{"name": "w"}\n', "src/config.testnet.ts": "export const n = 1\n"}))
    assert "src/config.testnet.ts" in s["files"]
