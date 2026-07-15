"""Unit tests for devtools/_common.py — the shared source-tree walk + pyproject reader + ratchet primitives."""

import ast
import logging

import pytest

from devtools._common import Pyproject, Ratchet, Trees


def test_trees_walk_yields_path_and_parsed_ast(write_pkg, tmp_path):
    pkg = write_pkg(tmp_path, "walk_pos", "x = 1\nclass C: ...\n")
    walked = list(Trees([pkg]).walk())
    # __init__.py + mod.py, each as (Path, parsed Module)
    names = sorted(p.name for p, _ in walked)
    assert names == ["__init__.py", "mod.py"]
    assert all(isinstance(tree, ast.Module) for _, tree in walked)
    mod_tree = next(tree for p, tree in walked if p.name == "mod.py")
    assert any(isinstance(n, ast.ClassDef) for n in ast.walk(mod_tree)), "mod.py parses to a real AST"


def test_trees_files_lists_py_without_parsing(write_pkg, tmp_path):
    pkg = write_pkg(tmp_path, "files_pos", "y = 2\n")
    files = Trees([pkg]).files()
    assert sorted(p.name for p in files) == ["__init__.py", "mod.py"], "every .py under the package, no parse"


def test_pyproject_tool_section_reads_and_defaults(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[tool.structure]\nfile_max = 500\n")
    assert Pyproject.tool_section("structure", str(pp)) == {"file_max": 500}, "the named [tool.<section>] table"
    assert Pyproject.tool_section("absent", str(pp)) == {}, "a missing section is an empty dict"
    assert Pyproject.tool_section("structure", str(tmp_path / "none.toml")) == {}, "a missing file is an empty dict"


def test_ratchet_ceilings_from_pyproject(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[tool.magic_literals]\nmax_strings = 12\nmax_key_sets = 3\n")
    r = Ratchet("magic_literals", str(pp))
    assert r.ceilings(["strings", "key_sets"]) == {"strings": 12, "key_sets": 3}, "the FACT slot drives the ceiling"
    # a fresh base ships 0/0 -> enforced-at-zero (0 is a real ceiling, NOT the advisory None)
    pp.write_text("[tool.magic_literals]\nmax_strings = 0\nmax_key_sets = 0\n")
    assert Ratchet("magic_literals", str(pp)).ceilings(["strings", "key_sets"]) == {"strings": 0, "key_sets": 0}
    # absent key -> None for that axis (advisory); absent section/file -> all None
    pp.write_text("[tool.magic_literals]\nmax_strings = 5\n")
    assert Ratchet("magic_literals", str(pp)).ceilings(["strings", "key_sets"]) == {"strings": 5, "key_sets": None}
    assert Ratchet("magic_literals", str(tmp_path / "none.toml")).ceilings(["strings"]) == {"strings": None}


def test_ratchet_resolve_prefers_cli_override_over_fact():
    ceilings = {"strings": 4, "key_sets": 0}
    # a set CLI override wins; a None override keeps the FACT ceiling
    assert Ratchet.resolve(ceilings, {"strings": 9, "key_sets": None}) == {"strings": 9, "key_sets": 0}
    assert Ratchet.resolve(ceilings, {"strings": None, "key_sets": None}) == ceilings


def test_ratchet_breaches_reports_only_over_axes():
    ceilings = {"strings": 4, "key_sets": 11}
    assert Ratchet.breaches({"strings": 5, "key_sets": 2}, ceilings) == ["strings 5 > 4"], "over the string ceiling"
    assert Ratchet.breaches({"strings": 2, "key_sets": 12}, ceilings) == ["key_sets 12 > 11"], "over the key-set ceiling"
    assert Ratchet.breaches({"strings": 4, "key_sets": 11}, ceilings) == [], "equal to the ceiling is under (not over)"
    # a None ceiling is advisory -> never a breach, however large the count
    assert Ratchet.breaches({"strings": 999}, {"strings": None}) == [], "no ceiling = advisory, never bites"


def test_ratchet_enforce_raises_on_breach_and_is_advisory_safe():
    log = logging.getLogger("test.ratchet")
    # advisory (no ceilings resolved) -> returns silently
    Ratchet("absent_section").enforce({"strings": 999}, {"strings": None}, log)
    # a CLI override alone (no pyproject) can bite
    with pytest.raises(SystemExit) as exc:
        Ratchet("absent_section").enforce({"strings": 5}, {"strings": 4}, log)
    assert exc.value.code == 1, "a breach exits 1"
