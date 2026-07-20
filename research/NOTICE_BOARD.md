# Research Notice Board

External/field synthesis for **sdlc-scaffold** — the `research/` doc layer (what the field says), as
distinct from `interpretations/` (sense-making of our OWN results). Newest first.

## Active Questions

| Question | Status | Deep-Dive | Notes |
|----------|--------|-----------|-------|
| Python call-graph tools & architecture-smell detection: which tools expose resolved call edges, and can we detect feature-envy/law-of-demeter? | **SETTLED** | [2026-07-18_python_callgraph_tools.md](deep_dives/2026-07-18_python_callgraph_tools.md) | **pyan3** (actively maintained, Python 3.10–3.14, inheritance + method resolution, DOT/SVG/HTML) is the only production call-graph tool. **Pyrefly** (Meta) LSP only, no API. **PyCG** archived Nov 2023. **SonarQube** is the only off-the-shelf tool for feature-envy/law-of-demeter (Cloud-only). New MCP tools (Tree-Sitter-Analyzer, Codebase-Memory, 2026) focus on agent interfaces. |
| How do you wire Pyrefly v1.1 strict as an enforcement gate in a uv/pyproject.toml project, and what breaks (jaxtyping, untyped deps)? | **SETTLED** | [2026-07-18_pyrefly_strict_integration.md](deep_dives/2026-07-18_pyrefly_strict_integration.md) | `[tool.pyrefly]` with `preset = "strict"`; official pre-commit hook `facebook/pyrefly-pre-commit`. Untyped deps default to ERRORS — `ignore-missing-imports` / `replace-imports-with-any` to suppress. jaxtyping forward-ref shape strings only partially supported, and architecturally limited for cross-function sharing. **Shipped**: the strict gate (bd i5q), graduated to blocking on devtools at 52 → 0 errors (bd dun.2), and `python-version` aimed at the declared floor (bd 166). |
| ML template landscape: does the owner's 7-ingredient scaffold pattern exist as an integrated off-the-shelf template? | **SETTLED** | [2026-07-17_ml_template_scaffold_comparison.md](deep_dives/2026-07-17_ml_template_scaffold_comparison.md) | Verdict: Novel as a *combination*. Individual ingredients exist (Hydra config, MLflow, ruff, etc.). Closest existing: Lightning-Hydra-Template + Cookiecutter-Data-Science (~3/7 coverage). Biggest novel gaps: evaluation harness with sync_numbers → RESULTS.json single-source-of-truth rendering, Adapter/Protocol/Registry data pattern, enforced 3-tier layering with import-linter. |

| Interactive architecture-graph viewer: which library does arbitrary-depth expand/collapse WITH aggregating dependency arrows, self-contained and Java-free? | **SETTLED** | [2026-07-16_interactive_archviz_libs.md](deep_dives/2026-07-16_interactive_archviz_libs.md) | grimp → committed `graph.json` → one self-contained HTML, on **cytoscape.js + fcose** (all MIT, client-side). G6 v5 kept as fallback. The diffable-source vs interactive-runtime tension is inherent, and resolved by committing the JSON rather than the render. **Shipped** as `archmap` + the archviz viewer (epic 433); the aggregation is hand-rolled rather than expand-collapse, so a folded pair is exactly one counted arrow. |

## Closed / Reference

(none yet)
