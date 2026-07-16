# sdlc-devtools

The structural-guardrail **analyzers** of the [sdlc-scaffold](../README.md) stack, packaged so consumers
depend on a **pinned version** instead of vendoring the source. Each engine is `engine + config`, invoked
identically in a generated project's `noxfile.py` / CI as `python -m devtools.<engine> <packages>`.

## Install (in a generated project)

The scaffold's template adds this as a git-dependency pinned by tag — an engine update is a one-line pin
bump (`devtools_ref`), not a re-vendored source diff:

```toml
# pyproject.toml (rendered by copier)
devtools @ git+https://github.com/dimiturtrz/sdlc-scaffold.git@v1.6.0#subdirectory=sdlc-devtools
```

The import name stays `devtools`, so every gate invocation is unchanged.

## The engines

- **graph.py** — import-graph arch fitness (god-module = fan-in AND fan-out over a degree / import cycle /
  god-file / **test-mirror gap**). Gate: `python -m devtools.graph --assert <packages>` (thresholds in
  `pyproject [tool.structure]`). Also computes **Martin's instability** `I = Ce/(Ce+Ca)` and
  **main-sequence distance** `D = |A + I − 1|` — reported in the explorer, advisory as a gate
  (`main_sequence_max`, OFF at 0). Drop `--assert` for ranked fan-in/out/bottleneck/chokepoint tables;
  `--assert --no-test-mirror` gates structure only, for a legitimately test-less tree.
- **test-mirror rule** (in graph.py) — every logic module needs a unit test. `[tool.structure] test_layout`
  sets *where*: `"mirror"` (strict path-mirror, default), `"flat"`, or `"off"`. `__init__`/`__main__` and
  coverage-**omitted** shells (via **omit.py**) are exempt.
- **lcom.py** — LCOM4 cohesion: ranks concrete stateful classes whose methods split into disjoint-state
  groups. `python -m devtools.lcom <packages>`.
- **data_clumps.py** — Fowler data clumps: param sets that travel together across signatures (Introduce
  Parameter Object). `python -m devtools.data_clumps <packages>`.
- **state_candidates.py** — namespace classes with latent shared instance state.
  `python -m devtools.state_candidates <packages>`.

  The three class-shape tools above are ADVISORY explorers — ranked report, always exit 0, never block.
- **magic_literals.py** — the non-comparison, cross-file axis ruff PLR2004 can't see: recurring
  identifier-shaped string literals (>= 4x → `StrEnum`/named-constant candidate) + repeated dict key-sets
  (drift-prone implicit record → dataclass/TypedDict). **ADVISORY** — a ranked report, always exit 0. There
  is no honest universal ceiling (0 too strict, N arbitrary), so it surfaces candidates and the reviewer
  decides; a repo that wants to enforce a budget adds a legislated config knob at that point.
- **shape_contracts.py** — the ML-domain shape gate: a public array/tensor boundary (`np.ndarray`/`Tensor`
  or a `[tool.shape_contracts] array_aliases` name) must carry a **jaxtyping** shape
  (`Float[Tensor, "b c h w"]`). `python -m devtools.shape_contracts <packages> --assert` — ENFORCED (a
  clean binary rule: typed-or-not, not a threshold seeded from current). Wired ML-only by the scaffold.
- **complexity.py** — cyclomatic complexity on **radon**'s CC (McCabe), ranked report + current max.
  **ADVISORY** (exit 0). The FIXED complexity gate is ruff `C901`/`PLR09xx` (CC>10, legislated); this just
  surfaces the ranking as reviewer signal.
- **archmap.py** — architecture autoviz: the marked package tree → a committed **graph.json** + a
  self-contained **interactive** cytoscape viewer. grimp builds the combined import graph
  (folder≡package≡module, so nodes come free from `packages` — no separate architecture language). It emits
  two files under `docs/architecture/`: **graph.json** (nodes with containment `parent` + `descendants`
  count, import edges weighted by import-statement count) — the deterministic, **committed diff-truth** so
  architecture erosion shows as a JSON diff in review; and **index.html** — a static viewer (vendored
  cytoscape/fcose inlined, no CDN/server/Java) that hydrates graph.json and lets you **fold/expand packages
  to any depth** (a folded pair is ONE arrow labelled the summed import count), and **focus** a module's
  dependency neighbourhood. Served as a per-repo **GitHub Pages** architecture site — one repo = one Pages
  site, so it's either sole-owner (opt-in `archviz_pages`: a staged `/architecture/` main + `/preview/` dev +
  root redirect) or composed as an `/architecture/` subpath into a repo's existing Pages deploy (see
  [SPEC](../docs/SPEC.md) row 15).
  `python -m devtools.archmap <packages>` regenerates both; `--check` fails if the committed graph.json is
  stale. **DOC-GEN / ADVISORY** — it visualizes structure, it does not enforce it; directional enforcement
  stays with import-linter. (Superseded the static mermaid mirror-tree of v1.5.0 — epic m5c.)
- **analytics.py** — a one-shot **explorer** (not a gate): per-area code lines, def count, src:test ratio,
  largest files. `python -m devtools.analytics --areas <packages> devtools`. Its McCabe branch-proxy is
  superseded by `complexity.py` (radon CC, properly); the area/ratio stats remain useful.
- **_common.py** — shared primitives: `Trees(packages).walk()/files()` (the one glob+parse) and
  `Pyproject.tool_section()` (the one `[tool.*]` read) the engines build on.
- **omit.py** — the coverage-`omit` reader + glob matcher: the 'non-logic shell' set the test-mirror and
  state-candidate gates treat specially, kept in agreement with the coverage gate.

## Prior art — and what's actually novel

These analyzers stand on mature work; honesty about the overlap matters more than a flattering pitch. The
**commodity axes** have battle-tested equivalents — we compute them inline (one walk, one config, one
advisory surface) rather than headline them:

- **LCOM4 cohesion** (`lcom.py`) — [`cohesion`](https://pypi.org/project/cohesion/) computes LCOM4;
  [ArchUnitPython](https://pypi.org/project/archunit/) offers 8 LCOM variants. Ours is one LCOM4 ranking.
- **Martin metrics** — instability `I` and main-sequence distance `D` (`graph.py`) are Robert Martin's
  (*Agile Software Development*, 2002); ArchUnitPython computes them too.
- **import axis** — cycles/god-modules ride [grimp](https://pypi.org/project/grimp/) (which we depend on);
  directional contracts are [import-linter](https://pypi.org/project/import-linter/) (which the scaffold
  ships as a gate). [tach](https://github.com/gauge-sh/tach) and pytest-archon cover the same ground.
- **complexity** (`analytics.py`) — a McCabe branch-proxy; [radon](https://pypi.org/project/radon/) (CC+MI)
  and ruff `C901`/`PLR09xx` do this properly (radon replaces it — bd 85l.4).
- **DRY / dead code / CVE / dep hygiene** — jscpd, vulture, pip-audit, deptry: all vendored, not ours.
- **architecture diagrams** (`archmap.py`) — the diagram ENGINE is commodity:
  [pyreverse](https://pypi.org/project/pylint/) (UML from code), [pydeps](https://pypi.org/project/pydeps/)
  (import graphs), [tach](https://github.com/gauge-sh/tach) (a live web viz, but remote-rendered),
  [Structurizr](https://structurizr.com/) (interactive C4, but manual DSL + 4-level cap), and interactive
  graph libs ([cytoscape.js](https://js.cytoscape.org/), which ours rides). Ours derives from grimp (already
  a dep). The niche is the COMBINATION, below.

The **moat** is the set of checks nothing in the survey does:

- **cross-file magic-literal detection** (`magic_literals.py`) — ruff `PLR2004` is comparison-only and
  single-file, and allows strings by default; the recurring-vocab + repeated-key-set axis is unique here.
- **data clumps** (`data_clumps.py`) — Fowler's smell, detected mechanically; no surveyed tool does it.
- **namespace-state candidates** (`state_candidates.py`) — latent shared instance state; novel.
- **shape contracts** (`shape_contracts.py`) — jaxtyping boundary enforcement; novel.
- **test-mirror gate** (`graph.py`) — every logic module has a mirrored test; novel as a gate.
- **auto-derived + committed + interactive architecture** (`archmap.py`) — no surveyed tool does all three
  at once (interactivity needs a runtime; a commit is static): tach/Structurizr are interactive but
  ephemeral or manual-DSL; mermaid/graphviz are committable but static. Ours splits it — a committed,
  diffable **graph.json** (auto-derived from the import graph, the erosion signal in review) + a
  self-contained **interactive** viewer (fold/expand to any depth, summed edge counts, focus) served as a
  **GitHub Pages** site. The empty leg of that triangle, filled.

## Self-gating

The engines obey the same house rules they impose — every helper is a method on its engine class (only the
thin `main()` is a top-level function, per the ast-grep rule), and each carries a per-engine mirror test
under `tests/unit/devtools/`. `cd sdlc-devtools && uvx nox` runs the full standalone bar: ruff, the engines'
own `graph --assert` (with test-mirror), ast-grep class-shape, deptry, the advisory explorers, and the
per-engine mirror tests.
