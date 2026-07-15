# Rule inventory — general vs specific, defined before vs after the scaffold

Every gate is made of parts that live at different points on two axes:

- **General ↔ Specific** — does the rule hold for *any* project (a universal predicate), or is it a *fact
  about this codebase* (a name, an edge, a domain number)?
- **When is it defined** — three moments:
  - **Authored** (*before* the scaffold): baked into the template, byte-identical for every repo (the o70
    UNION law — RULES never vary per repo).
  - **Generated** (*at* `copier copy`): a per-project answer, frozen into the generated files.
  - **Evolved** (*after* generation): the consumer edits a LOCAL-SLOT.

The load-bearing finding: **RULES are always General + Authored. Only thresholds and vocabulary move.** And
a threshold is either **legislated** (a decided value) or the metric stays **advisory** — never seeded from
a repo's current state. See [the decide-or-advisory rule](#the-decide-or-advisory-rule) below.

## The 2×2

| | **Authored** (before) | **Generated / Evolved** (after) |
|---|---|---|
| **General** (universal) | the RULES + decided absolutes (cycles, god-file, dead-code, CC≤10, select codes, line-length) | — *(a universal rule never becomes per-project)* |
| **Specific** (project fact) | *seeds* only (kernel-independence starter, ml naming vocab, deptry starter-ignore) | **answers** (packages, coverage %, scan scopes) · **vocab slots** (layers, aliases, FP allowlists) |

The top-right is empty on purpose: a universal predicate is never redefined per project. Everything that
varies is either a **fact asked at generation** or a **fact filled after** — never a rule, never a number
measured from the code.

## Full inventory

### Universal predicates — General · Authored · no project number to pick
The house bar. Byte-identical across repos (o70 union); shipped enforced (or advisory where noted), clean on
a fresh gen.

| rule | gate | enforced? | knob? |
|---|---|---|---|
| formatting / import order / naming case | ruff `format` / `I` / `N` | yes | none |
| lint code SET (`F,B,S,C901,PLR…`) | ruff `--select` (`ruff_select`, authored union) | yes | none — the set never varies (a per-repo rule slot = o70 dodge, rejected) |
| no import cycle | `graph.py --assert` | yes | none (0 is universal) |
| no god-module (high `Ca` **and** `Ce`) | `graph.py` | yes | degree is decided ↓ |
| no god-file | `graph.py` | yes | line ceiling is decided ↓ |
| every logic module has a test | `graph.py` test-mirror | yes | `test_layout` mode (authored) |
| helpers in a class, no import-time side effects | ast-grep `sg-rules` | yes | none |
| no dead code | vulture | yes | confidence is decided ↓ |
| complexity under the ceiling | ruff `C901`/`PLR09xx` | yes | CC 10 is decided ↓ |
| no undeclared / unused / transitive dep | deptry | yes | starter-ignore ↓ |
| public array/tensor boundary is shape-typed (ml) | `shape_contracts --assert` | yes (binary rule) | aliases ↓ |
| directional layer contracts | import-linter | yes | contracts ↓ |
| tested to a floor | coverage | yes | % is an answer ↓ |
| no known CVE | pip-audit (nightly) | yes (off the PR path) | none (external advisory DB) |
| recurring magic literals | `magic_literals` | **advisory** | none — no honest universal ceiling |
| cyclomatic-complexity ranking | `complexity` (radon) | **advisory** | none — ruff C901 is the gate |
| cohesion / data-clumps / namespace-state | `lcom` / `data_clumps` / `state_candidates` | **advisory** | none |
| tiered architecture diagrams | `archmap` (grimp → mermaid) | **advisory / doc-gen** | none — nodes/edges derived from `packages`, nothing to legislate |

### Decided absolutes — General-normative · Authored default · Evolved-tunable
Numbers that encode a **human ceiling** (what's humane to read / hold), not a measurement. Legislated, not
measured — deriving them from a bad repo would ratify the mess.

| threshold | default | where |
|---|---|---|
| ruff line-length | 120 | `[tool.ruff]` |
| vulture confidence | 80 enforced / 60 advisory | `[tool.vulture]` |
| god-module degree | 8 | `[tool.structure]` slot |
| god-file lines | 750 | `[tool.structure]` slot |
| chokepoint betweenness | 0.10 (advisory) | `[tool.structure]` slot |
| cyclomatic complexity | 10 (ruff C901) | `ruff_select` |
| duplication | jscpd threshold | package `jscpd.json` |
| magic recurrence trigger | 4× (report-only) | authored in `magic_literals.py` |
| coverage target | 95 (advisory) | ci/nox |

### Advisory-only metrics — General · Authored · no number to legislate yet
Signals with **no honest universal threshold**, so they report and the reviewer decides. Never a gate,
never a config knob — a legislated knob is added on real need, not speculatively.

| metric | why advisory |
|---|---|
| recurring magic literals | some recurrence is legit vocab (0 too strict), any budget N is arbitrary |
| radon cyclomatic complexity | ruff `C901=10` is already the fixed gate; radon just ranks below it |
| LCOM / data-clumps / namespace-state | heuristic refactor candidates, not defects |
| architecture diagrams (`archmap`) | doc-gen, not a metric — visualizes the import graph as tiered mermaid; `--check` only asserts the committed docs match the graph (staleness), never judges the structure. Enforcement is import-linter's job |

### Project answers — Specific · Generated at `copier` · frozen
Facts asked once and baked into the generated files (survive `copier update` via `.copier-answers.yml`).

| answer | what it fixes |
|---|---|
| `project_name` | name / LICENSE / data-env derivation |
| `packages` | the architected set every arch gate scans |
| `domain` (`enable_ml`) | ml bundle: numpy/jaxtyping deps, shape gate wiring, naming vocab, doc layers |
| `coverage_floor` | the enforced coverage % |
| `lint_paths` / `jscpd_paths` | R1-hygiene scan scope (widenable past the arch set) |
| `data_env_var` | the ml data-skip env name |
| `author` | LICENSE copyright |

### Project vocabulary — Specific · Evolved · LOCAL-SLOTs
The irreducible facts about *this* codebase. Can't be derived — they're inputs. The consumer fills them;
`copier update` never overwrites a slot.

| slot | the fact |
|---|---|
| `import-contracts` | which package imports which (directional layering) |
| `pep8-naming` ignore-names | this repo's allowed idioms (`X*`, MRI `T1/T2`) |
| `vulture-ignore-names` | documented dead-code false positives (framework dispatch) |
| `shape-aliases` | type names that mean "an array" (`Volume`, `Mask`) |
| `deptry-unused` | shipped starters ignored until wired (prune as used) |
| `arch-thresholds` | per-repo overrides of the decided absolutes |
| `vulture-scan` / `coverage-scan` / `ruff-exclude` | per-gate scope |
| `ci-lint-steps` / `ci-test-steps` | repo-only extra CI steps |

## The decide-or-advisory rule

A metric that isn't a universal `0` (cycles, dead code) needs a threshold to become a gate. That threshold
is **legislated or the metric stays advisory** — it is *never* seeded from the repo's current value.

- **Legislate an absolute** when the number is a **cognitive ceiling** independent of the codebase — file
  size, complexity, coupling degree. "A reviewer can hold ~750 lines / CC 10" is a *value*, not a
  measurement. A repo above it is broken and must show red.
- **Stay advisory** when there is no honest universal number — recurring magic literals (some recurrence is
  legit, any budget is arbitrary), heuristic smells. Report; let the reviewer decide. If a specific repo
  later needs enforcement, it adds a legislated knob *then* — a knob on real need, not speculatively.

**Never measure the threshold from current state.** Freezing a repo's current worst as the ceiling ratifies
the mess (deriving `file_max` from a 5326-line monster enshrines the monster) — it only forbids getting
*worse* and never forces getting *better*. Legislate the bar, or leave the metric advisory.

## Where this leaves the design

- **General + Authored is the spine** — universal rules, byte-identical, zero per-project burden. This is
  where the scaffold beats an ArchUnit-style tool (which pushes *every* rule onto the user).
- **Specific facts are pushed to the edge** — answers (frozen at gen) + slots (evolved after). Small,
  explicit, and the *only* thing a consumer owns.
- **Thresholds are legislated or absent** — a decided human ceiling, or an advisory report. No number is
  ever measured from the code it judges.
