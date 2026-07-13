# SPEC — the scaffold contract

Single source of truth for every subagent authoring template files. Freeze names + values here.
Derived from the 3 real repos (cardiac-seg / mindscape / synthscape), read-only reference.

## Design model (recap)

A **gate** = engine + parameters + invocation. Two axes decide delivery:
- **engine owner**: vendored (ruff/vulture/coverage/import-linter/ast-grep/jscpd) → pinned version; ours (`graph.py`) → shipped code.
- **param locality**: PORTABLE (house style, same everywhere → shared SUPERSET block) vs LOCAL-SLOT (project facts: paths/source/omit/contracts → stays in repo).

**Superset rule**: a portable param that is harmless-when-unused (ignore-lists, exclude-lines) is shipped as the UNION of all 3 repos. Do NOT thin it to make a gate pass.

## copier.yml — toggles + EXACT jinja var names (freeze)

| var | type | default | meaning |
|---|---|---|---|
| `project_name` | str | (ask) | repo/folder name, kebab-case (e.g. `sample-proj`) |
| `package_name` | str | (ask) | python package, snake_case (e.g. `sample_pkg`) — the "trainer" layer |
| `has_viewer` | bool | false | ship a viewer layer |
| `viewer_name` | str | `{{package_name}}_viz` | viewer package (only when has_viewer) |
| `viewer_imports_trainer` | bool | false | allow viewer→trainer downward edge (mindscape-style); if false, forbid it (cardiac-style) |
| `enforce_arch_fitness` | bool | true | ship `graph.py --assert` gate + `[tool.structure]` |
| `enable_astgrep` | bool | false | ship ast-grep module-shape gate + `devtools/sg-rules` |
| `enable_jscpd` | bool | false | ship jscpd DRY gate + `devtools/jscpd.json` |
| `coverage_floor` | int | 80 | `coverage report --fail-under` value |

Layer model (imports point DOWN only): `core` < `{{package_name}}` < `{{viewer_name}}`(optional).

## Gate inventory (the 7 + toggled extras)

| # | gate | engine | portable params (SUPERSET block) | local-slot params |
|---|---|---|---|---|
| 1 | ruff lint | vendored ruff@0.15.13 | `line-length`, `select`, `ignore`, `per-file-ignores` | `extend-exclude` (project dirs) |
| 2 | ruff format --check | vendored ruff@0.15.13 | (advisory, never blocks) | — |
| 3 | vulture dead-code | vendored vulture@2.16 | `min_confidence`, `ignore_decorators`, `ignore_names` core | `paths`, `exclude`, `ignore_names` domain |
| 4 | coverage floor | vendored coverage/pytest-cov | `exclude_lines`, `show_missing` | `source`, `omit`, `fail-under`(=coverage_floor) |
| 5 | import-linter layers | vendored import-linter | (mechanism only) | `root_packages`, `contracts` (project layers) |
| 6 | arch fitness | OURS `devtools/graph.py --assert` | `[tool.structure]` defaults + merge | `[tool.structure]` overrides (file_max etc.) |
| 7 | ast-grep module-shape (toggle `enable_astgrep`) | vendored ast-grep + our `sg-rules` | rule yml (portable) | scan paths |
| + | jscpd DRY (toggle `enable_jscpd`) | vendored jscpd | `jscpd.json` threshold | scan paths |

## PORTABLE SUPERSET VALUES (union of 3 repos — use verbatim)

### ruff (`[tool.ruff]` + `[tool.ruff.lint]`)
```toml
line-length = 120
# select = UNION of families across the 3 repos (mindscape broad ∪ cardiac/synth curated)
select = ["F","E","W","B","C4","UP","I","T20","FBT","BLE001","S","C90","PLR","PLC","SIM","RUF"]
ignore = ["RUF001","RUF002","RUF003"]   # intentional → ≈ × unicode; all 3 disable
# per-file-ignores = union
"__init__.py" = ["F401"]                 # re-export facades
"tests/**"    = ["S101","PLR2004","FBT"] # asserts + literal fixtures + bool flags fine in tests
```
`extend-exclude` is LOCAL-SLOT (project dirs). In the sample keep it minimal/empty.

### vulture (`[tool.vulture]`)
```toml
min_confidence = 60
# PORTABLE ignore core (all repos): pydantic ClassVar
ignore_names = ["model_config"]         # + LOCAL-SLOT domain names appended per project
ignore_decorators = ["@model_validator","@field_validator","@field_serializer","@model_serializer","@computed_field"]
```
`paths`/`exclude` LOCAL-SLOT.

### coverage (`[tool.coverage.report]`)
```toml
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "^\\s*\\.\\.\\.$",
    "@(abc\\.)?abstractmethod",          # union incl. mindscape's addition (harmless when unused)
]
```
`[tool.coverage.run] source`/`omit` LOCAL-SLOT. `fail-under` = `{{coverage_floor}}`.

### [tool.structure] defaults (graph.py reads these; ship as portable defaults)
```toml
bottleneck_degree = 8    # fan-in AND fan-out both over this = god-module
file_max = 750           # god-file line ceiling
betweenness_max = 0.10   # advisory chokepoint threshold
```

## LOCAL-SLOT convention (the seam)

In `pyproject.toml.jinja`, every local-slot region is wrapped with marker comments so `copier update` and humans see the boundary:
```toml
# >>> LOCAL-SLOT: <name> — edit freely, the template will not overwrite intent here
... project-specific values ...
# <<< LOCAL-SLOT: <name>
```
Portable superset blocks carry NO marker (template owns them; regenerated on update).

## Pinned tool versions (use everywhere — CI, pre-commit, nox)
- ruff `0.15.13`
- vulture `2.16`
- import-linter (latest via `uvx --from import-linter lint-imports`)
- ast-grep via `uvx --from ast-grep-cli ast-grep` (toggle)
- jscpd via `npx --yes jscpd` (toggle)

## Sample/example code shipped BY THE TEMPLATE (so a fresh gen is green)

Template ships a minimal-but-real example forming a genuine layer edge:
- `core/` kernel: 2 pure functions (e.g. `mean`, `clamp`) — no upward imports.
- `{{package_name}}/` trainer: 1 function importing from `core` (the real edge import-linter + graph.py chew).
- `tests/unit/`: tests covering the above to satisfy `coverage_floor`.
- (viewer example only when `has_viewer`.)

Anti-shortcut: gate failures are fixed in the TEMPLATE example/config, then regenerate. Never hand-patch generated output.

## Copier mechanics the authors must respect
- `_subdirectory: template` in copier.yml → only `template/` is rendered.
- Files ending `.jinja` are Jinja-rendered and lose the suffix. Static files (e.g. `.gitattributes`, `graph.py`, `__init__.py`) are copied verbatim — do NOT put unescaped `{{ }}` in them.
- Conditional files/dirs: use `{% if enable_astgrep %}` in filename via copier's `_templates_suffix`? No — use `copier.yml` `_exclude` is global; for per-file conditionals name the FILE with a jinja condition producing empty path, OR gate the content inside. SIMPLEST + chosen here: ship all files, gate their CONTENT with `{% if %}`; for whole-file skip use copier's templated filename `{% if enable_astgrep %}devtools/sgconfig.yml{% endif %}.jinja` (empty name → skipped). Author B/C decide per file; document what you chose.
- TOML + Jinja: `{{` collides. In TOML string values needing literal braces, use `{{ "{{" }}` or `{% raw %}`. Watch coverage regex + f-string-like content.
