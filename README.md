# sdlc-scaffold

A [copier](https://copier.readthedocs.io) template for the personal-projects SDLC guardrail stack:
ruff · vulture · coverage floor · arch-fitness (`graph.py --assert`) · ast-grep + jscpd +
class-shape explorers + magic-literals · nox task runner · pre-commit gate binding · versioned rollout via `copier update`.

It ships **guardrails, not package architecture** — the gates target whatever `packages` you declare and
impose no import layering. (One structural choice the arch gate *does* make, and it's configurable: the
test-existence rule defaults to a strict source-mirror test tree — set `test_layout = "flat"` or `"off"`
in `[tool.structure]` if your tests don't mirror the source.) Derived from the common skeleton of cardiac-seg / mindscape / synthscape. See `docs/SPEC.md`
for the gate contract (portable-superset vs project-local slot) and `docs/LEARNINGS.md` for the build log.

The template ships **zero package code** — only guardrails. Every gate is on, always; there are no
feature toggles to answer.

## Two ways to use it (+ update)

### New project
```bash
uvx copier copy path/to/sdlc-scaffold ./my-project   # answer: packages, domain, coverage_floor
cd my-project
git init && git add -A && git commit -m "scaffold"
uv sync --extra dev --extra devtools
# cold start: no code ships. Write your first module + its mirror test, then:
nox -s gates        # ruff + vulture + coverage + graph --assert + import-linter + ast-grep + jscpd
```
A brand-new empty project has nothing to cover yet — write `{packages[0]}/foo.py` and
`tests/unit/{packages[0]}/test_foo.py`, and the gates go green. (The gates are never weakened for the
empty case — you bring the first module.)

### Adopt into an existing repo
```bash
cd existing-repo
uvx copier copy --data packages=core,neuroscan,neuroviz <scaffold> .
```
copier **conflict-prompts** on files you already have (`pyproject.toml`, CI) — keep or merge per file. It
lays down the gate config + `devtools/`; your source packages it never touches (it ships none). Then
`git commit`, `uv sync && nox -s gates` — fix or ratchet whatever the gates flag.

### Update (both, identical)
```bash
uvx copier update       # reads .copier-answers.yml, fetches the newest scaffold tag
```
3-way merge: portable rule changes flow in, your `# >>> LOCAL-SLOT` edits survive, real conflicts land as
`.rej`. The scaffold advances by **git tags** — one reviewable rollout step each. Commit `.copier-answers.yml`.

## Questions (asked at copy time)

| question | default | effect |
|---|---|---|
| `project_name` | — | repo / folder name (kebab-case) |
| `packages` | `project_name` snake_cased | comma-list the guardrails target (`core,neuroscan,neuroviz`) |
| `domain` | `ml` | `ml` = numpy dep + ML-workflow gitignore (data-outside-repo/`paths.yaml`, MLflow, `runs/`) + data-skip CI env; `none` = domain-neutral |
| `coverage_floor` | `80` | `coverage report --fail-under` |

That's it. **The quality gates (ruff, vulture, coverage, arch-fitness incl. test-mirror, import-linter,
ast-grep, jscpd) + beads are always on — no toggles.** import-linter self-gates (only bites with >1
package). The ruff select + pinned tool versions are single-sourced (`when: false`) in `copier.yml`.

## What a generated project gets

- `pyproject.toml` — portable ruff/vulture/coverage superset blocks + marked LOCAL-SLOT regions.
- `noxfile.py` / `.pre-commit-config.yaml` / `.github/workflows/ci.yml` — the same gates as local, commit, merge.
- `devtools/` — the fitness tools (`graph.py`, `omit.py`, ast-grep rules, jscpd config, class-shape explorers, `magic_literals.py`) + a `README.md`.
- `tests/{unit,integration,e2e}/`, `docs/`, `CLAUDE.md`/`AGENTS.md` — the skeleton. **No package code** — you bring it.

Directional layer contracts (e.g. the kernel imports none of the others; a viewer never imports a
trainer) ship via **import-linter** once you declare >1 package — `[tool.importlinter]` carries a
kernel-independence starter + a contracts LOCAL-SLOT. A one-way forbidden import is no cycle, so it's the
axis `graph.py` can't see. See the generated `devtools/README.md`.

## Design

Gate = engine + params + invocation. Params are copied per-repo (template-owned superset + local slot);
gate invocations ride pre-commit; our own gate *code* (`graph.py`, the class-shape tools) is stamped in
and **unit-tested** (`tests/unit/` verifies the fitness-function logic). Versioned rollout (`copier update`
+ tags) heals drift in stages. The scaffold's own CI (`.github/workflows/e2e.yml`) generates real projects
across the toggle lattice and runs every gate — the guardrails guard themselves.
