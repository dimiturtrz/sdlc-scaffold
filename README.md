# sdlc-scaffold

A [copier](https://copier.readthedocs.io) template for the personal-projects SDLC guardrail stack:
ruff · vulture · coverage floor · import-linter layers · arch-fitness (`graph.py --assert`) ·
optional ast-grep + jscpd · nox task runner · pre-commit gate binding.

Derived from the common skeleton of cardiac-seg / mindscape / synthscape. See `docs/SPEC.md` for the
gate contract (portable-superset vs project-local slot, exact toggle names, superset values).

## Use

```bash
# birth a project
uvx copier copy path/to/sdlc-scaffold my-project
# later, pull template improvements into an existing project (needs git in the target)
uvx copier update
```

Toggles (asked at copy time): `project_name`, `package_name`, `has_viewer`,
`viewer_imports_trainer`, `enforce_arch_fitness`, `enable_astgrep`, `enable_jscpd`, `coverage_floor`.
Each toggle selects a ratchet stage — a fresh project can start minimal and graduate.

## What a generated project gets

- `pyproject.toml` — portable ruff/vulture/coverage superset blocks + marked LOCAL-SLOT regions.
- `noxfile.py` — one entrypoint (`nox -s lint test cov`) that runs exactly what CI runs.
- `.pre-commit-config.yaml` — the same gates bound to the commit event.
- `.github/workflows/ci.yml` — the gates as the merge gate.
- `devtools/graph.py` — the arch-fitness engine (fan-in/out, god-module, cycles, file size).
- a minimal-but-real `core/` + package + tests example that passes every gate on generation.

## Design

Gate = engine + params + invocation. Config (params) is copied per-repo (template-owned superset +
local slot); gate invocations ride pre-commit; our own gate *code* (`graph.py`) is stamped in.
Versioned rollout (`copier update` + tags) heals drift in stages — see `docs/LEARNINGS.md`.
