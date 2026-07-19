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
