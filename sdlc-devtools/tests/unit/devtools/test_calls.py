"""Unit tests for devtools/calls.py — behavioural arrows resolved to the DECLARED receiver type, and from
there to the method that type actually DEFINES (bd f1u.2)."""

from devtools.calls import CALLS, CONSTRUCT, CallArrows

_DEP = "class Dep:\n    def run(self) -> None: ...\n\n\n"


def _engine(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> CallArrows:
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return CallArrows([name])


def _edges(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> list:
    return _engine(monkeypatch, tmp_path, write_pkg, name, src).edges()


def _targets(edges, kind: str = CALLS) -> set[str]:
    """The class each arrow of this kind lands on — the coarse cut, for the resolution tests."""
    return {e.target for e in edges if e.kind == kind}


def _arrows(edges, kind: str = CALLS) -> set[tuple[str, str]]:
    """(source node, target node) — the METHOD-level cut, which is what actually ships now."""
    return {(e.source_id, e.target_id) for e in edges if e.kind == kind}


# ---- receivers that the source DECLARES ---------------------------------------------------------------


def test_a_call_on_a_field_resolves_through_the_field_map(monkeypatch, tmp_path, write_pkg):
    src = (
        _DEP
        + "class A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
    )
    assert "calls_field.mod.Dep" in _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_field", src))


def test_a_call_on_a_parameter_resolves_through_its_annotation(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n"
    assert "calls_param.mod.Dep" in _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_param", src))


def test_a_call_on_a_local_resolves_through_its_constructor(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self):\n        d = Dep()\n        d.run()\n"
    assert "calls_local.mod.Dep" in _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_local", src))


# ---- the arrow terminates on the METHOD (bd f1u.2) ----------------------------------------------------


def test_a_call_lands_on_the_method_it_invokes(monkeypatch, tmp_path, write_pkg):
    """The whole point of the tier: `self._d.run()` is an arrow into `Dep.run`, not merely at `Dep`. Both
    endpoints were always in hand at walk time — the target is the attribute name, the source is the
    enclosing def — and the per-class aggregation was throwing them away."""
    src = (
        _DEP
        + "class A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_method", src)
    assert ("calls_method.mod.A.go", "calls_method.mod.Dep.run") in _arrows(edges)


def test_an_inherited_call_lands_on_the_base_that_defines_it(monkeypatch, tmp_path, write_pkg):
    """ONE rule covers every case: walk the project MRO to whoever DEFINES the method. Sub inherits `run`,
    so the code being invoked lives on Base and that is where the arrow points — pointing at Sub would name
    a method that does not exist there."""
    src = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Sub(Base): ...\n\n\n"
        "class A:\n    def go(self, s: Sub):\n        s.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_mro", src)
    assert ("calls_mro.mod.A.go", "calls_mro.mod.Base.run") in _arrows(edges)


def test_an_override_wins_over_the_base(monkeypatch, tmp_path, write_pkg):
    """The walk stops at the FIRST definer, so a subclass that overrides gets the arrow. Without that, an
    override would be drawn as dead code while its base collected traffic it never receives."""
    src = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Sub(Base):\n    def run(self) -> None: ...\n\n\n"
        "class A:\n    def go(self, s: Sub):\n        s.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_override", src)
    assert _arrows(edges) == {("calls_override.mod.A.go", "calls_override.mod.Sub.run")}


def test_a_protocol_receiver_lands_on_the_protocol(monkeypatch, tmp_path, write_pkg):
    """Not a special case — the call->interface partition falling out of the same MRO rule. A declared
    Protocol receiver defines the method, so the arrow reaches the CONTRACT."""
    src = (
        "from typing import Protocol\n\n\n"
        "class Runs(Protocol):\n    def run(self) -> None: ...\n\n\n"
        "class A:\n    def go(self, r: Runs):\n        r.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_proto", src)
    assert ("calls_proto.mod.A.go", "calls_proto.mod.Runs.run") in _arrows(edges)


def test_a_call_on_a_construction_resolves_to_what_was_built(monkeypatch, tmp_path, write_pkg):
    """`Dep().run()` — the receiver is unnamed, not undeclared. The source says exactly which class it is,
    and refusing the shape was costing most of the tier's cross-class connectivity (fluent construction is
    ordinary in this codebase: `Trees(pkgs).walk()`)."""
    src = _DEP + "class A:\n    def go(self):\n        Dep().run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_fluent", src)
    assert ("calls_fluent.mod.A.go", "calls_fluent.mod.Dep.run") in _arrows(edges)


def test_a_static_call_through_the_class_name_resolves(monkeypatch, tmp_path, write_pkg):
    """`Dep.make()` — the receiver IS the class. It is not a parameter or a local, so the declared-types
    map is rightly empty for it; the name simply denotes a class, which is the resolver's usual question."""
    src = "class Dep:\n    @staticmethod\n    def make() -> None: ...\n\n\nclass A:\n    def go(self):\n        Dep.make()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_static", src)
    assert ("calls_static.mod.A.go", "calls_static.mod.Dep.make") in _arrows(edges)


def test_a_local_shadowing_a_class_name_keeps_its_declared_type(monkeypatch, tmp_path, write_pkg):
    """Precedence matters: a parameter named after a class is the PARAMETER. Resolving the bare name to the
    class instead would attribute the call to the wrong receiver — a wrong edge, which this resolver never
    emits by design."""
    src = (
        "class Dep:\n    def run(self) -> None: ...\n\n\n"
        "class Other:\n    def run(self) -> None: ...\n\n\n"
        "class A:\n    def go(self, Dep: Other):\n        Dep.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_shadow", src)
    assert _arrows(edges) == {("calls_shadow.mod.A.go", "calls_shadow.mod.Other.run")}


def test_an_intra_class_call_is_an_arrow_between_two_methods(monkeypatch, tmp_path, write_pkg):
    """SUPERSEDES "calling your own method is not a dependency". At the class tier that was right and still
    is — it projects to a self-pair and `class_edges` drops it. At the METHOD tier a public method calling
    its own private helper is real internal structure, and it is the reason the `all` depth stop exists."""
    src = "class A:\n    def _helper(self) -> None: ...\n\n    def go(self):\n        self._helper()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_self", src)
    assert ("calls_self.mod.A.go", "calls_self.mod.A._helper") in _arrows(edges)


def test_the_class_projection_drops_what_is_internal(monkeypatch, tmp_path, write_pkg):
    """The coarse view every existing consumer reads: an intra-class call is not a dependency BETWEEN
    classes, which is the same fold the import graph performs on an intra-file arrow."""
    src = "class A:\n    def _helper(self) -> None: ...\n\n    def go(self):\n        self._helper()\n"
    engine = _engine(monkeypatch, tmp_path, write_pkg, "calls_proj", src)
    assert engine.edges(), "the method-level arrow exists"
    assert engine.class_edges() == [], "...and projects away at the class tier"


def test_calling_a_field_is_not_a_call_to_a_method_of_that_name(monkeypatch, tmp_path, write_pkg):
    """`self._factory()` invokes the OBJECT held in that field. Asking which class defines a method called
    `_factory` is the wrong question, and answering "none" would report a miss on correct code — which is
    exactly what f1u.3's channel caught on our own `Cli.run` doing `self.engine(...)`."""
    src = "class A:\n    def __init__(self, factory: type):\n        self._factory = factory\n\n    def go(self):\n        self._factory()\n"
    engine = _engine(monkeypatch, tmp_path, write_pkg, "calls_field_call", src)
    assert engine.edges() == []
    assert engine.misses == [], "a callable field is not a missing method"


def test_direct_recursion_is_not_an_arrow(monkeypatch, tmp_path, write_pkg):
    """A method calling itself is one node, not two — there is no relationship to draw."""
    src = "class A:\n    def go(self, n: int):\n        self.go(n)\n"
    assert _edges(monkeypatch, tmp_path, write_pkg, "calls_rec", src) == []


# ---- construct: the CONCRETE, at the site that chose it -----------------------------------------------


def test_constructing_a_class_is_tagged_construct(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self):\n        return Dep()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_new", src)
    assert _targets(edges, CONSTRUCT) == {"calls_new.mod.Dep"}


def test_construct_lands_on_the_class_not_a_method(monkeypatch, tmp_path, write_pkg):
    """Constructing is `__init__`, i.e. the class as a whole. So the partition is: behavioural coupling
    lands INSIDE the box (on a method), wiring lands ON it."""
    src = _DEP + "class A:\n    def go(self):\n        return Dep()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_new_node", src)
    assert _arrows(edges, CONSTRUCT) == {("calls_new_node.mod.A.go", "calls_new_node.mod.Dep")}


def test_calls_and_construct_are_distinguishable(monkeypatch, tmp_path, write_pkg):
    """The partition the design rests on: behaviour on the contract, construction at the wiring site."""
    src = _DEP + "class A:\n    def go(self):\n        d = Dep()\n        d.run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_both", src)
    assert _targets(edges, CONSTRUCT) == {"calls_both.mod.Dep"}, "the construction is tagged"
    assert _targets(edges, CALLS) == {"calls_both.mod.Dep"}, "the behavioural call is separate"


def test_a_call_resolves_to_the_DECLARED_type_not_the_concrete(monkeypatch, tmp_path, write_pkg):
    """`self._d: Base` calling `.run()` is an edge to Base even though a Sub was injected — the declared
    type IS the architectural dependency, and chasing the concrete would invent an edge the source never
    states. The concrete coupling shows up only where it is CONSTRUCTED."""
    src = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Sub(Base): ...\n\n\n"
        "class A:\n    def __init__(self, d: Base):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
    )
    called = _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_declared", src))
    assert "calls_declared.mod.Base" in called, "the call lands on the declared contract"
    assert "calls_declared.mod.Sub" not in called, "never the concrete — the source does not say so here"


# ---- what must NOT produce an edge --------------------------------------------------------------------


def test_a_call_on_a_returned_value_yields_nothing(monkeypatch, tmp_path, write_pkg):
    """`self.make().run()` — the source declares no return type for `make`, so the receiver of `.run()` is
    undeclared and we emit nothing rather than guess. Precise but incomplete, by design.

    The inner `self.make()` IS an arrow, and asserting an empty edge set here would now be wrong: that call
    is stated in the source and lands on a method we own. What must not appear is anything reaching Dep.
    """
    src = _DEP + "class A:\n    def make(self):\n        return Dep()\n\n    def go(self):\n        self.make().run()\n"
    engine = _engine(monkeypatch, tmp_path, write_pkg, "calls_chain", src)
    assert _arrows(engine.edges()) == {("calls_chain.mod.A.go", "calls_chain.mod.A.make")}
    assert engine.misses == [], "an undeclared receiver is not a resolver miss — there was nothing to resolve"


def test_calling_an_unowned_type_yields_nothing(monkeypatch, tmp_path, write_pkg):
    src = "class A:\n    def go(self, d: SomethingExternal):\n        d.run()\n"
    assert _edges(monkeypatch, tmp_path, write_pkg, "calls_ext", src) == []


def test_edges_are_deduped(monkeypatch, tmp_path, write_pkg):
    """Calling the same collaborator twice is ONE dependency, not two."""
    src = _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n        d.run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_dedup", src)
    assert len([e for e in edges if e.kind == CALLS]) == 1


# ---- a resolver miss is a FINDING, not a silent fallback (bd f1u.3) -----------------------------------


def test_a_missing_method_on_an_in_project_chain_is_reported(monkeypatch, tmp_path, write_pkg):
    """Now that a call resolves to a DEFINER, a miss is mechanically meaningful. Every ancestor of Dep is
    ours, so `delete` existing nowhere means either our MRO walk has a gap or the repo has a missing
    attribute a type checker would also flag. Both are worth saying out loud."""
    src = _DEP + "class A:\n    def go(self, d: Dep):\n        d.delete()\n"
    engine = _engine(monkeypatch, tmp_path, write_pkg, "calls_miss", src)
    assert engine.edges() == [], "no edge is invented for a method we cannot find"
    assert any("Dep.delete" in m for m in engine.misses), engine.misses


def test_a_chain_leaving_the_project_drops_quietly(monkeypatch, tmp_path, write_pkg):
    """`Dep` derives from a base we do not own, so `serialise` is plausibly defined out there. We do not
    track outside our own packages by decision, and a drop we EXPECT must not be reported as a finding —
    a miss channel that cries wolf is one nobody reads."""
    src = (
        "from external import Model\n\n\n"
        "class Dep(Model):\n    def run(self) -> None: ...\n\n\n"
        "class A:\n    def go(self, d: Dep):\n        d.serialise()\n"
    )
    engine = _engine(monkeypatch, tmp_path, write_pkg, "calls_open", src)
    assert engine.edges() == []
    assert engine.misses == [], "the chain leaves the project — an honest drop, not a finding"
