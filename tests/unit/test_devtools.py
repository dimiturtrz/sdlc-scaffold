"""Unit tests for the shipped devtools fitness functions — the guardrails' own guardrails.

Each tool is tested for LOGIC with a POSITIVE case (must fire) and NEGATIVE cases (must stay silent),
so a test can't pass on a broken tool. The modules are imported from a generated full instance via the
`devtools` fixture (see conftest.py).
"""

import ast

import networkx as nx
import pytest


def _cls(src: str) -> ast.ClassDef:
    """The first class defined in a source snippet."""
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))


# ---- lcom.py — LCOM4 cohesion (8ru) ----------------------------------------------------------------

# two disjoint self-field groups: {a,b} touch self.x, {c,d} touch self.y -> LCOM4 == 2
_SPLIT = """
class Split:
    def a(self):
        return self.x
    def b(self):
        self.x += 1
    def c(self):
        return self.y
    def d(self):
        self.y += 1
"""

# every method touches self.x -> one component -> cohesive
_COHESIVE = """
class Cohesive:
    def a(self):
        return self.x
    def b(self):
        self.x += 1
    def c(self):
        return self.x * 2
"""


def test_lcom4_splits_disjoint_state(devtools):
    lcom = devtools["lcom"]
    score, comps = lcom.lcom4(_cls(_SPLIT))
    assert score == 2, f"two disjoint groups must give LCOM4==2, got {score}: {comps}"
    assert {frozenset(c) for c in comps} == {frozenset({"a", "b"}), frozenset({"c", "d"})}
    assert lcom._is_split_candidate(_cls(_SPLIT)) is not None


def test_lcom4_cohesive_is_one(devtools):
    lcom = devtools["lcom"]
    score, _ = lcom.lcom4(_cls(_COHESIVE))
    assert score == 1, "a class whose methods share a field is cohesive (LCOM4==1)"
    assert lcom._is_split_candidate(_cls(_COHESIVE)) is None


def test_lcom4_skips_interface_impl(devtools):
    lcom = devtools["lcom"]
    # subclasses a DOMAIN base -> its method split just mirrors the contract, not real fusion
    src = "class Backend(BaseStore):\n    def read(self):\n        return self.a\n    def draw(self):\n        return self.b\n"
    assert lcom._is_split_candidate(_cls(src)) is None


def test_lcom4_skips_abstract_and_trivial(devtools):
    lcom = devtools["lcom"]
    abstract = "class I(ABC):\n    def a(self):\n        return self.x\n    def b(self):\n        return self.y\n"
    trivial = "class Stub:\n    def a(self): ...\n    def b(self): ...\n"
    assert lcom._is_split_candidate(_cls(abstract)) is None
    assert lcom._is_split_candidate(_cls(trivial)) is None


def test_lcom4_ignores_fewer_than_two_methods(devtools):
    lcom = devtools["lcom"]
    src = "class One:\n    def a(self):\n        return self.x\n"
    assert lcom._is_split_candidate(_cls(src)) is None


# ---- data_clumps.py — Fowler data clumps (vq7) -----------------------------------------------------


def _write_pkg(root, name, source):
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(source)
    return str(pkg)


def test_data_clumps_finds_maximal_travelling_set(devtools, tmp_path):
    clumps = devtools["data_clumps"].clumps
    # {a,b,c} carried whole by 4 functions -> a clump at support 4 (>= _MIN_SUPPORT)
    src = (
        "def f1(a, b, c): pass\n"
        "def f2(a, b, c, d): pass\n"
        "def f3(a, b, c, e): pass\n"
        "def f4(a, b, c, g): pass\n"
    )
    pkg = _write_pkg(tmp_path, "clump_pos", src)
    rows = clumps([pkg])
    assert rows, "a param set carried by >=4 functions must surface as a clump"
    support, params, size, _ = rows[0]
    assert set(params) == {"a", "b", "c"}
    assert support == 4
    assert size == 3


def test_data_clumps_below_support_is_silent(devtools, tmp_path):
    clumps = devtools["data_clumps"].clumps
    # only 3 functions carry {a,b,c} -> support 3 < 4 -> nothing
    src = "def f1(a, b, c): pass\ndef f2(a, b, c): pass\ndef f3(a, b, c): pass\n"
    pkg = _write_pkg(tmp_path, "clump_neg", src)
    assert clumps([pkg]) == []


def test_data_clumps_reports_maximal_not_subset(devtools, tmp_path):
    clumps = devtools["data_clumps"].clumps
    # 4 functions all carry {a,b,c,d}; the maximal set must win, its {a,b,c} subset must be dropped
    src = "".join(f"def f{i}(a, b, c, d): pass\n" for i in range(4))
    pkg = _write_pkg(tmp_path, "clump_max", src)
    rows = clumps([pkg])
    param_sets = {frozenset(params) for _, params, _, _ in rows}
    assert frozenset({"a", "b", "c", "d"}) in param_sets
    assert frozenset({"a", "b", "c"}) not in param_sets, "a subset at the same support must be suppressed"


# ---- state_candidates.py — namespace latent state (b1a) --------------------------------------------

_BAG = """
class Bag:
    @staticmethod
    def load(cfg, path):
        return cfg
    @staticmethod
    def save(cfg, data):
        return cfg
"""


def test_shared_state_flags_threaded_param(devtools):
    shared_state = devtools["state_candidates"].shared_state
    shared = shared_state(_cls(_BAG))
    assert shared == {"cfg": 2}, f"a param shared by all staticmethods is latent state, got {shared}"


def test_shared_state_skips_stateful_class(devtools):
    shared_state = devtools["state_candidates"].shared_state
    src = (
        "class Stateful:\n"
        "    def __init__(self, cfg):\n"
        "        self.cfg = cfg\n"
        "    @staticmethod\n"
        "    def load(cfg, path): ...\n"
        "    @staticmethod\n"
        "    def save(cfg, data): ...\n"
    )
    assert shared_state(_cls(src)) == {}, "a class with __init__ is already stateful — skip"


def test_shared_state_skips_pydantic_and_command(devtools):
    shared_state = devtools["state_candidates"].shared_state
    pydantic = "class Cfg(BaseModel):\n    @staticmethod\n    def a(cfg, x): ...\n    @staticmethod\n    def b(cfg, y): ...\n"
    command = "class Cmd:\n    @staticmethod\n    def add_args(cfg, p): ...\n    @staticmethod\n    def run(cfg, a): ...\n"
    assert shared_state(_cls(pydantic)) == {}
    assert shared_state(_cls(command)) == {}


# ---- graph.py — arch-fitness gate (pjs) ------------------------------------------------------------


def test_structure_cfg_merges_over_defaults(devtools, tmp_path):
    graph = devtools["graph"]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.structure]\nfile_max = 500\n")
    cfg = graph.load_structure_cfg(str(pyproject))
    assert cfg["file_max"] == 500, "an explicit threshold overrides the default"
    assert cfg["bottleneck_degree"] == 8, "an unspecified threshold keeps the default"


def test_structure_cfg_all_defaults_when_absent(devtools, tmp_path):
    graph = devtools["graph"]
    cfg = graph.load_structure_cfg(str(tmp_path / "nope.toml"))
    assert cfg == {
        "bottleneck_degree": 8,
        "file_max": 750,
        "file_min": 0,
        "betweenness_max": 0.10,
        "test_layout": "mirror",
    }


def test_god_module_detected(devtools):
    graph = devtools["graph"]
    g = nx.DiGraph()
    for i in range(9):  # fan-in 9 and fan-out 9, both > 8
        g.add_edge(f"in{i}", "god")
        g.add_edge("god", f"out{i}")
    assert graph._god_modules(g, 8), "fan-in AND fan-out both over the degree is a god-module"
    # a small clean graph must not fire
    clean = nx.DiGraph([("a", "b"), ("b", "c")])
    assert graph._god_modules(clean, 8) == []


def test_import_cycle_detected(devtools):
    graph = devtools["graph"]
    cyclic = nx.DiGraph([("a", "b"), ("b", "a")])
    assert graph._cycles(cyclic), "a strongly-connected component >1 is an import cycle"
    assert graph._cycles(nx.DiGraph([("a", "b"), ("b", "c")])) == []


def test_oversized_file_detected(devtools):
    graph = devtools["graph"]
    assert graph._oversized([("big.py", 800)], 750), "a file over the ceiling is a god-file"
    assert graph._oversized([("small.py", 100)], 750) == []


def test_undersized_floor_advisory(devtools):
    graph = devtools["graph"]
    assert graph._undersized([("tiny.py", 3)], 0) == [], "floor OFF at file_min<=0 (the default)"
    assert graph._undersized([("tiny.py", 3)], 10), "under the floor flags (advisory)"
    assert graph._undersized([("ok.py", 50)], 10) == [], "above the floor is silent"
    assert graph._undersized([("pkg/__init__.py", 1)], 10) == [], "package plumbing is exempt"


def test_assert_fitness_clean_vs_dirty(devtools):
    graph = devtools["graph"]
    cfg = {"bottleneck_degree": 8, "file_max": 750, "file_min": 0, "betweenness_max": 0.10}
    clean = nx.DiGraph([("a", "b"), ("b", "c")])
    blocking, _ = graph.assert_fitness(clean, [("a.py", 100)], cfg)
    assert blocking == [], "a clean graph + small files has no blocking violations"
    cyclic = nx.DiGraph([("a", "b"), ("b", "a")])
    blocking, _ = graph.assert_fitness(cyclic, [("big.py", 900)], cfg)
    assert blocking, "a cycle + an oversized file must block"


# ---- graph.py test-mirror rule + omit.py (9fa) -----------------------------------------------------


def test_unmirrored_flags_missing_mirror(devtools, tmp_path, monkeypatch):
    graph = devtools["graph"]
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "foo.py").write_text("class Foo:\n    @staticmethod\n    def go(): ...\n")
    assert graph.unmirrored(["pkg"]), "a logic module with no mirror test must be flagged"
    # __init__ is plumbing — its presence must NOT be what fired
    assert all("__init__" not in m for m in graph.unmirrored(["pkg"]))
    # add the STRICT mirror -> silent
    mirror = tmp_path / "tests" / "unit" / "pkg"
    mirror.mkdir(parents=True)
    (mirror / "test_foo.py").write_text("def test_foo(): pass\n")
    assert graph.unmirrored(["pkg"]) == [], "a module with its strict path-mirror test is satisfied"


def test_unmirrored_flat_layout(devtools, tmp_path, monkeypatch):
    graph = devtools["graph"]
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "foo.py").write_text("class Foo:\n    @staticmethod\n    def go(): ...\n")
    (tmp_path / "tests").mkdir()
    assert graph.unmirrored(["pkg"], "flat"), "flat: no test anywhere -> flagged"
    # a test_<name>.py ANYWHERE under tests/ satisfies flat (even at a non-mirror path)
    (tmp_path / "tests" / "test_foo.py").write_text("def test_foo(): pass\n")
    assert graph.unmirrored(["pkg"], "flat") == [], "flat: a test_foo.py under tests/ satisfies it"
    assert graph.unmirrored(["pkg"], "mirror"), "mirror still wants the strict path (flat test doesn't count)"


def test_unmirrored_off(devtools, tmp_path, monkeypatch):
    graph = devtools["graph"]
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "foo.py").write_text("class Foo:\n    @staticmethod\n    def go(): ...\n")
    assert graph.unmirrored(["pkg"], "off") == [], "off = no test-existence gate"


def test_unmirrored_exempts_omitted_shell(devtools, tmp_path, monkeypatch):
    graph = devtools["graph"]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.coverage.run]\nomit = ["pkg/shell.py"]\n')
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "shell.py").write_text("class Shell:\n    @staticmethod\n    def run(): ...\n")
    assert graph.unmirrored(["pkg"]) == [], "a coverage-omitted shell needs no mirror test"


def test_matches_omit_glob_semantics(devtools):
    matches_omit = devtools["omit"].matches_omit
    assert matches_omit("pkg/runner.py", ["pkg/*.py"]), "* matches one segment"
    assert not matches_omit("pkg/sub/runner.py", ["pkg/*.py"]), "* must NOT cross a segment"
    assert matches_omit("pkg/sub/deep.py", ["pkg/**"]), "** crosses segments"
    assert not matches_omit("pkg/keep.py", ["other/*.py"]), "non-matching glob is silent"


def test_coverage_omit_reads_pyproject(devtools, tmp_path):
    coverage_omit = devtools["omit"].coverage_omit
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[tool.coverage.run]\nomit = ["a/*.py", "b/**"]\n')
    assert coverage_omit(str(pp)) == ["a/*.py", "b/**"]
    assert coverage_omit(str(tmp_path / "absent.toml")) == [], "absent file -> empty omit"
