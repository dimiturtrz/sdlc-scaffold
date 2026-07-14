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

- **Mechanical, not advisory.** A rule a human has to remember is a rule that erodes under deadline. Every
  property below is checked by a tool, and a violation is a red build — the reviewer is freed to think about
  design, not police conventions.
- **Ratcheted.** A check starts advisory, and the moment the code is clean on that axis it graduates to
  blocking; from then on any regression fails. You *fix* the finding, never suppress it — suppressions stay
  minimal and meaningful (a bare `# noqa: RULE`, never a blanket ignore). The bar only moves one way.
- **Guardrails, not architecture.** The scaffold imposes no particular layering or package shape. It targets
  whatever packages you declare and checks *universal* structural health (cycles, cohesion, dead code,
  duplication). The one directional rule it can express — who may import whom — is opt-in and project-owned.

Each check owns an **axis the others structurally cannot see**. That is the point of running many small
tools instead of one: a linter reading a single file can't see an import cycle; a cycle-checker can't see a
one-way forbidden dependency; none of them can see a class whose methods split into two unrelated halves, or
a string literal that has quietly become domain vocabulary. Coverage is the union.

## The axes

Two kinds of engine. **Vendored** tools are pinned third-party binaries. **Ours** are small AST/graph
analyzers shipped as source under `devtools/` and unit-tested in `tests/unit/` — the guardrails have their
own guardrails, so a broken check can't pass silently.

| Axis | Engine | Catches what nothing else can |
|---|---|---|
| Style + likely bugs | ruff *(vendored)* | unused/undefined names, magic numbers, blind excepts, high complexity, imports-not-at-top, keyword-only bools |
| Dead code | vulture *(vendored)* | unreachable functions/attrs a reader would never notice — the axis coverage masks when a test is the only caller |
| Test presence + coverage | pytest-cov *(vendored)* | logic that ships with no test exercising it, below a declared floor |
| Structural architecture | `graph.py --assert` *(ours)* | import **cycles**, **god-modules** (high fan-in *and* fan-out), **god-files**, and **missing test mirrors** — metric properties of the whole import graph |
| Directional layering | import-linter *(vendored)* | a one-way *forbidden* import (`kernel → trainer`) — legal as a graph (no cycle), illegal as architecture |
| Module shape | ast-grep *(vendored + our rules)* | syntactic house rules a linter has no plugin for: behaviour lives in a class, no import-time side effects |
| Duplication | jscpd *(vendored)* | copy-paste beyond a DRY threshold — the axis coupling tools don't measure |
| Class cohesion / coupling | lcom · data_clumps · state_candidates *(ours)* | a class that is really two classes fused (disjoint-state method groups), parameter sets that always travel together, namespaces with latent shared state |
| Vocabulary drift | magic_literals *(ours)* | an identifier-shaped string repeated across files (a `StrEnum` in hiding) or a dict key-set built in many places (an implicit record) — the non-comparison, cross-file context a magic-value linter can't reach |

Structural and cohesion/vocabulary checks are **advisory explorers** where the honest threshold is a
judgment call (cohesion, duplication ranking, literal frequency) and **blocking** where it is not (cycles,
god-files). Advisory checks ratchet to blocking per project as the code earns it.

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
