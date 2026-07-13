"""Import-graph architecture diagnostic + fitness gate. grimp builds the honest import graph;
networkx ranks structure and `--assert` turns the measurable properties into a RATCHETED gate (the
metric arch axis import-linter's categorical layer contracts can't express):

  fan-in   (in_degree)   load-bearing        -> freeze its interface, test hardest
  fan-out  (out_degree)  orchestrating a lot -> decompose, hard to test isolated
  bottleneck (in*out)    classic tangle      -> prime refactor target
  betweenness            chokepoint          -> where to place a boundary/interface
  cycles (SCC>1)         tangle              -> break (import-linter gates layer cycles)

`report` is the one-shot EXPLORER (ranked tables). `--assert` is the GATE: it fails when a module is a
god-module (fan-in AND fan-out BOTH over a degree), a new import cycle appears, or a file blows the line
ceiling — plus an advisory chokepoint warning that never blocks. Thresholds live in `pyproject
[tool.structure]`, defaulted when absent. IMPORT-level only. Packages to graph are the positional argv
(default `core`). Run: `python -m devtools.graph [pkgs...]` | `python -m devtools.graph --assert [pkgs...]`.
"""

from __future__ import annotations

import argparse
import logging
import tomllib
from pathlib import Path

import grimp
import networkx as nx

log = logging.getLogger("devtools.graph")

# Fitness thresholds — SPEC [tool.structure] defaults, overridable in pyproject. Chosen so the blocking
# rules start CLEAN on a fresh project and ratchet: fan-in&out both>8, file>750 lines, any import cycle.
_DEFAULTS = {"bottleneck_degree": 8, "file_max": 750, "betweenness_max": 0.10}
_ADVISORY_PREVIEW = 15  # advisory lines shown before "… +N more" (avoid log spam)


def load_structure_cfg(pyproject: str = "pyproject.toml") -> dict:
    """Fitness thresholds from pyproject [tool.structure], merged onto SPEC defaults. One config home."""
    cfg = dict(_DEFAULTS)
    p = Path(pyproject)
    if p.exists():
        cfg.update(tomllib.loads(p.read_text(encoding="utf-8")).get("tool", {}).get("structure", {}))
    return cfg


def build_graph(packages: list[str]) -> nx.DiGraph:
    """The honest import DiGraph (importer -> imported) over the given root packages, via grimp."""
    g = nx.DiGraph()
    for pkg in packages:
        mods = grimp.build_graph(pkg)
        for m in mods.modules:
            g.add_node(m)
            for dep in mods.find_modules_directly_imported_by(m):
                g.add_edge(m, dep)
    return g


def file_lines(packages: list[str]) -> list[tuple[str, int]]:
    """(path, line-count) for every .py under the root packages — the file-shape axis the graph can't see."""
    return [
        (str(f), f.read_text(encoding="utf-8").count("\n") + 1)
        for pkg in packages
        for f in sorted(Path(pkg).rglob("*.py"))
    ]


def _god_modules(g: nx.DiGraph, degree: int) -> list[str]:
    ind, outd = dict(g.in_degree()), dict(g.out_degree())
    return [
        f"{n}: fan-in {ind[n]} x fan-out {outd[n]} (both > {degree}) — god-module, split by responsibility"
        for n in g
        if ind[n] > degree and outd[n] > degree
    ]


def _cycles(g: nx.DiGraph) -> list[str]:
    return [f"import cycle (SCC>1): {sorted(c)}" for c in nx.strongly_connected_components(g) if len(c) > 1]


def _oversized(files: list[tuple[str, int]], mx: int) -> list[str]:
    return [f"{f}: {n} lines > {mx} — god-file, split" for f, n in files if n > mx]


def _chokepoints(g: nx.DiGraph, mx: float) -> list[str]:
    return [
        f"{n}: betweenness {v:.3f} > {mx} — chokepoint, consider a boundary here"
        for n, v in nx.betweenness_centrality(g).items()
        if v > mx
    ]


def assert_fitness(g: nx.DiGraph, files: list[tuple[str, int]], cfg: dict) -> tuple[list[str], list[str]]:
    """(blocking, advisory) fitness violations. BLOCKING = god-module, import cycle, god-file (clean on a
    fresh project, so they ratchet); ADVISORY = the chokepoint warning (print-only, never blocks)."""
    blocking = _god_modules(g, cfg["bottleneck_degree"]) + _cycles(g) + _oversized(files, cfg["file_max"])
    advisory = _chokepoints(g, cfg["betweenness_max"])
    return blocking, advisory


def _top(pairs, n: int):
    """Top-n (name, score) by descending score — the shared ranking for every metric."""
    return sorted(pairs, key=lambda kv: -kv[1])[:n]


def report(g: nx.DiGraph, top: int) -> str:
    """Ranked fan-in / fan-out / bottleneck / chokepoint tables + the cycle list, as one text block."""
    ind, outd = dict(g.in_degree()), dict(g.out_degree())
    out = [
        f"import graph: {g.number_of_nodes()} modules, {g.number_of_edges()} edges",
        "",
    ]
    for title, pairs in (
        ("fan-in (load-bearing)", ind.items()),
        ("fan-out (orchestrators)", outd.items()),
        ("bottleneck (fan-in x fan-out)", [(m, ind[m] * outd[m]) for m in g]),
        ("chokepoints (betweenness)", nx.betweenness_centrality(g).items()),
    ):
        out.append(f"{title}:")
        out += [
            f"  {score:>7.3f}  {name}" if isinstance(score, float) else f"  {score:>4}  {name}"
            for name, score in _top(pairs, top)
        ]
        out.append("")
    cycles = [sorted(c) for c in nx.strongly_connected_components(g) if len(c) > 1]
    out.append(f"import cycles (SCC>1): {len(cycles)}")
    out += [f"  {c}" for c in cycles]
    return "\n".join(out)


def _run_assert(packages: list[str]) -> int:
    """The gate: log advisory warnings, log blocking errors, return exit code (1 if any blocking)."""
    cfg = load_structure_cfg()
    g, files = build_graph(packages), file_lines(packages)
    blocking, advisory = assert_fitness(g, files, cfg)
    if advisory:
        shown = advisory[:_ADVISORY_PREVIEW]
        extra = f"\n  … +{len(advisory) - _ADVISORY_PREVIEW} more" if len(advisory) > _ADVISORY_PREVIEW else ""
        log.warning(
            "architecture fitness — advisory (%d, non-blocking):\n  %s",
            len(advisory),
            "\n  ".join(shown) + extra,
        )
    if blocking:
        log.error(
            "architecture fitness — BLOCKING (%d):\n  %s",
            len(blocking),
            "\n  ".join(blocking),
        )
        return 1
    log.info(
        "architecture fitness: clean (0 god-modules / cycles / god-files; %d advisory)",
        len(advisory),
    )
    return 0


def main():
    ap = argparse.ArgumentParser(description="Import-graph architecture diagnostic + fitness gate.")
    ap.add_argument(
        "packages",
        nargs="*",
        default=["core"],
        help="root packages to graph (default: core)",
    )
    ap.add_argument("--top", type=int, default=10, help="rows per ranked table")
    ap.add_argument(
        "--assert",
        action="store_true",
        dest="assert_",
        help="fitness GATE: exit 1 on a god-module / import cycle / god-file (advisory: chokepoint)",
    )
    args = ap.parse_args()
    packages = args.packages or ["core"]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.assert_:
        raise SystemExit(_run_assert(packages))
    log.info("\n%s", report(build_graph(packages), args.top))


if __name__ == "__main__":
    main()
