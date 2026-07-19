# Research Notice Board

## Active Questions

| Question | Status | Deep-Dive | Notes |
|----------|--------|-----------|-------|
| Python call-graph tools & architecture-smell detection: which tools expose resolved call edges, and can we detect feature-envy/law-of-demeter? | **SETTLED** | [2026-07-18_python_callgraph_tools.md](deep_dives/2026-07-18_python_callgraph_tools.md) | **pyan3** (actively maintained, Python 3.10–3.14, inheritance + method resolution, DOT/SVG/HTML) is the only production call-graph tool. **Pyrefly** (Meta) LSP only, no API. **PyCG** archived Nov 2023. **SonarQube** is the only off-the-shelf tool for feature-envy/law-of-demeter (Cloud-only). New MCP tools (Tree-Sitter-Analyzer, Codebase-Memory, 2026) focus on agent interfaces. |
| ML template landscape: does the owner's 7-ingredient scaffold pattern exist as an integrated off-the-shelf template? | **SETTLED** | [2026-07-17_ml_template_scaffold_comparison.md](deep_dives/2026-07-17_ml_template_scaffold_comparison.md) | Verdict: Novel as a *combination*. Individual ingredients exist (Hydra config, MLflow, ruff, etc.). Closest existing: Lightning-Hydra-Template + Cookiecutter-Data-Science (~3/7 coverage). Biggest novel gaps: evaluation harness with sync_numbers → RESULTS.json single-source-of-truth rendering, Adapter/Protocol/Registry data pattern, enforced 3-tier layering with import-linter. |

## Closed / Reference

(none yet)
