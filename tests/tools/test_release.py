import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import release  # noqa: E402

TEXT = '{"metadata": {"version": "1.1.1"}, "plugins": [{"name": "x", "version": "1.1.1", "keywords": ["a", "b"]}]}'


def test_bump_sets_both_fields_and_keeps_the_rest():
    out = release.bump(TEXT, "1.2.0")
    assert release.versions(out) == ["1.2.0", "1.2.0"]
    assert out == TEXT.replace("1.1.1", "1.2.0")


@pytest.mark.parametrize("new", ["1.1.1", "1.1.0", "0.9.9"])
def test_bump_refuses_a_version_not_above_the_current(new):
    with pytest.raises(ValueError, match="not above"):
        release.bump(TEXT, new)


def test_bump_refuses_fields_that_disagree():
    with pytest.raises(ValueError, match="disagree"):
        release.bump(TEXT.replace('"version": "1.1.1", "keywords"', '"version": "1.1.0", "keywords"'), "1.2.0")


def test_the_marketplace_fields_agree():
    assert len(set(release.versions(release.MARKETPLACE.read_text()))) == 1
