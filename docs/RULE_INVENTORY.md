# Rule inventory — general vs specific, defined before vs after the scaffold

Every gate is made of parts that live at different points on two axes:

- **General ↔ Specific** — does the rule hold for *any* project (a universal predicate), or is it a *fact
  about this codebase* (a name, an edge, a domain number)?
- **When is it defined** — three moments:
  - **Authored** (*before* the scaffold): baked into the template, byte-identical for every repo (the o70
    UNION law — RULES never vary per repo).
  - **Generated** (*at* `copier copy`): a per-project answer, frozen into the generated files.
  - **Evolved** (*after* generation): the consumer edits a LOCAL-SLOT, or a ratchet grows as the repo does.

The load-bearing finding: **RULES are always General + Authored. Only thresholds and vocabulary move.** And
thresholds split by kind — see [the decide/derive rule](#the-decidederive-rule) below.

## The 2×2

| | **Authored** (before) | **Generated / Evolved** (after) |
|---|---|---|
| **General** (universal) | the RULES + decided absolutes (cycles, god-file, dead-code, CC≤10, select codes, line-length) | — *(a universal rule never becomes per-project)* |
| **Specific** (project fact) | *seeds* only (kernel-independence starter, ml naming vocab, deptry starter-ignore) | **answers** (packages, coverage %, scan scopes) · **vocab slots** (layers, aliases, FP allowlists) · **ratchet growth** (magic 0/0 →, complexity max) |

The top-right is empty on purpose: a universal predicate is never redefined per project. Everything that
varies is either a **fact asked at generation** or a **fact filled/derived after** — never a rule.

## Full inventory

### Universal predicates — General · Authored · no project number to pick
The house bar. Byte-identical across repos (o70 union); shipped enforced, clean on a fresh gen.

| rule | gate | knob? |
|---|---|---|
| formatting / import order / naming case | ruff `format` / `I` / `N` | none |
| lint code SET (`F,B,S,C901,PLR…`) | ruff `--select` (`ruff_select`, authored union) | none — the set never varies (a per-repo rule slot = o70 dodge, rejected) |
| no import cycle | `graph.py --assert` | none (0 is universal) |
| no god-module (high `Ca` **and** `Ce`) | `graph.py` | degree is decided ↓ |
| no god-file | `graph.py` | line ceiling is decided ↓ |
| every logic module has a test | `graph.py` test-mirror | `test_layout` mode (authored) |
| helpers in a class, no import-time side effects | ast-grep `sg-rules` | none |
| no dead code | vulture | confidence is decided ↓ |
| cohesion / data-clumps / namespace-state (advisory) | `lcom` / `data_clumps` / `state_candidates` | none |
| no undeclared / unused / transitive dep | deptry | starter-ignore ↓ |
| no known CVE | pip-audit | none (external advisory DB) |
| no new cross-file magic vocabulary | `magic_literals` | ceiling is ratcheted ↓ |
| public array/tensor boundary is shape-typed (ml) | `shape_contracts` | aliases ↓ |
| directional layer contracts | import-linter | contracts ↓ |
| tested to a floor | coverage | % is an answer ↓ |

### Decided absolutes — General-normative · Authored default · Evolved-tunable
Numbers that encode a **human ceiling** (what's humane to read / hold), not a measurement. Legislated, not
derived — deriving them from a bad repo would ratify the mess.

| threshold | default | where |
|---|---|---|
| ruff line-length | 120 | `[tool.ruff]` |
| vulture confidence | 80 enforced / 60 advisory | `[tool.vulture]` |
| god-module degree | 8 | `[tool.structure]` slot |
| god-file lines | 750 | `[tool.structure]` slot |
| chokepoint betweenness | 0.10 (advisory) | `[tool.structure]` slot |
| cyclomatic complexity | 10 (ruff C901) | `ruff_select` |
| duplication | jscpd threshold | package `jscpd.json` |
| magic recurrence trigger | 4× | authored in `magic_literals.py` |
| coverage target | 95 (advisory) | ci/nox |

### Derived ratchets — Specific-derived · Authored `0` · Evolved per-repo
Numbers whose target is **0 / monotone-toward-clean**, so freezing the current value is honest (it starts
clean and only grows with a reason). The only axes where *deriving* the threshold is correct.

| ratchet | fresh | grows how |
|---|---|---|
| magic strings / key-sets | `0 / 0` | migrate the literal to an enum, or raise the ceiling with a documented reason |
| complexity max CC | absent = advisory | opt-in: freeze current max to ratchet *below* the decided CC≤10 floor |

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
| `complexity-ceiling` | opt-in CC ratchet value |
| `vulture-scan` / `coverage-scan` / `ruff-exclude` | per-gate scope |
| `ci-lint-steps` / `ci-test-steps` | repo-only extra CI steps |

## The decide/derive rule

The split between *decided absolutes* and *derived ratchets* is the one judgment the inventory encodes:

- **Derive (ratchet)** only when the target is **0 or monotone-toward-0** and the current value is a
  *legit floor, not a debt* — magic-literals (fresh 0), cycles, dead code, coverage-up. Freezing current is
  honest because current ≈ clean.
- **Decide (legislate an absolute)** when the number is a **cognitive ceiling** independent of your mess —
  file size, complexity, coupling degree. "A reviewer can hold ~750 lines / CC 10" is a *value*, not a
  measurement. A repo above it is broken and must show red — exactly what a *derived* ceiling would hide
  (deriving `file_max` from a 5326-line monster ratifies the monster).

**Descriptive metrics can ratchet; normative ceilings must be legislated.** You legislate what's humane to
read; you can't measure your way to it from a codebase that already violated it.

## Where this leaves the design

- **General + Authored is the spine** — universal rules, byte-identical, zero per-project burden. This is
  where the scaffold beats an ArchUnit-style tool (which pushes *every* rule onto the user).
- **Specific facts are pushed to the edge** — answers (frozen at gen) + slots (evolved after). Small,
  explicit, and the *only* thing a consumer owns.
- **Thresholds are the subtle middle** — decided where normative, ratcheted where zero-target. Never a
  magic number without one of those two justifications.
