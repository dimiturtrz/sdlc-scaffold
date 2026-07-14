# SPEC — the scaffold contract

Single source of truth for the template's gate contract: exact names, values, and mechanics.
Derived from the 3 real repos (cardiac-seg / mindscape / synthscape), read-only reference.

## Design model

**What a gate defends.** Every gate protects one or more of **seven properties** — Correctness · Consistency
· Minimality · Simplicity · Cohesion · Structure · Completeness — each at a **radius** (R1 line / R2 module /
R3 graph, plus Completeness as the orthogonal behavioural axis). The property↔tool map is many-to-many. The
README owns that taxonomy (the *why*); this file owns the *what-exactly* (names, values, mechanics).

A **gate** = engine + parameters + invocation. Two axes decide delivery:
- **engine owner**: vendored (ruff/vulture/coverage/ast-grep/jscpd) → pinned version; ours
  (`graph.py`, the class-shape tools) → shipped code, unit-tested in `tests/unit/`.
- **param locality**: PORTABLE (house style, same everywhere → shared SUPERSET block, template-owned),
  LOCAL-SLOT (project facts: paths/source/thresholds → stays in repo, `# >>> LOCAL-SLOT` marked), or
  ANSWER (asked at copy time, recorded in `.copier-answers.yml`, replayed on update).

**Superset rule**: a portable param that is harmless-when-unused (ignore-lists, exclude-lines) is
shipped as the UNION of the 3 repos. Do NOT thin it to make a gate pass.

**Guardrails, not architecture**: the scaffold imposes NO layering. Gates target the `packages` the
project declares; directional layer contracts (import-linter) are opt-in, never shipped.

## copier.yml — prompt surface + EXACT var names (freeze)

Asked at copy time:

| var | type | default | meaning |
|---|---|---|---|
| `project_name` | str | (ask) | repo/folder name, kebab-case (e.g. `sample-proj`) |
| `packages` | str | `project_name` snake_cased | comma-list of packages the guardrails target (e.g. `core,neuroscan,neuroviz`) |
| `domain` | enum | `ml` | `ml` = numpy dep + ML-workflow gitignore (data/`paths.yaml`/MLflow/`runs/`) + data-skip CI env; `none` = domain-neutral |
| `coverage_floor` | int | 80 | `coverage report --fail-under` value |

That's the whole prompt surface. **The quality gates + beads are NON-optional (no toggles): arch-fitness,
import-linter, ast-grep, jscpd, class-shape, beads are always shipped** — the house bar (bd rji). Their
template blocks render unconditionally — the inert `{% if enable_X %}` guards were removed (bd 9nq); the
only in-file gating left is `use_import_linter` (import-linter self-gates on >1 package) and `enable_ml`
(domain). The **template ships ZERO package code** (bd r2w) — only guardrails; a fresh gen is empty, you
write the first module.

Domain: `domain=ml` (default) makes this an ML-project scaffold (numpy + data-outside-repo + MLflow).
`domain=none` = neutral Python guardrail scaffold. **Doc-layer convention** (documented in the generated
`CLAUDE.md`/`AGENTS.md`, not shipped as folders — no speculative dirs) is `domain=ml`-only in full:
`learning/<date>_<topic>.md` (study ramp), `research/` (external field synthesis), and
`interpretations/<task>/<date>_<topic>.md` (sense-making of *our own* results, `converging/` for cross-task) —
a study ramp presumes a field to study, so a neutral tool gets none of them, nor the `paths.yaml`/data-outside-repo
bullet. The ruff `extend-exclude` default gates all three to ml (only `docs` is always excluded). `pydantic`,
`docs/PLAN.md`+`ROADMAP.md` ship regardless (house conventions, a later trim).

Computed / never asked (`when: false`, one home in copier.yml): `enable_ml` (=`domain == 'ml'`),
`use_import_linter` (=`packages` has >1), plus:

| var | value | used for |
|---|---|---|
| `ruff_select` | narrow curated list (below) | rendered into pyproject/ci/nox/pre-commit + parsed by the E2E conftest |
| `ruff_version` / `vulture_version` / `nox_version` / `precommit_version` | pins (below) | single-sourced into ci/nox/pre-commit + conftest |

## Gate inventory

| # | gate | engine | portable params | local-slot / answer |
|---|---|---|---|---|
| 1 | ruff lint (enforced) | vendored ruff | `line-length`, `select` (=`ruff_select`), `ignore`, `per-file-ignores` | `extend-exclude` (slot) |
| 2 | ruff format --check (advisory) | vendored ruff | (never blocks) | — |
| 3 | vulture dead-code | vendored vulture | `min_confidence`, `ignore_decorators`, `ignore_names` core | `paths`, `exclude` (slot) |
| 4 | coverage floor | vendored coverage/pytest-cov | `exclude_lines`, `show_missing` | `source`, `omit` (slot); `fail-under`=`coverage_floor` (answer) |
| 5 | arch fitness | OURS `graph.py --assert` | (mechanism) | `[tool.structure]` thresholds (slot) |
| 5b | test-mirror (part of #5) | OURS `graph.py` `unmirrored()` + `omit.py` | `__init__`/`__main__` exempt | `[tool.coverage] omit` shells exempt |
| 6 | ast-grep module-shape | vendored ast-grep + our `sg-rules` | rule yml | scan paths = `packages` |
| 7 | jscpd DRY | vendored jscpd | `jscpd.json` threshold | scan paths = `packages` |
| 8 | class-shape explorers | OURS lcom/data_clumps/state_candidates | (advisory, always exit 0) | scan paths = `packages` |
| 9 | import-linter (self-gates on >1 pkg) | vendored import-linter | (mechanism) | `[tool.importlinter]` contracts (LOCAL-SLOT) |
| 10 | magic-literals (advisory; opt-in ratchet) | OURS `magic_literals.py` | `_STRING_THRESHOLD`/key-set mins | scan paths = `packages`; `--max-strings`/`--max-key-sets` ceilings a repo sets in its own CI |

import-linter is a shipped gate (all 3 house repos run it): it enforces DIRECTIONAL forbidden-import
contracts — a one-way `core -> trainer` import is no cycle, so it passes `graph.py` but must fail here.
The GATE is universal; the CONTRACTS are project-local (kernel-independence starter + slot). It is the ONE
gate that self-gates: shipped only when `packages` has >1 entry (nothing to forbid in a single package),
via the computed `use_import_linter`. Every other gate is unconditional (no toggle). jscpd is ENFORCED
(blocks over threshold) in ci+nox — the cardiac/mindscape majority — not a commit hook (Node).

## PORTABLE SUPERSET VALUES

### ruff (`[tool.ruff]` + `[tool.ruff.lint]`)
```toml
line-length = 120
# select = ruff_select (copier.yml, single source) — curated-narrow: specific codes, NOT broad families
# (excludes UP/C4 opinionated churn). SIM is IN — the 2/3 majority (cardiac-seg + mindscape) graduated it (bd 7g0).
select = ["F","B","E501","I","T201","FBT","BLE001","S110","C901","PLR0912","PLR0913","PLR0915","PLR2004","PLC0415","RUF100","SIM"]
ignore = ["RUF001","RUF002","RUF003"]    # intentional ≈ × unicode
[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]                 # re-export facades
"tests/**"    = ["PLR2004","FBT"]        # literal fixtures + bool flags fine in tests
```
`extend-exclude` is LOCAL-SLOT.

### vulture (`[tool.vulture]`)
```toml
min_confidence = 60
ignore_names = ["model_config"]          # + LOCAL-SLOT domain names per project
ignore_decorators = ["@model_validator","@field_validator","@field_serializer","@model_serializer","@computed_field"]
```
`paths`/`exclude` LOCAL-SLOT (rendered over `packages`).

### coverage (`[tool.coverage.report]`)
```toml
show_missing = true
exclude_lines = [
    "pragma: no cover", "if __name__ == .__main__.:", "if TYPE_CHECKING:",
    "raise NotImplementedError", "^\\s*\\.\\.\\.$", "@(abc\\.)?abstractmethod",
]
```
`[tool.coverage.run] source`/`omit` LOCAL-SLOT (rendered over `packages`). `fail-under` = `coverage_floor`.

### [tool.structure] defaults (graph.py reads these — LOCAL-SLOT so per-repo tuning survives update)
```toml
bottleneck_degree = 8    # fan-in AND fan-out both over this = god-module
file_max = 750           # god-file line ceiling
file_min = 0             # advisory line floor — 0 = OFF (no honest universal floor)
betweenness_max = 0.10   # advisory chokepoint threshold
test_layout = "mirror"   # test-existence layout: "mirror" (strict path-mirror) | "flat" (anywhere under tests/) | "off"
```

## LOCAL-SLOT convention (the seam)

In `pyproject.toml.jinja`, every local-slot region is wrapped so `copier update` and humans see the
boundary; portable superset blocks carry NO marker (template owns them, regenerated on update):
```toml
# >>> LOCAL-SLOT: <name> — edit freely, the template will not overwrite intent here
... project-specific values ...
# <<< LOCAL-SLOT: <name>
```
Slots: `ruff-exclude`, `vulture-scan`, `coverage-scan`, `arch-thresholds`, `import-contracts`.

### Per-gate scope (bd vip.3 — minimal forking, maximal-abstract identical set)

Real repos scan DIFFERENT package sets per gate (cardiac-seg: vulture + import-linter include `cardioview`;
coverage + ruff don't. mindscape: hygiene widens to a quarantined `baselines/`). Rather than a per-gate
`packages` map (prompt-surface + fork bloat), scope divergence rides **existing slots**, and the abstract
gate set stays identical:
- **arch (graph.py / ast-grep / jscpd) + ruff** scan `packages` — the owned/architected set, via CLI. Not
  slotted: widening these beyond `packages` is intentionally NOT templated (a repo conforms, it doesn't fork
  — cardiac-seg lints its arch set, not its quarantined baselines).
- **vulture** is config-driven — `[tool.vulture] paths` (the `vulture-scan` slot); NO CLI package args in
  nox/CI/pre-commit. A repo widens the dead-code scan there.
- **coverage** — `[tool.coverage.run] source` (the `coverage-scan` slot).
- **import-linter** — `root_packages` lives inside the `import-contracts` slot (layering scope is repo-owned;
  a viewer with layer rules but outside the arch set is added there).

Result: a repo overrides at most ONE slot per divergent gate; a conforming repo (synthscape) renders
identically (every scope = `packages`). No new questions, no new slots.

## Pinned tool versions (single-sourced in copier.yml, `when: false`)
- ruff `0.15.13` · vulture `2.16` · nox `2026.7.11` · pre-commit `4.6.0`
- ast-grep via `uvx --from ast-grep-cli ast-grep` · jscpd via `npx --yes jscpd` (both always shipped)
- graph.py deps: `grimp`, `networkx` (project `devtools` extra)

## No example code shipped — the template ships ZERO package code (bd r2w)

A fresh generation has an empty `tests/unit/` and no package source — only the gate config + `devtools/`.
A brand-new project has nothing to lint/cover yet; you write the first module + its mirror test, then the
gates go green (never weakened for the empty case — you bring the first module).

The demo the gates need to be exercised is OWNED BY THE E2E, not the template: `tests/e2e/conftest.py`
`seed_example()` injects an astgrep-compliant leaf class (`{pkg}/math_ops.py`) + an intra-package edge
(`{pkg}/pipeline.py`, the edge graph.py chews) + strict-mirror unit tests into a generated project before
running the gates. That keeps the template code-less while still proving every gate bites on real code.

Anti-shortcut: gate failures are fixed in the TEMPLATE config (or the e2e seed), then regenerate — never
hand-patch generated output.

## Copier mechanics

- `_subdirectory: template` → only `template/` is rendered; scaffold-meta at repo root is never seen.
- `.jinja` files are Jinja-rendered and lose the suffix. Static files are copied verbatim — the
  `devtools/*.py` tools ship verbatim (they contain literal f-string braces `{{ }}`); do NOT add a
  `.jinja` suffix or unescaped `{{ }}` to them.
- **No conditional files/dirs.** Every gate is always shipped, so nothing is excluded by feature: `_exclude`
  is just the housekeeping list (`.git`/`.venv`/`__pycache__`/`*.pyc`). NO `{% if %}` in filenames. (In-file
  gating survives only for `use_import_linter` and `enable_ml`, as `{% if %}` blocks inside a file, never
  as a file/dir name.)
- **No variable folders.** The template ships zero package code, so there is no `{{ package_name }}/` dir —
  the generated `tests/unit/` is empty and the consumer creates package dirs themselves.
- TOML + Jinja: `{{` collides. For literal braces in TOML use `{% raw %}` or `{{ "{{" }}`. Watch the
  coverage regex and any f-string-like content.
