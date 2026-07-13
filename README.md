# sdlc-scaffold

A [copier](https://copier.readthedocs.io) template for the personal-projects SDLC guardrail stack:
ruff · vulture · coverage floor · arch-fitness (`graph.py --assert`) · optional ast-grep + jscpd +
class-shape explorers · nox task runner · pre-commit gate binding · versioned rollout via `copier update`.

It ships **guardrails, not architecture** — the gates target whatever `packages` you declare and impose
no layering. Derived from the common skeleton of cardiac-seg / mindscape / synthscape. See `docs/SPEC.md`
for the gate contract (portable-superset vs project-local slot) and `docs/LEARNINGS.md` for the build log.

## Three ways to use it

### 1. New project

```bash
uvx copier copy path/to/sdlc-scaffold ./my-project
cd my-project
git init && git add -A && git commit -m "scaffold v0.1.0"
uv sync --extra dev --extra devtools
nox -s gates        # ruff + vulture + coverage + graph --assert, all green on the demo
```

The demo package (`math_ops` ← `pipeline`) ships so the gates have real code to bite on day one.
Replace it with your own; the gates guard every commit from there.

### 2. Adopt into an existing repo

```bash
cd existing-repo
uvx copier copy --data packages=core,neuroscan,neuroviz --data ship_example=false <scaffold> .
```

- `ship_example=false` → **no demo stub**, guardrails only.
- copier **conflict-prompts** on files you already have (your `pyproject.toml`, `README.md`, CI) — keep or
  merge per file. It lays down the gate config + `devtools/`; your source packages it leaves alone.
- `git add -A && git commit`, then `uv sync && nox -s gates` — fix or ratchet whatever the gates flag.

### 3. Update (new + adopted, identical)

```bash
uvx copier update       # reads .copier-answers.yml, fetches the newest scaffold tag
```

3-way merge: portable rule changes flow in, your `# >>> LOCAL-SLOT` edits survive, real conflicts land as
`.rej`. The scaffold advances by **git tags** — each tag is one reviewable rollout step. Commit the result.
`.copier-answers.yml` (copier writes it, records `_commit:` + your answers) is the anchor — commit it.

## Toggles (asked at copy time)

| toggle | default | effect |
|---|---|---|
| `project_name` | — | repo / folder name (kebab-case) |
| `packages` | `project_name` snake_cased | comma-list the guardrails target; add your own (`core,neuroscan,neuroviz`) |
| `ship_example` | `true` | ship the demo package; `false` for guardrails-only adoption |
| `enforce_arch_fitness` | `true` | `graph.py --assert` gate (god-module / cycle / god-file / test-mirror) + `[tool.structure]` |
| `enable_astgrep` | `false` | ast-grep module-shape gate (in-a-class, no import-time side effects) |
| `enable_jscpd` | `false` | jscpd duplication (DRY) gate — advisory |
| `enable_class_shape_smells` | `false` | LCOM4 / data-clumps / namespace-state advisory explorers |
| `enable_beads` | `false` | beads (bd) issue tracking — CLAUDE/AGENTS section + gitignore |
| `coverage_floor` | `80` | `coverage report --fail-under` |

`package_name` (= `packages[0]`, the demo folder), the ruff select, and the pinned tool versions are
computed/single-sourced (`when: false`) — never asked, one home in `copier.yml`.

## What a generated project gets

- `pyproject.toml` — portable ruff/vulture/coverage superset blocks + marked LOCAL-SLOT regions.
- `noxfile.py` — one entrypoint (`nox -s gates`) that runs exactly what CI runs.
- `.pre-commit-config.yaml` — the same gates bound to the commit event.
- `.github/workflows/ci.yml` — the gates as the merge gate.
- `devtools/` — the fitness tools (`graph.py` arch-fitness; optional ast-grep rules, jscpd config,
  class-shape explorers) + a toggle-aware `README.md`.
- `{packages}/` + `tests/` — a minimal-but-real example that passes every gate on generation
  (omitted when `ship_example=false`).

Directional layer contracts (e.g. viewer never imports trainer) are **opt-in** — add import-linter
yourself; the scaffold's shipped arch gate is layer-agnostic. See the generated `devtools/README.md`.

## Design

Gate = engine + params + invocation. Params are copied per-repo (template-owned superset + local slot);
gate invocations ride pre-commit; our own gate *code* (`graph.py`, the class-shape tools) is stamped in
and **unit-tested** (`tests/unit/` verifies the fitness-function logic). Versioned rollout (`copier update`
+ tags) heals drift in stages. The scaffold's own CI (`.github/workflows/e2e.yml`) generates real projects
across the toggle lattice and runs every gate — the guardrails guard themselves.
