"""Unit tests for devtools/resolve.py — name -> class resolution shared by the arrow engines.

Method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a dense
container of parameter combinations rather than one case per behaviour.
"""

import ast
from pathlib import Path

import pytest

from devtools.plumbing.resolve import FileScope, Resolver


def _module(src: str) -> ast.Module:
    return ast.parse(src)


def _expr(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body


def _resolver(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> Resolver:
    """A real Resolver over a real one-module package — the substrate is a filesystem walk, so a double
    here would only assert that our arithmetic agrees with itself."""
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return Resolver([name])


# A three-link chain, reused wherever the MRO walk's DEPTH is what is under test.
_CHAIN = "class Base:\n    def run(self) -> None: ...\n\n\nclass Mid(Base): ...\n\n\nclass Leaf(Mid): ...\n"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pkg/sub/mod.py", "pkg.sub.mod"),
        ("mod.py", "mod"),
        # `__init__` IS its package — a module named `pkg.sub.__init__` would never match the `pkg.sub`
        # that an importing file's `from pkg.sub import X` binds, so every arrow into a package would miss.
        ("pkg/sub/__init__.py", "pkg.sub"),
        ("pkg/__init__.py", "pkg"),
        # Only the SUFFIX is stripped, never a dotted stem — `mod.v2.py` keeps its inner dot.
        ("pkg/mod.v2.py", "pkg.mod.v2"),
    ],
)
def test_module_of(path, expected):
    assert Resolver.module_of(Path(path)) == expected


def test_classes_in():
    """TOP-LEVEL classes only — the tier the class graph's nodes live at.

    The nesting rows are the load-bearing ones. `ast.walk` would find a class defined inside another class
    or inside a function and hand it back with a qualified id that collides with a top-level class of the
    same name, so a local helper class would silently become a node other files resolve arrows onto.
    """
    tree = _module(
        "class A: ...\n\n\nclass B:\n    class Inner: ...\n\n\n"
        "def f():\n    class Local: ...\n\n\nasync def g():\n    class Async: ...\n"
    )
    assert [c.name for c in Resolver.classes_in(tree)] == ["A", "B"], "declaration order, top level only"
    assert all(isinstance(c, ast.ClassDef) for c in Resolver.classes_in(tree))
    assert Resolver.classes_in(_module("x = 1\n")) == [], "a module with no classes is no nodes, not an error"


def test_functions_in():
    """TOP-LEVEL functions only — a call source with no class to hang from (bd 94j). It must NOT reach into a
    class body (those are methods, walked at the class tier) nor into a nested def (attributed to its
    enclosing function), or a `main` and a method named `main` would collide as graph nodes."""
    tree = _module(
        "def main(): ...\n\n\nasync def serve(): ...\n\n\n"
        "class A:\n    def method(self): ...\n\n\ndef outer():\n    def inner(): ...\n"
    )
    # `serve` is absent: an `async def` is an AsyncFunctionDef, excluded here as it is uniformly across the
    # walk (methods, class bodies) — not a 94j gap, just the same sync-only scope everywhere.
    assert [f.name for f in Resolver.functions_in(tree)] == ["main", "outer"], "top level, declaration order"
    assert Resolver.functions_in(_module("class A: ...\n")) == [], "a class-only module has no free functions"


def test_imported_names():
    """{local name: home module} for the bindings a bare name can travel through.

    `import numpy` is deliberately absent: it binds a MODULE, and resolving `numpy.array` would need
    attribute-path resolution this layer does not do. Including it would produce a binding whose "class"
    never exists, i.e. a wrong edge — the one failure mode the precise-but-incomplete rule forbids.

    A relative import is dropped for the same reason: `node.module` is None for `from . import X`, and
    guessing the package from the dot count would resolve to a module we never verified we own.
    """
    assert Resolver.imported_names(_module("from pkg.store import Store\n")) == {"Store": "pkg.store"}
    assert Resolver.imported_names(_module("from pkg.store import Store as S\n")) == {"S": "pkg.store"}
    assert Resolver.imported_names(_module("import numpy\n")) == {}, "a module binding is not a name binding"
    assert Resolver.imported_names(_module("import numpy as np\n")) == {}
    assert Resolver.imported_names(_module("from . import sibling\n")) == {}, "no `module` to resolve through"
    multi = Resolver.imported_names(_module("from pkg.a import X, Y\nfrom pkg.b import Z\n"))
    assert multi == {"X": "pkg.a", "Y": "pkg.a", "Z": "pkg.b"}, "every alias of every from-import"
    # A function-local import still binds a name the body can annotate with, so the walk is whole-module.
    assert Resolver.imported_names(_module("def f():\n    from pkg.c import W\n")) == {"W": "pkg.c"}


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("Store", {"Store"}),
        # `None` is an ast.Constant, not a name — an optional yields only the real type.
        ("Store | None", {"Store"}),
        ("Optional[Store]", {"Optional", "Store"}),
        ("list[Store]", {"list", "Store"}),
        ("dict[str, list[Store]]", {"dict", "str", "list", "Store"}),
        # A string forward reference is PARSED, not treated as opaque — the common shape in a
        # `TYPE_CHECKING` import, where every arrow would otherwise vanish.
        ("'Store'", {"Store"}),
        # A string forward reference NESTED in a subscript is re-parsed too — the `list['Store']` /
        # `dict[str, 'Store']` form is an ordinary TYPE_CHECKING field, and dropping its inner name blinded
        # every arrow-level gate to that edge (bd eq6). The re-parse now recurses to any depth.
        ("list['Store']", {"list", "Store"}),
        ("dict[str, 'Store']", {"dict", "str", "Store"}),
        ("list['a.Store']", {"list", "Store", "a"}),
        # A `Literal[...]`'s arguments are VALUES, not types, so they are NOT re-parsed: `Literal['Store']`
        # is the string "Store", and minting a `Store` name from it would be the one thing this resolver
        # forbids — a wrong edge. Only the `Literal` name itself leaks (and resolves to nothing).
        ("Literal['Store', 'Mid']", {"Literal"}),
        ("list[Literal['Store']]", {"list", "Literal"}),
        # A jaxtyping shape string is not a type expression. It must return empty rather than raise: one
        # such annotation anywhere in a repo would otherwise take down every gate standing on this.
        ("'b n'", set()),
        # A dotted name yields its TRAILING segment (what a local binding would be spelled as) AND the
        # qualifier, because the walk visits both nodes. Harmless by construction: `mod` is a module, so it
        # resolves to no class we own and the caller emits nothing for it.
        ("mod.Store", {"Store", "mod"}),
    ],
)
def test_annotation_names(annotation, expected):
    assert Resolver.annotation_names(_expr(annotation)) == expected


def test_annotation_names_of_none_is_empty():
    """An unannotated parameter/field is the common case and must not be a special case at every call site."""
    assert Resolver.annotation_names(None) == set()


def test_scope_of(tmp_path):
    """The three facts that travel together as "here" — module, own classes, import bindings.

    Asserted as one value because they were a data clump before: passing them separately let a caller mix
    one file's imports with another file's locals, which resolves a name to a class that file cannot see.
    """
    tree = _module("from pkg.store import Store as S\n\n\nclass A: ...\n\n\nclass B: ...\n")
    scope = Resolver.scope_of(Path("pkg/sub/mod.py"), tree)
    assert scope.module == "pkg.sub.mod"
    assert scope.local == frozenset({"A", "B"}), "the file's OWN classes, which win over imports"
    assert scope.imports == {"S": "pkg.store"}, "aliases as spelled locally"
    empty = Resolver.scope_of(Path("pkg/bare.py"), _module("x = 1\n"))
    assert (empty.module, empty.local, empty.imports) == ("pkg.bare", frozenset(), {})


def test_qualified(monkeypatch, tmp_path, write_pkg):
    """The ownership lookup: a (module, name) pair -> the id we own, or None.

    This is the gate between "a name we can see" and "a class we can point an arrow AT". The two None rows
    are the contract: the right name in the wrong module, and a module we do not scan at all. Either
    returning a synthesised id would emit an edge to a node the graph has no box for.
    """
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "qual_pkg", "class Base: ...\n\n\nclass Other: ...\n")
    assert resolver.qualified("qual_pkg.mod", "Base") == "qual_pkg.mod.Base"
    assert resolver.qualified("qual_pkg.mod", "Other") == "qual_pkg.mod.Other"
    assert resolver.qualified("qual_pkg.elsewhere", "Base") is None, "right name, wrong module"
    assert resolver.qualified("pandas", "DataFrame") is None, "a module we do not own"
    assert resolver.qualified("qual_pkg.mod", "Absent") is None


def test_resolve(monkeypatch, tmp_path, write_pkg):
    """A bare name -> the class it denotes here: same-file first, then imports, then nothing.

    The ORDER is load-bearing and gets its own row: a file defining `Base` while also importing a different
    `Base` must resolve to its own, because that is what Python does at runtime.
    """
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "res_pkg", "class Base: ...\n")
    local = FileScope("res_pkg.mod", frozenset({"Base"}))
    assert resolver.resolve("Base", local) == "res_pkg.mod.Base"
    imported = FileScope("res_pkg.other", imports={"Base": "res_pkg.mod"})
    assert resolver.resolve("Base", imported) == "res_pkg.mod.Base", "reached through the file's import"
    shadow = FileScope("res_pkg.mod", frozenset({"Base"}), {"Base": "somewhere.else"})
    assert resolver.resolve("Base", shadow) == "res_pkg.mod.Base", "a local definition wins over an import"
    assert resolver.resolve("ValueError", FileScope("res_pkg.mod")) is None, "a builtin is not ours"
    third_party = FileScope("res_pkg.mod", imports={"DataFrame": "pandas"})
    assert resolver.resolve("DataFrame", third_party) is None, "an import of something we do not own"
    # A name declared local but with no class behind it (a stale scope) resolves to None, never to a
    # fabricated id — the caller emits nothing rather than an edge into a box that does not exist.
    assert resolver.resolve("Ghost", FileScope("res_pkg.mod", frozenset({"Ghost"}))) is None


def test_resolve_all(monkeypatch, tmp_path, write_pkg):
    """The set-to-list lift: keep what resolves, drop what does not, SORTED.

    Sorted because these become graph edges and a diff of an arch map has to be stable across runs — set
    iteration order would make an unchanged repo produce a changed map.

    The self-arrow row records a decision: `resolve_all` no longer takes an `exclude`, because whether a
    class pointing at itself is wanted is the CONSUMER's question (the object graph wants it, a construct
    arrow does not), so this one just answers what the names denote.
    """
    src = "class A: ...\n\n\nclass B: ...\n"
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "all_pkg", src)
    scope = FileScope("all_pkg.mod", frozenset({"A", "B"}))
    assert resolver.resolve_all({"B", "A"}, scope) == ["all_pkg.mod.A", "all_pkg.mod.B"], "sorted, not set order"
    assert resolver.resolve_all({"A", "ValueError", "DataFrame"}, scope) == ["all_pkg.mod.A"], "misses drop out"
    assert resolver.resolve_all(set(), scope) == []
    assert resolver.resolve_all({"ValueError"}, scope) == [], "nothing owned is an empty list, not None"
    assert resolver.resolve_all({"A"}, scope) == ["all_pkg.mod.A"], "a self-arrow is kept — the caller decides"


def test_definer(monkeypatch, tmp_path, write_pkg):
    """Which class DEFINES a method, walking the project MRO upward — one rule behind every call edge.

    An edge must point at where the invoked code LIVES, not at the receiver's declared type; the two-links
    row is what separates this from "the immediate base". The override row is the counterweight: the walk
    stops at the nearest definition, or every override would look like dead code while its base collected
    traffic it never receives.

    The diamond row is termination, not resolution: multiple inheritance means a class is reachable twice,
    and without the seen-set the walk revisits and — on a malformed tree with a cycle — never returns.
    """
    own = _resolver(monkeypatch, tmp_path, write_pkg, "mro_own", _CHAIN)
    assert own.definer("mro_own.mod.Base", "run") == "mro_own.mod.Base", "defined here"
    assert own.definer("mro_own.mod.Leaf", "run") == "mro_own.mod.Base", "two links up, not the immediate base"
    assert own.definer("mro_own.mod.Leaf", "absent") is None, "not ours to find"
    assert own.definer("nowhere.Unknown", "run") is None, "an unknown class is a miss, not a crash"

    over = "class Base:\n    def run(self) -> None: ...\n\n\nclass Sub(Base):\n    def run(self) -> None: ...\n"
    sub = _resolver(monkeypatch, tmp_path, write_pkg, "mro_over", over)
    assert sub.definer("mro_over.mod.Sub", "run") == "mro_over.mod.Sub", "the nearest definition wins"

    diamond = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Left(Base): ...\n\n\nclass Right(Base): ...\n\n\nclass D(Left, Right): ...\n"
    )
    dia = _resolver(monkeypatch, tmp_path, write_pkg, "mro_diamond", diamond)
    assert dia.definer("mro_diamond.mod.D", "run") == "mro_diamond.mod.Base", "breadth-first, terminates"


def test_leaves_project(monkeypatch, tmp_path, write_pkg):
    """Whether a miss above this class is OUR gap or the project boundary (bd f1u.3).

    This is what makes a resolver miss readable. A method not found on a class whose every ancestor is ours
    is a real finding; the same miss on a class deriving from `BaseModel` is the chain simply leaving the
    project, an expected drop by decision. Without the distinction both look identical and neither can be
    reported — so the two outcomes are asserted against the same shape of tree, differing only in the base.

    The inherited row matters because it is the whole ANCESTRY that decides, not the immediate base.
    """
    closed = _resolver(monkeypatch, tmp_path, write_pkg, "open_closed", _CHAIN)
    assert closed.leaves_project("open_closed.mod.Leaf") is False, "every ancestor is ours — a miss is real"
    assert closed.leaves_project("open_closed.mod.Base") is False, "a root with no bases is closed"

    ext = _resolver(
        monkeypatch, tmp_path, write_pkg, "open_ext", "from external import Model\n\n\nclass D(Model): ...\n"
    )
    assert ext.leaves_project("open_ext.mod.D") is True, "a foreign base opens the chain"

    deep = "from external import Model\n\n\nclass Mid(Model): ...\n\n\nclass Leaf(Mid): ...\n"
    down = _resolver(monkeypatch, tmp_path, write_pkg, "open_deep", deep)
    assert down.leaves_project("open_deep.mod.Leaf") is True, "the opening is inherited down the chain"
    assert down.leaves_project("nowhere.Unknown") is False, "an unknown class claims nothing"


def test_init_of(make_cls):
    """The `__init__` of a class, or None — the seam `field_types` reads assigned state through.

    The "another method" row is the point: a naive "first FunctionDef" would hand back whatever method was
    declared first and then read ITS parameters as the class's fields, inventing state from a method
    signature. The None row is the ordinary dataclass/namespace case, not an edge case.
    """
    found = Resolver.init_of(make_cls("class A:\n    def run(self): ...\n    def __init__(self, x: int): ...\n"))
    assert found is not None and found.name == "__init__", "found past an earlier method, not the first def"
    assert [a.arg for a in found.args.args] == ["self", "x"], "the real node, with its signature intact"
    assert Resolver.init_of(make_cls("class B:\n    x: int\n")) is None, "no __init__ is None, not an error"
    assert Resolver.init_of(make_cls("class C:\n    def run(self): ...\n")) is None, "another method is not it"


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("self.store", True),
        # Everything below is why this is a TypeGuard rather than a bool: each one would make a caller's
        # unguarded `.attr` read either wrong or an AttributeError.
        ("other.store", False),
        ("self", False),
        ("self.store.inner", False),
        ("self()", False),
        ("items[0].store", False),
        ("self.store()", False),
    ],
)
def test_is_self_attr(expr, expected):
    assert Resolver.is_self_attr(_expr(expr)) is expected


def test_field_types(make_cls):
    """{field: declared type names} — every way a class declares its own state, in one cut.

    Keyed by FIELD rather than flattened because the two engines need different cuts: structural arrows
    want the values ("what does this class hold"), the call resolver needs the key ("what type is
    `self._store`") to bind a receiver. A flattened set answers only the first.

    The `= T(...)` row is the one that cannot come from an annotation: an unannotated field constructed in
    place is real held state, and dropping it loses the arrow for the most common composition spelling.
    """
    src = (
        "class A:\n"
        "    declared: Store\n"
        "    generic: list[Cache] | None = None\n"
        "    def __init__(self, passed: Backend, *, kw: Clock, plain) -> None:\n"
        "        self.annotated: Index = build()\n"
        "        self.passed = passed\n"
        "        self.kw = kw\n"
        "        self.built = Writer(passed)\n"
        "        self.plain = plain\n"
        "        self.literal = 3\n"
        "        local = Ignored()\n"
    )
    fields = Resolver.field_types(make_cls(src))
    assert fields["declared"] == {"Store"}, "a class-body annotation"
    assert fields["generic"] == {"list", "Cache"}, "unwrapped through the generic and the optional"
    assert fields["annotated"] == {"Index"}, "a `self.x: T` inside __init__"
    assert fields["passed"] == {"Backend"}, "an annotated param kept as state carries the param's type"
    assert fields["kw"] == {"Clock"}, "keyword-only params are state too"
    assert fields["built"] == {"Writer"}, "a direct construction is the object graph"
    assert fields["plain"] == set(), "an unannotated param is known state of unknown type — kept, empty"
    assert fields["literal"] == set(), "a literal denotes no class we could point at"
    assert "local" not in fields, "a local variable is not the class's state"

    bare = Resolver.field_types(make_cls("class B:\n    x: Store\n"))
    assert bare == {"x": {"Store"}}, "no __init__ still yields the class-body annotations"
    assert Resolver.field_types(make_cls("class C: ...\n")) == {}, "a stateless class holds nothing"
