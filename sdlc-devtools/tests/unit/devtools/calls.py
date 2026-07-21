"""Unit tests for devtools/calls.py — behavioural arrows resolved to the DECLARED receiver type, and from
there to the method that type actually DEFINES (bd f1u.2).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour. `test_edges` is where nearly
all of that density lives — every resolution rule is the same question (this source snippet yields exactly
these arrows), so it is one table rather than twenty near-identical functions.
"""

import ast

import pytest

from devtools.calls import CALLS, CONSTRUCT, CallArrows, CallSite
from devtools.resolve import FileScope

_DEP = "class Dep:\n    def run(self) -> None: ...\n\n\n"
# `self._d: Dep` assigned in __init__, then invoked — the field-map path, needed by several rows.
_FIELD = (
    _DEP
    + "class A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
)


def _engine(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> CallArrows:
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return CallArrows([name])


def _triples(edges) -> set[tuple[str, str, str]]:
    """(source node, target node, kind) — the METHOD-level cut, which is what actually ships now.

    Asserted as an EXACT set rather than by membership: this resolver's contract is "never a wrong edge",
    and a subset check cannot see a spurious one. The arrows a snippet does NOT produce are half the design.
    """
    return {(e.source_id, e.target_id, e.kind) for e in edges}


@pytest.mark.parametrize(
    ("name", "src", "expected", "miss"),
    [
        # ---- receivers that the source DECLARES ------------------------------------------------------
        # A call on a field resolves through the class's field map...
        ("field", _FIELD, {("field.mod.A.go", "field.mod.Dep.run", CALLS)}, None),
        # ...a parameter through its annotation...
        (
            "param",
            _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n",
            {("param.mod.A.go", "param.mod.Dep.run", CALLS)},
            None,
        ),
        # ...and a local through the constructor that made it. Note it yields BOTH arrows: building the Dep
        # is the wiring, calling it is the behaviour, and the two cuts partition the coupling.
        (
            "local",
            _DEP + "class A:\n    def go(self):\n        d = Dep()\n        d.run()\n",
            {("local.mod.A.go", "local.mod.Dep.run", CALLS), ("local.mod.A.go", "local.mod.Dep", CONSTRUCT)},
            None,
        ),
        # `Dep().run()` — the receiver is unnamed, not UNDECLARED. Refusing this shape was costing most of
        # the tier's cross-class connectivity: fluent construction is ordinary here (`Trees(pkgs).walk()`).
        (
            "fluent",
            _DEP + "class A:\n    def go(self):\n        Dep().run()\n",
            {("fluent.mod.A.go", "fluent.mod.Dep.run", CALLS), ("fluent.mod.A.go", "fluent.mod.Dep", CONSTRUCT)},
            None,
        ),
        # `Dep.make()` — the receiver IS the class. It is not a parameter or a local, so the declared-types
        # map is rightly empty for it; the name simply denotes a class, the resolver's usual question.
        (
            "static",
            "class Dep:\n    @staticmethod\n    def make() -> None: ...\n\n\nclass A:\n    def go(self):\n        Dep.make()\n",
            {("static.mod.A.go", "static.mod.Dep.make", CALLS)},
            None,
        ),
        # Precedence: a parameter NAMED after a class is the parameter. Resolving the bare name to the class
        # would attribute the call to the wrong receiver — a wrong edge, which this resolver never emits.
        (
            "shadow",
            "class Dep:\n    def run(self) -> None: ...\n\n\nclass Other:\n    def run(self) -> None: ...\n\n\n"
            "class A:\n    def go(self, Dep: Other):\n        Dep.run()\n",
            {("shadow.mod.A.go", "shadow.mod.Other.run", CALLS)},
            None,
        ),
        # ---- the arrow terminates on the method that DEFINES it (bd f1u.2) ---------------------------
        # Sub inherits `run`, so the code being invoked lives on Base and that is where the arrow points.
        # Pointing at Sub would name a method that does not exist there.
        (
            "mro",
            "class Base:\n    def run(self) -> None: ...\n\n\nclass Sub(Base): ...\n\n\n"
            "class A:\n    def go(self, s: Sub):\n        s.run()\n",
            {("mro.mod.A.go", "mro.mod.Base.run", CALLS)},
            None,
        ),
        # The walk stops at the FIRST definer, so an override takes the arrow. Without that, an override
        # would be drawn as dead code while its base collected traffic it never receives.
        (
            "override",
            "class Base:\n    def run(self) -> None: ...\n\n\nclass Sub(Base):\n    def run(self) -> None: ...\n\n\n"
            "class A:\n    def go(self, s: Sub):\n        s.run()\n",
            {("override.mod.A.go", "override.mod.Sub.run", CALLS)},
            None,
        ),
        # Not a special case — the call->interface partition falling out of the same MRO rule. A declared
        # Protocol receiver defines the method, so the arrow reaches the CONTRACT.
        (
            "proto",
            "from typing import Protocol\n\n\nclass Runs(Protocol):\n    def run(self) -> None: ...\n\n\n"
            "class A:\n    def go(self, r: Runs):\n        r.run()\n",
            {("proto.mod.A.go", "proto.mod.Runs.run", CALLS)},
            None,
        ),
        # A public method calling its own private helper is real internal structure at the METHOD tier, and
        # it is the reason the `all` depth stop exists. (`class_edges` folds it away — see that test.)
        (
            "intra",
            "class A:\n    def _helper(self) -> None: ...\n\n    def go(self):\n        self._helper()\n",
            {("intra.mod.A.go", "intra.mod.A._helper", CALLS)},
            None,
        ),
        # ---- construct: the CONCRETE, at the site that chose it ---------------------------------------
        # Constructing is `__init__`, i.e. the class as a whole — so behavioural coupling lands INSIDE the
        # box (on a method) and wiring lands ON it (on the bare class name).
        (
            "new",
            _DEP + "class A:\n    def go(self):\n        return Dep()\n",
            {("new.mod.A.go", "new.mod.Dep", CONSTRUCT)},
            None,
        ),
        # `self._d: Base` calling `.run()` is an edge to Base even though a Sub may be injected — the
        # DECLARED type is the architectural dependency, and chasing the concrete would invent an edge the
        # source never states. Sub must be absent, which only an exact-set assertion can show.
        (
            "declared",
            "class Base:\n    def run(self) -> None: ...\n\n\nclass Sub(Base): ...\n\n\n"
            "class A:\n    def __init__(self, d: Base):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n",
            {("declared.mod.A.go", "declared.mod.Base.run", CALLS)},
            None,
        ),
        # ---- what must NOT produce an edge ------------------------------------------------------------
        # `self._factory()` invokes the OBJECT held in that field. Asking which class defines a method named
        # `_factory` is the wrong question, and answering "none" would report a miss on correct code — which
        # is exactly what f1u.3's channel caught on our own `Cli.run` doing `self.engine(...)`.
        (
            "field_call",
            "class A:\n    def __init__(self, factory: type):\n        self._factory = factory\n\n"
            "    def go(self):\n        self._factory()\n",
            set(),
            None,
        ),
        # A method calling itself is one node, not two — there is no relationship to draw.
        ("rec", "class A:\n    def go(self, n: int):\n        self.go(n)\n", set(), None),
        # An unowned annotation resolves to nothing: we do not invent edges into types we do not have.
        ("ext", "class A:\n    def go(self, d: SomethingExternal):\n        d.run()\n", set(), None),
        # `self.make().run()` — `make` declares no return type, so the receiver of `.run()` is undeclared and
        # nothing is emitted rather than guessed. The INNER `self.make()` is still a stated arrow, and the
        # construction inside `make` is still wiring; what must not appear is anything reaching `Dep.run`.
        (
            "chain",
            _DEP
            + "class A:\n    def make(self):\n        return Dep()\n\n    def go(self):\n        self.make().run()\n",
            {("chain.mod.A.go", "chain.mod.A.make", CALLS), ("chain.mod.A.make", "chain.mod.Dep", CONSTRUCT)},
            None,
        ),
        # Calling the same collaborator twice is ONE dependency, not two — edges are a deduped set.
        (
            "dedup",
            _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n        d.run()\n",
            {("dedup.mod.A.go", "dedup.mod.Dep.run", CALLS)},
            None,
        ),
        # ---- a resolver miss is a FINDING, not a silent fallback (bd f1u.3) ---------------------------
        # Every ancestor of Dep is ours, so `delete` existing nowhere means either our MRO walk has a gap or
        # the repo has a missing attribute a type checker would also flag. Both are worth saying out loud.
        (
            "miss",
            _DEP + "class A:\n    def go(self, d: Dep):\n        d.delete()\n",
            set(),
            "Dep.delete",
        ),
        # `Dep` derives from a base we do not own, so `serialise` is plausibly defined out there. We do not
        # track outside our packages by decision, and a drop we EXPECT must not be reported — a miss channel
        # that cries wolf is one nobody reads.
        (
            "open",
            "from external import Model\n\n\nclass Dep(Model):\n    def run(self) -> None: ...\n\n\n"
            "class A:\n    def go(self, d: Dep):\n        d.serialise()\n",
            set(),
            None,
        ),
    ],
)
def test_edges(monkeypatch, tmp_path, write_pkg, name, src, expected, miss):
    engine = _engine(monkeypatch, tmp_path, write_pkg, name, src)
    edges = engine.edges()
    assert _triples(edges) == expected, f"{name}: {sorted(_triples(edges))}"
    if miss is None:
        assert engine.misses == [], f"{name}: nothing here is an unresolved in-project chain"
    else:
        assert any(miss in m for m in engine.misses), f"{name}: {engine.misses}"


def test_class_edges(monkeypatch, tmp_path, write_pkg):
    """The coarse projection every existing consumer reads: (source, target, kind), deduped.

    The dropped self-pair is the load-bearing half. An intra-class call is real structure at the method tier
    and NOT a dependency between two classes, which is the same fold the import graph performs on an
    intra-file arrow — so the two tiers must disagree here, deliberately.
    """
    internal = "class A:\n    def _helper(self) -> None: ...\n\n    def go(self):\n        self._helper()\n"
    engine = _engine(monkeypatch, tmp_path, write_pkg, "ce_self", internal)
    assert engine.edges(), "the method-level arrow exists"
    assert engine.class_edges() == [], "...and projects away at the class tier"

    both = _engine(monkeypatch, tmp_path, write_pkg, "ce_both", _FIELD)
    assert both.class_edges() == [("ce_both.mod.A", "ce_both.mod.Dep", CALLS)], "a real pair survives, method-free"

    # Two calls to the same collaborator from DIFFERENT methods are two method arrows and one class arrow —
    # the projection is what makes the coarse view stable under refactoring inside a class.
    twice = (
        _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n\n    def again(self, d: Dep):\n        d.run()\n"
    )
    engine = _engine(monkeypatch, tmp_path, write_pkg, "ce_fold", twice)
    assert len(engine.edges()) == 2 and len(engine.class_edges()) == 1


def test_report(monkeypatch, tmp_path, write_pkg):
    """The explorer view, and the one place the calls/construct partition is stated to a human.

    Both sections are asserted present even when one is empty: a reader scanning for "what does this class
    construct?" must be able to tell "none" from "the section is missing", and a report that silently drops
    an empty half makes those two look identical.
    """
    engine = _engine(
        monkeypatch, tmp_path, write_pkg, "rep", _DEP + "class A:\n    def go(self):\n        Dep().run()\n"
    )
    text = engine.report()
    assert text.splitlines()[0] == "call arrows: 2"
    assert "calls -> the defining method (1):" in text and "construct -> the concrete class (1):" in text
    assert "  rep.mod.A.go -> rep.mod.Dep.run" in text, "a call names both METHOD endpoints"
    assert "  rep.mod.A.go -> rep.mod.Dep" in text, "a construction lands on the class, not a method"
    assert "unresolved" not in text, "the miss section appears only when there are misses"

    # A miss is surfaced in the report rather than only on the attribute — it is a finding about OUR
    # resolution, and one nobody can see is one nobody fixes.
    missing = _engine(
        monkeypatch, tmp_path, write_pkg, "rep_miss", _DEP + "class A:\n    def go(self, d: Dep):\n        d.delete()\n"
    )
    assert "unresolved on an in-project chain (1):" in missing.report()

    empty = _engine(monkeypatch, tmp_path, write_pkg, "rep_none", "class A: ...\n").report()
    assert "call arrows: 0" in empty and "calls -> the defining method (0):" in empty


def _expr(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body


@pytest.mark.parametrize(
    ("receiver", "expected"),
    [
        # `self.x` -> the class's field map, which is where a declared field's type already lives.
        ("self._d", {"Dep"}),
        # A field the map does not know is not a guess — an undeclared field yields nothing, never the
        # attribute name as if it were a type.
        ("self._unknown", set()),
        # A CONSTRUCTION receiver: the value is unnamed, not undeclared, and the source says which class.
        ("Dep()", {"Dep"}),
        ("mod.Dep()", {"Dep"}),  # the trailing name is the class even through a dotted callee
        # A bare name prefers its DECLARED type — a local/param shadowing a class name is the local.
        ("d", {"Other"}),
        # ...and a name with no declared type is returned AS a name, so the caller can ask the resolver
        # whether it denotes a class (the static-call path, `Resolver.field_types(cls)`).
        ("Dep", {"Dep"}),
        # Anything the source does not declare here — a subscript, a reflective lookup — yields nothing.
        ("xs[0]", set()),
        ("getattr(self, 'x')", {"getattr"}),
    ],
)
def test_receiver_type_names(receiver, expected):
    """The receiver rule, read straight off what is already in scope — the question every call edge starts
    from, and the reason this resolver is "precise but incomplete" rather than merely approximate.

    Driven on a real `CallSite` with a hand-built scope instead of through `edges()`, because the four
    shapes it distinguishes are otherwise only reachable in combination; a wrong answer for a subscript
    would show up at the top level as one missing arrow among many, with nothing pointing here.
    """
    site = CallSite(
        cls="mod.A",
        method="go",
        scope=FileScope(module="mod", local=frozenset({"Dep", "Other", "A"})),
        fields={"_d": {"Dep"}},
        declared={"d": {"Other"}},
    )
    assert site.receiver_type_names(_expr(receiver)) == expected
