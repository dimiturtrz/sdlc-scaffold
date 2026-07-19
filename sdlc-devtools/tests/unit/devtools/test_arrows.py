"""Unit tests for devtools/arrows.py — typed class->class arrow extraction (inherits / holds / references)."""

import ast

from devtools.arrows import HOLDS, INHERITS, REFERENCES, ClassArrows


def _held(src: str) -> set[str]:
    return ClassArrows.field_types(next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)))


def _referenced(src: str) -> set[str]:
    return ClassArrows.signature_types(next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)))


def _kinds(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> set[tuple[str, str, str]]:
    """Edges for a one-module package, scanned the way the gate runs it: from the project root, by
    RELATIVE package name (an absolute path would dot-join into a nonsense module id)."""
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return set(ClassArrows([name]).edges())


# ---- HOLDS: every way a field's type is declared ------------------------------------------------------


def test_holds_from_a_class_body_annotation():
    assert "Store" in _held("class A:\n    store: Store\n")


def test_holds_from_a_self_annotated_assignment():
    assert "Store" in _held("class A:\n    def __init__(self):\n        self.store: Store = None\n")


def test_holds_from_an_init_parameter_assigned_to_a_field():
    """The DI shape: an annotated parameter kept as state — the annotation IS the field's type."""
    assert "Store" in _held("class A:\n    def __init__(self, store: Store):\n        self._store = store\n")


def test_holds_from_a_direct_construction():
    assert "Store" in _held("class A:\n    def __init__(self):\n        self._store = Store()\n")


def test_an_unassigned_parameter_is_not_held():
    """A parameter the class never keeps is a signature REFERENCE, not composition."""
    assert "Store" not in _held("class A:\n    def __init__(self, store: Store):\n        pass\n")


# ---- REFERENCES: signature types that are not held ----------------------------------------------------


def test_references_a_parameter_type():
    assert "Report" in _referenced("class A:\n    def run(self, r: Report) -> None: ...\n")


def test_references_a_return_type():
    assert "Report" in _referenced("class A:\n    def build(self) -> Report: ...\n")


# ---- resolution + edges ------------------------------------------------------------------------------


def test_same_file_base_resolves(monkeypatch, tmp_path, write_pkg):
    src = "class Base: ...\n\n\nclass Sub(Base): ...\n"
    edges = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_res", src)
    assert ("arrows_res.mod.Sub", "arrows_res.mod.Base", INHERITS) in edges, "same-file base resolves"


def test_unresolvable_names_are_dropped_not_guessed(monkeypatch, tmp_path, write_pkg):
    """A builtin / third-party base is not a class we own — emit nothing rather than a wrong edge."""
    edges = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_ext", "class Boom(ValueError): ...\n")
    assert edges == set(), "no edge to a type outside the graphed packages"


def test_a_class_never_points_at_itself(monkeypatch, tmp_path, write_pkg):
    src = "class A:\n    def clone(self) -> A: ...\n"
    edges = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_self", src)
    assert not [e for e in edges if e[0] == e[1]], "a self-referencing signature is not an arrow"


def test_holds_wins_over_references_for_the_same_type(monkeypatch, tmp_path, write_pkg):
    """A type both held and named in a signature is COMPOSITION — not double-counted as an API reference."""
    src = "class Dep: ...\n\n\nclass A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def use(self, d: Dep) -> None: ...\n"
    edges = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_dedup", src)
    kinds = {k for _, d, k in edges if d.endswith(".Dep")}
    assert kinds == {HOLDS}, f"expected holds only, got {kinds}"


def test_reference_only_type_stays_a_reference(monkeypatch, tmp_path, write_pkg):
    src = "class Dep: ...\n\n\nclass A:\n    def use(self, d: Dep) -> None: ...\n"
    edges = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_refonly", src)
    assert {k for _, d, k in edges if d.endswith(".Dep")} == {REFERENCES}


# ---- the ROLL-UP invariant ---------------------------------------------------------------------------


def test_arrows_roll_up_to_the_real_import_graph(monkeypatch, tmp_path):
    """`import` is the file-level ROLL-UP of the finer arrows (bd 4bl.2). Project each arrow's endpoints to
    their modules: a CROSS-file arrow must ride a real grimp import, and an INTRA-file arrow collapses to a
    self-loop the import graph legitimately cannot represent. This is the invariant tying the two tiers."""
    import sys

    import grimp

    pkg = tmp_path / "rollup_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text("class Base: ...\n")
    (pkg / "leaf.py").write_text(
        "from rollup_pkg.base import Base\n\n\nclass Leaf(Base): ...\n\n\nclass Local(Leaf): ...\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("rollup_pkg", None)

    edges = ClassArrows(["rollup_pkg"]).edges()
    imports = grimp.build_graph("rollup_pkg")
    module_of = {s: s.rsplit(".", 1)[0] for s, _, _ in edges} | {d: d.rsplit(".", 1)[0] for _, d, _ in edges}

    cross, intra = 0, 0
    for src, dst, _ in edges:
        src_mod, dst_mod = module_of[src], module_of[dst]
        if src_mod == dst_mod:
            intra += 1  # Local -> Leaf, both in leaf.py: a self-loop, so there is no import to find
            continue
        cross += 1
        assert dst_mod in imports.find_modules_directly_imported_by(src_mod), (
            f"cross-file arrow {src} -> {dst} has no backing import {src_mod} -> {dst_mod}"
        )
    assert cross and intra, f"fixture must exercise BOTH directions (cross={cross}, intra={intra})"
