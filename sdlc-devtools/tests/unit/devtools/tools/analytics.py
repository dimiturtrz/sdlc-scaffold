"""Unit tests for devtools/analytics.py — the code-size / complexity explorer's counting logic.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import logging
from pathlib import Path

import pytest

from devtools.tools.analytics import Analytics, AreaStat, FileStat

# One area's worth of source, sized so every derived number below is checkable by hand: 2 defs, 4 branch
# nodes (If, comprehension, BoolOp, For), 7 code lines out of 10 physical.
_SNIPPET = (
    "# a comment (not counted)\n"
    "\n"  # blank (not counted)
    "def f(x):\n"  # def 1
    "    if x:\n"  # branch: If
    "        return [i for i in x]\n"  # branch: comprehension
    "    return x and 1\n"  # branch: BoolOp
    "\n"
    "def g():\n"  # def 2
    "    for _ in range(3):\n"  # branch: For
    "        pass\n"
)


@pytest.fixture
def repo(tmp_path):
    """A repo tree with two real areas, one absent area, a nested module, a __pycache__ to be skipped, and a
    tests/ dir — the INPUT only; every count this file asserts is written out by hand in the test."""
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text(_SNIPPET, encoding="utf-8")
    (tmp_path / "core" / "deep").mkdir()
    (tmp_path / "core" / "deep" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "core" / "__pycache__").mkdir()
    (tmp_path / "core" / "__pycache__" / "a.py").write_text(_SNIPPET, encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "c.py").write_text("def h(a, b):\n    return a\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
    return tmp_path


def _area(*counts: tuple[int, int, int]) -> AreaStat:
    """An area over hand-written per-file (code_lines, defs, branches) — the INPUT only.

    Built from real `FileStat`s rather than from `analyze_file`, because the three rollups below are pure
    arithmetic over that list: routing them through the AST counters would make a wrong sum and a wrong
    count look identical, and it is `test_analyze_file` that owns the counting.
    """
    return AreaStat("area", [FileStat(Path(f"f{i}.py"), *counts_i) for i, counts_i in enumerate(counts)])


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([(7, 2, 4), (1, 0, 0)], 8),
        ([(3, 1, 2), (5, 2, 0), (1, 0, 1)], 9),
        # An area with no files sums to 0 rather than raising: `analyze` builds a stat per existing
        # directory, and a directory holding no .py files is a real, reportable zero row.
        ([], 0),
        ([(0, 0, 0), (0, 0, 0)], 0),
    ],
)
def test_code_lines(counts, expected):
    """The area's size, summed over its files — the row the report prints and the denominator of the
    src-vs-test ratio, so a rollup that dropped a file would quietly flatter every ratio in the report."""
    assert _area(*counts).code_lines == expected


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([(7, 2, 4), (1, 0, 0)], 2),
        ([(3, 1, 2), (5, 2, 0), (1, 0, 1)], 3),
        ([], 0),
        # A file with no defs still counts as a file — module-level script code must not vanish from the
        # rollup, or complexity-per-def would divide by a def count that excluded it.
        ([(4, 0, 0)], 0),
    ],
)
def test_defs(counts, expected):
    assert _area(*counts).defs == expected


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([(7, 2, 4), (1, 0, 0)], 4),
        ([(3, 1, 2), (5, 2, 0), (1, 0, 1)], 3),
        ([], 0),
        # Branch-free files sum to 0 branches, not to their def count — the two are independent axes, and
        # complexity-per-def is the number this engine exists to watch.
        ([(4, 3, 0)], 0),
    ],
)
def test_branches(counts, expected):
    assert _area(*counts).branches == expected


def test_analyze_file(tmp_path):
    """The three counters, on one snippet where each is small enough to verify by reading.

    `branches` is the one worth pinning: it is a McCabe-style DECISION-POINT proxy, so a comprehension and a
    boolean operator count as branches even though neither is an `if`. Miss those and complexity-per-def —
    the number this whole engine exists to watch — silently under-reports the leaf functions it is meant to
    catch logic leaking into.
    """
    path = tmp_path / "snippet.py"
    path.write_text(_SNIPPET, encoding="utf-8")
    stat = Analytics.analyze_file(path)
    assert stat.path == path, "the stat carries the file it came from — the report prints it"
    assert stat.defs == 2, "f, g"
    assert stat.branches == 4, "If, comprehension, BoolOp, For"
    assert stat.code_lines == 7, "10 lines - 1 comment - 2 blank"

    empty = tmp_path / "empty.py"
    empty.write_text("", encoding="utf-8")
    assert (Analytics.analyze_file(empty).defs, Analytics.analyze_file(empty).branches) == (0, 0)


def test_analyze(repo):
    """Areas rolled up from files, with the two exclusions that decide whether the numbers mean anything.

    A missing area is SKIPPED rather than reported as an empty one: `--areas` is a generic default list, so a
    repo that has no `src/` must not have a zero row dilute its own totals. And a `__pycache__` copy of a
    module would double every count in that area — the compiled mirror is the same source twice.
    """
    stats = Analytics(repo, ["core", "app", "absent"]).analyze()
    assert [a.name for a in stats] == ["core", "app"], "an area that is not a directory is skipped, not empty"

    core = stats[0]
    assert [f.path.name for f in core.files] == ["a.py", "b.py"], "rglob is recursive, sorted, no __pycache__"
    assert (core.code_lines, core.defs, core.branches) == (8, 2, 4), "the area is the sum of its files"
    assert (stats[1].code_lines, stats[1].defs, stats[1].branches) == (2, 1, 0)
    assert Analytics(repo, []).analyze() == [], "no areas is no stats, not an error"


def test_report(repo, caplog):
    """The explorer's whole output, read off the log it writes to.

    Asserted on the emitted TEXT because that text is the product — this engine returns nothing, so the
    report IS the state it produces. The `flag_over` half is the load-bearing case: it is the only part that
    is conditional, and a budget nobody is over must still print its (empty) section rather than vanish and
    leave the reader unable to tell "clean" from "not run".
    """
    caplog.set_level(logging.INFO, logger="devtools.tools.analytics")
    Analytics(repo, ["core", "app"]).report(top_n=1, flag_over=5)
    text = caplog.text
    assert "core" in text and "app" in text, "every area gets a row"
    assert "src 10 : test 2" in text, "src is the sum over areas; tests/ is counted separately"
    assert "ratio 0.20" in text, "2 test lines / 10 src lines — the number the header exists to show"
    assert "top 1 largest" in text, "top_n is honoured rather than fixed at its default"
    assert text.count("a.py") >= 1 and "b.py" not in text, "top_n=1 lists ONLY the largest file"
    assert "1 file(s) over 5 code lines" in text, "a.py at 8 lines is over the budget; b.py and c.py are not"

    caplog.clear()
    Analytics(repo, ["core"]).report()
    assert "over" not in caplog.text, "no --flag-over means the budget section is not printed at all"
    assert "top 10 largest" in caplog.text, "the default top_n still reports"

    caplog.clear()
    Analytics(repo, ["absent"]).report()
    assert "src 0 : test 2" in caplog.text, "zero src lines must not divide by zero — the ratio degrades to 0"
    assert "ratio 0.00" in caplog.text


def test_code_lines_excludes_blank_and_comment():
    assert Analytics._code_lines("a = 1\n# c\n\n   \nb = 2\n") == 2, "only the two assignments count"
