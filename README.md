# sdlc-scaffold

A [copier](https://copier.readthedocs.io) template that installs a codebase's **structural guardrails** —
a set of executable checks that keep the code within stated architectural bounds as it grows, enforced
identically at commit, locally, and in CI. It ships the guardrails, not a program: no application code, no
imposed layering — just the standing rules and the machinery to run them.

## Why — architecture as a fitness function

Code quality stated in a style guide rots; code quality expressed as a **check that fails the build** does
not. Each guardrail here is an *architecture fitness function*: an automated test whose subject is a
structural property of the system — no import cycles, no god-modules, every logic module has a test — rather
than a runtime behaviour. (The term is from *Building Evolutionary Architectures*, Ford / Parsons / Kua.)
The design rests on three commitments:

- **Mechanical, not advisory.** A rule a human has to remember erodes under deadline. Every property below is
  checked by a tool; a violation is a red build — the reviewer is freed to think about design, not police
  conventions.
- **Ratcheted.** A check starts advisory, and the moment the code is clean on that axis it graduates to
  blocking; from then on any regression fails. You *fix* the finding, never suppress it — suppressions stay
  minimal and meaningful (a bare `# noqa: RULE`, never a blanket ignore). The bar only moves one way.
- **Guardrails, not architecture.** The scaffold imposes no particular layering or package shape. It targets
  whatever packages you declare and checks *universal* structural health. The one directional rule it can
  express — who may import whom — is opt-in and project-owned.

## The guardrail pyramid

The test pyramid organizes tests by **scope** — unit → integration → e2e, many-cheap → few-expensive.
Structural guardrails stratify the same way, by **radius of analysis**: how much code a check must read to
fire. Each tier sees things the tiers below it structurally cannot, and the gradient tracks cost-to-fix and
blast-radius — a magic number is a local nit; an import cycle is architectural debt.

```
        ┌────────────────────────────────────────────────────┐
  R3    │  ACROSS THE MODULE GRAPH    (whole corpus)          │
 graph  │  Structure  — cycles · fan-in/out · layering ·      │
        │               test tree mirrors source              │
        │  Minimality — cross-file duplication · vocab drift   │
        ├────────────────────────────────────────────────────┤
  R2    │  WITHIN A MODULE / CLASS    (one file)              │
 module │  Cohesion   — LCOM · latent state · data clumps     │
        │  Simplicity — god-file       Minimality — dead code │
        ├────────────────────────────────────────────────────┤
  R1    │  WITHIN A LINE / FUNCTION   (one construct)         │
  line  │  Correctness — real-bug lints   Simplicity — cyclo. │
        │  Minimality  — magic values     Consistency — style │
        └────────────────────────────────────────────────────┘
   ⟂  Completeness  (behavioural, not spatial): coverage floor — is the behaviour exercised at all?
```

Running many small checks instead of one is the point: a linter reading a single line can't see an import
cycle; a cycle-checker can't see a one-way forbidden dependency; neither sees a class whose methods split
into two unrelated halves. Coverage of the code's *health* is the union of the tiers — and the same property
often recurs at several radii (a duplicated fact is a Minimality failure whether it's two lines or two files).

## The properties — and the tools that enforce them

The checks decompose into **seven properties** — the *what is protected*. The honest test that each is
distinct: each has its own **remediation verb** (if two properties are fixed the same way, they're one). The
map to tools is many-to-many by design — a property abstracts over the tools that enforce it; some tools
serve two properties (a data clump is both a missing object and a duplication). Tools are **vendored**
(pinned third-party binaries) or **ours** — small AST/graph analyzers shipped as source under `devtools/`
and unit-tested in `tests/unit/`, so a broken check can't pass silently.

| Property | Predicate — what it asserts | Fix | Tools | R |
|---|---|---|---|---|
| **Correctness** | no line does the wrong thing, swallows an error, or is unreachable-as-a-bug | *repair* | ruff `F/B/BLE/S` · vulture | R1 |
| **Consistency** | one convention, no drift — formatting, import order, naming | *conform* | ruff `format`/`I`/`N`/`RUF` | R1 |
| **Minimality** | nothing dead, nothing duplicated — each fact in exactly one home | *delete / dedupe* | vulture · jscpd · `magic_literals` · ruff `F401` | R1–R3 |
| **Simplicity** | each unit small + low-branching enough to hold in the head | *split / flatten* | ruff `C901/PLR09xx` · god-file (`graph.py`) | R1–R2 |
| **Cohesion** | a unit is one idea — no hidden missing abstraction | *extract an object* | `lcom` · `state_candidates` · `data_clumps` · ast-grep shape | R2 |
| **Structure** | the module graph is well-formed: acyclic, directional, bounded coupling, tests mirror source | *redirect / break edges* | `graph.py --assert` · import-linter | R3 |
| **Completeness** | behaviour is exercised to a stated floor | *add tests* | coverage | ⟂ |

Seven predicates, seven distinct fixes — *repair, conform, delete, split, extract, redirect, test*. The
vocabulary is a deliberate **bridge** between formal-methods terms (Correctness — Hoare; Completeness &
Consistency — logic; Minimality — Occam / DRY; Simplicity — McCabe / Kolmogorov) and the empirical
design lineage (Cohesion — Constantine, LCOM; Structure — Parnas, Martin). It doesn't claim a linter proves
theorems; it claims these are the *named properties* the checks defend. Each is **blocking** where the
threshold is objective (cycles, god-files, undefined names) and **advisory** where it's a judgment call
(cohesion ranking, duplication, literal frequency, format); advisory checks ratchet to blocking per project.

**Structure, in the standard coupling vocabulary.** In-arrows to a module are *afferent* coupling (`Ca`,
fan-in); out-arrows are *efferent* (`Ce`, fan-out). The scaffold enforces three structural sub-properties:
**direction** (import-linter — a kernel that imports nothing is maximally stable by construction),
**acyclicity** (no import cycles), and **degree** (a *god-module* is high `Ca` *and* high `Ce` — a hub both
widely depended-on and widely depending, the thing to split). `graph.py` computes `Ca`/`Ce` + betweenness on
the grimp import graph. (Martin's *instability* `I = Ce/(Ce+Ca)` and main-sequence distance sharpen this
further — a planned addition, since the raw counts are already in hand.)

## How the config travels

A gate is *engine + parameters + invocation*. Parameters split three ways, and that split is what lets one
template serve many repos without fighting them:

- **Portable superset** — house style that is the same everywhere (the ruff rule set, coverage exclusions).
  Template-owned; regenerated on update.
- **Local slot** — genuine per-project facts (scan paths, thresholds, the naming vocabulary a repo allows).
  Marked `# >>> LOCAL-SLOT` and never overwritten.
- **Answer** — asked once at copy time, recorded in `.copier-answers.yml`, replayed on update.

The scaffold advances by **git tags**, and a project pulls improvements with `copier update`: a 3-way merge
flows new portable rules in, keeps your local-slot edits, and lands real conflicts as `.rej` — one
reviewable rollout step per tag. Drift between the template and a repo is a thing to *heal*, not a steady
state. The full contract (exact rule values, the superset-vs-slot boundary) lives in
[`docs/SPEC.md`](docs/SPEC.md).

## Using it

Four questions, asked once:

| question | default | effect |
|---|---|---|
| `project_name` | — | repo / folder name (kebab-case) |
| `packages` | `project_name` snake_cased | comma-list the guardrails target (`core,neuroscan,neuroviz`) |
| `domain` | `ml` | `ml` adds numpy + an ML-workflow gitignore (data-outside-repo/`paths.yaml`, MLflow, `runs/`) + a data-skip CI env; `none` = domain-neutral |
| `coverage_floor` | `80` | `coverage report --fail-under` |

Every gate is on from the first generation — there are no feature toggles. import-linter is the sole
self-gating one (it needs >1 package to have anything to forbid).

**New project.** The template ships zero package code, so a fresh generation is empty — you bring the first
module.
```bash
uvx copier copy path/to/sdlc-scaffold ./my-project
cd my-project && git init && git add -A && git commit -m "scaffold"
uv sync --extra dev --extra devtools
# write your first module + its mirror test, then:
nox -s gates        # every gate, exactly as CI runs them
```

**Adopt into an existing repo.** copier conflict-prompts on files you already have; it lays down the gate
config + `devtools/` and never touches your source (it ships none).
```bash
cd existing-repo
uvx copier copy --data packages=core,neuroscan,neuroviz path/to/sdlc-scaffold .
uv sync --extra dev --extra devtools && nox -s gates   # fix or ratchet whatever fires
```

**Update (both paths, identical).**
```bash
uvx copier update       # reads .copier-answers.yml, fetches the newest scaffold tag; commit the result
```

## What a generated project gets

- `pyproject.toml` — the portable ruff/vulture/coverage blocks + marked LOCAL-SLOT regions.
- `noxfile.py` · `.pre-commit-config.yaml` · `.github/workflows/ci.yml` — the same gates bound to the local
  runner, the commit event, and the merge.
- `devtools/` — the analyzers (`graph.py`, the class-shape + magic-literal explorers, ast-grep rules, jscpd
  config, `omit.py`) with their own `README.md`.
- `tests/{unit,integration,e2e}/`, `docs/`, `CLAUDE.md` / `AGENTS.md` — the skeleton. No package code.

The scaffold's own CI generates real projects and runs every gate against them, including tests that prove
each gate *bites* on a planted violation — the guardrails guard themselves. See
[`docs/SPEC.md`](docs/SPEC.md) for the contract and the generated `devtools/README.md` for each tool.
