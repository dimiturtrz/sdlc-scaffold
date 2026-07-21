"""Unit tests for devtools/purity.py — a @property must not mutate."""

import ast

from devtools.purity import PropertyPurity


def _hits(src: str) -> list[str]:
    return PropertyPurity([], trees=[])._violations_in(ast.parse(src), "mod.py")


def _prop(body: str, decorator: str = "@property") -> str:
    return f"class A:\n    {decorator}\n    def total(self):\n{body}\n"


# ---- the mutation, in each of the four shapes an assignment takes -------------------------------------


def test_a_property_that_assigns_to_self_is_a_violation():
    hits = _hits(_prop("        self._cache = 1\n        return self._cache"))
    assert len(hits) == 1
    assert "A.total" in hits[0], "the finding names the property"
    assert "self._cache" in hits[0], "and the field it writes"
    assert "mod.py:4" in hits[0], "and its line"


def test_an_augmented_assignment_is_a_violation():
    """`self.n += 1` in a getter is the reads-are-writes bug in its purest form."""
    assert len(_hits(_prop("        self.n += 1\n        return self.n"))) == 1


def test_an_annotated_assignment_is_a_violation():
    assert len(_hits(_prop("        self.n: int = 1\n        return self.n"))) == 1


def test_deleting_a_field_is_a_violation():
    """`del self.x` changes the object exactly as much as writing to it does."""
    assert len(_hits(_prop("        del self.n\n        return 1"))) == 1


def test_a_lazy_memo_is_the_case_this_gate_exists_for():
    """The hand-rolled cache — the shape that reads as innocent and is why the message names
    `functools.cached_property` rather than just saying no."""
    hits = _hits(_prop("        if self._r is None:\n            self._r = build()\n        return self._r"))
    assert len(hits) == 1
    assert "cached_property" in hits[0], "the finding points at the fix, not just the fault"


def test_a_cached_property_is_still_held_to_purity():
    """Its caching is the DESCRIPTOR's job; a body that also writes self is a second, hand-rolled cache."""
    assert len(_hits(_prop("        self._x = 1\n        return self._x", decorator="@cached_property"))) == 1


def test_a_write_inside_a_nested_function_still_counts():
    assert len(_hits(_prop("        def go():\n            self.n = 1\n        return go"))) == 1


def test_every_write_is_reported_not_just_the_first():
    """Two writes are two places to fix — a reviewer wants both lines, not a sample."""
    assert len(_hits(_prop("        self.a = 1\n        self.b = 2\n        return self.a"))) == 2


# ---- the setter is the declared exception ------------------------------------------------------------


def test_a_setter_may_assign_to_self():
    """That is the entire purpose of a setter — the one place where writing is the contract."""
    assert _hits(_prop("        self._total = 1", decorator="@total.setter")) == []


def test_a_deleter_may_delete():
    assert _hits(_prop("        del self._total", decorator="@total.deleter")) == []


# ---- not a mutation ----------------------------------------------------------------------------------


def test_a_pure_property_is_fine():
    assert _hits(_prop("        return self._a + self._b")) == []


def test_a_local_variable_is_not_a_mutation():
    assert _hits(_prop("        total = self._a + 1\n        return total")) == []


def test_writing_to_something_that_is_not_self_is_not_this_gate():
    """Mutating a collaborator is a different smell; this axis is about the object's OWN state."""
    assert _hits(_prop("        other.n = 1\n        return 1")) == []


def test_a_plain_method_may_mutate_freely():
    assert _hits("class A:\n    def go(self):\n        self.n = 1\n") == []


def test_a_module_level_function_is_not_a_property():
    """The walk is class-scoped: a bare decorated function outside a class has no property semantics."""
    assert _hits("@property\ndef total(self):\n    self.n = 1\n") == []
