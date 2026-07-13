# LEARNINGS — sdlc-scaffold MVP

Built + verified 2026-07-13. A copier template + a generated `sample-proj`, every gate run green
locally across 3 toggle combos. The 3 real repos (cardiac-seg / mindscape / synthscape) untouched.

## Verified green (real command output, not asserted)

| gate | base | viewer ON | astgrep+jscpd ON |
|---|---|---|---|
| ruff (full superset select) | ✅ | ✅ | ✅ |
| ruff format --check | ✅ | — | — |
| vulture conf80 | ✅ | ✅ | ✅ |
| coverage floor 80 (actual 100%) | ✅ | ✅ | ✅ |
| import-linter | ✅ (1 contract) | ✅ (3 contracts) | ✅ |
| graph.py --assert | ✅ | ✅ | ✅ |
| ast-grep in-a-class | n/a (off) | n/a | ✅ + proven to catch an injected top-level func |
| jscpd DRY | n/a | n/a | ✅ (0 clones) |
| nox lint/test/cov | ✅ | — | — |
| pre-commit (all hooks) | ✅ | — | — |

Toggles proven to GATE (not cosmetic): viewer ON adds `VIEWER/render.py` + a 3rd import-linter
contract (`viewer ≠ trainer`, the cardiac-style forbid — flips with `viewer_imports_trainer`);
astgrep/jscpd ON add `sgconfig.yml` + `sg-rules/*` + `jscpd.json`.

## What worked

- **copier needs a git repo even for a local template.** `copier copy` on a plain dir crashed with
  `WinError 193` — the Bash shell resolves `git` to an MSYS shim the uvx-spawned Windows process can't
  exec. Run copier from **PowerShell** (real `C:\Program Files\Git\cmd\git.exe`) against a **local
  git-init'd + tagged** scaffold. `_commit: v0.1.0` lands in `.copier-answers.yml` → versioning armed.
  "No git" is impossible for copier; "no remote / no push" is the honest constraint.
- **Class-based example is the unifier.** The ast-grep rule forbids module-level functions. Free
  functions break astgrep-ON. Making the example a class (`MathOps`, `Pipeline`, `Renderer` with
  staticmethods — the real cardiac house style) makes EVERY toggle combo green with one example.
- **Superset ruff select** (union of the 3 repos' families: `F,E,W,B,C4,UP,I,T20,FBT,BLE001,S,C90,PLR,PLC,SIM,RUF`)
  passes on clean example code — the "ship the union, don't thin" rule held.
- **import-linter contracts generated from toggles** — 1 → 3 contracts driven by `has_viewer` +
  `viewer_imports_trainer`. The layer policy is fully data-driven from answers.
- **nox `venv_backend="none"`** shelling to pinned `uvx`/`uv run` = local `nox` runs byte-identical
  commands to CI. Closes the "green locally, red in CI" gap the 3 real repos all have.
- **pre-commit `repo: local` + `language: system`** runs the same gates at commit with no remote.

## What to modulate (next iterations)

1. **ruff-format target trap.** Formatting a template file standalone from the scaffold dir uses ruff's
   DEFAULT line-length 88; the sample enforces 120 → perpetual "would reformat". Fix used: format inside
   a generated instance, copy the result back into the template. BETTER: ship a tiny `ruff.toml`
   (line-length 120) in the scaffold ROOT so template-file formatting matches. Do this.
2. **nox `graph.py --assert` passes no packages** → defaults to `["core"]` only, missing the trainer.
   The `noxfile.py.jinja` should pass `core {{ package_name }}{% if has_viewer %} {{ viewer_name }}{% endif %}`.
3. **Viewer is unmeasured by default.** `coverage.source` + `vulture.paths` local-slots default to
   `[core, package]`, NOT the viewer — a viewer project's logic is neither covered nor dead-code-scanned
   until it adds the viewer to those slots (or ships viewer tests). Template should either add viewer to
   the slots when `has_viewer`, or ship a viewer test + a `# TODO add viewer to coverage source` note.
4. **astgrep forces class-based even when off.** The shipped example is class-y to satisfy an OFF-by-
   default gate. Acceptable (matches house style) but if a project wants free functions with astgrep off,
   that's friction. Option: a second example variant keyed on `enable_astgrep`.
5. **Windows dir-lock.** A shell whose CWD is inside a dir blocks `Remove-Item` on it. Regenerate from
   the parent; keep the Bash CWD out of the target. `uv sync` leaves gitignored `*.egg-info/` — harmless
   tree-diff noise.
6. **coverage floor lives in the INVOCATION, not pyproject.** `coverage report --fail-under={{coverage_floor}}`
   is in CI/nox/pre-commit; `pyproject` carries only `exclude_lines`/`source`/`omit`. Correct (mirrors the
   real repos) — don't add a `[tool.coverage.report] fail_under`, it would double-source the number.

## Migration path — the 3 real repos (deferred, when ready)

Each real repo becomes a copier-managed project WITHOUT losing its rich local slots:
1. In a branch: `copier copy --overwrite --data <that repo's stage answers> sdlc-scaffold .` (answers preset
   — cardiac: viewer ON + `viewer_imports_trainer=false` + astgrep ON + jscpd ON; mindscape: viewer ON +
   `viewer_imports_trainer=true` + astgrep OFF; synth: viewer OFF + astgrep OFF).
2. `git diff` — ACCEPT the portable superset blocks (ruff select, vulture ignores, coverage exclude_lines);
   KEEP the LOCAL-SLOT regions (cardiac's 40-line coverage omit, domain vulture `ignore_names`, the
   store-surface import contract). The `# >>> LOCAL-SLOT` markers make the seam mechanical.
3. Reconcile select drift: real repos are mid-ratchet (mindscape's graduated subset). Either jump to the
   full superset (if the repo is clean for it) or temporarily override `select` in a local slot and ratchet.
4. Add `.copier-answers.yml` → the repo is now update-able.

## Git-versioned staged rollout — PROVEN on WSL (2026-07-13)

The MVP first left this untested (copier needed a local git-init just to `copier copy`; the `copier
update` drift-heal was deferred). Finished it in a WSL clean-room (native LF git, no Windows shim
friction). Test: hand-edit a LOCAL-SLOT in the sample (`MY_LOCAL_DIR` into ruff extend-exclude) →
tighten a PORTABLE rule in the scaffold (`file_max 750→500`) → `git tag v0.2.0` → `copier update`.

Result — all four held, no `.rej` conflicts, gates green post-update:
- **Pin advanced**: sample `_commit: v0.1.0 → v0.2.0` (staged — each repo bumps when ready).
- **Portable change flowed in**: `file_max = 500` landed in the sample's pyproject.
- **Local-slot survived**: `MY_LOCAL_DIR` preserved through copier's 3-way merge — the seam works
  because the portable edit and the local edit sat in different file regions, so the merge is clean.
  (Caveat: the LOCAL-SLOT markers are a HUMAN convention; copier does a git-style 3-way merge on the
  whole file, not marker-aware. Same-line edits to a portable line WOULD conflict → keep local edits
  inside the marked slots, which are never the lines the template rewrites.)
- **Per-repo `_commit` advancing independently = the ratchet mechanized** ("one family per PR, graduate
  at zero", now across repos via tags).

Still to flip (only the network hop remains):
- Gate DELIVERY `repo: local` → `repo: <scaffold> rev: vN` in `.pre-commit-config.yaml` for central
  versioned gates (root `.pre-commit-hooks.yaml` already stubbed).
- `copier update` from a real REMOTE + Actions fetching by URL — verified after a first push.

## Windows vs WSL

`copier copy`/`update` and the whole git flow are friction-free on WSL (matches CI `ubuntu-latest`);
on Windows, run copier from PowerShell (real `git.exe`, not the Bash MSYS shim → the `WinError 193`).
Do the versioned-rollout / CI-parity work on WSL; Windows is fine for authoring + single-shot gate runs.

## Cardioseg-mirror gaps CLOSED (2026-07-13)

Made the scaffold faithfully mirror cardioseg (most-mature) and verified a full-toggle generation hits
every cardioseg gate. Done on WSL native git; node installed WITHOUT sudo (static tarball to `~/.local`,
since WSL has no passwordless sudo — `apt` needs a password).

**Template fixes shipped:**
1. **Coverage ≥95 advisory tier** — `ci.yml` (`continue-on-error` + `::warning::`) and noxfile `cov`
   (`success_codes=[0, 2]`). Floor 80 still blocks; 95 only warns.
2. **Viewer separate-coverage lane** (when `has_viewer`) — main run `--ignore=tests/viewer` keeps the
   floor calibrated to core+trainer; a separate `COVERAGE_FILE=.coverage.viewer` step measures the
   viewer (advisory). Shipped a viewer test (`tests/viewer/test_render.py`) so the lane is real (100%).
3. **nox arch-fitness passes all layers** (`*LAYERS`), and `graph.py --assert` now includes the viewer
   in CI + pre-commit too (was core+trainer only) — consistent everywhere.
4. **Scaffold-root `ruff.toml` (line-length 120)** — kills the 88-vs-120 format-target trap for the
   static `template/devtools/graph.py`.
5. **nox now runs ast-grep + jscpd** when enabled (was CI-only) → local `nox` == CI.

**Full cardioseg-mirror generation** (`has_viewer=true, viewer_imports_trainer=false, arch_fitness=true,
astgrep=true, jscpd=true, floor=80`) — every gate GREEN, verified with pasted output:

| gate | solo | nox | pre-commit | CI |
|---|---|---|---|---|
| ruff enforced + advisory + format | ✅ | ✅ | ✅ | ✅ |
| vulture conf80 (block) / conf60 (warn) | ✅ | ✅ | ✅(80) | ✅ |
| coverage floor 80 + 95 advisory | ✅ | ✅ | — (by design) | ✅ |
| viewer coverage lane | ✅ | ✅ | — | ✅ |
| import-linter (3 contracts incl viewer≠trainer) | ✅ | ✅ | ✅ | ✅ |
| graph.py --assert (all layers) | ✅ | ✅ | ✅ | ✅ |
| ast-grep (in-a-class + no import-time side-effects) | ✅ | ✅ | ✅ | ✅ |
| jscpd (DRY) | ✅ | ✅ | ✅ | ✅ |

**New gates proven to actually GATE** (not just present): injected a top-level function → ast-grep
non-zero (caught); injected a duplicated block → jscpd "Found 1 clones" non-zero (caught); both green
after revert.

**Channel matrix — deliberate, documented:** the fast lint-family gates bind to all of solo/nox/
pre-commit/CI. **Coverage + jscpd are intentionally NOT pre-commit hooks** — a full test-suite run per
commit is wrong, and jscpd is advisory (see harmonization below); both live in nox + CI. Class-shape
smells (exit-0 explorers) DO ride pre-commit — they surface findings without ever blocking.

## Repos surpassed the scaffold → harmonization (2026-07-13)

Re-checked the 3 real repos mid-project: **they had all converged AND grown past the scaffold.** All
three now carry the full gate set (import-linter, arch-fitness, ast-grep, jscpd) — synthscape went from
*none* of those to all. cardiac + synthscape also grew a new **class-shape-smell trio** the scaffold
lacked; mindscape independently grew a `.pre-commit-config.yaml`. A scaffold built to mirror cardiac's
*earlier* state was now the LAGGARD — migrating a repo onto it would have STRIPPED tooling. So the
scaffold had to catch up before any rollout. What changed:

1. **Absorbed the class-shape trio** (`lcom.py` LCOM4 cohesion, `data_clumps.py` Fowler data-clumps,
   `state_candidates.py` namespace-latent-state) from cardiac, GENERALIZED — dropped `core.obs`, argv
   packages default `["core"]`, stdlib logging, bd-refs stripped. Gated by `enable_class_shape_smells`
   (default false). Shipped as non-`.jinja` static files (their f-string braces `{{{…}}}` would collide
   with jinja) via conditional-name paths. Advisory everywhere (exit-0 explorers): CI `continue-on-error`
   step, nox loop, 3 pre-commit hooks. Formatted at 120 (cardiac's own format is only advisory, so its
   source wasn't clean).
2. **jscpd reconciled to advisory default** (cardiac + synth = 2-of-3 majority): CI `continue-on-error`,
   nox `success_codes=[0,1]`, and **removed from pre-commit** (an advisory gate shouldn't block a commit).
   A repo wanting it enforced (mindscape-style, blocks >1%) adds the hook back — documented inline.
3. **pre-commit `--extra devtools`** on arch-fitness (adopted from mindscape's version — guarantees
   grimp/networkx present).

## Item 8 RESOLVED — ruff select is NARROW

Settled by the repos themselves: cardiac and synthscape now carry the **identical curated-narrow** select
(specific codes, no `UP`/`SIM`/`C4`/broad-`E`/`W`); only mindscape is broad. **2-of-3 + the most-mature
both vote narrow**, so the scaffold now ships cardiac's exact list:
`F,B,E501,I,T201,FBT,BLE001,S110,C901,PLR0912,PLR0913,PLR0915,PLR2004,PLC0415,RUF100` (ignore
`RUF001-3`). Also **single-sourced** — a `ruff_select` value in `copier.yml` (`when: false`) renders into
all four consumers (`pyproject` via a jinja split-loop, `ci`/`nox`/`pre-commit` as the raw string), so the
old 4-place duplication is gone. Grep-verified: no `UP`/`SIM`/`C4` leak anywhere.

## E2E test suite (2026-07-13)

The manual verification is now codified as pytest — `tests/end_to_end/test_e2e.py` (scaffold root,
outside `template/`, so never copied into generated projects). It black-boxes the scaffold: builds a
throwaway git repo from the on-disk template, generates real projects for each toggle combo, and asserts:
- **renders clean** (no leftover jinja; toggle-gated files present/absent as expected);
- **every gate GREEN** solo (ruff/format/vulture/coverage/viewer-lane/import-linter/graph/ast-grep/jscpd)
  and via **nox** + **pre-commit**;
- **optional gates BITE** — inject a top-level function → ast-grep fails; inject a duplicated block →
  jscpd fails;
- **`copier update` heals drift** — a portable `file_max` change flows in while a project-local slot
  edit (`MY_LOCAL_DIR`) survives the 3-way merge, pin advances to v0.2.0.

Run: `cd sdlc-scaffold && uv run pytest` (Linux/WSL; jscpd steps skip if node absent). Result:
**27 passed, 4 skipped** (base-combo astgrep/jscpd/class-shape/viewer skips) in ~12s. The scaffold's own
`.github/workflows/e2e.yml` runs it on push/PR (installs node for jscpd). This is the regression guard
for the scaffold itself — a template edit that breaks any gate now fails a test, not a manual run.

## One-line status

Scaffold ships layout-agnostic guardrails (one `packages` list, no imposed layering), every gate green
across solo/nox/pre-commit/CI, new gates proven to bite, drift-healing proven — and both the gates AND
their own fitness-function logic are under test (`uv run pytest`: 44 passed). Superseded below by the
2026-07-13 refactor pass (this section's item-8 select call + 4-place duplication are resolved: the select
+ tool versions are single-sourced in `copier.yml`).

## Refactor + guardrail-testing pass (2026-07-13)

The scaffold was maintainable-refactored and its own tooling put under test.

**Maintainability (Phase A).**
- **Conditional filenames → `copier _exclude`.** `{% if toggle %}name{% endif %}` in paths was replaced
  with clean names + jinja `_exclude` rules keyed on the toggles (rendered per-answers). The class-shape
  trio became real `.py` files → ruff formats them in place (the temp-file copy-back dissolved).
- **De-opinionated the layout.** The scaffold was shipping the 3-repo `core → trainer → viewer` layering
  as imposed structure. Guardrails must be layout-agnostic, so: the layer *roles* + directional
  import-linter contracts were dropped (import-linter is now opt-in, documented in `devtools/README.md`);
  `graph.py --assert` stays as the layer-agnostic structural gate (god-module / cycle / god-file).
- **`packages` is a declared LIST, not one name.** A repo with `core,neuroscan,neuroviz` names them all;
  every gate (ruff/vulture/coverage/graph/ast-grep/jscpd/class-shape/setuptools) renders over the list.
  `package_name` is a computed `when:false` var = `packages[0]`, keeping the demo folder a simple
  interpolation. `ship_example` (default true) drops the demo package for clean repo-adoption.
- **Single-sourced versions.** ruff/vulture/nox/pre-commit pins + the ruff select live once in
  `copier.yml` (`when:false`), rendered into ci/nox/pre-commit and regex-parsed by the E2E conftest.
- **Tidy.** `tests/end_to_end → tests/e2e` (matches the shipped convention); `SPEC.md`+`LEARNINGS.md → docs/`.

**Testing the guardrails (Phase B).** `tests/unit/test_devtools.py` tests the LOGIC of the four shipped
fitness functions — pos + neg each, imported from a generated full instance:
- **lcom** — disjoint self-field groups → LCOM4==2; cohesive → 1; impl/abstract/trivial/<2 skipped.
- **data_clumps** — a param set carried by ≥4 functions surfaces; support<4 silent; maximal beats subset.
- **state_candidates** — a param threaded through the staticmethods flags; `__init__`/pydantic/command skip.
- **graph** — `[tool.structure]` merges over defaults; god-module/cycle/oversized detected; assert clean vs dirty.
The E2E gained a `graph --assert` inject-test (close an import cycle → non-zero → revert → 0), matching the
ast-grep/jscpd bite-proofs. The scaffold CI runs `tests/unit` + `tests/e2e` under one `pytest`.

Also fixed a latent bug: `_exclude: "README.md"` matched *any* depth (gitignore semantics), silently
dropping the generated project's own README — the redundant root-meta excludes were removed
(`_subdirectory` already scopes rendering).

Result: **44 passed, 3 skipped** (`uv run pytest tests`, WSL). The guardrails now guard themselves.
