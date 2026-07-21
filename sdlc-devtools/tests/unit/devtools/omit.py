"""Unit tests for devtools/omit.py — the coverage-omit glob reader + matcher (the 'non-logic shell' set).

Method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a dense
container of parameter combinations rather than one case per behaviour.
"""

import pytest

from devtools.omit import Omit


def test_coverage_omit(tmp_path):
    """Reading the globs out of pyproject, over every shape of an ABSENT declaration.

    The three "empty" rows are the load-bearing ones and they are not the same case: no file at all (a
    consumer repo running a gate from the wrong cwd), a file with no `[tool.coverage]`, and a `coverage`
    table with no `run.omit`. All three must yield `[]` rather than raise — an exception here would take
    down every arch gate that asks "is this module a shell?" on a repo that simply omits nothing.
    """
    absent = tmp_path / "absent.toml"
    no_section = tmp_path / "no_section.toml"
    no_section.write_text('[project]\nname = "x"\n')
    no_omit = tmp_path / "no_omit.toml"
    no_omit.write_text("[tool.coverage.run]\nbranch = true\n")
    declared = tmp_path / "declared.toml"
    declared.write_text('[tool.coverage.run]\nomit = ["a/*.py", "b/**"]\n')

    assert Omit.coverage_omit(str(declared)) == ["a/*.py", "b/**"], "globs come back in declaration order"
    for path, why in (
        (absent, "an absent file omits nothing"),
        (no_section, "no [tool.coverage] omits nothing"),
        (no_omit, "a coverage table without `omit` omits nothing"),
    ):
        assert Omit.coverage_omit(str(path)) == [], why


@pytest.mark.parametrize(
    ("path", "patterns", "expected"),
    [
        # `*` is one segment. This pair is the whole reason the matcher is hand-rolled rather than
        # `fnmatch`, whose `*` happily crosses `/` and would swallow every nested module under `pkg/`.
        ("pkg/runner.py", ["pkg/*.py"], True),
        ("pkg/sub/runner.py", ["pkg/*.py"], False),
        # `**` is the opt-in for crossing segments — the spelling coverage itself uses for a whole subtree.
        ("pkg/sub/deep.py", ["pkg/**"], True),
        ("pkg/shallow.py", ["pkg/**"], True),
        ("pkg/keep.py", ["other/*.py"], False),
        # Anchored at BOTH ends: a pattern is not a substring search. Without the `$` anchor `pkg/*.py`
        # would match `pkg/runner.py.bak`; without `^`, `runner.py` would match `vendor/pkg/runner.py`.
        ("pkg/runner.py.bak", ["pkg/*.py"], False),
        ("vendor/pkg/runner.py", ["pkg/*.py"], False),
        # Windows call sites hand this backslashed paths from `Path`; both sides normalise, or the gate
        # would report every module as non-omitted on one OS and correctly on the other.
        (r"pkg\runner.py", ["pkg/*.py"], True),
        ("pkg/runner.py", [r"pkg\*.py"], True),
        # Regex metacharacters in a glob are LITERAL — `.` must not act as "any character".
        ("pkgXrunner.py", ["pkg/runner.py"], False),
        # Any pattern matching is enough; none matching (and the empty list) is a silent no.
        ("pkg/runner.py", ["other/**", "pkg/*.py"], True),
        ("pkg/runner.py", [], False),
    ],
)
def test_matches_omit(path, patterns, expected):
    assert Omit.matches_omit(path, patterns) is expected
