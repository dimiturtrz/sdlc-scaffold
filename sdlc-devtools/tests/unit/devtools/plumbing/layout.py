"""Unit tests for devtools/layout.py — where a module's unit test lives.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

from pathlib import Path

import pytest

from devtools.plumbing.layout import DEFAULT_TEST_ROOT, STRUCTURAL, TestLayout


def test_names():
    """The advertised value set IS the dispatch table — a value that resolves but is not listed would be
    undiscoverable, and one that is listed but does not resolve would be a lie in an error message.

    TWO values, and the count is the assertion: a lenient third that let a repo satisfy the gate without
    adopting the convention would be the RULE varying per repo, which the o70 union law rejects.
    """
    assert TestLayout.names() == ["mirror", "off"]
    for name in TestLayout.names():
        assert TestLayout.of(name) is not None, f"{name} is advertised, so it must resolve"


def test_of():
    """Each value resolves to something answering the whole contract, and an unknown one is a HARD error.

    The last case is the load-bearing one. A typo'd layout falling back to the mirror would gate a tree it
    was never meant to gate; falling back to `off` would turn two gates off and report clean. A config error
    must never be able to look like an answer.
    """
    for name in ("mirror", "off"):
        layout = TestLayout.of(name)
        assert hasattr(layout, "mirror_of") and hasattr(layout, "missing"), f"{name} answers the contract"
    assert TestLayout.of("mirror", "custom/root").test_root.as_posix() == "custom/root"
    assert TestLayout.of("mirror").test_root.as_posix() == DEFAULT_TEST_ROOT
    with pytest.raises(SystemExit, match="unknown test_layout"):
        TestLayout.of("mirrror")
    # The layouts that USED to exist must not silently resolve — a repo carrying an old value in its
    # pyproject has to be told, not quietly re-gated against a different rule.
    for gone in ("bare", "flat"):
        with pytest.raises(SystemExit, match="unknown test_layout"):
            TestLayout.of(gone)


# `mirror_of` and `missing` are polymorphic: each strategy overrides them with its own behaviour, so each
# override is its own public member with its own named test (bd kai). The abstract `TestLayout` versions are
# declarations (they raise NotImplementedError), so they need no test of their own.


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        # The test file carries the MODULE's name — that is what makes the path a mirror.
        ("pkg/store.py", "tests/unit/pkg/store.py"),
        ("pkg/deep/nested.py", "tests/unit/pkg/deep/nested.py"),
    ],
)
def test_mirror_mirror_of(module, expected):
    """`_Mirror.mirror_of` — the strict path mirror always names a file, mirroring the module's own path."""
    assert TestLayout.of("mirror").mirror_of(Path(module)).as_posix() == expected


def test_off_mirror_of():
    """`_Off.mirror_of` — demands nothing and so names no file, exactly when the METHOD-level gate has
    nowhere to look and must stand down rather than guess."""
    assert TestLayout.of("off").mirror_of(Path("pkg/store.py")) is None


def test_mirror_missing(tmp_path, monkeypatch):
    """`_Mirror.missing` — the file-level finding, over both outcomes.

    Driven through a real tree rather than a stubbed `exists`, because the thing under test IS a filesystem
    question — a double here would be asserting that our arithmetic matches itself.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text("")
    (tmp_path / "pkg" / "lonely.py").write_text("")
    (tmp_path / "tests" / "unit" / "pkg").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "pkg" / "store.py").write_text("")

    convention = TestLayout.of("mirror")
    assert convention.missing(Path("pkg/store.py")) is None, "a present mirror is covered"
    finding = convention.missing(Path("pkg/lonely.py"))
    assert finding is not None and "lonely.py" in finding, "the finding names the module"

    # One home per module: a same-purpose test under another name, or at another path, does not count.
    (tmp_path / "tests" / "unit" / "pkg" / "test_lonely.py").write_text("")
    (tmp_path / "tests" / "somewhere").mkdir(parents=True)
    (tmp_path / "tests" / "somewhere" / "lonely.py").write_text("")
    assert convention.missing(Path("pkg/lonely.py")) is not None, "neither the prefix nor a stray path counts"


def test_off_missing():
    """`_Off.missing` — demands nothing, so it never reports a module as uncovered."""
    assert TestLayout.of("off").missing(Path("pkg/lonely.py")) is None


def test_testable(tmp_path, monkeypatch):
    """Which modules the rule covers at all — package plumbing and coverage-omitted shells are exempt.

    This lives on the layout rather than on either gate so the file-level and method-level mirrors cannot
    disagree about the population; a tree reading as covered from one gate and uncovered from the other
    would give no way to tell which is lying.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.coverage.run]\nomit = ["pkg/shell.py"]\n')
    (tmp_path / "pkg").mkdir()
    for name in ("logic.py", "shell.py", *STRUCTURAL):
        (tmp_path / "pkg" / name).write_text("")

    covered = {p.name for p in TestLayout.testable(["pkg"])}
    assert covered == {"logic.py"}, "plumbing and omitted shells are not forced to carry a stub test"
    assert TestLayout.testable([]) == [], "no packages is no findings, not an error"
