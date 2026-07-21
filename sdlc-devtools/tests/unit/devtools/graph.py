"""Unit tests for devtools/graph.py — the arch-fitness gate + Martin stability metrics + test-mirror.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import sys

import networkx as nx
import pytest

from devtools.graph import ImportGraph

_DEFAULTS = {
    "bottleneck_degree": 8,
    "file_max": 750,
    "file_min": 0,
    "betweenness_max": 0.10,
    "main_sequence_max": 0.0,
    "test_layout": "mirror",
}


def test_load_structure_cfg(tmp_path):
    """Merge-over-defaults, and the two ways a config can LIE — both of which must raise, never fall back.

    A silently-ignored override is a config's worst failure mode: `bottlneck_degree = 20` would leave the
    gate on its default and the repo would read as PASSING at a threshold nobody set. Same silent-typo shape
    as the contracts bug `malformed()` exists to stop. A wrong TYPE is the same failure one step later — the
    threshold reaches a gate that compares it numerically, so a string there is a crash or a skipped compare.
    """
    assert ImportGraph.load_structure_cfg(str(tmp_path / "nope.toml")) == _DEFAULTS, "absent file -> all defaults"

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.structure]\nfile_max = 500\n")
    cfg = ImportGraph.load_structure_cfg(str(pyproject))
    assert cfg["file_max"] == 500, "an explicit threshold overrides the default"
    assert cfg["bottleneck_degree"] == 8, "an unspecified threshold keeps the default"

    for body, match in (
        ("[tool.structure]\nbottlneck_degree = 20\n", "unknown key 'bottlneck_degree'"),
        ('[tool.structure]\nfile_max = "750"\n', "'file_max' must be int, got str"),
    ):
        pyproject.write_text(body)
        with pytest.raises(ValueError, match=match):
            ImportGraph.load_structure_cfg(str(pyproject))


def test_god_module_detected():
    g = nx.DiGraph()
    for i in range(9):  # fan-in 9 and fan-out 9, both > 8
        g.add_edge(f"in{i}", "god")
        g.add_edge("god", f"out{i}")
    assert ImportGraph._god_modules(g, 8), "fan-in AND fan-out both over the degree is a god-module"
    clean = nx.DiGraph([("a", "b"), ("b", "c")])
    assert ImportGraph._god_modules(clean, 8) == []


def test_import_cycle_detected():
    cyclic = nx.DiGraph([("a", "b"), ("b", "a")])
    assert ImportGraph._cycles(cyclic), "a strongly-connected component >1 is an import cycle"
    assert ImportGraph._cycles(nx.DiGraph([("a", "b"), ("b", "c")])) == []


def test_oversized_file_detected():
    assert ImportGraph._oversized([("big.py", 800)], 750), "a file over the ceiling is a god-file"
    assert ImportGraph._oversized([("small.py", 100)], 750) == []


def test_undersized_floor_advisory():
    assert ImportGraph._undersized([("tiny.py", 3)], 0) == [], "floor OFF at file_min<=0 (the default)"
    assert ImportGraph._undersized([("tiny.py", 3)], 10), "under the floor flags (advisory)"
    assert ImportGraph._undersized([("ok.py", 50)], 10) == [], "above the floor is silent"
    assert ImportGraph._undersized([("pkg/__init__.py", 1)], 10) == [], "package plumbing is exempt"


def test_assert_fitness():
    """The blocking/advisory SPLIT is the contract here — a rule landing in the wrong bucket either blocks a
    repo on an opinion or lets a real defect through as a warning."""
    cfg = dict(_DEFAULTS)
    clean = nx.DiGraph([("a", "b"), ("b", "c")])
    blocking, advisory = ImportGraph.assert_fitness(clean, [("a.py", 100)], cfg)
    assert blocking == [], "a clean graph + small files has no blocking violations"
    # The chokepoint rule is ON by default (betweenness_max 0.10) and `b` sits on the only a->c path, so it
    # fires here — and lands in ADVISORY. That is the point: a chokepoint is a design observation, not a
    # defect, and a rule with no honest universal threshold must never reach the blocking list.
    assert any("chokepoint" in m for m in advisory), advisory

    cyclic = nx.DiGraph([("a", "b"), ("b", "a")])
    blocking, _ = ImportGraph.assert_fitness(cyclic, [("big.py", 900)], cfg)
    assert len(blocking) == 2, f"a cycle AND an oversized file are two separate findings, got {blocking}"

    # Opting into the line floor must move the finding into ADVISORY, never into blocking.
    blocking, advisory = ImportGraph.assert_fitness(clean, [("tiny.py", 3)], {**cfg, "file_min": 10})
    assert blocking == [] and advisory, "the line floor is advisory even once opted into"


def test_instability():
    g = nx.DiGraph()
    for src in ("a", "b", "c"):  # X imported by a,b,c (Ca=3) and imports Y (Ce=1) -> I = 1/(1+3)
        g.add_edge(src, "X")
    g.add_edge("X", "Y")
    inst = ImportGraph.instability(g)
    assert inst["X"] == 0.25, "I = Ce/(Ce+Ca) = out/(out+in)"
    assert inst["Y"] == 0.0, "Y only depended-on (Ce=0) -> maximally stable"
    assert inst["a"] == 1.0, "a only depends (Ca=0) -> maximally unstable"
    # An isolated node has I undefined (0/0) and must be SKIPPED, not reported as 0.0 — a module nobody
    # touches is not "maximally stable", and emitting it would put noise at the top of the stability table.
    isolated = nx.DiGraph()
    isolated.add_node("lonely")
    assert "lonely" not in ImportGraph.instability(isolated)


def test_is_abstract_detects_abc_metaclass_abstractmethod(make_cls):
    assert ImportGraph._is_abstract(make_cls("class I(ABC):\n    pass\n"))
    assert ImportGraph._is_abstract(make_cls("class M(metaclass=ABCMeta):\n    pass\n"))
    assert ImportGraph._is_abstract(make_cls("class A:\n    @abstractmethod\n    def go(self): ...\n"))
    assert not ImportGraph._is_abstract(make_cls("class C:\n    def go(self):\n        return 1\n"))


def test_abstractness(tmp_path, monkeypatch):
    """A = abstract/total classes, plus the two ways A is UNDEFINED — both must be None, not 0.0.

    0.0 would place a class-less module at D=|0+I-1| and rank it in the main-sequence table as if it were a
    measured concrete module; None keeps unmeasurable modules out of the ranking entirely.
    """
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(
        "from abc import ABC\nclass I(ABC): ...\nclass C:\n    def go(self):\n        return 1\n"
    )
    assert ImportGraph.abstractness("pkg.mod") == 0.5, "1 abstract + 1 concrete -> A = 0.5"
    (pkg / "allabc.py").write_text("from abc import ABC\nclass I(ABC): ...\nclass J(ABC): ...\n")
    assert ImportGraph.abstractness("pkg.allabc") == 1.0, "every class abstract -> A = 1"
    (pkg / "noclass.py").write_text("X = 1\n")
    assert ImportGraph.abstractness("pkg.noclass") is None, "no classes -> A undefined"
    assert ImportGraph.abstractness("pkg.missing") is None, "no backing file -> None"
    # A package resolves through its __init__.py, so a dotted name need not name a .py file directly.
    assert ImportGraph.abstractness("pkg") is None, "an empty __init__ has no classes -> undefined, not a crash"


def test_main_sequence_distance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "leaf.py").write_text("class C:\n    def go(self):\n        return 1\n")  # concrete, A=0
    (pkg / "noclass.py").write_text("X = 1\n")
    g = nx.DiGraph()
    g.add_edge("importer", "pkg.leaf")  # leaf depended-on only: Ca=1, Ce=0 -> I=0 -> D=|0+0-1|=1.0
    g.add_edge("importer", "pkg.noclass")
    d = ImportGraph.main_sequence_distance(g)
    assert d["pkg.leaf"] == 1.0
    assert "pkg.noclass" not in d, "A undefined -> D undefined; the module is omitted, not scored at 0"
    assert "importer" not in d, "no backing file -> omitted too"
    assert ImportGraph._off_main_sequence(g, 0.0) == [], "OFF by default (a concrete stable leaf sits at D≈1)"
    assert ImportGraph._off_main_sequence(g, 0.7), "opt in with a threshold -> the far-off module surfaces"


def test_unmirrored(tmp_path, monkeypatch):
    """The file-level test-mirror finding across every layout, plus the two exemptions.

    ONE HOME per module, which is what makes this checkable: the test file carries the module's name at the
    mirror path, and nothing else counts. A lenient "a test named for it exists somewhere" mode used to sit
    beside this and was removed — that is not a threshold, it is the rule meaning something else per repo.
    """
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "foo.py").write_text("class Foo:\n    @staticmethod\n    def go(): ...\n")
    engine = ImportGraph(["pkg"])

    assert engine.unmirrored(), "a logic module with no mirror test must be flagged"
    assert all("__init__" not in m for m in engine.unmirrored()), "package plumbing is never a finding"
    assert engine.unmirrored("off") == [], "off = no test-existence gate"

    # Neither a stray path nor the pytest prefix satisfies the mirror — one home, and it is this one.
    (tmp_path / "tests" / "unit" / "pkg").mkdir(parents=True)
    (tmp_path / "tests" / "foo.py").write_text("def test_go(): pass\n")
    (tmp_path / "tests" / "unit" / "pkg" / "test_foo.py").write_text("def test_go(): pass\n")
    assert engine.unmirrored(), "a test elsewhere, or under the old prefix, is not the mirror"

    (tmp_path / "tests" / "unit" / "pkg" / "foo.py").write_text("def test_go(): pass\n")
    assert engine.unmirrored() == [], "a module with its strict path-mirror test is satisfied"
    # test_root moves where the mirror is LOOKED FOR, so the same satisfied tree is a finding again under a
    # different root — the root is part of the convention, not a search path that falls back to the default.
    assert engine.unmirrored("mirror", "tests/other") == ["pkg/foo.py — no mirrored tests/other/pkg/foo.py"]

    # A coverage-omitted shell is out of the population entirely — the same exemption the method-level gate
    # reads, so the two mirrors cannot disagree about what is covered.
    (tmp_path / "pyproject.toml").write_text('[tool.coverage.run]\nomit = ["pkg/shell.py"]\n')
    (pkg / "shell.py").write_text("class Shell:\n    @staticmethod\n    def run(): ...\n")
    assert ImportGraph(["pkg"]).unmirrored() == [], "a coverage-omitted shell needs no mirror test"


def test_graph_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.graph"])
    with pytest.raises(SystemExit) as exc:
        from devtools import graph

        graph.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"


# ---- metrics as EDGE-SUBSET queries (bd 4bl.4) -------------------------------------------------------


_USAGE_SRC = {
    "dep.py": "class Dep:\n    def go(self) -> None: ...\n",
    "user.py": (
        "from usage_pkg.dep import Dep\n\n\n"
        "class User:\n"
        "    def __init__(self, dep: Dep):\n        self._dep = dep\n\n"
        "    def run(self) -> None:\n        self._dep.go()\n"
    ),
}


def _usage_pkg(monkeypatch, tmp_path):
    package = tmp_path / "usage_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for name, src in _USAGE_SRC.items():
        (package / name).write_text(src)
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return ImportGraph(["usage_pkg"])


def test_build_graph(monkeypatch, tmp_path):
    """The honest import DiGraph via grimp — direction is the load-bearing fact.

    Edges run importer -> imported, which is what makes in_degree afferent coupling (Ca) and out_degree
    efferent (Ce). Reversed, every instability score inverts and the whole stability table means the
    opposite, silently — nothing downstream could detect it, so it is pinned here.
    """
    g = _usage_pkg(monkeypatch, tmp_path).build_graph()
    assert g.has_edge("usage_pkg.user", "usage_pkg.dep"), "user imports dep, so the edge points user -> dep"
    assert not g.has_edge("usage_pkg.dep", "usage_pkg.user"), "and NOT the other way — direction is the metric"
    assert {"usage_pkg", "usage_pkg.dep", "usage_pkg.user"} <= set(g), "every module is a node, edges or not"
    assert dict(g.in_degree())["usage_pkg.dep"] == 1, "Ca counts the importers"


def test_file_lines(monkeypatch, tmp_path):
    """(path, line-count) for every .py — the file-shape axis the import graph cannot see.

    Counted as `\\n` + 1, so a file with no trailing newline still counts its last line; the god-file gate
    compares this against `file_max`, and an off-by-one there is a threshold nobody agreed to.
    """
    engine = _usage_pkg(monkeypatch, tmp_path)
    (tmp_path / "usage_pkg" / "three.py").write_text("a = 1\nb = 2\nc = 3\n")
    (tmp_path / "usage_pkg" / "nonewline.py").write_text("a = 1")
    lines = dict(engine.file_lines())
    by_name = {k.replace("\\", "/").rsplit("/", 1)[-1]: v for k, v in lines.items()}
    assert by_name["three.py"] == 4, f"three lines + the trailing newline, got {by_name['three.py']}"
    assert by_name["nonewline.py"] == 1, "a single unterminated line still counts as one"
    assert "__init__.py" in by_name, "every .py is measured — the ceiling applies to plumbing too"
    assert all(n >= 1 for n in by_name.values()), "no file measures zero lines"


def test_typed_graph(monkeypatch, tmp_path):
    """A CLASS-level graph over one arrow subset — the same metrics, a different question.

    The ranking functions never cared what an edge MEANT; they were only ever handed imports. Given a
    kind-filtered subset they answer real USAGE coupling, which import fan-in only approximates (importing
    is not using, and a type-only import counts the same as a call).
    """
    engine = _usage_pkg(monkeypatch, tmp_path)
    usage = engine.typed_graph({"calls"})
    assert "usage_pkg.user.User" in usage and "usage_pkg.dep.Dep" in usage, "nodes are CLASSES here"
    assert usage.has_edge("usage_pkg.user.User", "usage_pkg.dep.Dep")

    holds_only = engine.typed_graph({"holds"})
    assert holds_only.has_edge("usage_pkg.user.User", "usage_pkg.dep.Dep"), "User HOLDS a Dep"
    assert engine.typed_graph({"inherits"}).number_of_edges() == 0, "nothing inherits here"
    assert engine.typed_graph(set()).number_of_edges() == 0, "no kinds selected is an empty graph, not all of them"

    # Reusing the ranking code is the point — the metrics run unchanged over the subset.
    assert dict(usage.in_degree())["usage_pkg.dep.Dep"] == 1
    assert ImportGraph.instability(usage)["usage_pkg.user.User"] == 1.0, "a pure consumer is maximally unstable"


def test_report_labels_whatever_subset_it_is_given(monkeypatch, tmp_path):
    engine = _usage_pkg(monkeypatch, tmp_path)
    text = ImportGraph._render(engine.typed_graph({"calls"}), top=3, label="usage graph (calls)", unit="classes")
    assert text.startswith("usage graph (calls): 2 classes"), text.splitlines()[0]
    assert "fan-in (load-bearing):" in text, "the same tables, a different question"


def test_report(monkeypatch, tmp_path):
    """The one-shot explorer: the import tier, then the class-level `calls` tier when there is one.

    The second block is conditional on there BEING usage edges, which is the case worth pinning — a repo
    with no resolvable class arrows must get a clean single-block report, not an empty table captioned as
    if it had measured something.
    """
    engine = _usage_pkg(monkeypatch, tmp_path)
    text = engine.report(top=5)
    assert text.startswith("import graph: 3 modules"), text.splitlines()[0]
    assert "usage graph (calls):" in text, "a tree with real class arrows gets the second, class-level block"
    assert "usage_pkg.user.User" in text, "the usage block ranks CLASSES, not modules"
    for table in ("fan-in (load-bearing):", "bottleneck (fan-in x fan-out)", "instability I=Ce/(Ce+Ca)"):
        assert table in text, f"{table} missing from the explorer view"
    assert "import cycles (SCC>1): 0" in text, "a clean tree still states the cycle count rather than omitting it"

    bare = tmp_path / "bare_pkg"
    bare.mkdir()
    (bare / "__init__.py").write_text("")
    (bare / "lone.py").write_text("X = 1\n")
    solo = ImportGraph(["bare_pkg"]).report()
    assert "usage graph (calls):" not in solo, "no class arrows -> no second block, not an empty one"


def test_run_assert(monkeypatch, tmp_path):
    """The gate's exit code, and the `test_mirror` switch that a legitimately test-less tree needs.

    Deliberate that the gates run on the IMPORT graph: it is sound + complete, so a blocking rule cannot
    false-positive. The typed subsets are the explorer side, where an approximate answer is still useful.
    """
    engine = _usage_pkg(monkeypatch, tmp_path)
    assert engine.run_assert(test_mirror=False) == 0, "a clean tree passes; gates unchanged by the query surface"
    assert engine.run_assert() == 1, "with the mirror check on, two untested modules block"

    (tmp_path / "tests" / "unit" / "usage_pkg").mkdir(parents=True)
    for name in ("dep.py", "user.py"):
        (tmp_path / "tests" / "unit" / "usage_pkg" / name).write_text("def test_x(): pass\n")
    assert engine.run_assert() == 0, "once every module has its mirror test the same tree passes"

    # A god-file blocks regardless of the mirror switch — the file-shape axis is independent of tests.
    (tmp_path / "pyproject.toml").write_text("[tool.structure]\nfile_max = 1\n")
    assert ImportGraph(["usage_pkg"]).run_assert(test_mirror=False) == 1, "an oversized file blocks on its own"
