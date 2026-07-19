# sdlc-scaffold

**v1.20** — the guardrails now reach **below the import graph**. An import edge is the coarse OR of every
reason one module needs another; it decomposes into typed class-level arrows (`inherits`, `holds`,
`references`, `calls`, `construct`) that say *what kind* of dependency it is, which is what lets a rule
forbid one kind of coupling without forbidding the file. That graph backs new gates — Law of Demeter,
composition-cycle, feature-envy, directional use-contracts — and an interactive
[architecture viewer](https://dimiturtrz.github.io/sdlc-scaffold/) that folds from packages down to methods.

The analyzers ship as a **pinned package** (`sdlc-devtools`), not vendored source: an engine update is a
one-line pin bump on `copier update`, with no analyzer diff in consumer PRs. In use by three converged repos.

**Self-gating, precisely:** the package runs the same gate set it ships — ruff, format, vulture, deptry,
pyrefly strict, jscpd, ast-grep, coverage, and every analyzer — against its own source, and blocks on all of
them but one. Class-roles is advisory *there* for the same measured reason it is advisory anywhere: it still
fires on genuine multi-abstraction files, which is refactoring work rather than a classifier bug. It blocks
once a real tree reaches zero, which is how pyrefly strict graduated — it opened at 52 errors on this
package and now sits at 0. That is a ratchet with the work counted, not an exemption; an absent gate is the
thing this project treats as a bug, because a gate that does not run is indistinguishable from a clean
codebase.

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
- **Graduated, never suppressed.** A check starts advisory, and the moment the code is clean on that axis it
  graduates to blocking; from then on any regression fails. You *fix* the finding, never suppress it —
  suppressions stay minimal and meaningful (a bare `# noqa: RULE`, never a blanket ignore). Thresholds are
  *legislated* (a decided value — file_max 750, CC 10), never seeded from a repo's current mess.
- **Guardrails, not architecture.** The scaffold imposes no particular layering or package shape. It targets
  whatever packages you declare and checks *universal* structural health. The one directional rule it can
  express — who may import whom — is opt-in and project-owned.

## The guardrail pyramid

The test pyramid organizes tests by **scope** — unit → integration → e2e, many-cheap → few-expensive.
Structural guardrails stratify the same way, by **radius of analysis** = the minimum code a check must READ
to fire (R1 unit / R2 module / R3 system — the structural mirror of the test pyramid's unit→integration→e2e).
Each tier sees things the tiers below it structurally cannot, and the gradient tracks cost-to-fix and
blast-radius — a magic number is a local nit; an import cycle is architectural debt.

```
        ┌────────────────────────────────────────────────────┐
  R3    │  ACROSS THE SYSTEM GRAPH    (whole corpus)          │
 system │  Structure  — cycles · fan-in/out · layering ·      │
        │               test-mirror (Correctness) · god-file · │
        │               data clumps                            │
        │  Minimality — cross-file dup · vocab drift · dead    │
        ├────────────────────────────────────────────────────┤
  R2    │  WITHIN A MODULE / CLASS    (one file, self-cont.)  │
 module │  Structure  — LCOM cohesion · latent shared state ·  │
        │               class roles (one subject / file)       │
        ├────────────────────────────────────────────────────┤
  R1    │  WITHIN A LINE / FUNCTION   (one construct)         │
  unit  │  Correctness — real-bug lints · types · shapes      │
        │  Structure   — cyclomatic complexity · demeter depth │
        │  Minimality  — magic values                         │
        │  Consistency — style / naming                       │
        └────────────────────────────────────────────────────┘
   ⟂  Security      (supply-chain): ruff S unsafe-construct · pip-audit known-CVE
   ⟂  Completeness  (math: all required subcases) — ABSENT, no requirements spec; coverage floors
                    test presence under Correctness, not requirement-completeness
```

Running many small checks instead of one is the point: a linter reading a single line can't see an import
cycle; a cycle-checker can't see a one-way forbidden dependency; neither sees a class whose methods split
into two unrelated halves. Coverage of the code's *health* is the union of the tiers — and the same property
often recurs at several radii (a duplicated fact is a Minimality failure whether it's two lines or two files).

## The properties — and the tools that enforce them

The checks decompose into **four structural properties** (plus an orthogonal **Security** axis) — the *what
is protected*. The honest test that each is distinct: a distinct **kind of defect** it defends. Two are the
behaviour-preserving-cleanup pair, split by *remove vs reshape*: **Minimality** = economy (how *much* code —
delete dead, dedupe) and **Structure** = shape (how it's *arranged* — split the over-complex, extract the
missing object, redirect a bad edge), the latter spanning intra-unit cohesion (LCOM) up to the module graph.
The
map to tools is many-to-many by design — a property abstracts over the tools that enforce it; some tools
serve two properties (a data clump is both a missing object and a duplication). Tools are **vendored**
(pinned third-party binaries) or **ours** — small AST/graph analyzers shipped as the `sdlc-devtools` package
and unit-tested alongside it, so a broken check can't pass silently.

| Property | Predicate — what it asserts | Fix | Tools | R |
|---|---|---|---|---|
| **Correctness** | no construct is provably broken (bad reference, swallowed error, wrong shape); every logic module carries a test, exercised to a coverage floor | *repair / test* | ruff `F/B/BLE` · `pyrefly` (strict types) · `shape_contracts` (ML) · test-mirror (`graph.py`) · coverage | R1, R3 |
| **Consistency** | one convention, no drift — formatting, import order, naming | *conform* | ruff `format`/`I`/`N`/`RUF` | R1 |
| **Minimality** | nothing that shouldn't exist — no dead code, no duplication (each fact one home) | *delete / dedupe* | vulture · jscpd · `magic_literals` · ruff `F401` · deptry (unused/undeclared) | R1, R3 |
| **Structure** | code is well-SHAPED at every radius — units right-sized + low-branching (not god-files), cohesive (one idea, no missing object), and the graph acyclic / directional / bounded-coupling / test-mirrored | *split / extract / redirect / flatten* | ruff `C901/PLR09xx` · `demeter` (reach-through) · god-file · `lcom` · `state_candidates` · `data_clumps` · `classes` (one subject/file) · `arrows` (inherits/holds/references) · `calls` (contract vs concrete) · `composition` (has-a cycles) · `envy` (method belongs elsewhere) · `contracts` (forbidden-USE) · ast-grep shape · `graph.py --assert` · import-linter · `archmap` (viz) | R1–R3 |
| **Security** (orthogonal) | no unsafe construct, no known-CVE dependency | *patch / pin* | ruff `S` · pip-audit | ⟂ |

Four structural properties, fixed by *repair/test, conform, delete/dedupe, split/extract/redirect*. The
vocabulary is a deliberate **bridge** between formal-methods terms (Correctness — Hoare; Consistency —
logic; Minimality — Occam / DRY) and the empirical design lineage (Structure — McCabe / Kolmogorov for
per-unit complexity, Constantine / LCOM for cohesion, Parnas / Martin for the graph). **Completeness** (the math sense: every required subcase
proven) is deliberately ABSENT — it needs a requirements spec this scaffold has no access to; coverage
enforces test *presence* + a floor (a Correctness verification layer), NOT requirement-completeness, and we
do not overclaim it. **Security** (unsafe construct + known-CVE dep) is orthogonal to the four structural
axes — same bucket as pip-audit's supply-chain scan. It doesn't claim a linter proves
theorems; it claims these are the *named properties* the checks defend. Each is **blocking** where the
threshold is objective (cycles, god-files, undefined names) and **advisory** where it's a judgment call
(cohesion ranking, duplication, literal frequency, format); advisory checks graduate to blocking once clean.
One property axis is **domain-gated**: an `ml` project also ships `shape_contracts` (an array/tensor
boundary on any function must carry a **jaxtyping** shape — a checked contract, not a silent assumption; make
it live at a call with a `@shapecheck` decorator) — meaningless off a tensor codebase, so a domain-neutral scaffold omits it.

**Prior art — and the moat.** Most axes here have mature equivalents, and the honest pitch says so: LCOM
cohesion ([`cohesion`](https://pypi.org/project/cohesion/), [ArchUnitPython](https://pypi.org/project/archunit/)),
Martin instability/main-sequence (Robert Martin; ArchUnitPython), import cycles + directional layers
([grimp](https://pypi.org/project/grimp/), [import-linter](https://pypi.org/project/import-linter/),
[tach](https://github.com/gauge-sh/tach)), complexity ([radon](https://pypi.org/project/radon/), ruff),
duplication/dead-code/CVE/dep-hygiene (jscpd, vulture, pip-audit, deptry — all vendored). What the survey
found *nowhere*: **cross-file magic-literal** detection, **data-clumps** and **namespace-state** detection,
**jaxtyping shape contracts**, the **test-mirror** gate, and **auto-derived + committed + interactive**
architecture (`archmap` — no surveyed tool does all three at once; ours splits a committed diffable
`graph.json` from a self-contained interactive viewer served as a staged GitHub Pages site (`/architecture/`
= main, `/preview/` = dev), filling the empty leg of that triangle). Full citation in
[`sdlc-devtools/README`](sdlc-devtools/README.md#prior-art--and-whats-actually-novel).

**Structure, in the standard coupling vocabulary.** In-arrows to a module are *afferent* coupling (`Ca`,
fan-in); out-arrows are *efferent* (`Ce`, fan-out). The scaffold enforces three structural sub-properties:
**direction** (import-linter — a kernel that imports nothing is maximally stable by construction),
**acyclicity** (no import cycles), and **degree** (a *god-module* is high `Ca` *and* high `Ce` — a hub both
widely depended-on and widely depending, the thing to split). `graph.py` computes `Ca`/`Ce` + betweenness on
the grimp import graph, plus Martin's *instability* `I = Ce/(Ce+Ca)` and *main-sequence distance*
`D = |A + I − 1|` (with abstractness `A` from the class AST) — reported for every module, and an **advisory**
gate a repo opts into (off by default: a concrete stable leaf legitimately sits at `D ≈ 1`, so there is no
honest universal threshold).

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

Five questions, asked once:

| question | default | effect |
|---|---|---|
| `project_name` | — | repo / folder name (kebab-case) |
| `packages` | `project_name` snake_cased | comma-list the guardrails target (`core,neuroscan,neuroviz`) |
| `domain` | `ml` | `ml` adds numpy + an ML-workflow gitignore (data-outside-repo/`paths.yaml`, MLflow, `runs/`) + a data-skip CI env; `none` = domain-neutral |
| `coverage_floor` | `80` | `coverage report --fail-under` |
| `author` | `project_name` | copyright holder for the generated MIT `LICENSE` |

Three more default from `packages`/name and are usually accepted with Enter — `lint_paths` / `jscpd_paths`
(widen the hygiene-lint scope to a viewer or tests tree) and `data_env_var` (the env var your ML data
adapters read, ml only). They're stored answers, so a non-default survives `copier update`.

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
uv sync --extra dev --extra devtools && nox -s gates   # fix whatever fires
```

**Update (both paths, identical).**
```bash
uvx copier update       # reads .copier-answers.yml, fetches the newest scaffold tag; commit the result
```
When a gate graduates (advisory → enforced) an update can go red on pre-existing code — that's the ratchet,
not a regression. [`docs/UPGRADING.md`](docs/UPGRADING.md) is the per-version migration recipe (e.g. the
v1.12 `SLF001` op-namespace fix), so you fix the code the intended way instead of carving the gate back out.

## What a generated project gets

- `pyproject.toml` — the portable ruff/vulture/coverage blocks + marked LOCAL-SLOT regions, and the
  `devtools` optional-dependency: the analyzers as a **pinned package** (`sdlc-devtools @ git+…@<tag>`), not
  vendored source. An engine improvement is a one-line pin bump (`devtools_ref`) on `copier update` — no
  analyzer source diff in your PRs. They still import as `devtools` (`python -m devtools.graph …`); the
  ast-grep/jscpd config ships inside the package and is located via `python -m devtools.config`.
- `noxfile.py` · `.pre-commit-config.yaml` · `.github/workflows/ci.yml` — the same gates bound to the local
  runner, the commit event, and the merge. Plus `.github/workflows/audit.yml` — a nightly pip-audit CVE scan
  (`nox -s audit` locally), the one gate on a schedule rather than per-PR (advisories change under you).
- `devtools/README.md` — a short project-local doc: how the gates are invoked here, the `@shapecheck`
  wiring (ML), and the import-linter contract guidance. No analyzer source lives here.
- `tests/{unit,integration,e2e}/`, `docs/`, `CLAUDE.md` / `AGENTS.md` — the skeleton. No package code, and
  no shipped tests (the analyzers are tested in their own package).

The scaffold's own CI generates real projects and runs every gate against them, including tests that prove
each gate *bites* on a planted violation — the guardrails guard themselves. See
[`docs/SPEC.md`](docs/SPEC.md) for the contract and the generated `devtools/README.md` for each tool.

## Developing this scaffold

Two products, one tree — the copier template (scaffold) and `sdlc-devtools/` (the analyzer package). Each
gates itself; the test suite is split by feedback speed (`slow` marker):

```bash
uv run --group dev pytest -m "not slow"          # QUICK (~0.4s): scaffold consistency + self-lint. The edit loop.
uv run --group dev pytest                          # FULL: also the slow e2e (generate real projects + run every gate).
cd sdlc-devtools && uvx nox                         # the analyzer PACKAGE's own standalone gate (lint + mirror tests).
```

The quick layer is scaffold meta-tests only; the slow layer generates projects with copier (~40s) and is
what CI / pre-push runs. The package gate is fully independent of the scaffold (extraction-ready, bd uo0) —
[`docs/SPLIT.md`](docs/SPLIT.md) is the checklist for lifting `sdlc-devtools/` into its own repo.
