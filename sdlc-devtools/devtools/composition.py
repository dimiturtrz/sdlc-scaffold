"""Composition cycles — a `holds` loop in the object graph (bd 4bl.4).

`graph.py` gates cycles in the IMPORT graph. This gates them one tier down, in the arrow that actually
means ownership: `holds`. A owns a B that owns an A is a defect the import cycle check can miss entirely —
two classes can compose each other through a single module (no import cycle at all, since the roll-up
collapses to a file self-loop), and it still means neither object can be constructed, tested, or reasoned
about without the other.

Uses the `holds` subgraph only. That subset is SOUND — a field's declared type is stated in the source, not
inferred — so this blocks rather than advises.

Run: `python -m devtools.composition [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import argparse
import logging

import networkx as nx

from devtools.arrows import HOLDS, ClassArrows

log = logging.getLogger("devtools.composition")


class CompositionCycles:
    """Cycles in the `holds` (has-a) subgraph over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def graph(self) -> nx.DiGraph:
        """The object graph: an edge means "owns an instance of"."""
        g = nx.DiGraph()
        for src, dst, kind in ClassArrows(self.packages).edges():
            if kind == HOLDS:
                g.add_edge(src, dst)
        return g

    def cycles(self) -> list[str]:
        """Every mutually-composing group — each reported once, members sorted for a stable message."""
        return [
            f"composition cycle: {' -> '.join([*sorted(component), sorted(component)[0]])} — "
            f"neither can be built or tested without the other; break the loop with an interface or an owner"
            for component in nx.strongly_connected_components(self.graph())
            if len(component) > 1
        ]

    def run_assert(self) -> int:
        """The gate: log any composition cycle and return an exit code."""
        found = self.cycles()
        if found:
            log.error("composition cycles — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("composition cycles: clean (the object graph is acyclic)")
        return 0


def main():
    ap = argparse.ArgumentParser(description="Composition cycles — mutually-owning classes.")
    ap.add_argument("packages", nargs="+", help="root packages to scan")
    ap.add_argument("--assert", action="store_true", dest="assert_", help="gate: exit 1 on a composition cycle")
    args = ap.parse_args()
    engine = CompositionCycles(args.packages)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.assert_:
        raise SystemExit(engine.run_assert())
    found = engine.cycles()
    log.info("composition cycles: %d\n%s", len(found), "\n".join(found))


if __name__ == "__main__":
    main()
