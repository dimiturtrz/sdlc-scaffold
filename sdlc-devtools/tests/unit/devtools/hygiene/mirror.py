"""Unit tests for devtools/mirror.py — the method-level test mirror.

Written in the convention it enforces (docs/UNIT_TESTS.md), which is the only honest way to ship it: a gate
whose own tests do not satisfy it is asking for something nobody has tried.
"""

import ast
from pathlib import Path

import pytest

from devtools.hygiene.mirror import MethodMirror


def _module(src: str) -> ast.Module:
    return ast.parse(src)


def _fn(src: str) -> ast.FunctionDef:
    """The first function in a snippet — a method's own node, decorators intact."""
    return next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef))


def _mirror(tmp_path, source: str, test_source: str, layout: str = "mirror") -> MethodMirror:
    """A repo with one module and its mirror, wired through a real pyproject.

    Built on disk rather than injected because the gate's whole job is a question ABOUT the filesystem —
    which file mirrors which module — and a double for that would only assert that our arithmetic agrees
    with itself.
    """
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.structure]\ntest_layout = "{layout}"\n[tool.pytest.ini_options]\npython_files = ["*.py"]\n'
    )
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text(source)
    mirrors = tmp_path / "tests" / "unit" / "pkg"
    mirrors.mkdir(parents=True, exist_ok=True)
    (mirrors / "mod.py").write_text(test_source)
    return MethodMirror(["pkg"], trees=[(Path("pkg/mod.py"), ast.parse(source))])


def test_layout(tmp_path, monkeypatch):
    """The convention comes from config, so this gate and the file-level one cannot drift apart."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.structure]\ntest_layout = "mirror"\n')
    assert MethodMirror([]).layout().mirror_of(Path("pkg/a.py")).as_posix() == "tests/unit/pkg/a.py"
    (tmp_path / "pyproject.toml").write_text('[tool.structure]\ntest_layout = "off"\n')
    assert MethodMirror([]).layout().mirror_of(Path("pkg/a.py")) is None, "off leaves this gate nowhere to look"


@pytest.mark.parametrize(
    ("layout", "python_files", "expected"),
    [
        # The failure this exists to prevent: a mirror tree under pytest's DEFAULT discovery is not
        # collected at all, so the suite reports green and this gate agrees with it — every mirror file
        # exists and is full of tests that never run.
        ("mirror", None, 1),
        ("mirror", '["test_*.py"]', 1),
        ("mirror", '["*.py"]', 0),
        # `off` demands no mirror, so there is no discovery to get wrong. The check is UNCONDITIONAL while
        # the gate is on — it used to fire for one layout of two, which was a leftover of a distinction
        # that no longer exists.
        ("off", None, 0),
        ("off", '["test_*.py"]', 0),
    ],
)
def test_misconfigured(tmp_path, monkeypatch, layout, python_files, expected):
    monkeypatch.chdir(tmp_path)
    section = f"[tool.pytest.ini_options]\npython_files = {python_files}\n" if python_files else ""
    (tmp_path / "pyproject.toml").write_text(f'[tool.structure]\ntest_layout = "{layout}"\n{section}')
    assert len(MethodMirror([]).misconfigured()) == expected


@pytest.mark.parametrize(
    ("src", "public"),
    [
        ("def run(self):\n    return 1", True),
        ("def _helper(self):\n    return 1", False),
        ("def __init__(self):\n    self.n = 1", False),
        ("def main(self):\n    return 1", False),
        # PROPERTIES ARE IN. They were exempt because a Call-node counter reports every one as untested —
        # a fact about the detector, not about properties, which are public API like any other member.
        # They are matched by attribute ACCESS instead; see test_accessed_names.
        ("@property\ndef total(self):\n    return 1", True),
        ("@cached_property\ndef total(self):\n    return 1", True),
        ("@total.setter\ndef total(self, v):\n    self._t = v", True),
        # A DECLARATION has no behaviour to call — see test_is_declaration.
        ("def get(self, k): ...", False),
        ("@abstractmethod\ndef go(self): raise NotImplementedError", False),
    ],
)
def test_is_public(src, public):
    assert MethodMirror.is_public(_fn(src)) is public


@pytest.mark.parametrize(
    ("src", "prop"),
    [
        ("@property\ndef total(self):\n    return 1", True),
        ("@cached_property\ndef total(self):\n    return 1", True),
        ("@functools.cached_property\ndef total(self):\n    return 1", True),
        # The SETTER and DELETER are in, which is where this deliberately differs from
        # `purity.PropertyPurity.is_property`. That one asks "is this a pure read" and excludes them on
        # purpose; this one asks "how is it exercised", and all three answer "by attribute access".
        ("@total.setter\ndef total(self, v):\n    self._t = v", True),
        ("@total.deleter\ndef total(self):\n    del self._t", True),
        ("def total(self):\n    return 1", False),
        ("@staticmethod\ndef total():\n    return 1", False),
    ],
)
def test_is_property(src, prop):
    assert MethodMirror.is_property(_fn(src)) is prop


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        # All three attribute CONTEXTS reach the member, which is why a setter needs no separate rule.
        ("x = obj.total", {"total"}),
        ("obj.total = 1", {"total"}),
        ("del obj.total", {"total"}),
        ("assert a.b.c == 1", {"b", "c"}),
        ("obj.method()", {"method"}),
        ("x = 1", set()),
    ],
)
def test_accessed_names(body, expected):
    """How a property is credited. A method is CALLED and a property is READ, so the matching site looks
    for different syntax depending on the member kind — the same concept reached two ways."""
    assert MethodMirror.accessed_names(_fn(f"def test_a():\n    {body}\n")) == expected


@pytest.mark.parametrize(
    ("src", "declaration"),
    [
        # The three spellings that produce a declaration agree on the BODY and on nothing else, which is why
        # this is detected by body rather than by base class or decorator.
        ("def get(self, k): ...", True),
        ('def get(self, k):\n    """Value for `k`."""\n    ...', True),
        ("def get(self, k):\n    pass", True),
        ("def get(self, k):\n    raise NotImplementedError", True),
        ('def get(self, k):\n    """Doc."""\n    raise NotImplementedError("subclass me")', True),
        # Anything that actually does something is not a declaration, however short.
        ("def get(self, k):\n    return 1", False),
        ("def get(self, k):\n    raise ValueError('no')", False),
        ("def get(self, k):\n    self.n = 1", False),
    ],
)
def test_is_declaration(src, declaration):
    """A `Protocol` member or an abstract method is a SIGNATURE. Demanding a test that calls it would be
    demanding a test of a no-op — the implementations are covered by their own mirrors, which is where the
    behaviour is. Found by pointing the gate at the scaffold's own seeded `Store` Protocol."""
    assert MethodMirror.is_declaration(_fn(src)) is declaration


def test_ignored():
    """The escape hatch is rule-named and per-method, so silencing this gate never silences another."""
    src = (
        "class A:\n"
        "    def a(self): ...  # devtools-ignore: test-mirror\n"
        "    @staticmethod  # devtools-ignore: test-mirror\n"
        "    def b(): ...\n"
        "    @staticmethod\n"
        "    # devtools-ignore: test-mirror\n"
        "    def c(): ...\n"
        "    def d(self): ...  # noqa: S101\n"
        "    # devtools-ignore: test-mirror\n"
        "    def e(self): ...\n"
    )
    lines = src.splitlines()
    by_name = {fn.name: fn for fn in ast.walk(ast.parse(src)) if isinstance(fn, ast.FunctionDef)}
    assert MethodMirror.ignored(by_name["a"], lines), "on the def line"
    assert MethodMirror.ignored(by_name["b"], lines), "on a decorator line"
    assert MethodMirror.ignored(by_name["c"], lines), "on its own line among the decorators"
    assert not MethodMirror.ignored(by_name["d"], lines), "another tool's suppression is not this one's"
    # The window is the decorators-through-def block and nothing above it. A bare comment line ABOVE an
    # undecorated method is not claimed: it reads equally as a trailing note on the PREVIOUS method, and a
    # suppression that might belong to either of two methods is worse than one that must be placed exactly.
    assert not MethodMirror.ignored(by_name["e"], lines), "a line above the def is ambiguous, so it does not count"


def test_methods(tmp_path, monkeypatch):
    """Which members the rule covers — decided by the METHOD, never by its class.

    The second class is named with a leading underscore to pin exactly that: the spelling of a class name
    changes nothing about which of its methods need tests. Private METHODS are out, in both classes alike.
    """
    monkeypatch.chdir(tmp_path)
    src = (
        "class Alpha:\n    def a(self):\n        return 1\n    def _b(self):\n        return 2\n"
        "class _Beta:\n    def c(self):\n        return 3\n    def _d(self):\n        return 4\n"
    )
    engine = _mirror(tmp_path, src, "")
    found = {(cls, fn.name) for members in engine.methods().values() for cls, fn in members}
    assert found == {("Alpha", "a"), ("_Beta", "c")}, "the class name is a label, not a filter"

    # An OVERRIDE of a same-module base is a member in full — its own behaviour to pin (bd kai). The base's
    # concrete method AND each override are counted; the abstract declaration falls out via is_declaration.
    strat = (
        "class Base:\n    def go(self):\n        raise NotImplementedError\n"
        "class Sub(Base):\n    def go(self):\n        return 1\n"
        "class Alt(Base):\n    def go(self):\n        return 2\n"
    )
    over = {(cls, fn.name) for members in _mirror(tmp_path, strat, "").methods().values() for cls, fn in members}
    assert over == {("Sub", "go"), ("Alt", "go")}, "both overrides are members; the abstract base is a declaration"


def test_callers(monkeypatch, tmp_path):
    """Which files call a name — the input to choosing which remedy a finding names."""
    monkeypatch.chdir(tmp_path)
    trees = [
        (Path("pkg/a.py"), _module("class A:\n    def go(self): self.helper()\n    def helper(self): ...\n")),
        (Path("pkg/b.py"), _module("def use(a): a.go()\n")),
    ]
    callers = MethodMirror(["pkg"], trees=trees).callers
    assert callers["go"] == {Path("pkg/b.py")}, "reached across a module boundary — a contract"
    assert callers["helper"] == {Path("pkg/a.py")}, "own file only — a visibility decision"
    assert callers["absent"] == set(), "an uncalled name is empty, not a KeyError"


def test_functions():
    """Tests AND the helpers they delegate to — both halves are needed to resolve delegation."""
    found = MethodMirror.functions(_module("def test_a(): ...\ndef _helper(): ...\nclass C:\n    def m(self): ...\n"))
    assert set(found) == {"test_a", "_helper", "m"}


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("def f(): x.a()", {"a"}),
        ("def f(): a()", {"a"}),
        ("def f(): x.y.z.deep()", {"deep"}),
        ("def f(): x.a(); b()", {"a", "b"}),
        ("def f(): pass", set()),
        # Reached through a nested body — a call inside a `with` or a comprehension still counts.
        ("def f():\n    with open('x'):\n        y.a()", {"open", "a"}),
    ],
)
def test_called_names(src, expected):
    assert MethodMirror.called_names(_fn(src)) == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [("x.y.a", "a"), ("a", "a"), ("x[0]", ""), ("(lambda: 1)", "")],
)
def test_name_of(expr, expected):
    assert MethodMirror.name_of(ast.parse(expr, mode="eval").body) == expected


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        ("CallEdge", "call_edge"),
        ("Cli", "cli"),
        ("AstGrep", "ast_grep"),
        ("A", "a"),
        # Leading underscores are stripped so the generated name reads like a hand-written one —
        # `test__mirror_mirror_of` is not something anyone would type.
        ("_Mirror", "mirror"),
        ("__Dunderish", "dunderish"),
    ],
)
def test_snake(cls, expected):
    assert MethodMirror.snake(cls) == expected


def test_reachable():
    """Delegation, transitively — without this the gate over-fires on exactly the helper extraction that
    the complexity limits encourage (measured: 19 false positives out of 19 on the e2e suite)."""
    helpers = MethodMirror.functions(
        _module("def test_a(): _one()\ndef _one(): _two()\ndef _two(): ...\ndef _unrelated(): ...\n")
    )
    reached = {fn.name for fn in MethodMirror.reachable(helpers["test_a"], helpers)}
    assert reached == {"test_a", "_one", "_two"}, "two hops deep, and the unrelated helper is not swept in"

    # A cycle between helpers must terminate rather than recurse forever.
    cyclic = MethodMirror.functions(_module("def test_a(): _p()\ndef _p(): _q()\ndef _q(): _p()\n"))
    assert {fn.name for fn in MethodMirror.reachable(cyclic["test_a"], cyclic)} == {"test_a", "_p", "_q"}


@pytest.mark.parametrize(
    ("body", "asserts"),
    [
        ("assert x", True),
        ("raise AssertionError('no')", True),
        ("with pytest.raises(ValueError): go()", True),
        ("assert_that(x)", True),
        ("x = 1", False),
        ("go()", False),
        # Nested inside control flow still counts — the assertion does not have to be top-level.
        ("if x:\n        assert y", True),
    ],
)
def test_asserts(body, asserts):
    assert MethodMirror.asserts([_fn(f"def test_a():\n    {body}\n")]) is asserts


@pytest.mark.parametrize(
    ("cls", "method", "shared", "expected"),
    [
        # Unique in the module: the bare name is expected, the qualified one is still accepted, so a repo
        # preferring the qualified spelling everywhere is never fought by a gate that knows only one.
        ("Cli", "run", False, ["test_run", "test_cli_run"]),
        # Shared: one `test_source_id` cannot mean both CallEdge's and CallSite's, so it is not offered.
        ("CallEdge", "source_id", True, ["test_call_edge_source_id"]),
    ],
)
def test_expected(cls, method, shared, expected):
    assert MethodMirror.expected(cls, method, shared=shared) == expected


def test_violations(tmp_path, monkeypatch):
    """The whole gate, over the cases that decide whether a method is covered."""
    monkeypatch.chdir(tmp_path)
    src = (
        "class A:\n    def covered(self):\n        return 1\n"
        "    def misnamed(self):\n        return 2\n    def bare(self):\n        return 3\n"
    )
    tests = (
        "def test_covered():\n    A().covered()\n    assert 1\n"
        "def test_something_else():\n    A().misnamed()\n    assert 1\n"
        "def test_bare():\n    A().bare()\n"  # calls, never asserts
    )
    found = _mirror(tmp_path, src, tests).violations()
    assert len(found) == 2, "the correctly-named asserting test is the only one that satisfies the rule"
    rename = next(f for f in found if "misnamed" in f)
    assert "rename it" in rename, "a test that calls and asserts under another name is a RENAME"
    assert "test_misnamed" in rename, "and the message names the exact function to write"
    assert "no `test_bare`" in next(f for f in found if "`A.bare`" in f), "calling without asserting is not covered"

    # A delegated assertion counts, or the gate punishes the extraction PLR0915 encourages.
    delegated = "def test_covered():\n    A().covered()\n    _check()\ndef _check():\n    assert 1\n"
    assert not [f for f in _mirror(tmp_path, src, delegated).violations() if "covered" in f]

    # A PROPERTY is credited by attribute ACCESS, not by a call — reading it IS exercising it. A setter is
    # credited by the WRITE for the same reason, which is the case the old blanket exemption made
    # unsatisfiable: it asked for a `test_size` that called `size()`, and nothing can call a setter.
    props = (
        "class A:\n"
        "    @property\n    def size(self):\n        return self._n\n"
        "    @size.setter\n    def size(self, v):\n        self._n = v\n"
        "    @property\n    def bare(self):\n        return 1\n"
    )
    read_and_written = "def test_size():\n    a = A()\n    a.size = 2\n    assert a.size == 2\n"
    found = _mirror(tmp_path, props, read_and_written).violations()
    assert [f for f in found if "A.size" in f] == [], "one test_size covers the getter and its setter"
    uncovered = next(f for f in found if "A.bare" in f)
    assert "reads it" in uncovered, "the message says READS for a property — 'calls' would be unwritable"

    # An ignored method is excused; a module with no mirror FILE is the file-level gate's finding, not this
    # one's — reporting every method here would bury that one line under twenty.
    ignored_src = src.replace("def bare(self):", "def bare(self):  # devtools-ignore: test-mirror")
    assert len(_mirror(tmp_path, ignored_src, tests).violations()) == 1

    engine = _mirror(tmp_path, src, tests)
    (tmp_path / "tests" / "unit" / "pkg" / "mod.py").unlink()
    assert engine.violations() == [], "no mirror FILE is the file-level gate's one line, not twenty of ours"


def test_report(tmp_path, monkeypatch):
    """The explorer view: a count plus every finding, so a reader sees scale before detail."""
    monkeypatch.chdir(tmp_path)
    src = "class A:\n    def bare(self):\n        return 1\n"
    text = _mirror(tmp_path, src, "def test_other():\n    assert 1\n").report()
    assert text.splitlines()[0] == "untested public methods: 1"
    assert "A.bare" in text


def test_run_assert(tmp_path, monkeypatch):
    """The gate view, and the config error that must be LOUDER than the findings it would suppress."""
    monkeypatch.chdir(tmp_path)
    src = "class A:\n    def covered(self):\n        return 1\n"
    clean = _mirror(tmp_path, src, "def test_covered():\n    A().covered()\n    assert 1\n")
    assert clean.run_assert() == 0
    dirty = _mirror(tmp_path, "class A:\n    def bare(self):\n        return 1\n", "def test_other():\n    assert 1\n")
    assert dirty.run_assert() == 1

    # A mirror tree without `python_files` is not collected at all, so every mirror file is full of tests
    # that never run — the gate must fail on the CONFIG rather than pass on findings it can no longer trust.
    (tmp_path / "pyproject.toml").write_text('[tool.structure]\ntest_layout = "mirror"\n')
    assert clean.run_assert() == 1
