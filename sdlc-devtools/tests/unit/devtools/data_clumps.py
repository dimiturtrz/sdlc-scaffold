"""Unit tests for devtools/data_clumps.py — Fowler data clumps (maximal travelling param sets).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import sys

import pytest

from devtools import data_clumps
from devtools.data_clumps import DataClumps


@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [
        # {a,b,c} carried WHOLE by 4 functions -> a clump at support 4 (>= the _MIN_SUPPORT default). The
        # extra param on three of them is the point: support is a SUPERSET test, not signature equality.
        (
            "pos",
            "def f1(a, b, c): pass\ndef f2(a, b, c, d): pass\ndef f3(a, b, c, e): pass\ndef f4(a, b, c, g): pass\n",
            [(4, ("a", "b", "c"), 3)],
        ),
        # One function short of the threshold reports NOTHING. Three co-occurrences is coincidence; the whole
        # engine's value is that it stays quiet below the bar rather than flooding a review with near-misses.
        ("neg", "def f1(a, b, c): pass\ndef f2(a, b, c): pass\ndef f3(a, b, c): pass\n", []),
        # 4 functions all carry {a,b,c,d}: only the MAXIMAL set survives. Its {a,b,c} subset has the same
        # support, and reporting both would bury the real travelling tuple under its own combinations —
        # this is the difference between one finding and the four a naive subset count would emit.
        ("max", "".join(f"def f{i}(a, b, c, d): pass\n" for i in range(4)), [(4, ("a", "b", "c", "d"), 4)]),
        # Below _MIN_PARAMS a signature cannot even seed a candidate, so a pair repeated ten times is silent:
        # a two-param clump is just a long-arg smell, which ruff's PLR0913 already owns.
        ("pair", "".join(f"def f{i}(a, b): pass\n" for i in range(10)), []),
        # self/cls never travel — every method in a class would otherwise share them and hub every clump.
        (
            "self",
            "class K:\n" + "".join(f"    def m{i}(self, a, b, c): pass\n" for i in range(4)),
            [(4, ("a", "b", "c"), 3)],
        ),
    ],
)
def test_clumps(write_pkg, tmp_path, name, source, expected):
    rows = DataClumps([write_pkg(tmp_path, f"clump_{name}", source)]).clumps()
    assert [(support, params, size) for support, params, size, _ in rows] == expected
    for _support, _params, _size, files in rows:
        assert files and all(f.endswith(".py") for f in files), "each row names example files a reader can open"


def test_clumps_tuning_moves_the_threshold(write_pkg, tmp_path):
    """The two knobs are the CLI's whole surface, so a default-only test would leave both flags unproven.

    Lowering `min_support` must surface what the default suppressed and raising it must silence what the
    default found — a knob that only ever moves one way is indistinguishable from one that is ignored.
    """
    src = "def f1(a, b, c): pass\ndef f2(a, b, c): pass\ndef f3(a, b, c): pass\n"
    engine = DataClumps([write_pkg(tmp_path, "clump_tune", src)])
    assert engine.clumps() == [], "support 3 is below the default of 4"
    assert {p for _s, p, _n, _f in engine.clumps(min_support=3)} == {("a", "b", "c")}, "lowering the bar finds it"
    assert engine.clumps(min_support=3, min_clump=4) == [], "a clump smaller than min_clump cannot be reported"


def test_report(write_pkg, tmp_path):
    """The uniform explorer view every engine answers to — a count line plus the ranked table.

    It carries the same tuning as `clumps` so the CLI passes flags to ONE method; the parametrized knobs
    below are what stops the report growing a second, drifting notion of what counts as a clump.
    """
    src = "def f1(a, b, c): pass\ndef f2(a, b, c, d): pass\ndef f3(a, b, c, e): pass\ndef f4(a, b, c, g): pass\n"
    engine = DataClumps([write_pkg(tmp_path, "clump_report", src)])
    lines = engine.report().splitlines()
    assert lines[0] == "1 data clumps", "the headline is the row COUNT, so a reader sees the scale first"
    assert lines[1].split() == ["supp", "size", "clump", "(params", "that", "travel", "together)", "examples"]
    assert "a, b, c" in lines[2], "the travelling tuple is spelled out, not just counted"
    assert lines[2].split()[:2] == ["4", "3"], "support then size, matching the header order"
    assert "mod.py" in lines[2], "and an example file to open"

    # Same tuning as `clumps`, or the CLI's flags would mean different things through the two entry points.
    empty = engine.report(min_support=5)
    assert empty.startswith("0 data clumps"), "nothing above the raised bar"
    assert len(empty.splitlines()) == 2, "the header row survives an empty table — an empty result is not a blank"


def test_data_clumps_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.data_clumps"])
    with pytest.raises(SystemExit) as exc:
        data_clumps.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
