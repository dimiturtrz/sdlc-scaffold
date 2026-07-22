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

import logging
from collections.abc import Iterable

import networkx as nx

from devtools.arrows import HOLDS, ClassArrows
from devtools.plumbing.cli import Cli

log = logging.getLogger("devtools.composition")


class CompositionCycles:
    """Cycles in the `holds` (has-a) subgraph over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def graph(self) -> nx.DiGraph[str]:
        """The object graph: an edge means "owns an instance of"."""
        owns: nx.DiGraph[str] = nx.DiGraph()
        for src, dst, kind in ClassArrows(self.packages).edges():
            if kind == HOLDS:
                owns.add_edge(src, dst)
        return owns

    @staticmethod
    def _names(component: Iterable[object]) -> list[str]:
        """An SCC's members as sorted names.

        networkx's stubs return the unparameterised `_Node` from `strongly_connected_components` even for a
        `DiGraph[str]`, so sorting them fails the comparability bound. Our nodes are dotted class NAMES by
        construction, and this states that once instead of at each use.
        """
        return sorted(map(str, component))

    def cycles(self) -> list[str]:
        """Every mutually-composing group — each reported once, members sorted for a stable message.

        A SELF-LOOP does not block, and that is now a stated boundary rather than an accident (bd a0a).
        `holds` emits self-arrows, so a class owning an instance of its own type does reach this graph —
        but a tree node, a linked list and a Composite are all exactly that shape and all ordinary designs.
        What cannot be built is MUTUAL ownership, so `len(component) > 1` is the rule itself and not a
        convenience: a recursive type can be constructed and tested alone, a mutually-recursive pair cannot.
        """
        return [
            f"composition cycle: {' -> '.join([*self._names(component), self._names(component)[0]])} — "
            f"neither can be built or tested without the other; break the loop with an interface or an owner"
            for component in nx.strongly_connected_components(self.graph())
            if len(component) > 1
        ]

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.cycles()
        return "\n".join([f"composition cycles: {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: log any composition cycle and return an exit code."""
        found = self.cycles()
        if found:
            log.error("composition cycles — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("composition cycles: clean (the object graph is acyclic)")
        return 0


def main():
    Cli(
        CompositionCycles,
        "Composition cycles — a `holds` loop in the object graph.",
        gate="exit 1 on a composition cycle",
    ).run()


if __name__ == "__main__":
    main()
