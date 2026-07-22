"""Import-graph architecture diagnostic + fitness gate. grimp builds the honest import graph;
networkx ranks structure and `--assert` turns the measurable properties into a RATCHETED gate (the
metric arch axis import-linter's categorical layer contracts can't express):

  fan-in   (in_degree)   load-bearing        -> freeze its interface, test hardest
  fan-out  (out_degree)  orchestrating a lot -> decompose, hard to test isolated
  bottleneck (in*out)    classic tangle      -> prime refactor target
  betweenness            chokepoint          -> where to place a boundary/interface
  cycles (SCC>1)         tangle              -> break (import-linter gates layer cycles)
  instability I=Ce/(Ce+Ca)  stable vs. volatile  -> depend in the direction of stability
  main-seq. distance |A+I-1|  balance of A vs I  -> off it = zone of pain / uselessness (advisory)

`report` is the one-shot EXPLORER (ranked tables). `--assert` is the GATE: it fails when a module is a
god-module (fan-in AND fan-out BOTH over a degree), a new import cycle appears, a file blows the line
ceiling, or a logic module has no strict path-mirror test (`tests/unit/<pkg>/<path>/foo.py` under the
default `bare` layout; `devtools/layout.py` owns the convention) — plus
an advisory chokepoint warning that never blocks. Thresholds live in `pyproject
[tool.structure]`, defaulted when absent. IMPORT-level only. Packages to graph are the positional argv
(default `src`). Run: `python -m devtools.graph.fitness [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

import grimp
import networkx as nx

from devtools.graph.arrows import ClassArrows
from devtools.graph.calls import CONSTRUCT, CallArrows
from devtools.graph.classes import ClassIndex
from devtools.plumbing._common import ENCODING
from devtools.plumbing.cli import Cli, Flag, Switch
from devtools.plumbing.layout import DEFAULT_TEST_ROOT, STRUCTURAL, TestLayout
from devtools.plumbing.names import Names
from devtools.plumbing.pyproject import Pyproject
from devtools.plumbing.resolve import Resolver
from devtools.plumbing.trees import Trees

log = logging.getLogger("devtools.graph.fitness")


class StructureCfg(TypedDict):
    """The [tool.structure] key set, typed — so a threshold reaches its gate as an int/float, not as an
    `object` the caller quietly assumes about."""

    bottleneck_degree: int
    file_max: int
    file_min: int
    betweenness_max: float
    main_sequence_max: float
    test_layout: str


_ADVISORY_PREVIEW = 15  # advisory lines shown before "… +N more" (avoid log spam)
# Martin's stability metrics (bd x3b). Edges are importer -> imported, so in_degree = afferent coupling Ca
# (who depends on me) and out_degree = efferent Ce (who I depend on). Instability I = Ce/(Ce+Ca) and
# abstractness A = abstract-classes / classes place a module on the A-I plane; distance from the "main
# sequence" (the ideal A + I = 1 line) is D = |A + I - 1|.
_ABSTRACT_BASES = {"ABC", "ABCMeta", "Protocol"}
_ABSTRACT_DECORATORS = {"abstractmethod", "abstractproperty"}


class ImportGraph:
    """Import-graph architecture diagnostic + fitness gate over the given root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def load_structure_cfg(pyproject: str = "pyproject.toml") -> StructureCfg:
        """This engine's slice of [tool.structure], typed. Validation lives in Pyproject because the SECTION
        is shared — demeter and envy read their own keys from it, so no one engine owns the schema."""
        cfg = Pyproject.structure_cfg(pyproject)
        return StructureCfg(
            bottleneck_degree=int(cfg["bottleneck_degree"]),
            file_max=int(cfg["file_max"]),
            file_min=int(cfg["file_min"]),
            betweenness_max=float(cfg["betweenness_max"]),
            main_sequence_max=float(cfg["main_sequence_max"]),
            test_layout=str(cfg["test_layout"]),
        )

    def build_graph(self) -> nx.DiGraph[str]:
        """The honest import DiGraph (importer -> imported) over the root packages, via grimp."""
        g: nx.DiGraph[str] = nx.DiGraph()
        for pkg in self.packages:
            mods = grimp.build_graph(pkg)
            for m in mods.modules:
                g.add_node(m)
                for dep in mods.find_modules_directly_imported_by(m):
                    g.add_edge(m, dep)
        return g

    def file_lines(self) -> list[tuple[str, int]]:
        """(path, line-count) for every .py under the root packages — the file-shape axis the graph can't see."""
        return [(str(f), f.read_text(encoding=ENCODING).count("\n") + 1) for f in Trees(self.packages).files()]

    @staticmethod
    def _god_modules(g: nx.DiGraph[str], degree: int) -> list[str]:
        ind, outd = dict(g.in_degree()), dict(g.out_degree())
        return [
            f"{n}: fan-in {ind[n]} x fan-out {outd[n]} (both > {degree}) — god-module, split by responsibility"
            for n in g
            if ind[n] > degree and outd[n] > degree
        ]

    @staticmethod
    def _cycles(g: nx.DiGraph[str]) -> list[str]:
        # networkx's stubs return the unparameterised _Node from strongly_connected_components even for a
        # DiGraph[str], so the comparability bound fails; our nodes are dotted NAMES by construction.
        return [
            f"import cycle (SCC>1): {sorted(map(str, c))}" for c in nx.strongly_connected_components(g) if len(c) > 1
        ]

    @staticmethod
    def _oversized(files: list[tuple[str, int]], mx: int) -> list[str]:
        return [f"{f}: {n} lines > {mx} — god-file, split" for f, n in files if n > mx]

    def unmirrored(self, layout: str = "mirror", test_root: str = DEFAULT_TEST_ROOT) -> list[str]:
        """LOGIC source modules with no unit test. The universal rule is "every logic module HAS a test";
        WHERE it lives is `test_layout`, and `devtools.plumbing.layout` owns that convention for every gate that
        reads it (bd 1a8) — this one and the method-level mirror both resolve through the same strategy,
        over the same population, so they cannot disagree about what is covered."""
        convention = TestLayout.of(layout, test_root)
        return [msg for f in convention.testable(self.packages) if (msg := convention.missing(f))]

    @staticmethod
    def _undersized(files: list[tuple[str, int]], mn: int) -> list[str]:
        """Advisory line floor. OFF at mn<=0 (the default) — no honest universal floor; small files are often
        SSOT / strategy / shared-vocab leaves, and 'too thin' is a responsibility call, not a line count."""
        if mn <= 0:
            return []
        return [
            f"{f}: {n} lines < {mn} — earn its keep? (fold, or accept a small leaf)"
            for f, n in files
            if n < mn and not f.endswith(STRUCTURAL)
        ]

    @staticmethod
    def _chokepoints(g: nx.DiGraph[str], mx: float) -> list[str]:
        return [
            f"{n}: betweenness {v:.3f} > {mx} — chokepoint, consider a boundary here"
            for n, v in nx.betweenness_centrality(g).items()
            if v > mx
        ]

    @staticmethod
    def _is_abstract(cls: ast.ClassDef) -> bool:
        """A class is abstract if it subclasses ABC/Protocol, sets metaclass=ABCMeta, or has an @abstractmethod."""
        if Names.bases(cls) & _ABSTRACT_BASES:
            return True
        if any(kw.arg == "metaclass" and Names.trailing(kw.value) == "ABCMeta" for kw in cls.keywords):
            return True
        return any(
            isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)
            and any(Names.trailing(d) in _ABSTRACT_DECORATORS for d in m.decorator_list)
            for m in cls.body
        )

    @staticmethod
    def _module_file(mod: str) -> Path | None:
        """The .py file backing a dotted module name (`a.b` -> a/b.py or a/b/__init__.py), if it exists."""
        parts = mod.split(".")
        for cand in (Path(*parts).with_suffix(".py"), Path(*parts) / "__init__.py"):
            if cand.exists():
                return cand
        return None

    @staticmethod
    def abstractness(mod: str) -> float | None:
        """Martin's A = abstract classes / total classes in the module (None if no backing file or no classes)."""
        f = ImportGraph._module_file(mod)
        if f is None:
            return None
        classes = [n for n in ast.walk(ast.parse(f.read_text(encoding=ENCODING))) if isinstance(n, ast.ClassDef)]
        if not classes:
            return None
        return sum(ImportGraph._is_abstract(c) for c in classes) / len(classes)

    @staticmethod
    def instability(g: nx.DiGraph[str]) -> dict[str, float]:
        """Martin's I = Ce/(Ce+Ca): 0 = maximally STABLE (only depended-on), 1 = maximally UNSTABLE (only
        depends on others). Isolated nodes (no coupling) are skipped — I is undefined there."""
        ind, outd = dict(g.in_degree()), dict(g.out_degree())
        return {n: outd[n] / (outd[n] + ind[n]) for n in g if outd[n] + ind[n] > 0}

    @staticmethod
    def main_sequence_distance(g: nx.DiGraph[str]) -> dict[str, float]:
        """D = |A + I - 1|: distance from the main sequence. High D = the zone of PAIN (stable + concrete, hard
        to extend) or the zone of USELESSNESS (abstract + unstable). Only modules with classes (A defined)."""
        out = {}
        for n, i in ImportGraph.instability(g).items():
            a = ImportGraph.abstractness(n)
            if a is not None:
                out[n] = abs(a + i - 1)
        return out

    @staticmethod
    def _off_main_sequence(g: nx.DiGraph[str], mx: float) -> list[str]:
        """Advisory. OFF at mx<=0 (the default): a concrete stable leaf legitimately sits at D≈1, so there is no
        honest universal threshold — a repo opts in by setting `main_sequence_max`, then flags modules past it."""
        if mx <= 0:
            return []
        return [
            f"{n}: main-sequence distance {d:.2f} > {mx} — off the main sequence (zone of pain/uselessness)"
            for n, d in ImportGraph.main_sequence_distance(g).items()
            if d > mx
        ]

    @staticmethod
    def assert_fitness(
        g: nx.DiGraph[str], files: list[tuple[str, int]], cfg: StructureCfg
    ) -> tuple[list[str], list[str]]:
        """(blocking, advisory) fitness violations. BLOCKING = god-module, import cycle, god-file (clean on a
        fresh project, so they ratchet); ADVISORY = line-floor (off by default) + chokepoint (never blocks)."""
        blocking = (
            ImportGraph._god_modules(g, cfg["bottleneck_degree"])
            + ImportGraph._cycles(g)
            + ImportGraph._oversized(files, cfg["file_max"])
        )
        advisory = (
            ImportGraph._undersized(files, cfg["file_min"])
            + ImportGraph._chokepoints(g, cfg["betweenness_max"])
            + ImportGraph._off_main_sequence(g, cfg["main_sequence_max"])
        )
        return blocking, advisory

    @staticmethod
    def _top(pairs: Iterable[tuple[object, float]], n: int) -> list[tuple[object, float]]:
        """Top-n (label, score) by descending score — the shared ranking for every metric.

        The label is `object`, not `str`, because networkx's stubs hand back the
        unparameterised `_Node` from betweenness_centrality while our own metrics yield `str`.
        A ranking helper does not care what the label IS — only that the score sorts — so the
        wider signature is the honest one rather than a concession.
        """
        return sorted(pairs, key=lambda kv: -kv[1])[:n]

    def typed_graph(self, kinds: set[str]) -> nx.DiGraph[str]:
        """A CLASS-level DiGraph over one arrow subset — the same metrics, a different question.

        This is what "metrics as edge-subset queries" means concretely (bd 4bl.4). The ranking functions
        below never cared what an edge MEANT; they were simply only ever handed imports. Give them a
        kind-filtered subset and fan-in becomes REAL usage coupling — which import fan-in only
        approximates, because importing is not using and a type-only import counts the same as a call.

        The GATES deliberately stay on the import graph: it is sound and complete, so a blocking rule
        cannot false-positive. This is the explorer side, where an approximate answer is still useful.
        """
        g: nx.DiGraph[str] = nx.DiGraph()
        resolver = Resolver(self.packages)  # built once and shared by both engines (bd 5cg)
        arrows = ClassArrows(self.packages, resolver).edges() + CallArrows(self.packages, resolver).class_edges()
        for src, dst, kind in arrows:
            if kind in kinds and src != dst:  # a self-arrow is a shape, not a ranking signal
                g.add_edge(src, dst)
        return g

    def report(self, top: int = 10) -> str:
        """The ranked tables as one text block — the import graph, then the same rankings over the
        `calls` subset when there is one (who is actually USED, not merely imported).
        """
        blocks = [self._render(self.build_graph(), top)]
        usage = self.typed_graph({"calls", CONSTRUCT})
        if usage.number_of_edges():
            blocks.append(self._render(usage, top, label="usage graph (calls)", unit="classes"))
        return "\n\n".join(blocks)

    @staticmethod
    def _render(g: nx.DiGraph[str], top: int, label: str = "import graph", unit: str = "modules") -> str:
        """Ranked fan-in / fan-out / bottleneck / chokepoint tables + the cycle list, as one text block.

        Takes the graph rather than building one, so the SAME rankings serve any edge subset — the import
        tier, or the class-level `calls` tier via `typed_graph`.
        """
        ind, outd = dict(g.in_degree()), dict(g.out_degree())
        out = [f"{label}: {g.number_of_nodes()} {unit}, {g.number_of_edges()} edges", ""]
        for title, pairs in (
            ("fan-in (load-bearing)", ind.items()),
            ("fan-out (orchestrators)", outd.items()),
            ("bottleneck (fan-in x fan-out)", [(m, ind[m] * outd[m]) for m in g]),
            ("chokepoints (betweenness)", nx.betweenness_centrality(g).items()),
            ("instability I=Ce/(Ce+Ca)", ImportGraph.instability(g).items()),
            ("main-sequence distance |A+I-1|", ImportGraph.main_sequence_distance(g).items()),
        ):
            out.append(f"{title}:")
            out += [
                f"  {score:>7.3f}  {name}" if isinstance(score, float) else f"  {score:>4}  {name}"
                for name, score in ImportGraph._top(pairs, top)
            ]
            out.append("")
        cycles = [sorted(map(str, c)) for c in nx.strongly_connected_components(g) if len(c) > 1]
        out.append(f"import cycles (SCC>1): {len(cycles)}")
        out += [f"  {c}" for c in cycles]
        return "\n".join(out)

    def run_assert(self, *, test_mirror: bool = True) -> int:
        """The gate: log advisory warnings, log blocking errors, return exit code (1 if any blocking).

        ``test_mirror=False`` skips the every-module-needs-a-test check — for a legitimately test-less tree
        (e.g. gating a bag of single-file CLI tools for structure without demanding a per-tool mirror test).
        """
        cfg = self.load_structure_cfg()
        g, files = self.build_graph(), self.file_lines()
        blocking, advisory = self.assert_fitness(g, files, cfg)
        if test_mirror:
            blocking += [f"test mirror: {m}" for m in self.unmirrored(cfg["test_layout"])]  # module w/o a test blocks
        # One file = one SUBJECT (bd 4bl.1): a second PRIMARY class means two subjects sharing a module.
        # Idiomatic companions (its error family, its config dataclass/enum, a local subclass) are
        # SATELLITES and never count — see devtools/classes.py for the role rules.
        blocking += [f"class roles: {m}" for m in ClassIndex(self.packages).multi_primary()]
        if advisory:
            shown = advisory[:_ADVISORY_PREVIEW]
            extra = f"\n  … +{len(advisory) - _ADVISORY_PREVIEW} more" if len(advisory) > _ADVISORY_PREVIEW else ""
            log.warning(
                "architecture fitness — advisory (%d, non-blocking):\n  %s", len(advisory), "\n  ".join(shown) + extra
            )
        if blocking:
            log.error("architecture fitness — BLOCKING (%d):\n  %s", len(blocking), "\n  ".join(blocking))
            return 1
        log.info("architecture fitness: clean (0 god-modules / cycles / god-files; %d advisory)", len(advisory))
        return 0


def main():
    Cli(
        ImportGraph,
        "Import-graph architecture diagnostic + fitness gate.",
        gate="fitness GATE: exit 1 on a god-module / import cycle / god-file / test-mirror gap",
        flags=(
            Flag("--top", "rows per ranked table", type=int, default=10),
            Switch("--no-test-mirror", "skip the test-mirror check under --assert", dest="test_mirror"),
        ),
    ).run()


if __name__ == "__main__":
    main()
