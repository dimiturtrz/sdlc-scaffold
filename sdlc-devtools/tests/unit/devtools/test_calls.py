"""Unit tests for devtools/calls.py — behavioural arrows resolved to the DECLARED receiver type."""

from devtools.calls import CONSTRUCT, CallArrows

_DEP = "class Dep:\n    def run(self) -> None: ...\n\n\n"


def _edges(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> set[tuple[str, str, str, str]]:
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return set(CallArrows([name]).edges())


def _targets(edges, via: str | None = None) -> set[str]:
    return {d for _, d, _, v in edges if via is None or v == via}


# ---- receivers that the source DECLARES ---------------------------------------------------------------


def test_a_call_on_a_field_resolves_through_the_field_map(monkeypatch, tmp_path, write_pkg):
    src = (
        _DEP
        + "class A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
    )
    assert "calls_field.mod.Dep" in _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_field", src), "")


def test_a_call_on_a_parameter_resolves_through_its_annotation(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n"
    assert "calls_param.mod.Dep" in _targets(_edges(monkeypatch, tmp_path, write_pkg, "calls_param", src), "")


def test_a_call_on_a_local_resolves_through_its_constructor(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self):\n        d = Dep()\n        d.run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_local", src)
    assert "calls_local.mod.Dep" in _targets(edges, "")


# ---- construct: the CONCRETE, at the site that chose it -----------------------------------------------


def test_constructing_a_class_is_tagged_construct(monkeypatch, tmp_path, write_pkg):
    src = _DEP + "class A:\n    def go(self):\n        return Dep()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_new", src)
    assert _targets(edges, CONSTRUCT) == {"calls_new.mod.Dep"}


def test_calls_and_construct_are_distinguishable(monkeypatch, tmp_path, write_pkg):
    """The partition the design rests on: behaviour on the contract, construction at the wiring site."""
    src = _DEP + "class A:\n    def go(self):\n        d = Dep()\n        d.run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_both", src)
    assert _targets(edges, CONSTRUCT) == {"calls_both.mod.Dep"}, "the construction is tagged"
    assert _targets(edges, "") == {"calls_both.mod.Dep"}, "the behavioural call is separate"


def test_a_call_resolves_to_the_DECLARED_type_not_the_concrete(monkeypatch, tmp_path, write_pkg):
    """`self._d: Base` calling `.run()` is an edge to Base even though a Sub was injected — the declared
    type IS the architectural dependency, and chasing the concrete would invent an edge the source never
    states. The concrete coupling shows up only where it is CONSTRUCTED."""
    src = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Sub(Base): ...\n\n\n"
        "class A:\n    def __init__(self, d: Base):\n        self._d = d\n\n    def go(self):\n        self._d.run()\n"
    )
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_declared", src)
    called = _targets(edges, "")
    assert "calls_declared.mod.Base" in called, "the call lands on the declared contract"
    assert "calls_declared.mod.Sub" not in called, "never the concrete — the source does not say so here"


# ---- what must NOT produce an edge --------------------------------------------------------------------


def test_calling_your_own_method_is_not_a_dependency(monkeypatch, tmp_path, write_pkg):
    src = "class A:\n    def helper(self) -> None: ...\n\n    def go(self):\n        self.helper()\n"
    assert _edges(monkeypatch, tmp_path, write_pkg, "calls_self", src) == set()


def test_a_call_on_a_returned_value_yields_nothing(monkeypatch, tmp_path, write_pkg):
    """`self.make().run()` — the source declares no type for that receiver here, so emit nothing rather
    than guess. Precise but incomplete, by design."""
    src = _DEP + "class A:\n    def make(self):\n        return Dep()\n\n    def go(self):\n        self.make().run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_chain", src)
    assert _targets(edges, "") == set(), "no behavioural edge invented for an undeclared receiver"


def test_calling_an_unowned_type_yields_nothing(monkeypatch, tmp_path, write_pkg):
    src = "class A:\n    def go(self, d: SomethingExternal):\n        d.run()\n"
    assert _edges(monkeypatch, tmp_path, write_pkg, "calls_ext", src) == set()


def test_edges_are_deduped(monkeypatch, tmp_path, write_pkg):
    """Calling the same collaborator twice is ONE dependency, not two."""
    src = _DEP + "class A:\n    def go(self, d: Dep):\n        d.run()\n        d.run()\n"
    edges = _edges(monkeypatch, tmp_path, write_pkg, "calls_dedup", src)
    assert len([e for e in edges if e[3] == ""]) == 1
