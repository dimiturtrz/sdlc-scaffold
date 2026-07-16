"""Architecture autoviz: the marked package tree -> tiered, edge-counted, clickable mermaid docs.

grimp builds the honest combined import graph (folder≡package≡module, so nodes come free from the
`packages` marking — no separate architecture language). Each nesting tier is one document: the boxes are a
package's direct sub-packages, an arrow `viewer -->|3| core` is the count of module→module imports crossing
that pair (coupling weight), and a `Drill:` markdown-link line descends into each box that has children. The
result is a mirror tree under `docs/architecture/` — committed, so architecture erosion shows up as a
DIAGRAM DIFF in review.

DOC-GEN / ADVISORY. This visualizes structure; it does not enforce it — directional enforcement stays with
import-linter (the layer gate). Drill uses markdown links, not mermaid `click`: GitHub's CSP blocks `click`
navigation, so links are the portable path (a `click` directive is emitted too, as a free bonus where a
renderer honors it).

    python -m devtools.archmap core cardioseg      # regenerate docs/architecture/ (writes the mirror tree)
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

import grimp

log = logging.getLogger("devtools.archmap")

_ROOT = Path("docs/architecture")
_DOC = "ARCHITECTURE.md"
_JSON = _ROOT / "graph.json"


class Archmap:
    """Tiered edge-counted mermaid generator over the marked package tree (one document per nesting tier)."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def graph(self) -> grimp.ImportGraph:
        """The combined import graph over ALL marked packages — combined (not per-package like graph.py) so
        cross-package edges (`cardioseg -> core`) survive to become the tier-1 arrows."""
        return grimp.build_graph(*self.packages, include_external_packages=False)

    @staticmethod
    def _ancestor(module: str, depth: int) -> str | None:
        """`module` truncated to `depth` dotted segments — the tier-`depth` box it lives in (None if shorter).

        depth 1 -> top package (`core`); depth 2 -> sub-package (`core.data`)."""
        parts = module.split(".")
        return ".".join(parts[:depth]) if len(parts) >= depth else None

    def _boxes_under(self, graph: grimp.ImportGraph, box: str | None) -> set[str]:
        """The direct child boxes of `box` (its sub-packages one tier down); `box=None` -> the top packages."""
        depth = (box.count(".") + 2) if box else 1
        prefix = box + "." if box else ""
        return {a for m in graph.modules if (a := self._ancestor(m, depth)) and a.startswith(prefix)}

    def _edges_under(self, graph: grimp.ImportGraph, box: str | None) -> Counter:
        """Module→module imports aggregated to the child-box pairs under `box`, counted (intra-box dropped)."""
        depth = (box.count(".") + 2) if box else 1
        prefix = box + "." if box else ""
        edges: Counter = Counter()
        for mod in graph.modules:
            src = self._ancestor(mod, depth)
            if src is None or not src.startswith(prefix):
                continue
            for imp in graph.find_modules_directly_imported_by(mod):
                dst = self._ancestor(imp, depth)
                if dst is None or dst == src or not dst.startswith(prefix) or imp not in graph.modules:
                    continue
                edges[(src, dst)] += 1
        return edges

    def _has_children(self, graph: grimp.ImportGraph, box: str) -> bool:
        return bool(self._boxes_under(graph, box))

    @staticmethod
    def _node_id(box: str) -> str:
        return box.replace(".", "_")

    def _render(self, graph: grimp.ImportGraph, box: str | None) -> str:
        """One tier's document: a heading, the mermaid diagram (counted edges + bonus `click`), and the
        portable `Drill:` markdown-link line into every child that itself has children."""
        boxes = sorted(self._boxes_under(graph, box))
        edges = self._edges_under(graph, box)
        title = box or " / ".join(self.packages)
        drillable = [b for b in boxes if self._has_children(graph, b)]

        out = [f"# Architecture — `{title}`", "", "```mermaid", "graph LR"]
        out.extend(f'  {self._node_id(b)}["{b.split(".")[-1]}"]' for b in boxes)
        out.extend(
            f"  {self._node_id(s)} -->|{n}| {self._node_id(d)}" for (s, d), n in sorted(edges.items())
        )
        out.extend(f'  click {self._node_id(b)} "./{b.split(".")[-1]}/{_DOC}"' for b in drillable)
        out.append("```")
        if drillable:
            links = " · ".join(f"[{b.split('.')[-1]}](./{b.split('.')[-1]}/{_DOC})" for b in drillable)
            out += ["", f"**Drill:** {links}"]
        out.append("")
        return "\n".join(out)

    @staticmethod
    def _doc_path(box: str | None) -> Path:
        """Mirror-tree location for a box's document: `core.data` -> docs/architecture/core/data/ARCHITECTURE.md."""
        return _ROOT.joinpath(*(box.split(".") if box else []), _DOC)

    def documents(self) -> dict[Path, str]:
        """The full mirror tree {path: markdown} — the root tier plus one doc per box that has children.
        A single source for both `write()` and the `--check` stale gate (bd 2vt.3)."""
        graph = self.graph()
        docs = {self._doc_path(None): self._render(graph, None)}
        for module in graph.modules:
            for depth in range(1, module.count(".") + 1):
                box = self._ancestor(module, depth)
                if box and self._has_children(graph, box):
                    docs[self._doc_path(box)] = self._render(graph, box)
        return docs

    def write(self) -> list[Path]:
        """Regenerate the mirror tree on disk; return the written paths (sorted)."""
        written = []
        for path, text in self.documents().items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(path)
        return sorted(written)

    @staticmethod
    def _parent(module: str, module_set: set[str]) -> str | None:
        """The containment parent that EXISTS as a node (None for a top package or a gap in the tree)."""
        p = module.rsplit(".", 1)[0] if "." in module else None
        return p if p in module_set else None

    def graph_data(self) -> dict:
        """The full graph as committed-diffable JSON — the diff-truth the cytoscape viewer hydrates. Every
        module is a node carrying its containment `parent` (compound nesting) + `descendants` count (the
        collapsed-node badge); every module→module import is an edge weighted by import-statement count
        (the viewer aggregates these into counted meta-edges when a parent collapses). Deterministic order
        (modules + imports sorted, keys sorted) so the committed diff is minimal and meaningful."""
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

    def write_json(self, path: Path = _JSON) -> Path:
        """Write the committed graph.json (deterministic) — the diffable erosion signal + viewer input."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.graph_data(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def check(self) -> list[str]:
        """Drift between the committed mirror tree and a fresh derivation (empty == in sync). Catches a
        missing doc, a stale doc (structure moved but the diagram wasn't regenerated), and an orphan doc
        (a box was deleted but its file lingers) — the `--check` gate keeps committed diagrams honest."""
        expected = self.documents()
        drift = []
        for path, text in sorted(expected.items()):
            if not path.exists():
                drift.append(f"missing:  {path.as_posix()}")
            elif path.read_text(encoding="utf-8") != text:
                drift.append(f"stale:    {path.as_posix()}")
        drift += [f"orphan:   {p.as_posix()}" for p in sorted(_ROOT.rglob(_DOC)) if p not in expected]
        return drift


def main():
    ap = argparse.ArgumentParser(
        prog="python -m devtools.archmap",
        description="tiered edge-counted mermaid architecture docs from the marked package tree (doc-gen)",
    )
    ap.add_argument("packages", nargs="+", help="package dirs to map (>=1 required)")
    ap.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed docs/architecture/ tree is out of sync — do not write",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help=f"write the committed graph.json (nodes + weighted import edges) to {_JSON.as_posix()}",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = Archmap(args.packages)
    if args.json:
        log.info("archmap: wrote %s", engine.write_json().as_posix())
        return
    if args.check:
        drift = engine.check()
        if drift:
            log.error("archmap: %d document(s) out of sync (run `python -m devtools.archmap %s`):\n%s",
                      len(drift), " ".join(args.packages), "\n".join(drift))
            raise SystemExit(1)
        log.info("archmap: docs/architecture/ in sync")
        return
    written = engine.write()
    log.info("archmap: wrote %d document(s) under %s", len(written), _ROOT)


if __name__ == "__main__":
    main()
