"""Unit tests for devtools/complexity.py — radon-backed cyclomatic-complexity ranking (advisory)."""

from devtools.complexity import Complexity


def test_complexity_ranks_functions_by_cc(write_pkg, tmp_path):
    # a branchy function (CC grows with each if) must outrank a straight-line one
    src = (
        "def straight():\n    return 1\n\n"
        "def branchy(x):\n"
        "    if x > 0:\n        return 1\n"
        "    if x > 1:\n        return 2\n"
        "    if x > 2:\n        return 3\n"
        "    return 0\n"
    )
    pkg = write_pkg(tmp_path, "cx_rank", src)
    rows = Complexity([pkg]).scan()
    top_cc, _, top_name = rows[0]
    assert top_name == "branchy", f"the branchy function must rank highest, got {rows}"
    assert top_cc == 4, f"three ifs -> CC 4 (1 base + 3 branches), got {top_cc}"


def test_complexity_flattens_methods_skips_class_aggregate(write_pkg, tmp_path):
    # radon emits a Class aggregate alongside its methods; scan must count methods, not the aggregate
    src = "class C:\n    def a(self):\n        return 1\n    def b(self, x):\n        if x:\n            return 1\n        return 0\n"
    pkg = write_pkg(tmp_path, "cx_methods", src)
    names = sorted(name for _, _, name in Complexity([pkg]).scan())
    assert names == ["a", "b"], f"methods flattened, no 'C' class-aggregate row, got {names}"


def test_complexity_report_shows_max(write_pkg, tmp_path):
    pkg = write_pkg(tmp_path, "cx_report", "def f(x):\n    if x:\n        return 1\n    return 0\n")
    report = Complexity._render(Complexity([pkg]).scan())
    assert "max cyclomatic complexity 2" in report, report
    # an empty scan reports max 0 (advisory-safe, no crash on a code-less tree)
    assert "max cyclomatic complexity 0" in Complexity._render([])
