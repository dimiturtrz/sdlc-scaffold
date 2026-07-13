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

## Deferred growth — git-versioned staged rollout (the ratchet, mechanized)

Not built in the MVP (goal scoped it out). To enable:
- Push `sdlc-scaffold` to a shared location (remote OR a stable local path). Tag releases `vN`.
- Tighten a rule → `git tag v0.2.0`. In each repo: `copier update` 3-way-merges the change in; bump when
  that repo is clean. **Per-repo `_commit` pin advancing independently = the "one family per PR, graduate
  at zero" ratchet, mechanized across repos.**
- Gate DELIVERY goes from `repo: local` → `repo: <scaffold> rev: vN` in `.pre-commit-config.yaml`, so gate
  invocations are versioned centrally (the root `.pre-commit-hooks.yaml` is already stubbed for this).
- MVP proved everything EXCEPT the network-fetch (`copier update` from a real remote + Actions fetching by
  URL) — the last flip, verified after a first push.

## One-line status

MVP done: versioned local template + generated sample, all gates green across the toggle matrix, drift-
healing mechanism (copier answers + tags) armed. Ready to modulate items 1-3 above, then migrate repo #1.
