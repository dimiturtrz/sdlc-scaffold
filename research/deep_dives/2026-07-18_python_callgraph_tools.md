# Python Call-Graph Tools & Architecture-Smell Detection (2026)

**Date**: 2026-07-18
**Status**: settled
**Supersedes**: none

## TL;DR

**pyan3** is the only actively maintained static call-graph tool for Python 3.11+/3.13 with method-resolution + inheritance support; **Pyrefly** (Meta) exposes call hierarchy only via LSP, not programmatically; **PyCG** is archived. Architecture-smell detection (feature-envy, law-of-demeter) is sparse: SonarQube's "Couplers" rule is the most explicit, others require custom analysis.

## Question

What static call-graph tools exist for Python 3.11+ that expose resolved call edges programmatically? Can we detect architecture smells (feature-envy, law-of-demeter) off-the-shelf?

## Findings

### 1. Pyrefly (Meta, v1.0/1.1, 2026)

**Call-edge exposure**: Limited to LSP [S1].
- **LSP Call Hierarchy**: Pyrefly 1.0 (May 2026) and 1.1 (June 2026) support LSP's `textDocument/callHierarchy` for goto-definition and find-references, exposing **IDE-facing call stacks only** [S2][S3].
- **No programmatic API**: The official documentation and GitHub do not expose a call-graph export API, JSON dump, or library interface for consuming resolved call edges [S1][S4].
- **Type resolution**: Pyrefly resolves types at the call site but does not expose this resolution for static analysis workflows [S2].
- **Verdict**: Use Pyrefly for IDE navigation; not suitable for batch call-graph extraction or custom analysis pipelines.

### 2. pyan3 (Technologicat/PyPI, current, Python 3.10–3.14)

**Maintenance & precision**: **Actively maintained, production-ready** [S5][S6].
- **Python version support**: Tested on 3.10–3.14; covers 3.11+ and 3.13 [S5].
- **Method resolution**: Handles inheritance explicitly: "looks up also in base classes when resolving attributes," resolves `super()` based on static type at call site, tracks method calls through assignment with lexical scoping [S5].
- **Output formats**: DOT (GraphViz), SVG, HTML, TGF, yEd, plain text for dependency lists [S5].
- **Verdict**: **Recommended for call-graph generation.** Only actively-maintained Python call-graph tool with inheritance support and multiple export formats.

### 3. PyCG (vitsalis/archived, Nov 2023)

**Status**: **Archived and unmaintained** [S7].
- Explicit notice: "PyCG is archived. Due to limited availability, no further development improvements are planned" [S7].
- **Python version support**: Requires Python 3.4+; compatibility with 3.11+ uncertain [S7].
- **Method resolution**: Implements MRO tracking (`pycg/machinery/classes.py`), ~99.2% precision, ~69.9% recall on evaluation set [S8].
- **Verdict**: Do not use. Archived November 2023; Python 3.11+ support unconfirmed. Consider forking if precision metrics matter more than maintenance.

### 4. Newer Tools (2024–2026)

**Tree-Sitter-based approaches** [S9][S10]:

- **Tree-Sitter-Analyzer** (2026-05-24): MCP server for AI agents, 13+ languages (bash/scala graduated v1.22.0; Swift/Kotlin/Ruby/PHP/C# unblocked 2026-05-24), family-gated call graphs. ~390× cleaner than CodeGraph on evaluated repo [S9].
  - No direct library API documented; MCP server designed for agent consumption.

- **Codebase-Memory** (Feb 25, 2026): Tree-sitter–based knowledge graph via MCP, parses 66 languages, parallel workers, impact analysis, community discovery. 900+ stars in 4 weeks [S10].
  - MCP-only; not a library.

**Verdict**: New tools prioritize **MCP/agent interfaces** over library APIs. No traditional call-graph library emerged 2024–2026.

### 5. In-House via AST + Type Info

**Feasibility & hard problems** [S11][S12]:

- **ast.Call resolution**: Resolvable in principle (walk ast.Call nodes, infer receiver type from annotations), but **dynamic dispatch, decorators, and higher-order functions make this intractable without runtime info** [S11].
- **Jedi for name resolution**: Jedi provides `get_references()` and `goto()` for IDE use; these resolve names via import graph + scope analysis [S12].
  - `get_references()`: "Lists all references of a variable in a project. Since this can be quite hard to do for Jedi, if it is too complicated, Jedi will stop searching" [S12].
  - Designed for editor integration, not batch call-graph analysis.
- **Griffe**: Python tool for extracting signatures and structure; supports decorators but **not call-graph generation** [S13].
- **Verdict**: Jedi + manual AST walking viable for **name-to-definition resolution on annotated code**, but call-graph completeness requires heuristics. No off-the-shelf solution for dynamic dispatch.

### 6. Architecture-Smell Detection (Feature-Envy, Law-of-Demeter)

**Current coverage across linters**:

- **Pylint** (v4.0+): Design checker (McCabe plugin) covers **complexity metrics only** (too many arguments, too many branches). No feature-envy or law-of-demeter detection [S14].
- **Ruff** (2026): 900+ built-in rules; **no explicit architecture-smell rules documented** [S15]. Focus: correctness, style, import sorting.
- **SonarQube (Python)**: **Explicitly detects "Couplers"** — inappropriate intimacy and feature-envy violations [S16].
  - Available on SonarQube Cloud (not Community Edition); supports Python alongside Java, JS, TS, C#.
  - Defines feature-envy as "function frequently interacts with data/functions in other modules, violating Law of Demeter" [S16].
  - Architecture management (visualize component dependencies, flag rule violations) **available on Cloud only** [S16].

**Verdict**: **SonarQube is the only off-the-shelf tool** with explicit feature-envy/law-of-demeter rules; available on Cloud tier. Pylint and Ruff do not offer these checks.

## Open Questions

- Can Pyrefly's type engine be exposed as a library for call-graph export? (GitHub issue search suggests "not on roadmap")
- Does pyan3's output handle async/await and type-stubs correctly? (No public test suite on these features found)
- What precision/recall trade-off does Tree-Sitter-Analyzer accept vs. PyCG? (Tool is new; no published evaluation)
- Can SonarQube's Couplers rules be tuned or run locally without Cloud licensing? (Not documented in public resources)

## Sources

- [S1] [Pyrefly — pyrefly.org](https://pyrefly.org/) — accessed 2026-07-18
- [S2] [IDE Supported Features | Pyrefly](https://pyrefly.org/en/docs/IDE-features/) — 2026-05
- [S3] [Pyrefly LSP Integration with Type Engine in PyCharm 2026.1.2 — JetBrains Blog](https://blog.jetbrains.com/pycharm/2026/05/pyrefly-lsp-integration-in-pycharm-2026-1-2/) — 2026-05
- [S4] [facebook/pyrefly — GitHub](https://github.com/facebook/pyrefly) — accessed 2026-07-18
- [S5] [Technologicat/pyan — GitHub](https://github.com/Technologicat/pyan) — main repo, tested 3.10–3.14
- [S6] [pyan3 — PyPI](https://pypi.org/project/pyan3/)
- [S7] [vitsalis/PyCG — GitHub](https://github.com/vitsalis/PyCG) — archived notice
- [S8] [PyCG: Practical Call Graph Generation in Python — arXiv:2103.00587](https://arxiv.org/pdf/2103.00587)
- [S9] [aimasteracc/tree-sitter-analyzer — GitHub](https://github.com/aimasteracc/tree-sitter-analyzer) — 2026-05-24 patch notes
- [S10] [Codebase-Memory: Tree-Sitter-Based Knowledge Graphs — arXiv:2603.27277](https://arxiv.org/html/2603.27277v1) — Feb 25, 2026 release, 900+ stars in 4 weeks
- [S11] [The Power of Dynamic Method Dispatch in Python — llego.dev](https://llego.dev/posts/power-dynamic-method-dispatch-python/)
- [S12] [API Overview — Jedi 0.20.0 documentation](https://jedi.readthedocs.io/en/latest/docs/api.html)
- [S13] [Griffe — mkdocstrings](https://mkdocstrings.github.io/griffe/)
- [S14] [Optional checkers — Pylint 4.1.0-dev0 documentation](https://pylint.pycqa.org/en/latest/user_guide/checkers/extensions.html)
- [S15] [Ruff — astral-sh/ruff](https://github.com/astral-sh/ruff) — GitHub discussion #20699: architecture-smell tools operate in "necessary, but isolated, silos"
- [S16] [Understanding Code Smells & SonarQube Architecture Management — Sonar](https://www.sonarsource.com/resources/library/code-smells/) and [SonarQube Architecture Management — Sonar blog](https://www.sonarsource.com/blog/sonarqube-architecture-management-keeps-agent-generated-code-sound/)
