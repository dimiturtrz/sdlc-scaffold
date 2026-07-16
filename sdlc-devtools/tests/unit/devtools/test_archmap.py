"""Unit tests for devtools/archmap.py — tiered edge-counted mermaid generation from the package tree.

The tiering/counting/render logic is tested against a stub import graph (deterministic, no real import),
plus one real-grimp integration proving the end-to-end build on a written two-package tree."""

import json
import sys
from pathlib import Path

import pytest
from devtools.archmap import Archmap, main


class _FakeGraph:
    """Minimal grimp.ImportGraph stand-in: a module set + a module->imported-modules map (+ per-pair
    import-detail weights, so graph_data's edge weighting is testable without a real grimp build)."""

    def __init__(self, imports: dict[str, set[str]], weights: dict[tuple[str, str], int] | None = None) -> None:
        self._imports = imports
        self.modules = set(imports)
        self._weights = weights or {}

    def find_modules_directly_imported_by(self, module: str) -> set[str]:
        return self._imports.get(module, set())

    def get_import_details(self, importer: str, imported: str) -> list[dict]:
        return [{}] * self._weights.get((importer, imported), 1)


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


def test_check_in_sync_after_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    a.write()
    assert a.check() == [], "a freshly written tree is in sync"


def test_check_flags_missing_stale_orphan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    a.write()
    # stale: mutate a committed doc; missing: delete one; orphan: add an unexpected doc
    Path("docs/architecture/ARCHITECTURE.md").write_text("tampered\n", encoding="utf-8")
    Path("docs/architecture/core/data/ARCHITECTURE.md").unlink()
    Path("docs/architecture/ghost").mkdir()
    Path("docs/architecture/ghost/ARCHITECTURE.md").write_text("orphan\n", encoding="utf-8")
    drift = a.check()
    assert any(d.startswith("stale:") and "architecture/ARCHITECTURE.md" in d for d in drift), drift
    assert any(d.startswith("missing:") and "core/data" in d for d in drift), drift
    assert any(d.startswith("orphan:") and "ghost" in d for d in drift), drift


def test_main_check_exits_nonzero_on_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "solo").mkdir()
    (tmp_path / "solo" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["devtools.archmap", "solo", "--check"])
    with pytest.raises(SystemExit) as exc:  # nothing written yet -> missing -> exit 1
        main()
    assert exc.value.code == 1, "an out-of-sync tree fails the --check gate"


def test_real_grimp_build(tmp_path, monkeypatch):
    # end-to-end on a written two-package tree: `app` imports `lib`
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")
    root = Archmap(["app", "lib"]).documents()[Path("docs/architecture/ARCHITECTURE.md")]
    assert "app -->|1| lib" in root, root


def test_graph_data_nodes_carry_parent_and_descendants(monkeypatch):
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    by_id = {n["id"]: n for n in a.graph_data()["nodes"]}
    assert by_id["core.data"]["parent"] == "core", "containment parent = the existing dotted-prefix node"
    assert by_id["core"]["parent"] is None, "a top package has no parent"
    assert by_id["core.data.loader"]["parent"] == "core.data", "nesting is arbitrary depth"
    assert by_id["core"]["descendants"] == 3, "core.model + core.data + core.data.loader nest under core"
    assert by_id["core.model"]["descendants"] == 0, "a leaf has no descendants"
    assert by_id["viewer.ui"]["label"] == "ui", "label is the last dotted segment"


def test_graph_data_edges_weighted_by_import_count(monkeypatch):
    # viewer.ui imports core.model with 3 import statements -> the edge weight is 3
    fake = _FakeGraph(
        {"viewer": set(), "viewer.ui": {"core.model"}, "core": set(), "core.model": set()},
        weights={("viewer.ui", "core.model"): 3},
    )
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", lambda: fake)
    edges = {(e["source"], e["target"]): e["weight"] for e in a.graph_data()["edges"]}
    assert edges[("viewer.ui", "core.model")] == 3, "edge weight = number of import-detail lines"


def test_write_json_is_deterministic(tmp_path, monkeypatch):
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    p = tmp_path / "graph.json"
    first = a.write_json(p).read_text(encoding="utf-8")
    second = a.write_json(p).read_text(encoding="utf-8")
    assert first == second, "two writes are byte-identical (sorted keys + sorted rows) — clean diffs"
    data = json.loads(first)
    assert set(data) == {"nodes", "edges"}, "the committed json is {nodes, edges}"


def test_write_viewer_is_self_contained(tmp_path):
    # write_viewer only assembles the template + vendored assets (no grimp) — the interactive site shell
    p = Archmap(["core"]).write_viewer(tmp_path / "index.html", project="demo-proj")
    html = p.read_text(encoding="utf-8")
    assert "<script src=" not in html, "no external <script src> — every lib is inlined (self-contained)"
    assert "fetch('./graph.json')" in html, "the viewer hydrates the sibling graph.json at load"
    assert "demo-proj" in html, "the project label is injected into the page"
    assert "cytoscape" in html, "the cytoscape lib is inlined"
    for marker in ("__CYTOSCAPE__", "__FCOSE__", "__VIEWER__"):
        assert f"/*{marker}*/" not in html, f"the {marker} placeholder was filled, not left in the output"


def test_main_json_writes_graph(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["devtools.archmap", "app", "lib", "--json"])
    main()
    written = (tmp_path / "docs/architecture/graph.json").read_text(encoding="utf-8")
    assert '"source": "app"' in written and '"target": "lib"' in written, written


def test_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.archmap"])
    with pytest.raises(SystemExit):
        main()
