"""Architecture autoviz: the marked package tree -> a committed graph.json + a self-contained interactive
viewer (docs/architecture/), the interactive successor to the old static mermaid mirror-tree (epic m5c).

grimp builds the honest combined import graph (folder≡package≡module, so nodes come free from the
`packages` marking — no separate architecture language). We emit:

  * graph.json — nodes (id, label, containment `parent`, `descendants` count) + weighted import edges. This
    committed, deterministic file IS the diffable erosion signal: architecture drift shows as a JSON diff
    in review, and it is the data the viewer hydrates.
  * index.html — a static, self-contained cytoscape viewer (vendored libs inlined, no CDN/server/Java) that
    fetches graph.json and lets you fold/expand packages to any depth, read the summed import count on each
    aggregated arrow, and focus a module's neighbourhood. Served as a per-repo GitHub Pages architecture site.

DOC-GEN / ADVISORY. This visualizes structure; it does not enforce it — directional enforcement stays with
import-linter (the layer gate). `--check` fails only if the committed graph.json is stale.

    python -m devtools.archmap core cardioseg          # (re)write docs/architecture/{graph.json,index.html}
    python -m devtools.archmap core cardioseg --check  # fail if the committed graph.json is out of date
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
from pathlib import Path
from typing import TypedDict

import grimp

from devtools._common import ENCODING
from devtools.arrows import ClassArrows
from devtools.calls import CallArrows
from devtools.classes import ClassIndex
from devtools.resolve import Resolver

log = logging.getLogger("devtools.archmap")


# graph.json's SCHEMA, typed. It is a committed artifact the viewer hydrates, so the shape is a contract,
# not an implementation detail — and TypedDict states it per FIELD, which `dict[str, <union>]` cannot: it
# would make every field the same widened union and force the reader to re-narrow `id` back to `str`.
class NodeRow(TypedDict):
    """A containment-tree node: module, class or method."""

    id: str
    label: str
    parent: str | None
    descendants: int
    level: str
    role: str | None


class EdgeRow(TypedDict):
    """One arrow, tagged with the kind an import decomposes into."""

    source: str
    target: str
    weight: int
    kind: str


class GraphData(TypedDict):
    """The whole committed artifact."""

    nodes: list[NodeRow]
    edges: list[EdgeRow]


_ROOT = Path("docs/architecture")
_JSON = _ROOT / "graph.json"
_INDEX = _ROOT / "index.html"
_ARCHVIZ = Path(__file__).parent / "archviz"  # vendored cytoscape/fcose libs + our engine + the page shell
# viewer <script> placeholder -> vendored asset filename (inlined so the page is static / offline / no CDN).
_ASSETS = {
    "__CYTOSCAPE__": "cytoscape.min.js",
    "__LAYOUT_BASE__": "layout-base.js",
    "__COSE_BASE__": "cose-base.js",
    "__FCOSE__": "cytoscape-fcose.js",
    "__VIEWER__": "viewer.js",
}


class Archmap:
    """Emitter of the committed graph.json + the self-contained interactive viewer over the package tree."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        # ONE Resolver for the whole emission (bd 5cg): the class arrows, the call arrows and the method
        # tier all read the same parsed trees, and each used to walk the source itself.
        self.resolver = Resolver(packages)

    def graph(self) -> grimp.ImportGraph:
        """The combined import graph over ALL marked packages — combined (not per-package like graph.py) so
        cross-package edges (`cardioseg -> core`) survive as arrows."""
        return grimp.build_graph(*self.packages, include_external_packages=False)

    @staticmethod
    def _parent(module: str, module_set: set[str]) -> str | None:
        """The containment parent that EXISTS as a node (None for a top package or a gap in the tree)."""
        p = module.rsplit(".", 1)[0] if "." in module else None
        return p if p in module_set else None

    def _class_nodes(self) -> list[NodeRow]:
        """The CLASS tier of the containment tree (bd 433.1): every class as a node under its module,
        carrying its ROLE — `primary` (the file's subject) or `satellite` (its error / config / local
        specialisation). The role is what lets a view hide companions and show the real skeleton."""
        return sorted(
            (
                {
                    "id": f"{Resolver.module_of(path)}.{name}",
                    "label": name,
                    "parent": Resolver.module_of(path),
                    "descendants": 0,
                    "level": "class",
                    "role": role,
                }
                for path, records in ClassIndex(self.packages, self.resolver.trees).by_file().items()
                for name, role in records
            ),
            key=lambda n: n["id"],
        )

    def _method_nodes(self) -> list[NodeRow]:
        """The METHOD tier (bd 433.4) — the deepest fold level, so a class can be opened to read its actual
        surface instead of guessing it from the class name.

        The tier is where the BEHAVIOURAL arrows now terminate (bd f1u.2): a `calls` edge lands on the
        method it invokes, so opening a class shows what its methods actually do rather than a wall of
        labels with no connectivity.
        """
        return sorted(
            (
                {
                    "id": f"{Resolver.module_of(path)}.{cls.name}.{fn.name}",
                    "label": fn.name,
                    "parent": f"{Resolver.module_of(path)}.{cls.name}",
                    "descendants": 0,
                    "level": "method",
                    "role": None,
                }
                for path, tree in self.resolver.trees
                for cls in Resolver.classes_in(tree)
                for fn in cls.body
                if isinstance(fn, ast.FunctionDef)
            ),
            key=lambda n: n["id"],
        )

    def _typed_edges(self) -> list[EdgeRow]:
        """The finer arrows an import edge decomposes into, each tagged with its KIND. Deduped and sorted so
        the committed diff stays minimal; `weight` is 1 because a kind between two nodes is a fact, not a
        count (the import edge keeps the statement count).

        Structural arrows join CLASSES; behavioural arrows are emitted at their finest endpoints — method
        to method for a call, method to class for a construction. They are emitted ONCE, at that depth,
        rather than also as a class-level copy: the viewer rolls an arrow up to whichever ancestor is on
        screen, so a duplicate coarse edge would draw the same fact twice at method depth. That roll-up is
        the same invariant the import tier already rests on, one tier further down.
        """
        structural = [(s, d, kind) for s, d, kind in ClassArrows(self.packages, self.resolver).edges()]
        behavioural = [(e.source_id, e.target_id, e.kind) for e in CallArrows(self.packages, self.resolver).edges()]
        return [
            {"source": s, "target": d, "weight": 1, "kind": kind}
            for s, d, kind in sorted(set(structural + behavioural))
        ]

    def graph_data(self) -> GraphData:
        """The full graph as committed-diffable JSON — the diff-truth the viewer hydrates.

        THREE tiers of one containment tree. Every MODULE is a node carrying its `parent` (compound nesting) +
        `descendants` count (the folded-node badge), and every module→module import is an edge weighted by
        import-statement count. Beneath that, every CLASS is a node with its `role`, joined by the TYPED
        arrows (`inherits` / `holds` / `references` / `calls` / `construct`) that the import edge is merely
        the coarse roll-up of.

        Beneath the classes sits the METHOD tier — nodes only, the deepest fold level.

        Every node carries `level` and every edge a `kind`, so a view can ask for a subset rather than
        guessing from shape. Deterministic throughout (sorted nodes, edges and keys) so the committed diff
        stays minimal and meaningful.
        """
        graph = self.graph()
        modules = sorted(graph.modules)
        module_set = set(modules)
        nodes = [
            {
                "id": m,
                "label": m.split(".")[-1],
                "parent": self._parent(m, module_set),
                "descendants": sum(1 for n in modules if n.startswith(m + ".")),
                "level": "module",
                "role": None,
            }
            for m in modules
        ]
        edges = [
            {
                "source": m,
                "target": imp,
                "weight": len(graph.get_import_details(importer=m, imported=imp)),
                "kind": "import",
            }
            for m in modules
            for imp in sorted(graph.find_modules_directly_imported_by(m))
            if imp in module_set
        ]
        return {"nodes": nodes + self._class_nodes() + self._method_nodes(), "edges": edges + self._typed_edges()}

    def _json_text(self) -> str:
        return json.dumps(self.graph_data(), indent=2, sort_keys=True) + "\n"

    def write_json(self, path: Path = _JSON) -> Path:
        """Write the committed graph.json (deterministic) — the diffable erosion signal + viewer input."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._json_text(), encoding=ENCODING)
        return path

    def write_viewer(self, path: Path = _INDEX, project: str | None = None) -> Path:
        """Assemble the self-contained interactive viewer (index.html) from the vendored cytoscape/fcose libs
        + our engine, all inlined so the page is static (GitHub Pages / offline / no CDN). It fetches the
        sibling graph.json at load, so graph.json stays the diffable artifact and this shell is template-
        identical across repos (only the project label differs)."""
        html = (_ARCHVIZ / "index.html.tmpl").read_text(encoding=ENCODING)
        html = html.replace("{project}", project or " / ".join(self.packages))
        for marker, filename in _ASSETS.items():
            html = html.replace(f"/*{marker}*/", (_ARCHVIZ / filename).read_text(encoding=ENCODING))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding=ENCODING)
        return path

    @staticmethod
    def _signature(data: GraphData) -> tuple[set[tuple[str, str]], set[tuple[str, str, str]]]:
        """(nodes, edges) as comparable tuples — the shape a diff is taken over."""
        nodes = {(n["id"], n.get("role") or n.get("level", "module")) for n in data.get("nodes", [])}
        edges = {(e["source"], e["target"], e.get("kind", "import")) for e in data.get("edges", [])}
        return nodes, edges

    def diff(self, baseline: Path) -> list[str]:
        """How this tree's architecture CHANGED against a baseline graph.json — added/removed nodes and
        typed edges, newest state first.

        Takes a FILE, not a git ref: the engine stays git-free and unit-testable, and CI does the
        `git show <base>:docs/architecture/graph.json > base.json` itself. A missing baseline is not an
        error — a first run has nothing to compare against and simply reports no change.

        Advisory by construction. The gates say what is FORBIDDEN; this says what MOVED, which is the part
        a reviewer (or someone deciding whether to trust a change they did not write) actually reads.
        """
        if not baseline.exists():
            return []
        old_nodes, old_edges = self._signature(json.loads(baseline.read_text(encoding=ENCODING)))
        new_nodes, new_edges = self._signature(self.graph_data())
        out = [f"+ {kind:<10} {src} -> {dst}" for src, dst, kind in sorted(new_edges - old_edges)]
        out += [f"- {kind:<10} {src} -> {dst}" for src, dst, kind in sorted(old_edges - new_edges)]
        out += [f"+ {role:<10} {node}" for node, role in sorted(new_nodes - old_nodes)]
        out += [f"- {role:<10} {node}" for node, role in sorted(old_nodes - new_nodes)]
        return out

    def check(self) -> list[str]:
        """Drift between the committed graph.json and a fresh derivation (empty == in sync). The viewer shell
        is template-owned + regenerated, so only graph.json — the diff-truth — is gated for staleness."""
        if not _JSON.exists():
            return [f"missing:  {_JSON.as_posix()}"]
        if _JSON.read_text(encoding=ENCODING) != self._json_text():
            return [f"stale:    {_JSON.as_posix()}"]
        return []


def main():
    ap = argparse.ArgumentParser(
        prog="python -m devtools.archmap",
        description="architecture autoviz: graph.json + a self-contained cytoscape viewer (doc-gen)",
    )
    ap.add_argument("packages", nargs="+", help="package dirs to map (>=1 required)")
    ap.add_argument(
        "--check", action="store_true", help="fail (exit 1) if the committed graph.json is out of date — do not write"
    )
    ap.add_argument(
        "--diff",
        metavar="BASELINE",
        help="report how the architecture CHANGED against a baseline graph.json (a FILE, so this stays "
        "git-free: CI does `git show <base>:docs/architecture/graph.json > base.json`). Advisory — the "
        "gates say what is forbidden, this says what moved",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = Archmap(args.packages)
    if args.diff:
        changes = engine.diff(Path(args.diff))
        log.info("architecture diff: %d change(s)\n%s", len(changes), "\n".join(changes))
        return
    if args.check:
        drift = engine.check()
        if drift:
            log.error(
                "archmap: graph.json is stale (run `python -m devtools.archmap %s`):\n%s",
                " ".join(args.packages),
                "\n".join(drift),
            )
            raise SystemExit(1)
        log.info("archmap: graph.json in sync")
        return
    engine.write_json()
    engine.write_viewer()
    log.info("archmap: wrote %s + %s", _JSON.as_posix(), _INDEX.as_posix())


if __name__ == "__main__":
    main()
