# SPEC — the scaffold contract

Single source of truth for the template's gate contract: exact names, values, and mechanics.
Derived from the 3 real repos (cardiac-seg / mindscape / synthscape), read-only reference.

## Design model

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

## copier.yml — toggles + EXACT var names (freeze)

Asked at copy time:

| var | type | default | meaning |
|---|---|---|---|
| `project_name` | str | (ask) | repo/folder name, kebab-case (e.g. `sample-proj`) |
| `packages` | str | `project_name` snake_cased | comma-list of packages the guardrails target (e.g. `core,neuroscan,neuroviz`) |
| `ship_example` | bool | true | ship the demo package (`math_ops`←`pipeline`) + its unit tests; false = guardrails-only adoption |
| `enforce_arch_fitness` | bool | true | ship `graph.py --assert` gate + `[tool.structure]` |
| `enable_astgrep` | bool | false | ship ast-grep module-shape gate + `devtools/sg-rules` + `sgconfig.yml` |
| `enable_jscpd` | bool | false | ship jscpd DRY gate + `devtools/jscpd.json` (advisory) |
| `enable_class_shape_smells` | bool | false | ship the LCOM4 / data-clumps / namespace-state advisory explorers |
| `coverage_floor` | int | 80 | `coverage report --fail-under` value |

Computed / never asked (`when: false`, one home in copier.yml):

| var | value | used for |
|---|---|---|
| `package_name` | `packages.split(',')[0]` | the demo package's folder name (simple interpolation) |
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
| 6 | ast-grep module-shape (`enable_astgrep`) | vendored ast-grep + our `sg-rules` | rule yml | scan paths = `packages` |
| 7 | jscpd DRY (`enable_jscpd`) | vendored jscpd | `jscpd.json` threshold | scan paths = `packages` |
| 8 | class-shape explorers (`enable_class_shape_smells`) | OURS lcom/data_clumps/state_candidates | (advisory, always exit 0) | scan paths = `packages` |

Directional layer contracts (import-linter) are **not** a shipped gate — opt-in, documented in the
generated `devtools/README.md`. `graph.py` covers the layer-agnostic structural axis (cycles included).

## PORTABLE SUPERSET VALUES

### ruff (`[tool.ruff]` + `[tool.ruff.lint]`)
```toml
line-length = 120
# select = ruff_select (copier.yml, single source) — curated-narrow, the cardiac/synth majority:
# specific codes, NOT broad families (deliberately excludes UP/SIM/C4 opinionated churn).
select = ["F","B","E501","I","T201","FBT","BLE001","S110","C901","PLR0912","PLR0913","PLR0915","PLR2004","PLC0415","RUF100"]
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
betweenness_max = 0.10   # advisory chokepoint threshold
```

## LOCAL-SLOT convention (the seam)

In `pyproject.toml.jinja`, every local-slot region is wrapped so `copier update` and humans see the
boundary; portable superset blocks carry NO marker (template owns them, regenerated on update):
```toml
# >>> LOCAL-SLOT: <name> — edit freely, the template will not overwrite intent here
... project-specific values ...
# <<< LOCAL-SLOT: <name>
```
Slots: `ruff-exclude`, `vulture-scan`, `coverage-scan`, `arch-thresholds`.

## Pinned tool versions (single-sourced in copier.yml, `when: false`)
- ruff `0.15.13` · vulture `2.16` · nox `2026.7.11` · pre-commit `4.6.0`
- ast-grep via `uvx --from ast-grep-cli ast-grep` (toggle) · jscpd via `npx --yes jscpd` (toggle)
- graph.py deps: `grimp`, `networkx` (project `devtools` extra)

## Example code shipped (when `ship_example=true`, so a fresh gen is green)

A minimal-but-real example under the FIRST package (`packages[0]`), with a genuine intra-package edge:
- `{packages[0]}/math_ops.py` — a leaf class (`mean`, `clamp`), imports nothing else.
- `{packages[0]}/pipeline.py` — a class importing `math_ops` (the internal edge graph.py chews).
- `tests/unit/test_math_ops.py` + `test_pipeline.py` — cover the above to satisfy `coverage_floor`.

`ship_example=false` omits the demo package + its unit tests (repo-adoption path). Anti-shortcut: gate
failures are fixed in the TEMPLATE example/config, then regenerate — never hand-patch generated output.

## Copier mechanics

- `_subdirectory: template` → only `template/` is rendered; scaffold-meta at repo root is never seen.
- `.jinja` files are Jinja-rendered and lose the suffix. Static files are copied verbatim — the
  `devtools/*.py` tools ship verbatim (they contain literal f-string braces `{{ }}`); do NOT add a
  `.jinja` suffix or unescaped `{{ }}` to them.
- **Conditional files/dirs: clean names + `_exclude`.** Template files have plain names; `copier.yml`
  `_exclude` carries jinja rules keyed on the toggles (`{% if not enable_astgrep %}devtools/sg-rules{% endif %}`)
  that render to `""` (a no-op) when the feature is on and to the path when off. NO `{% if %}` in filenames.
- **Variable folders** use pure interpolation (`{{ package_name }}/`), never a conditional expression.
- TOML + Jinja: `{{` collides. For literal braces in TOML use `{% raw %}` or `{{ "{{" }}`. Watch the
  coverage regex and any f-string-like content.
