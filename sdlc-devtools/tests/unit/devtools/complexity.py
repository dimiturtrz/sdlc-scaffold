"""Unit tests for devtools/complexity.py — radon-backed cyclomatic-complexity ranking (advisory).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

from devtools.complexity import Complexity

# A branchy function against a straight-line one — CC grows by 1 per branch, so `branchy` must outrank.
_RANK_SRC = (
    "def straight():\n    return 1\n\n"
    "def branchy(x):\n"
    "    if x > 0:\n        return 1\n"
    "    if x > 1:\n        return 2\n"
    "    if x > 2:\n        return 3\n"
    "    return 0\n"
)

# radon emits a `Class` aggregate block alongside its methods; the scan must count the METHODS and drop the
# aggregate, or every class silently contributes a phantom high-CC row that outranks real functions.
_METHOD_SRC = "class C:\n    def a(self):\n        return 1\n    def b(self, x):\n        if x:\n            return 1\n        return 0\n"


def test_scan(write_pkg, tmp_path):
    """Ranking, CC arithmetic, and the class-aggregate exclusion — the three things `scan` decides."""
    rows = Complexity([write_pkg(tmp_path, "cx_rank", _RANK_SRC)]).scan()
    top_cc, top_loc, top_name = rows[0]
    assert top_name == "branchy", f"the branchy function must rank highest, got {rows}"
    assert top_cc == 4, f"three ifs -> CC 4 (1 base + 3 branches), got {top_cc}"
    assert [cc for cc, _, _ in rows] == sorted((cc for cc, _, _ in rows), reverse=True), "most complex first"
    # The location is 'path:line' so a reviewer can jump straight to the function, not just learn its name.
    assert top_loc.endswith(":4") and "mod.py" in top_loc, top_loc

    names = sorted(name for _, _, name in Complexity([write_pkg(tmp_path, "cx_methods", _METHOD_SRC)]).scan())
    assert names == ["a", "b"], f"methods flattened, no 'C' class-aggregate row, got {names}"

    assert Complexity([write_pkg(tmp_path, "cx_empty", "X = 1\n")]).scan() == [], "no functions, no rows"


def test_report(write_pkg, tmp_path):
    """The explorer view: `report` computes the rows itself, so a caller needs only the engine.

    Load-bearing because three engines reach `report` through the shared CLI — it is the uniform contract,
    and a report that formatted rows it did not compute would make the CLI's single call site a lie.
    """
    pkg = write_pkg(tmp_path, "cx_report", "def f(x):\n    if x:\n        return 1\n    return 0\n")
    report = Complexity([pkg]).report()
    assert "max cyclomatic complexity 2" in report, report
    assert "1 functions" in report, "the header counts what was scanned"
    assert "  f" in report and "mod.py" in report, "the ranked row names the function and where it lives"
    assert report == Complexity._render(Complexity([pkg]).scan()), "report IS render-over-scan, not a variant"


def test_render_on_an_empty_scan(write_pkg, tmp_path):
    """A code-less tree reports max 0 rather than crashing — this is advisory, so it must never be the thing
    that breaks a run."""
    assert "max cyclomatic complexity 0" in Complexity._render([])
    assert "0 functions" in Complexity._render([])
