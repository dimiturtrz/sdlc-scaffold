"""Unit tests for devtools/names.py — dotted-name reduction over AST expressions."""

import ast

from devtools.names import Names


def _bases_of(src: str) -> set[str]:
    return Names.bases(next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef)))


def test_trailing_reduces_a_bare_name():
    assert Names.trailing(ast.parse("ABC", mode="eval").body) == "ABC"


def test_trailing_reduces_a_dotted_attribute():
    assert Names.trailing(ast.parse("abc.ABC", mode="eval").body) == "ABC", "dotted reduces to the trailing name"


def test_trailing_is_none_for_a_non_name_expression():
    assert Names.trailing(ast.parse("f()", mode="eval").body) is None


def test_bases_mixes_bare_and_dotted():
    assert _bases_of("class A(x.B, C): ...") == {"B", "C"}


def test_bases_of_a_baseless_class_is_empty():
    assert _bases_of("class A: ...") == set()


def test_decorator_reduces_the_bare_form():
    assert Names.decorator(ast.parse("dataclass", mode="eval").body) == "dataclass"


def test_decorator_unwraps_the_factory_call():
    """`@dataclass(frozen=True)` must reduce to the same name as `@dataclass` — a factory is still it."""
    assert Names.decorator(ast.parse("dataclass(frozen=True)", mode="eval").body) == "dataclass"


def test_decorator_unwraps_a_dotted_factory_call():
    assert Names.decorator(ast.parse("dataclasses.dataclass(frozen=True)", mode="eval").body) == "dataclass"
