"""Unit tests for devtools/arrows.py — typed class->class arrow extraction (inherits / holds / references).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import ast

import pytest

from devtools.arrows import HOLDS, INHERITS, REFERENCES, ClassArrows


def _cls(src: str) -> ast.ClassDef:
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))


def _kinds(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> set[tuple[str, str, str]]:
    """Edges for a one-module package, scanned the way the gate runs it: from the project root, by
    RELATIVE package name (an absolute path would dot-join into a nonsense module id)."""
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return set(ClassArrows([name]).edges())


@pytest.mark.parametrize(
    ("case", "src", "held"),
    [
        ("class-body annotation", "class A:\n    store: Store\n", True),
        ("self-annotated assignment", "class A:\n    def __init__(self):\n        self.store: Store = None\n", True),
        # The DI shape: an annotated parameter KEPT as state — the annotation is the field's type.
        (
            "init param kept as a field",
            "class A:\n    def __init__(self, store: Store):\n        self._store = store\n",
            True,
        ),
        ("direct construction", "class A:\n    def __init__(self):\n        self._store = Store()\n", True),
        # A parameter the class never keeps is a signature REFERENCE, not composition — this row is the
        # boundary between the two kinds, and getting it wrong collapses `references` into `holds`.
        ("unassigned param", "class A:\n    def __init__(self, store: Store):\n        pass\n", False),
    ],
)
def test_field_types(case, src, held):
    assert ("Store" in ClassArrows.field_types(_cls(src))) is held, case


@pytest.mark.parametrize(
    ("case", "src", "referenced"),
    [
        ("parameter type", "class A:\n    def run(self, r: Report) -> None: ...\n", True),
        ("return type", "class A:\n    def build(self) -> Report: ...\n", True),
        ("keyword-only parameter", "class A:\n    def run(self, *, r: Report) -> None: ...\n", True),
        # An unannotated signature names no type at all — the API surface is what is DECLARED, and guessing
        # from a parameter's name would invent edges the code never states.
        ("unannotated parameter", "class A:\n    def run(self, r) -> None: ...\n", False),
    ],
)
def test_signature_types(case, src, referenced):
    assert ("Report" in ClassArrows.signature_types(_cls(src))) is referenced, case


def test_edges(monkeypatch, tmp_path, write_pkg):
    """Every arrow kind, plus the two rules about which kind wins and what is emitted at all.

    The self-arrow row SUPERSEDES "a class never points at itself" (bd a0a). Self-arrows were filtered out,
    so a tree node owning a child of its own type produced no `holds` edge — self-composition was invisible
    in the object graph rather than excluded on purpose, and could never form an SCC for the cycle gate to
    see. An arrow is a FACT about the source; whether the shape is a defect belongs to a gate, and
    `composition.py` states its boundary: a recursive type can be built alone so a self-loop does not block,
    a mutually-owning PAIR cannot so it does.
    """
    base = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_res", "class Base: ...\n\n\nclass Sub(Base): ...\n")
    assert ("arrows_res.mod.Sub", "arrows_res.mod.Base", INHERITS) in base, "a same-file base resolves"

    # A builtin / third-party base is not a class we own — emit nothing rather than a wrong edge.
    external = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_ext", "class Boom(ValueError): ...\n")
    assert external == set(), "no edge to a type outside the graphed packages"

    recursive = "class Node:\n    def __init__(self, child: Node):\n        self._child = child\n"
    loops = _kinds(monkeypatch, tmp_path, write_pkg, "arrows_self", recursive)
    assert ("arrows_self.mod.Node", "arrows_self.mod.Node", HOLDS) in loops, "self-composition is a real arrow"

    # A type both HELD and named in a signature is composition, not double-counted as an API reference.
    both = "class Dep: ...\n\n\nclass A:\n    def __init__(self, d: Dep):\n        self._d = d\n\n    def use(self, d: Dep) -> None: ...\n"
    assert {k for _, d, k in _kinds(monkeypatch, tmp_path, write_pkg, "arrows_dedup", both) if d.endswith(".Dep")} == {
        HOLDS
    }, "holds wins over references for the same type"

    ref_only = "class Dep: ...\n\n\nclass A:\n    def use(self, d: Dep) -> None: ...\n"
    assert {
        k for _, d, k in _kinds(monkeypatch, tmp_path, write_pkg, "arrows_refonly", ref_only) if d.endswith(".Dep")
    } == {REFERENCES}, "a type only ever named in a signature stays a reference"


def test_report(monkeypatch, tmp_path, write_pkg):
    """The explorer view: a count, then one SECTION PER KIND, present even when a kind is empty.

    An absent section and a section reading `(0)` are different messages — the first looks like the engine
    forgot to look, the second says it looked and found nothing. A reader diffing two reports needs the
    stable shape, so the empty section is the contract rather than an accident of formatting.
    """
    src = "class Base: ...\n\n\nclass Sub(Base):\n    def __init__(self, b: Base):\n        self._b = b\n"
    write_pkg(tmp_path, "arrows_report", src)
    monkeypatch.chdir(tmp_path)
    engine = ClassArrows(["arrows_report"])
    text = engine.report()

    assert text.startswith(f"class arrows: {len(engine.edges())}"), "the headline counts the arrows emitted"
    for kind in (INHERITS, HOLDS, REFERENCES):
        assert f"{kind} (" in text, f"{kind} has a section even when it is empty"
    assert f"{REFERENCES} (0):" in text, "nothing is referenced-not-held here, and the section still says so"
    assert "  arrows_report.mod.Sub -> arrows_report.mod.Base" in text, "each row names both endpoints"
    assert text.count("arrows_report.mod.Sub -> arrows_report.mod.Base") == 2, "listed once per kind it carries"


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
