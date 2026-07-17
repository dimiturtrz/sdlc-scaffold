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
import json
import logging
from pathlib import Path

import grimp

from devtools._common import ENCODING

log = logging.getLogger("devtools.archmap")

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

    def graph(self) -> grimp.ImportGraph:
        """The combined import graph over ALL marked packages — combined (not per-package like graph.py) so
        cross-package edges (`cardioseg -> core`) survive as arrows."""
        return grimp.build_graph(*self.packages, include_external_packages=False)

    @staticmethod
    def _parent(module: str, module_set: set[str]) -> str | None:
        """The containment parent that EXISTS as a node (None for a top package or a gap in the tree)."""
        p = module.rsplit(".", 1)[0] if "." in module else None
        return p if p in module_set else None

    def graph_data(self) -> dict:
        """The full graph as committed-diffable JSON — the diff-truth the viewer hydrates. Every module is a
        node carrying its containment `parent` (compound nesting) + `descendants` count (the folded-node
        badge); every module→module import is an edge weighted by import-statement count (the viewer sums
        these into a counted arrow when a package folds). Deterministic order (modules + imports sorted, keys
        sorted) so the committed diff is minimal and meaningful."""
        graph = self.graph()
        modules = sorted(graph.modules)
        module_set = set(modules)
        nodes = [
            {
                "id": m,
                "label": m.split(".")[-1],
                "parent": self._parent(m, module_set),
                "descendants": sum(1 for n in modules if n.startswith(m + ".")),
            }
            for m in modules
        ]
        edges = [
            {"source": m, "target": imp, "weight": len(graph.get_import_details(importer=m, imported=imp))}
            for m in modules
            for imp in sorted(graph.find_modules_directly_imported_by(m))
            if imp in module_set
        ]
        return {"nodes": nodes, "edges": edges}

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
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed graph.json is out of date — do not write",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = Archmap(args.packages)
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
