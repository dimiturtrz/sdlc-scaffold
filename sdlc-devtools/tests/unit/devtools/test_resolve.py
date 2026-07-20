"""Unit tests for devtools/resolve.py — name -> class resolution shared by the arrow engines."""

import ast
from pathlib import Path

from devtools.resolve import FileScope, Resolver


def _module(src: str) -> ast.Module:
    return ast.parse(src)


# ---- module naming -----------------------------------------------------------------------------------


def test_module_of_a_plain_file():
    assert Resolver.module_of(Path("pkg/sub/mod.py")) == "pkg.sub.mod"


def test_module_of_a_package_init():
    assert Resolver.module_of(Path("pkg/sub/__init__.py")) == "pkg.sub", "__init__ IS its package"


# ---- annotation unwrapping ---------------------------------------------------------------------------


def test_annotation_unwraps_optional_union():
    """`None` is an ast.Constant, not a name — an optional yields only the real type."""
    assert Resolver.annotation_names(ast.parse("Store | None", mode="eval").body) == {"Store"}


def test_annotation_unwraps_a_generic_parameter():
    assert "Store" in Resolver.annotation_names(ast.parse("list[Store]", mode="eval").body)


def test_annotation_parses_a_string_forward_reference():
    assert "Store" in Resolver.annotation_names(ast.parse("'Store'", mode="eval").body)


def test_annotation_survives_a_jaxtyping_shape_string():
    """`Float[Array, "b n"]`-style shape strings are not type expressions — they must not raise."""
    assert Resolver.annotation_names(ast.parse("'b n'", mode="eval").body) == set()


def test_annotation_of_none_is_empty():
    assert Resolver.annotation_names(None) == set()


# ---- import bindings ---------------------------------------------------------------------------------


def test_imported_names_maps_a_from_import():
    assert Resolver.imported_names(_module("from pkg.store import Store\n")) == {"Store": "pkg.store"}


def test_imported_names_honours_an_alias():
    assert Resolver.imported_names(_module("from pkg.store import Store as S\n")) == {"S": "pkg.store"}


def test_plain_import_is_not_a_name_binding():
    """`import numpy` binds a MODULE, not a class this resolver can point an arrow at."""
    assert Resolver.imported_names(_module("import numpy\n")) == {}


# ---- resolution --------------------------------------------------------------------------------------


def test_a_same_file_class_resolves_locally(monkeypatch, tmp_path, write_pkg):
    write_pkg(tmp_path, "res_local", "class Base: ...\n")
    monkeypatch.chdir(tmp_path)
    resolver = Resolver(["res_local"])
    assert resolver.resolve("Base", FileScope("res_local.mod", frozenset({"Base"}))) == "res_local.mod.Base"


def test_an_imported_class_resolves_through_its_home(monkeypatch, tmp_path, write_pkg):
    write_pkg(tmp_path, "res_imp", "class Base: ...\n")
    monkeypatch.chdir(tmp_path)
    resolver = Resolver(["res_imp"])
    scope = FileScope("res_imp.other", imports={"Base": "res_imp.mod"})
    assert resolver.resolve("Base", scope) == "res_imp.mod.Base"


def test_an_unowned_name_resolves_to_nothing(monkeypatch, tmp_path, write_pkg):
    """A builtin / third-party name is not ours — resolve to None so the caller emits no edge."""
    write_pkg(tmp_path, "res_none", "class Base: ...\n")
    monkeypatch.chdir(tmp_path)
    assert Resolver(["res_none"]).resolve("ValueError", FileScope("res_none.mod")) is None


def test_an_import_of_something_we_do_not_own_resolves_to_nothing(monkeypatch, tmp_path, write_pkg):
    write_pkg(tmp_path, "res_ext", "class Base: ...\n")
    monkeypatch.chdir(tmp_path)
    scope = FileScope("res_ext.mod", imports={"DataFrame": "pandas"})
    assert Resolver(["res_ext"]).resolve("DataFrame", scope) is None


# ---- which class DEFINES a method: the MRO walk (bd f1u.2) -------------------------------------------


def _resolver(monkeypatch, tmp_path, write_pkg, name: str, src: str) -> Resolver:
    write_pkg(tmp_path, name, src)
    monkeypatch.chdir(tmp_path)
    return Resolver([name])


_CHAIN = "class Base:\n    def run(self) -> None: ...\n\n\nclass Mid(Base): ...\n\n\nclass Leaf(Mid): ...\n"


def test_a_method_defined_here_resolves_to_this_class(monkeypatch, tmp_path, write_pkg):
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "mro_own", _CHAIN)
    assert resolver.definer("mro_own.mod.Base", "run") == "mro_own.mod.Base"


def test_an_inherited_method_resolves_to_the_base_that_defines_it(monkeypatch, tmp_path, write_pkg):
    """Two links up the chain — the walk does not stop at the immediate base, because the arrow must point
    at where the code actually lives."""
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "mro_inh", _CHAIN)
    assert resolver.definer("mro_inh.mod.Leaf", "run") == "mro_inh.mod.Base"


def test_the_nearest_definition_wins(monkeypatch, tmp_path, write_pkg):
    """An override is a definition, so the walk stops there. Otherwise every override would look like dead
    code while its base collected traffic it never receives."""
    src = "class Base:\n    def run(self) -> None: ...\n\n\nclass Sub(Base):\n    def run(self) -> None: ...\n"
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "mro_over", src)
    assert resolver.definer("mro_over.mod.Sub", "run") == "mro_over.mod.Sub"


def test_a_method_nobody_defines_resolves_to_nothing(monkeypatch, tmp_path, write_pkg):
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "mro_miss", _CHAIN)
    assert resolver.definer("mro_miss.mod.Leaf", "absent") is None


def test_a_diamond_terminates(monkeypatch, tmp_path, write_pkg):
    """The walk is breadth-first over declared bases with a seen-set. Multiple inheritance means a class
    can be reached twice; without that set the walk would revisit and, with a cycle in a malformed tree,
    never return."""
    src = (
        "class Base:\n    def run(self) -> None: ...\n\n\n"
        "class Left(Base): ...\n\n\nclass Right(Base): ...\n\n\nclass D(Left, Right): ...\n"
    )
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "mro_diamond", src)
    assert resolver.definer("mro_diamond.mod.D", "run") == "mro_diamond.mod.Base"


# ---- is a miss OURS or the project boundary? (bd f1u.3) ----------------------------------------------


def test_a_wholly_owned_chain_does_not_leave_the_project(monkeypatch, tmp_path, write_pkg):
    """Every ancestor is ours, so a method we cannot find is a real finding — our walk has a gap, or the
    repo has a missing attribute a type checker would also flag."""
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "open_closed", _CHAIN)
    assert resolver.leaves_project("open_closed.mod.Leaf") is False


def test_a_foreign_base_opens_the_chain(monkeypatch, tmp_path, write_pkg):
    """`Model` is not ours, so a method missing from our index may well be defined out there. We do not
    track outside our own packages by decision, and that drop must stay quiet."""
    src = "from external import Model\n\n\nclass Dep(Model): ...\n"
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "open_ext", src)
    assert resolver.leaves_project("open_ext.mod.Dep") is True


def test_the_opening_is_inherited_down_the_chain(monkeypatch, tmp_path, write_pkg):
    """It is the whole ANCESTRY that decides, not the immediate base: a class two links below a foreign
    base still inherits whatever that base defines."""
    src = "from external import Model\n\n\nclass Mid(Model): ...\n\n\nclass Leaf(Mid): ...\n"
    resolver = _resolver(monkeypatch, tmp_path, write_pkg, "open_deep", src)
    assert resolver.leaves_project("open_deep.mod.Leaf") is True
