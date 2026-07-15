"""Unit tests for devtools/archmap.py — tiered edge-counted mermaid generation from the package tree.

The tiering/counting/render logic is tested against a stub import graph (deterministic, no real import),
plus one real-grimp integration proving the end-to-end build on a written two-package tree."""

import sys
from pathlib import Path

import pytest
from devtools.archmap import Archmap, main


class _FakeGraph:
    """Minimal grimp.ImportGraph stand-in: a module set + a module->imported-modules map."""

    def __init__(self, imports: dict[str, set[str]]) -> None:
        self._imports = imports
        self.modules = set(imports)

    def find_modules_directly_imported_by(self, module: str) -> set[str]:
        return self._imports.get(module, set())


def _tree() -> _FakeGraph:
    # two top packages; `viewer` imports `core` 2x across modules, `core.data` imports `core.model` 1x
    return _FakeGraph(
        {
            "viewer": set(),
            "viewer.ui": {"core.model", "core.data"},
            "core": set(),
            "core.model": set(),
            "core.data": {"core.model"},
            "core.data.loader": {"core.model"},
        }
    )


def test_ancestor_truncates_to_depth():
    assert Archmap._ancestor("core.data.loader", 1) == "core"
    assert Archmap._ancestor("core.data.loader", 2) == "core.data"
    assert Archmap._ancestor("core", 2) is None, "a module shorter than depth has no box at that tier"


def test_tier1_edges_counted_and_cross_package():
    a = Archmap(["viewer", "core"])
    edges = a._edges_under(_tree(), None)
    # viewer.ui imports core.model + core.data -> 2 crossings aggregate to viewer->core [2]
    assert edges == {("viewer", "core"): 2}, edges


def test_intra_box_edges_dropped():
    a = Archmap(["core"])
    edges = a._edges_under(_tree(), "core")
    # within core: data->model (1) and data.loader->model (1) both aggregate to core.data -> core.model [2]
    assert edges == {("core.data", "core.model"): 2}, edges


def test_boxes_under_are_direct_children_only():
    a = Archmap(["core"])
    assert a._boxes_under(_tree(), None) == {"viewer", "core"}
    assert a._boxes_under(_tree(), "core") == {"core.model", "core.data"}
    assert a._boxes_under(_tree(), "core.data") == {"core.data.loader"}


def test_render_has_counted_edge_drill_and_click():
    a = Archmap(["core"])
    doc = a._render(_tree(), "core")  # boxes: core.data (has a child) + core.model (childless leaf)
    assert "-->|2|" in doc, "data->model aggregates both module imports to count 2"
    assert "**Drill:** [data](./data/ARCHITECTURE.md)" in doc, "portable markdown drill link"
    assert 'click core_data "./data/ARCHITECTURE.md"' in doc, "bonus mermaid click where honored"
    # core.model is a childless leaf -> not drillable, no click for it
    assert "click core_model" not in doc


def test_documents_mirror_tree_paths(monkeypatch):
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    docs = a.documents()
    got = {p.as_posix() for p in docs}
    assert "docs/architecture/ARCHITECTURE.md" in got, "root tier doc"
    assert "docs/architecture/core/ARCHITECTURE.md" in got, "a box with children gets its own doc"
    assert "docs/architecture/core/data/ARCHITECTURE.md" in got, "nesting mirrors arbitrarily deep"
    assert "docs/architecture/viewer/ARCHITECTURE.md" in got, "viewer has child viewer.ui -> gets a doc"
    assert "docs/architecture/core/model/ARCHITECTURE.md" not in got, "a childless leaf box gets no doc"


def test_write_creates_mirror_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    written = a.write()
    assert (tmp_path / "docs/architecture/ARCHITECTURE.md").exists()
    assert (tmp_path / "docs/architecture/core/data/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert Path("docs/architecture/ARCHITECTURE.md") in written


def test_real_grimp_build(tmp_path, monkeypatch):
    # end-to-end on a written two-package tree: `app` imports `lib`
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")
    root = Archmap(["app", "lib"]).documents()[Path("docs/architecture/ARCHITECTURE.md")]
    assert "app -->|1| lib" in root, root


def test_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.archmap"])
    with pytest.raises(SystemExit):
        main()
