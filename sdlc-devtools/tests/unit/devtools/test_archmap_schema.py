"""Unit tests for the graph.json SCHEMA (bd 433.1) — edge kinds + node roles, kept deterministic.

Separate from test_archmap.py, which covers the emitter's file/viewer behaviour; this covers the CONTRACT
the viewer and the committed diff-truth both depend on.
"""

import json

from devtools.archmap import Archmap

_FILES = {
    "errors.py": "class StoreError(Exception): ...\n",
    "store.py": (
        "from schema_pkg.errors import StoreError\n\n\n"
        "class Store:\n"
        "    def put(self, k: str) -> None: ...\n\n\n"
        "class CapacityError(StoreError): ...\n"
    ),
    "service.py": (
        "from schema_pkg.store import Store\n\n\n"
        "class Service:\n"
        "    def __init__(self):\n"
        "        self._store = Store()\n\n"
        "    def go(self) -> None:\n"
        "        self._store.put('k')\n"
    ),
}


def _data(monkeypatch, tmp_path) -> dict:
    package = tmp_path / "schema_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("")
    for name, src in _FILES.items():
        (package / name).write_text(src)
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    return Archmap(["schema_pkg"]).graph_data()


def test_every_node_declares_its_level(monkeypatch, tmp_path):
    """A view asks for a tier by NAME rather than guessing from shape."""
    nodes = _data(monkeypatch, tmp_path)["nodes"]
    assert {n["level"] for n in nodes} == {"module", "class", "method"}
    assert all("role" in n for n in nodes), "role is present on every node (None for a module)"


def test_class_nodes_carry_their_role_and_hang_off_their_module(monkeypatch, tmp_path):
    classes = {n["id"]: n for n in _data(monkeypatch, tmp_path)["nodes"] if n["level"] == "class"}
    assert classes["schema_pkg.store.Store"]["role"] == "primary"
    assert classes["schema_pkg.store.CapacityError"]["role"] == "satellite", "an error is a companion"
    assert classes["schema_pkg.store.Store"]["parent"] == "schema_pkg.store", "containment: class under module"


def test_every_edge_declares_its_kind(monkeypatch, tmp_path):
    kinds = {e["kind"] for e in _data(monkeypatch, tmp_path)["edges"]}
    assert "import" in kinds, "the module tier is still emitted"
    assert {"holds", "calls", "construct", "inherits"} & kinds, "the finer arrows ride alongside it"


def test_the_import_tier_is_unchanged_by_the_new_tier(monkeypatch, tmp_path):
    """The module/import view a consumer already renders must be exactly what it was."""
    data = _data(monkeypatch, tmp_path)
    imports = [e for e in data["edges"] if e["kind"] == "import"]
    assert all(e["weight"] >= 1 for e in imports), "import edges keep their statement count"
    modules = [n for n in data["nodes"] if n["level"] == "module"]
    assert all({"id", "label", "parent", "descendants"} <= set(n) for n in modules)


def test_the_emission_is_deterministic(monkeypatch, tmp_path):
    """graph.json is committed diff-truth — an unstable order would make every run a spurious diff."""
    data = _data(monkeypatch, tmp_path)
    again = Archmap(["schema_pkg"]).graph_data()
    assert json.dumps(data, sort_keys=True) == json.dumps(again, sort_keys=True)
    classes = [n["id"] for n in data["nodes"] if n["level"] == "class"]
    assert classes == sorted(classes), "class nodes sorted"
    typed = [(e["source"], e["target"], e["kind"]) for e in data["edges"] if e["kind"] != "import"]
    assert typed == sorted(typed), "typed edges sorted"


# ---- the viewer contract that consumes the schema (bd 433.2 / 433.3) ---------------------------------


def _viewer(tmp_path) -> str:
    return Archmap(["core"]).write_viewer(tmp_path / "index.html", project="demo").read_text(encoding="utf-8")


def test_the_viewer_exposes_a_toggle_for_every_edge_kind(tmp_path):
    """Every kind the emitter can produce must be reachable in the UI, or that tier of the graph is data
    nobody can see."""
    html = _viewer(tmp_path)
    for kind in ("import", "inherits", "holds", "references", "calls", "construct"):
        assert f'id="kind-{kind}"' in html, f"no toggle for {kind}"
    assert 'id="tier-class"' in html, "the class tier needs a toggle"
    assert 'id="hide-satellites"' in html, "roles are filterable, not just decorative"


def test_line_style_carries_the_split_not_colour_alone(tmp_path):
    """SOLID = what a class knows, DASHED = what it does. Encoding that in style (not hue) keeps the graph
    readable in greyscale and for colour-blind viewers."""
    html = _viewer(tmp_path)
    assert "'line-style': 'dashed'" in html or '"line-style": "dashed"' in html or "dashed" in html
    for kind in ("inherits", "holds", "references", "calls", "construct"):
        assert f'edge[kind="{kind}"]' in html, f"{kind} has no distinct style rule"


def test_the_default_view_is_the_module_import_tier(tmp_path):
    """Adding a class tier must not change what a consumer already renders — only `import` starts checked."""
    html = _viewer(tmp_path)
    assert 'id="kind-import" checked' in html, "imports on by default"
    for kind in ("inherits", "holds", "references", "calls", "construct"):
        assert f'id="kind-{kind}" checked' not in html, f"{kind} must be OFF by default"
    assert 'id="tier-class" checked' not in html, "the class tier is opt-in"


def test_the_viewer_stays_self_contained(tmp_path):
    """It is served as a static GitHub Pages site — an external <script src> would break offline/CSP."""
    assert "script src=" not in _viewer(tmp_path)


# ---- the architecture CHANGELOG (bd 433.5) ----------------------------------------------------------


def _baseline(tmp_path, data: dict):
    path = tmp_path / "base.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_missing_baseline_is_not_an_error(monkeypatch, tmp_path):
    """A first run has nothing to compare against — report no change rather than fail."""
    _data(monkeypatch, tmp_path)
    assert Archmap(["schema_pkg"]).diff(tmp_path / "absent.json") == []


def test_no_change_reports_nothing(monkeypatch, tmp_path):
    data = _data(monkeypatch, tmp_path)
    assert Archmap(["schema_pkg"]).diff(_baseline(tmp_path, data)) == []


def test_an_added_edge_is_reported_with_its_kind(monkeypatch, tmp_path):
    """The point of the whole thing: a reviewer sees WHAT KIND of dependency appeared, not just that a
    JSON file moved."""
    data = _data(monkeypatch, tmp_path)
    thinned = {"nodes": data["nodes"], "edges": [e for e in data["edges"] if e["kind"] != "calls"]}
    changes = Archmap(["schema_pkg"]).diff(_baseline(tmp_path, thinned))
    assert changes and all(c.startswith("+") for c in changes)
    assert any("calls" in c for c in changes), f"the added arrow names its kind: {changes}"


def test_a_removed_edge_is_reported(monkeypatch, tmp_path):
    data = _data(monkeypatch, tmp_path)
    extra = dict(data)
    extra["edges"] = [*data["edges"], {"source": "schema_pkg.a.A", "target": "schema_pkg.b.B", "kind": "holds"}]
    changes = Archmap(["schema_pkg"]).diff(_baseline(tmp_path, extra))
    assert any(c.startswith("-") and "holds" in c for c in changes), changes


def test_an_added_class_is_reported_with_its_role(monkeypatch, tmp_path):
    data = _data(monkeypatch, tmp_path)
    thinned = {"nodes": [n for n in data["nodes"] if n["level"] != "class"], "edges": data["edges"]}
    changes = Archmap(["schema_pkg"]).diff(_baseline(tmp_path, thinned))
    assert any("primary" in c for c in changes), f"a new class shows its role: {changes}"


# ---- the METHOD tier (bd 433.4) ----------------------------------------------------------------------


def test_methods_are_emitted_under_their_class(monkeypatch, tmp_path):
    methods = {n["id"]: n for n in _data(monkeypatch, tmp_path)["nodes"] if n["level"] == "method"}
    assert "schema_pkg.store.Store.put" in methods, "a class's surface is readable, not guessed from its name"
    assert methods["schema_pkg.store.Store.put"]["parent"] == "schema_pkg.store.Store"
    assert methods["schema_pkg.store.Store.put"]["label"] == "put", "the label is the bare method name"


def test_no_method_level_edges_are_invented(monkeypatch, tmp_path):
    """The call resolver aggregates per CLASS, so a method->method arrow would be precision the graph does
    not have. Method nodes carry containment only; the edges arrive with bd 4bl.7."""
    data = _data(monkeypatch, tmp_path)
    methods = {n["id"] for n in data["nodes"] if n["level"] == "method"}
    touching = [e for e in data["edges"] if e["source"] in methods or e["target"] in methods]
    assert touching == [], f"no edge may terminate on a method yet: {touching}"


def test_the_method_tier_is_opt_in_in_the_viewer(tmp_path):
    """165 methods in a 23-module tree is a wall — it must be off until asked for."""
    html = _viewer(tmp_path)
    assert 'id="tier-method"' in html, "the tier needs a toggle"
    assert 'id="tier-method" checked' not in html, "and it must be OFF by default"
