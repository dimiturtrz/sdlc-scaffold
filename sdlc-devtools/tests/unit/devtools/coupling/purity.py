"""Unit tests for devtools/purity.py — a @property must not mutate.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.

Driven through the PUBLIC seam `violations()` with trees injected at the constructor, not through the
private `_violations_in`. The injection point is the module's own design (bd 5cg) — it takes parsed trees
precisely so a caller can supply them — so testing through it costs nothing and stops the suite from
freezing a private helper's signature.
"""

import ast
import logging
from pathlib import Path

import pytest

from devtools.coupling.purity import PropertyPurity


def _hits(src: str) -> list[str]:
    """The findings for one snippet, through the public seam with a hand-built tree."""
    return PropertyPurity([], trees=[(Path("mod.py"), ast.parse(src))]).violations()


def _prop(body: str, decorator: str = "@property") -> str:
    return f"class A:\n    {decorator}\n    def total(self):\n{body}\n"


@pytest.mark.parametrize(
    ("label", "decorator", "body", "hits"),
    [
        # ---- the mutation, in each of the four shapes an assignment takes ----------------------------
        ("plain assign", "@property", "        self._cache = 1\n        return self._cache", 1),
        # `self.n += 1` in a getter is the reads-are-writes bug in its purest form.
        ("augmented", "@property", "        self.n += 1\n        return self.n", 1),
        ("annotated", "@property", "        self.n: int = 1\n        return self.n", 1),
        # `del self.x` changes the object exactly as much as writing to it does.
        ("delete", "@property", "        del self.n\n        return 1", 1),
        # The hand-rolled cache — the shape that reads as innocent, and the reason the message names
        # `functools.cached_property` rather than just saying no.
        (
            "lazy memo",
            "@property",
            "        if self._r is None:\n            self._r = build()\n        return self._r",
            1,
        ),
        # A cached_property's caching is the DESCRIPTOR's job; a body that also writes self is a second,
        # hand-rolled cache on top of the real one — the exact confusion this gate exists to name.
        ("cached_property", "@cached_property", "        self._x = 1\n        return self._x", 1),
        ("nested function", "@property", "        def go():\n            self.n = 1\n        return go", 1),
        # Two writes are two places to fix — a reviewer wants both lines, not a sample.
        ("every write", "@property", "        self.a = 1\n        self.b = 2\n        return self.a", 2),
        # ---- the setter/deleter is the declared exception ---------------------------------------------
        # That is the entire purpose of a setter: the one place where writing to self IS the contract.
        ("setter", "@total.setter", "        self._total = 1", 0),
        ("deleter", "@total.deleter", "        del self._total", 0),
        # ---- not a mutation ---------------------------------------------------------------------------
        ("pure", "@property", "        return self._a + self._b", 0),
        ("local variable", "@property", "        total = self._a + 1\n        return total", 0),
        # Mutating a COLLABORATOR is a different smell; this axis is about the object's own state.
        ("not self", "@property", "        other.n = 1\n        return 1", 0),
    ],
)
def test_violations(label, decorator, body, hits):
    found = _hits(_prop(body, decorator=decorator))
    assert len(found) == hits, f"{label}: expected {hits} finding(s), got {found}"


def test_violations_message_and_scope():
    """The finding's TEXT (it must be actionable) and the walk's scope (class-bodied properties only).

    Split from the table above because these two assert on the message and on non-property shapes rather
    than on a count — the table's parameter is a count, and folding a string check into it would make every
    row carry a column only two rows use.
    """
    found = _hits(_prop("        self._cache = 1\n        return self._cache"))
    assert "A.total" in found[0], "the finding names the property"
    assert "self._cache" in found[0], "and the field it writes"
    assert "mod.py:4" in found[0], "and its line"
    assert "cached_property" in _hits(_prop("        self._r = build()\n        return self._r"))[0], (
        "the finding points at the fix, not just the fault"
    )
    assert _hits("class A:\n    def go(self):\n        self.n = 1\n") == [], "a plain method may mutate freely"
    # The walk is class-scoped: a bare decorated function outside a class has no property semantics.
    assert _hits("@property\ndef total(self):\n    self.n = 1\n") == []


@pytest.mark.parametrize(
    ("decorator", "expected"),
    [
        ("@property", True),
        # Included DELIBERATELY: caching is done by the descriptor, so a body that assigns to self is a
        # second cache, not an implementation of the first.
        ("@cached_property", True),
        ("@functools.cached_property", True),  # matched on the ATTRIBUTE half, so a qualified spelling works
        ("@total.setter", False),  # the declared exception — mutating is the whole job
        ("@total.deleter", False),
        ("@staticmethod", False),
        ("@lru_cache", False),  # a cache that is not a property is not this gate's subject
    ],
)
def test_is_property_read(decorator, expected):
    """Which functions the purity rule applies to at all — a pure READ (`@property`/`@cached_property`, not a
    setter/deleter). Distinct from `mirror.MethodMirror.is_property_member`, which INCLUDES setters because
    it asks a different question (how a member is exercised); the two are separate predicates, not one reused
    across gates, and the names now say so (bd 0d1).
    """
    src = f"class A:\n    {decorator}\n    def total(self):\n        return 1\n"
    func = next(n for n in ast.parse(src).body[0].body if isinstance(n, ast.FunctionDef))
    assert PropertyPurity.is_property_read(func) is expected, f"{decorator} -> {expected}"


def test_assigned_selves():
    """The four statement kinds normalised to ONE stream of `self.<field>` targets.

    They keep their targets in three differently-shaped fields (`targets` list, single `target`, `targets`
    again), so the normalisation is where a missed write would hide — and a missed write is a violation the
    gate silently fails to report, which is the expensive direction.
    """
    src = (
        "def f(self):\n"
        "    self.a = 1\n"
        "    self.b += 2\n"
        "    self.c: int = 3\n"
        "    del self.d\n"
        "    local = 4\n"
        "    other.e = 5\n"
        "    self.f.g = 6\n"
    )
    func = ast.parse(src).body[0]
    written = [node.attr for node in PropertyPurity.assigned_selves(func)]
    assert sorted(written) == ["a", "b", "c", "d"], f"one stream over all four shapes, got {written}"
    assert "e" not in written, "a write to a collaborator is not a write to self"
    assert "g" not in written, "`self.f.g = 6` writes to the FIELD's object, not to a field of self"


def test_report():
    """The explorer view: a headline count plus every finding, so the text is usable without the gate."""
    dirty = PropertyPurity([], trees=[(Path("mod.py"), ast.parse(_prop("        self.n = 1")))])
    text = dirty.report()
    assert text.startswith("mutating properties: 1"), f"the count leads, got {text!r}"
    assert "A.total" in text, "and the findings follow it"
    clean = PropertyPurity([], trees=[(Path("mod.py"), ast.parse(_prop("        return self._n")))])
    assert clean.report() == "mutating properties: 0", "a clean run is the headline alone, not an empty line"


def test_run_assert(caplog):
    """The gate view: exit code AND the logged findings.

    The code is what CI reads and the log is what the human reads; a gate that returned 1 while logging
    nothing would block a build with no way to learn why, so both halves are asserted together.
    """
    dirty = PropertyPurity([], trees=[(Path("mod.py"), ast.parse(_prop("        self.n = 1")))])
    with caplog.at_level(logging.ERROR):
        assert dirty.run_assert() == 1, "a mutating property blocks"
    assert "A.total" in caplog.text, "and the block says which property"
    caplog.clear()
    clean = PropertyPurity([], trees=[(Path("mod.py"), ast.parse(_prop("        return self._n")))])
    with caplog.at_level(logging.ERROR):
        assert clean.run_assert() == 0
    assert caplog.text == "", "a clean run logs nothing at ERROR"
