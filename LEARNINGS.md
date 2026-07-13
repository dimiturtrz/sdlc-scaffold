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
pre-commit/CI. **Coverage is intentionally NOT a pre-commit hook** — a full test-suite run on every
commit is wrong; it lives in nox + CI. jscpd IS a pre-commit hook but **stricter there than CI** (CI
marks it advisory `continue-on-error`; a commit hook blocks on any clone) — a "clean at commit" choice,
and it needs node/npx on PATH. Remove the `jscpd-gate` hook to make it advisory-only.

## DECISION NEEDED (item 8 — not auto-resolved, your call)

**ruff `select` is a UNION superset, broader than cardiac's curated-narrow.** Current select:
`F,E,W,B,C4,UP,I,T20,FBT,BLE001,S,C90,PLR,PLC,SIM,RUF`. This is the union of all 3 repos — it pulled
`UP` (pyupgrade) and `SIM` (flake8-simplify) from **mindscape**, which **cardiac deliberately keeps OFF**
("TRY/EM/SIM/UP — opinionated churn"). So the scaffold's ruff is *stricter* than cardiac, not a faithful
cardiac mirror on this axis.

- **Keep the union (current):** more rules caught out of the box; a fresh project starts maximally
  strict. Cost: `UP`/`SIM` fire opinionated rewrites cardiac considers churn; a migrating cardiac-style
  repo would see new findings.
- **Narrow to cardiac (drop `UP,SIM`, and reconsider `C4`):** faithful to the most-mature repo's
  deliberate choices; less churn. Cost: mindscape-style repos lose two families they run today.

Left AS-IS (union) pending your decision. Changing it is a one-line edit in `pyproject.toml.jinja`
(and the mirrored `SELECT`/`--select` strings in `ci.yml.jinja`, `noxfile.py.jinja`,
`.pre-commit-config.yaml.jinja` — grep for the select string; note it lives in 4 files, itself an
argument for extracting the select to a single source later).

## One-line status

Scaffold now mirrors cardioseg at full toggle: every cardioseg gate present + green across solo/nox/
pre-commit/CI, new gates proven to bite, drift-healing proven. Open: the ruff-select union-vs-narrow
call (item 8), and the 4-place duplication of the select string (extract to one source).
