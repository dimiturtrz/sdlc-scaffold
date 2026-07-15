# Splitting `sdlc-devtools` into its own repo

The repo is **two products in one tree** (bd uo0): the copier **scaffold** (the house policy —
thresholds, ruff codes, the LOCAL-SLOT contract, the gate wiring) and **`sdlc-devtools/`** (the generic
structural analyzers, an installable package). They are kept together until an external-consumer or
release-cadence forcing function makes a split worth it. This file is the extraction checklist so that day
is a checklist, not an archaeology dig.

The package is already **extraction-ready**: it has its own `pyproject.toml`, its own standalone gate
(`sdlc-devtools/noxfile.py`, `cd sdlc-devtools && uvx nox`, bd uo0.2), and imports nothing from the
scaffold. The couplings below are the entire seam.

## The seams (every scaffold ↔ package coupling)

| # | Coupling | Where | Kind |
|---|----------|-------|------|
| A | **Consumer git-dep URL** — `sdlc-devtools @ git+…/sdlc-scaffold.git@{{ devtools_ref }}#subdirectory=sdlc-devtools` | `template/pyproject.toml.jinja` | **load-bearing** — how consumers fetch the package |
| B | **`devtools_ref` pin var** — semantically "the scaffold release tag" | `copier.yml` (`devtools_ref`) | versioning — package version rides scaffold tags today |
| C | **uv workspace member** — `[tool.uv.workspace] members = ["sdlc-devtools"]` | root `pyproject.toml` | dev convenience — one shared lock |
| D | **Editable test override** — `use_local_devtools()` injects `[tool.uv.sources] sdlc-devtools = {path=…, editable=true}` | `tests/e2e/conftest.py` | test infra — e2e builds the working tree, not the unpublished tag |
| E | **Dogfood shells into the package** — `PKG = REPO/"sdlc-devtools"` → `uvx nox` | `tests/e2e/test_dogfood.py` | test infra — scaffold CI runs the package's own gate |
| F | **Duplicated ruff select + tool pins** — copier.yml `ruff_select`/versions copied into the package noxfile | `sdlc-devtools/noxfile.py` | intentional — a standalone package can't read the scaffold answer file; becomes clean ownership on split |
| G | **e2e dep assertions** — assert `sdlc-devtools @ git+` and `#subdirectory=sdlc-devtools` present | `tests/e2e/test_e2e.py` | test — verifies A rendered |
| H | **Narrative refs** — packaging model description | `docs/SPEC.md`, `README.md`, `copier.yml` comments | docs |

Seams are deliberately few and all necessary or intentional — no incidental coupling to unwind. The
package imports zero scaffold code (the F duplication is the price of standalone-ability, by design).

## Extraction checklist

1. **Move the tree.** `git filter-repo --subdirectory-filter sdlc-devtools` (or a fresh repo) → new repo,
   e.g. `github.com/dimiturtrz/sdlc-devtools`, preserving `devtools/`, `tests/`, `noxfile.py`,
   `pyproject.toml`, `README.md`. The package is already the repo root shape — no restructuring.
2. **Package release cadence (B).** The package now tags itself (`v1.2.0` → its own `v1.3.0`, …), decoupled
   from scaffold tags. Wire the new repo's CI to `uvx nox` (seam E moves here — it's already the package's
   own noxfile) + publish tags (and optionally to PyPI, which would retire the git-dep entirely).
3. **Repoint the consumer dep (A).** In `template/pyproject.toml.jinja` change the `devtools` extra to
   `sdlc-devtools @ git+https://github.com/dimiturtrz/sdlc-devtools.git@{{ devtools_ref }}` — **drop
   `#subdirectory=sdlc-devtools`** (the package is now the repo root). If published to PyPI instead:
   `sdlc-devtools=={{ devtools_ref }}` (or a version range) and drop the git+ entirely.
4. **Update `devtools_ref` (B).** In `copier.yml`, its default becomes the package's release tag and its
   help text changes from "scaffold release tag" to "sdlc-devtools release". Bump on each package release.
5. **Fix the e2e override (D).** `use_local_devtools()` must point `[tool.uv.sources]` at an **external
   checkout** of the package (env var / gitignored `external/sdlc-devtools` per the personal-projects
   external-dep convention) instead of `REPO/"sdlc-devtools"`, or drop the override and let the e2e pull the
   published package. Same for `config_path()`.
6. **Move the dogfood (E).** Delete `tests/e2e/test_dogfood.py` from the scaffold — the package repo's CI
   now owns `uvx nox`. (Optionally keep a thin scaffold e2e that pulls the published package and smoke-runs
   one gate, to catch a bad pin.)
7. **Update the e2e assertions (G).** In `tests/e2e/test_e2e.py` drop the `#subdirectory=sdlc-devtools`
   assertion and adjust the URL host in the `sdlc-devtools @ git+` checks (or the PyPI form).
8. **Remove the workspace member (C).** Delete `[tool.uv.workspace]` from the root `pyproject.toml` — the
   package is no longer in-tree.
9. **Move the API-diff gate.** `.github/workflows/api-diff.yml` runs `griffe check devtools -s sdlc-devtools`
   from the scaffold root (the package is a subdir). In the package's own repo it becomes `-s .` (or drop
   `-s` entirely) — move the workflow there, comparing the package's own tags.
10. **Update docs (H).** `docs/SPEC.md` "How the analyzers travel", `README.md` (drop the `cd sdlc-devtools`
    dev command; the package develops in its own repo), and the `copier.yml` comments.

## What does NOT change on split

- The consumer contract: still `python -m devtools.graph <pkg>`, config still via `python -m
  devtools.config` — the import name (`devtools`) and CLI are unchanged.
- The scaffold IS the policy (thresholds, ruff select, LOCAL-SLOT taxonomy, gate wiring). That stays in the
  scaffold repo; only the generic analyzers leave. See [`SPEC.md`](SPEC.md).
- The ratchet, the 5 novel checks, and the policy — the moat — are unaffected by where the code lives.
