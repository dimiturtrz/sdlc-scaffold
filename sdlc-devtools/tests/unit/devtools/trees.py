"""Unit tests for devtools/trees.py — the shared source-tree walk.

Method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a dense
container of parameter combinations rather than one case per behaviour.
"""

import ast

from devtools.trees import Trees


def test_walk(write_pkg, tmp_path):
    """(path, parsed AST) for every module under the roots — and the AST is REAL, not a stub.

    The parse half is the load-bearing assertion: every engine in the repo stands on this walk instead of
    re-globbing and re-parsing, so a walk that yielded paths with empty/wrong trees would silently make
    every downstream gate report a clean tree it never actually read.

    Multiple roots are exercised together because the ordering contract is *sorted within a package*, not
    globally sorted — an engine that assumed a global sort would mis-attribute modules across roots.
    """
    one = write_pkg(tmp_path, "walk_one", "x = 1\nclass C: ...\n")
    two = write_pkg(tmp_path, "walk_two", "y = 2\nclass D: ...\n")

    walked = list(Trees([one]).walk())
    assert sorted(p.name for p, _ in walked) == ["__init__.py", "mod.py"], "every .py, including plumbing"
    assert all(isinstance(tree, ast.Module) for _, tree in walked), "each yield carries a parsed Module"
    mod_tree = next(tree for p, tree in walked if p.name == "mod.py")
    assert [n.name for n in ast.walk(mod_tree) if isinstance(n, ast.ClassDef)] == ["C"], "a real AST"

    both = list(Trees([one, two]).walk())
    assert len(both) == 4, "roots accumulate rather than replace"
    assert [p.name for p, _ in both] == ["__init__.py", "mod.py"] * 2, "sorted WITHIN each package, in order"
    assert list(Trees([]).walk()) == [], "no packages is an empty walk, not an error"


def test_files(write_pkg, tmp_path):
    """The path-only cut: same population as `walk`, without paying to parse.

    Asserted against `walk`'s paths rather than a hand-written list, because the two drifting apart is the
    only failure that matters here — a line-count scan and an AST scan disagreeing about which files exist
    would make two gates report different denominators for the same tree.
    """
    one = write_pkg(tmp_path, "files_one", "y = 2\n")
    two = write_pkg(tmp_path, "files_two", "z = 3\n")

    files = Trees([one]).files()
    assert sorted(p.name for p in files) == ["__init__.py", "mod.py"], "every .py under the package"
    assert files == [p for p, _ in Trees([one]).walk()], "same population and order as the parsing walk"

    assert [p.name for p in Trees([one, two]).files()] == ["__init__.py", "mod.py"] * 2, "sorted per root"
    assert Trees([]).files() == [], "no packages is no files"

    # A non-.py sibling is not source — it must not enter a scan that will later try to parse it.
    (tmp_path / "files_one" / "notes.txt").write_text("not source")
    assert all(p.suffix == ".py" for p in Trees([one]).files())
