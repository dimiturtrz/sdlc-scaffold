"""Unit tests for the graph.json SCHEMA (bd 433.1) — edge kinds + node roles, kept deterministic.

Separate from test_archmap.py, which covers the emitter's file/viewer behaviour; this covers the CONTRACT
the viewer and the committed diff-truth both depend on.
"""

import json
import re

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
    for stop in ("module", "class", "public", "all"):
        assert f'data-v="{stop}"' in html, f"the depth control needs a {stop} stop"
    assert 'id="hide-satellites"' in html, "roles are filterable, not just decorative"


def _style_table(html: str) -> dict[str, tuple[str, str]]:
    """The kind -> (line, band) table the viewer derives its edge rules, swatches and bands from, read back
    out of the shipped JS so the tests check what actually ships rather than a restatement of it."""
    body = re.findall(r"const STYLE = \{(.*?)\n  \};", html, re.S)[0]
    rows = re.findall(r"(\w+):\s*\{.*?line: '(\w+)'.*?band: '(\w+)'", body)
    return {kind: (line, band) for kind, line, band in rows}


def test_every_edge_kind_declares_an_arrow_band(tmp_path):
    """The bands ARE the arrow control — a kind in no band is reachable only by hand-checking a box in the
    per-kind panel, which is how `references` stayed invisible while looking supported."""
    style = _style_table(_viewer(tmp_path))
    assert set(style) == {"import", "inherits", "holds", "references", "calls", "construct"}


def test_every_declared_band_has_a_button(tmp_path):
    """Membership is structural (one `band` per kind, so a kind cannot be in two), but the SEGMENTED CONTROL
    is hand-written markup — a kind given a brand-new band would silently become unreachable."""
    html = _viewer(tmp_path)
    offered = set(re.findall(r'<button data-v="(\w+)">', re.findall(r'id="arrows">(.*?)</span>', html, re.S)[0]))
    bands = {band for _, band in _style_table(html).values()}
    assert bands == offered, f"bands {bands} vs buttons {offered} — one side is unreachable"


def test_line_style_carries_the_split_not_colour_alone(tmp_path):
    """SOLID = what a class knows, DASHED = what it does. Encoding that in style (not hue) keeps the graph
    readable in greyscale and for colour-blind viewers — so the split must hold for EVERY kind, which is
    checkable now that one table drives both the edge rules and the legend swatches."""
    for kind, (line, band) in _style_table(_viewer(tmp_path)).items():
        knows = band in ("imports", "structure")
        assert (line != "dashed") == knows, f"{kind} is {band} but drawn {line} — the split would misread"


def test_the_legend_is_derived_from_the_same_table_as_the_graph(tmp_path):
    """A key that restates its colours by hand drifts from the picture the first time one is retuned. The
    swatches are generated from STYLE, so no hex or dash may appear in the markup."""
    html = _viewer(tmp_path)
    markup = re.sub(r"<!--.*?-->", "", html[html.index("<body>") : html.index("<script>")], flags=re.S)
    for restated in ("#", "solid", "dashed", "dotted"):
        assert restated not in markup, f"the markup restates {restated!r}, which STYLE already owns"


def test_the_default_view_is_the_module_import_tier(tmp_path):
    """Adding a class tier must not change what a consumer already renders. The default now lives in the
    control state rather than in `checked` attributes, because the two axes are ordinal segmented controls
    — but the rendered result it pins down is the same one."""
    html = _viewer(tmp_path)
    assert "let depth = 'module', band = 'imports';" in html, "the opening view is modules joined by imports"
    banded = {k for k, (_, band) in _style_table(html).items() if band == "imports"}
    assert banded == {"import"}, f"the opening band must be the import arrow alone, got {banded}"


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


def test_a_call_terminates_on_the_method_it_invokes(monkeypatch, tmp_path):
    """SUPERSEDES "no method-level edges are invented" (bd f1u.2). The resolver no longer aggregates per
    class: it walks the project MRO to whichever class DEFINES the called method, so the arrow lands on
    real code rather than inventing precision. `Service.go` calls `self._store.put(...)`, and `put` is
    defined on Store — that is the edge."""
    data = _data(monkeypatch, tmp_path)
    calls = {(e["source"], e["target"]) for e in data["edges"] if e["kind"] == "calls"}
    assert ("schema_pkg.service.Service.go", "schema_pkg.store.Store.put") in calls, calls


def test_a_construction_terminates_on_the_class(monkeypatch, tmp_path):
    """The partition: behavioural coupling lands INSIDE the box, wiring lands ON it. Constructing is
    `__init__`, i.e. the class as a whole, so a construct arrow keeps a class endpoint."""
    data = _data(monkeypatch, tmp_path)
    builds = {(e["source"], e["target"]) for e in data["edges"] if e["kind"] == "construct"}
    assert ("schema_pkg.service.Service.__init__", "schema_pkg.store.Store") in builds, builds


def test_no_edge_dangles_off_a_node_that_does_not_exist(monkeypatch, tmp_path):
    """The invariant the viewer's roll-up rests on. It climbs an arrow's endpoint to the nearest ancestor
    that is on screen — so an endpoint naming a node the file never emits would climb past every tier and
    the arrow would silently vanish, or worse, attach to a package. Cheap to state, and it is what makes
    the method tier trustworthy now that arrows terminate there."""
    data = _data(monkeypatch, tmp_path)
    known = {n["id"] for n in data["nodes"]}
    dangling = [
        (e["source"], e["target"]) for e in data["edges"] if e["source"] not in known or e["target"] not in known
    ]
    assert dangling == [], f"every endpoint must be a node: {dangling}"


def test_a_behavioural_arrow_is_emitted_once_at_its_finest_depth(monkeypatch, tmp_path):
    """The roll-up invariant, one tier down. The viewer climbs an arrow to whichever ancestor is on screen,
    so emitting a class-level COPY of a method-level call would draw the same fact twice at method depth —
    and the count on the legend would silently double."""
    data = _data(monkeypatch, tmp_path)
    classes = {n["id"] for n in data["nodes"] if n["level"] == "class"}
    coarse = [e for e in data["edges"] if e["kind"] == "calls" and e["source"] in classes]
    assert coarse == [], f"a call is emitted at method depth only: {coarse}"


def test_the_method_tier_is_opt_in_in_the_viewer(tmp_path):
    """165 methods in a 23-module tree is a wall — it must be off until asked for. Depth being ORDINAL is
    what guarantees that: the method stops are last, so they are unreachable until the user walks to them.

    `public` and `all` are two stops on ONE tier, not a tier plus a checkbox: a class's public surface is a
    strict subset of its methods, so walking further only ever adds nodes and the scale stays ordinal.
    """
    html = _viewer(tmp_path)
    assert "const DEPTHS = ['module', 'class', 'public', 'all'];" in html, "depth is a 4-stop ordinal scale"
    assert "let depth = 'module'" in html, "and it opens at the shallowest stop"


def test_folding_survives_a_filter_change(tmp_path):
    """Fold state is a reading position built by hand; dropping it on every toggle makes the depth and arrow
    axes unusable together. Only `reset view` may clear it."""
    html = _viewer(tmp_path)
    assert "function apply() { rebuild(); applyDefaultFold(); refresh(); }" in html
    assert "if (seen.has(n.id)) continue;" in html, "a node already seen keeps the fold the user gave it"
