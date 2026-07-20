"""Unit tests for devtools/archmap.py — the committed graph.json + self-contained viewer (epic m5c).

The derivation logic is tested against a stub import graph (deterministic, no real import); one real-grimp
integration proves the end-to-end build; the viewer assembly is tested directly (no grimp needed)."""

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
    # two top packages; viewer.ui imports into core; core.data + core.data.loader import core.model
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


def test_parent_is_the_existing_containment_prefix():
    ms = {"core", "core.data", "core.data.loader"}
    assert Archmap._parent("core.data.loader", ms) == "core.data", "parent = existing dotted prefix"
    assert Archmap._parent("core", ms) is None, "a top package has no parent"
    assert Archmap._parent("core.data", ms) == "core", "immediate existing prefix wins"
    assert Archmap._parent("gap.child", ms) is None, "a prefix that isn't a node yields None (gap)"


def test_graph_data_nodes_carry_parent_and_descendants(monkeypatch):
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    by_id = {n["id"]: n for n in a.graph_data()["nodes"]}
    assert by_id["core.data"]["parent"] == "core"
    assert by_id["core"]["parent"] is None
    assert by_id["core.data.loader"]["parent"] == "core.data", "nesting is arbitrary depth"
    assert by_id["core"]["descendants"] == 3, "core.model + core.data + core.data.loader nest under core"
    assert by_id["core.model"]["descendants"] == 0, "a leaf has no descendants"
    assert by_id["viewer.ui"]["label"] == "ui", "label is the last dotted segment"


def test_graph_data_edges_weighted_by_import_count(monkeypatch):
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
    assert set(json.loads(first)) == {"nodes", "edges"}, "the committed json is {nodes, edges}"


def test_check_flags_missing_and_stale(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    assert a.check()[0].startswith("missing:"), "no committed graph.json -> missing"
    a.write_json()
    assert a.check() == [], "a freshly written graph.json is in sync"
    Path("docs/architecture/graph.json").write_text("tampered\n", encoding="utf-8")
    assert a.check()[0].startswith("stale:"), "a drifted graph.json is stale"


def test_regen_writes_and_reports_the_drift_that_existed_before_the_write(tmp_path, monkeypatch):
    """The pre-push form. It replaced a `bash -c` hook that sequenced a write and a check with `;` — which
    discarded the regen's exit code (green when archmap failed) and could not find `uv` on Windows. Doing
    both in the engine makes the behaviour unit-testable instead of e2e-only, which is this test."""
    monkeypatch.chdir(tmp_path)
    a = Archmap(["viewer", "core"])
    monkeypatch.setattr(a, "graph", _tree)
    monkeypatch.setattr(a, "write_viewer", lambda *_, **__: None)  # the shell needs no grimp and no assets

    assert a.regen()[0].startswith("missing:"), "nothing committed yet -> drift reported"
    assert Path("docs/architecture/graph.json").exists(), "and it WROTE, which is the half `--check` skips"
    assert a.regen() == [], "a second run finds it current and reports no drift"

    Path("docs/architecture/graph.json").write_text("tampered\n", encoding="utf-8")
    assert a.regen()[0].startswith("stale:"), "drift is measured BEFORE the write, or there is nothing left to compare"
    assert a.check() == [], "and the write healed it, so the next check is clean"


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


def test_main_writes_json_and_viewer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["devtools.archmap", "app", "lib"])
    main()
    written = (tmp_path / "docs/architecture/graph.json").read_text(encoding="utf-8")
    assert '"source": "app"' in written and '"target": "lib"' in written, written
    assert (tmp_path / "docs/architecture/index.html").exists(), "the viewer is emitted alongside"


def test_main_check_exits_nonzero_on_drift(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "solo").mkdir()
    (tmp_path / "solo" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["devtools.archmap", "solo", "--check"])
    with pytest.raises(SystemExit) as exc:  # nothing written yet -> missing -> exit 1
        main()
    assert exc.value.code == 1, "an out-of-sync graph.json fails the --check gate"


def test_real_grimp_build(tmp_path, monkeypatch):
    # end-to-end on a written two-package tree: `app` imports `lib`
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")
    data = Archmap(["app", "lib"]).graph_data()
    # edges now declare their KIND (bd 433.1); the module tier is the `import` subset
    assert {"source": "app", "target": "lib", "weight": 1, "kind": "import"} in data["edges"], data


def test_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.archmap"])
    with pytest.raises(SystemExit):
        main()
