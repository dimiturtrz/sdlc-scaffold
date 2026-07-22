"""Unit tests for devtools/archmap.py — the committed graph.json + self-contained viewer (epic m5c).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.

The derivation logic is driven against a stub import graph (deterministic, no real import build); `test_graph`
carries the one real-grimp end-to-end proof; the viewer assembly needs no grimp at all.
"""

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


def _two_package_tree(tmp_path, monkeypatch) -> None:
    """A real importable tree on disk: `app` imports `lib`. The input to every real-grimp case."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    for pkg, src in {"lib": "X = 1\n", "app": "from lib import X\n"}.items():
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text(src, encoding="utf-8")


def test_parent_is_the_existing_containment_prefix():
    ms = {"core", "core.data", "core.data.loader"}
    assert Archmap._parent("core.data.loader", ms) == "core.data", "parent = existing dotted prefix"
    assert Archmap._parent("core", ms) is None, "a top package has no parent"
    assert Archmap._parent("core.data", ms) == "core", "immediate existing prefix wins"
    assert Archmap._parent("gap.child", ms) is None, "a prefix that isn't a node yields None (gap)"


def test_graph(tmp_path, monkeypatch):
    """The one REAL grimp build in this file — everything else stubs the graph, so if `build_graph` were
    called wrongly (per-package instead of combined, externals included) nothing else here would notice.

    Combined is the load-bearing half: `graph.py` builds one graph per package, which drops every
    cross-package edge. `app -> lib` surviving IS that difference, and it is the arrow the viewer exists to
    show. The `graph_data` assertion rides along because a real build feeding the real derivation is the only
    place the stub's shape is checked against grimp's.
    """
    _two_package_tree(tmp_path, monkeypatch)
    engine = Archmap(["app", "lib"])
    graph = engine.graph()
    assert {"app", "lib"} <= set(graph.modules), "both marked packages are in ONE combined graph"
    assert "lib" in graph.find_modules_directly_imported_by("app"), "the cross-package edge survives"
    # edges declare their KIND (bd 433.1); the module tier is the `import` subset
    assert {"source": "app", "target": "lib", "weight": 1, "kind": "import"} in engine.graph_data()["edges"]


def test_graph_data(monkeypatch):
    """The containment tree and the weighted import edges, over a stub graph so the arithmetic is pinned.

    `descendants` is the folded-node badge and `parent` is the compound nesting — both are derived from the
    dotted names rather than from grimp, so they are exactly the part a stub can and should hold to account.
    """
    engine = Archmap(["viewer", "core"])
    monkeypatch.setattr(engine, "graph", _tree)
    data = engine.graph_data()
    by_id = {n["id"]: n for n in data["nodes"]}
    assert by_id["core.data"]["parent"] == "core"
    assert by_id["core"]["parent"] is None
    assert by_id["core.data.loader"]["parent"] == "core.data", "nesting is arbitrary depth"
    assert by_id["core"]["descendants"] == 3, "core.model + core.data + core.data.loader nest under core"
    assert by_id["core.model"]["descendants"] == 0, "a leaf has no descendants"
    assert by_id["viewer.ui"]["label"] == "ui", "label is the last dotted segment"
    assert all(n["level"] == "module" for n in data["nodes"]), "no classes/methods in an empty source tree"

    # A second graph, differing only in import-detail count, isolates the weight from everything above.
    weighted = _FakeGraph(
        {"viewer": set(), "viewer.ui": {"core.model"}, "core": set(), "core.model": set()},
        weights={("viewer.ui", "core.model"): 3},
    )
    monkeypatch.setattr(engine, "graph", lambda: weighted)
    edges = {(e["source"], e["target"]): e["weight"] for e in engine.graph_data()["edges"]}
    assert edges[("viewer.ui", "core.model")] == 3, "edge weight = number of import-detail lines"


def test_write_json(tmp_path, monkeypatch):
    """Determinism is the whole product here: this file is COMMITTED, so a non-deterministic dump would make
    every run a diff and destroy the erosion signal the artifact exists to carry."""
    engine = Archmap(["viewer", "core"])
    monkeypatch.setattr(engine, "graph", _tree)
    path = tmp_path / "nested" / "graph.json"
    first = engine.write_json(path)
    assert first == path, "the written path is returned, so a caller can chain"
    second = engine.write_json(path).read_text(encoding="utf-8")
    assert first.read_text(encoding="utf-8") == second, "two writes are byte-identical (sorted keys + rows)"
    assert set(json.loads(second)) == {"nodes", "edges"}, "the committed json is {nodes, edges}"


def test_write_viewer(tmp_path):
    """Self-containment, asserted as the ABSENCE of every escape hatch — the page is served from GitHub Pages
    with no server and must work offline, so one surviving `<script src=` or unfilled placeholder is a broken
    site rather than a cosmetic slip. Needs no grimp: this only assembles the template + vendored assets."""
    path = Archmap(["core"]).write_viewer(tmp_path / "deep" / "index.html", project="demo-proj")
    html = path.read_text(encoding="utf-8")
    assert "<script src=" not in html, "no external <script src> — every lib is inlined (self-contained)"
    assert "fetch('./graph.json')" in html, "the viewer hydrates the sibling graph.json at load"
    assert "demo-proj" in html, "the project label is injected into the page"
    assert "cytoscape" in html, "the cytoscape lib is inlined"
    for marker in ("__CYTOSCAPE__", "__LAYOUT_BASE__", "__COSE_BASE__", "__FCOSE__", "__VIEWER__"):
        assert f"/*{marker}*/" not in html, f"the {marker} placeholder was filled, not left in the output"
    # No `project` -> the packages name the page, so the shell stays template-identical across repos.
    assert " / ".join(["a", "b"]) in Archmap(["a", "b"]).write_viewer(tmp_path / "d.html").read_text(encoding="utf-8")


def test_diff(tmp_path, monkeypatch):
    """What MOVED against a baseline file — the reviewer's view, and the one archmap surface that is advisory
    rather than gating.

    Takes a FILE and not a git ref deliberately, which is what makes this testable at all; the missing-file
    case is therefore load-bearing rather than defensive, because a first run legitimately has no baseline and
    must report no change instead of erroring.
    """
    monkeypatch.chdir(tmp_path)
    engine = Archmap(["viewer", "core"])
    monkeypatch.setattr(engine, "graph", _tree)
    assert engine.diff(tmp_path / "absent.json") == [], "a missing baseline is a first run, not an error"

    baseline = tmp_path / "base.json"
    engine.write_json(baseline)
    assert engine.diff(baseline) == [], "a baseline equal to the current tree reports no drift"

    # Drop one node and one edge from the baseline: what the tree HAS and the baseline lacks reads as `+`.
    data = json.loads(baseline.read_text(encoding="utf-8"))
    data["nodes"] = [n for n in data["nodes"] if n["id"] != "core.data.loader"]
    data["edges"] = [e for e in data["edges"] if not (e["source"] == "core.data" and e["target"] == "core.model")]
    baseline.write_text(json.dumps(data), encoding="utf-8")
    changes = engine.diff(baseline)
    assert any(c.startswith("+") and "core.data.loader" in c for c in changes), "a node the baseline lacks is added"
    assert any(c.startswith("+") and "core.data -> core.model" in c for c in changes), "and so is the edge"
    assert not any(c.startswith("-") for c in changes), "nothing was removed, so nothing reports as removed"

    # Reversing the roles reverses every sign — the diff is directional, not a symmetric set difference.
    full = tmp_path / "full.json"
    engine.write_json(full)
    monkeypatch.setattr(engine, "graph_data", lambda: data)
    assert all(c.startswith("-") for c in engine.diff(full)), "the baseline having MORE reads as removals"


def test_check(tmp_path, monkeypatch):
    """Staleness of the committed artifact, over its three states. Only graph.json is gated — the viewer
    shell is template-owned and regenerated, so gating it would fail every repo on a template bump."""
    monkeypatch.chdir(tmp_path)
    engine = Archmap(["viewer", "core"])
    monkeypatch.setattr(engine, "graph", _tree)
    assert engine.check()[0].startswith("missing:"), "no committed graph.json -> missing"
    engine.write_json()
    assert engine.check() == [], "a freshly written graph.json is in sync"
    Path("docs/architecture/graph.json").write_text("tampered\n", encoding="utf-8")
    assert engine.check()[0].startswith("stale:"), "a drifted graph.json is stale"


def test_regen(tmp_path, monkeypatch):
    """The pre-push form. It replaced a `bash -c` hook that sequenced a write and a check with `;` — which
    discarded the regen's exit code (green when archmap failed) and could not find `uv` on Windows. Doing
    both in the engine makes the behaviour unit-testable instead of e2e-only, which is this test."""
    monkeypatch.chdir(tmp_path)
    engine = Archmap(["viewer", "core"])
    monkeypatch.setattr(engine, "graph", _tree)
    monkeypatch.setattr(engine, "write_viewer", lambda *_, **__: None)  # the shell needs no grimp and no assets

    assert engine.regen()[0].startswith("missing:"), "nothing committed yet -> drift reported"
    assert Path("docs/architecture/graph.json").exists(), "and it WROTE, which is the half `--check` skips"
    assert engine.regen() == [], "a second run finds it current and reports no drift"

    Path("docs/architecture/graph.json").write_text("tampered\n", encoding="utf-8")
    assert engine.regen()[0].startswith("stale:"), "drift is measured BEFORE the write, or nothing is left to compare"
    assert engine.check() == [], "and the write healed it, so the next check is clean"


def test_main_writes_json_and_viewer(tmp_path, monkeypatch):
    _two_package_tree(tmp_path, monkeypatch)
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


def test_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.archmap"])
    with pytest.raises(SystemExit):
        main()
