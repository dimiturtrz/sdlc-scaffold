"""Unit tests for devtools/names.py — dotted-name reduction over AST expressions.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import ast

import pytest

from devtools.names import Names


def _expr(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body


def _bases_of(src: str) -> set[str]:
    return Names.bases(next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("ABC", "ABC"),
        # The dotted form is the whole reason this exists: `abc.ABC` and `ABC` must compare EQUAL against a
        # vocabulary, so an engine matching bases against {"ABC"} works whichever way the import was spelled.
        ("abc.ABC", "ABC"),
        ("a.b.c.Deep", "Deep"),
        # Anything that is not a Name/Attribute has no trailing identifier — None, never a guess. A call, a
        # subscript (`Generic[T]`) and a literal all reach this via decorator/base lists in real code.
        ("f()", None),
        ("Generic[T]", None),
        ("1", None),
    ],
)
def test_trailing(source, expected):
    assert Names.trailing(_expr(source)) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("class A(x.B, C): ...", {"B", "C"}),  # bare and dotted bases reduce into the same set
        ("class A: ...", set()),
        ("class A(object): ...", {"object"}),
        # A base with no trailing name (a subscripted generic) is DROPPED, not carried through as None — the
        # set is a vocabulary of names, and a None in it would poison every membership test downstream.
        ("class A(Generic[T], B): ...", {"B"}),
    ],
)
def test_bases(source, expected):
    assert _bases_of(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("dataclass", "dataclass"),
        # A decorator FACTORY is still that decorator: `@dataclass(frozen=True)` must reduce to the same name
        # as `@dataclass`, or a detector keyed on the name sees two different decorators and misses one form.
        ("dataclass(frozen=True)", "dataclass"),
        ("dataclasses.dataclass(frozen=True)", "dataclass"),
        ("abc.abstractmethod", "abstractmethod"),
        ("(lambda: None)()", None),  # a callee with no name at all still answers None rather than raising
    ],
)
def test_decorator(source, expected):
    assert Names.decorator(_expr(source)) == expected
