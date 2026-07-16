"""Standalone gate runner for sdlc-devtools (the analyzer package).

`cd sdlc-devtools && uvx nox@2026.7.11` runs the package's FULL self-gate with ZERO scaffold dependency:
the engines meet the same bar they enforce on consumers — ruff + import-graph arch-fitness (god-module /
cycle / god-file / test-mirror) + ast-grep class-shape + magic-literal ratchet — plus the per-engine mirror
tests. This is the same gate set the scaffold's dogfood e2e (tests/e2e/test_dogfood.py) drives; owning it
HERE makes the package independently maintainable and extraction-ready (bd uo0.2): lift the dir out, keep
this file, done. Sessions shell to uvx/uv run with pinned tool versions (venv_backend="none") so a local run
matches CI exactly.

The tool pins + ruff select below are duplicated from the scaffold's copier.yml ON PURPOSE — a standalone
package cannot read the scaffold's answer file. This is the seam: the scaffold is the POLICY source, the
package pins its own copy so it can gate itself alone. On extraction the duplication becomes ownership.
"""

import nox

nox.options.sessions = ["lint", "test"]

RUFF = "ruff@0.15.13"
# devtools imports as `devtools` but the CLI contract is unchanged; the whole package is one layer.
LAYER = "devtools"
# Curated-narrow select — the scaffold's house set (copier.yml ruff_select). F722/F821 ignored: the engines
# are jaxtyping-free, but keeping the ignore matches the scaffold CLI invocation byte-for-byte.
SELECT = (
    "F,B,I,T201,FBT,BLE001,S101,S110,C901,PLR0912,PLR0913,PLR0915,PLR2004,PLC0415,RUF100,N,E741,E742,E743,"
    "PLR0124,PLR1714,PLW3301,RUF012,RUF005,RUF007,RUF010,RUF022,RUF046,C408,C420,SIM,PERF401,PLW0108,E731,"
    "E402,ICN001,S603,S607,PTH123"
)


@nox.session(venv_backend="none")
def lint(session: nox.Session) -> None:
    """ruff + arch-fitness (--assert) + ast-grep class-shape + magic-literal ratchet — the enforced bar."""
    session.run("uvx", RUFF, "check", LAYER, "--select", SELECT, "--ignore", "F722,F821", external=True)
    # god-module / import-cycle / god-file AND test-mirror — the FULL --assert (engines carry their mirrors).
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.graph", LAYER, "--assert", external=True)
    # class-shape: every helper is a method on its engine class, only main() top-level. Config ships in the
    # package (devtools/sgconfig.yml), so ast-grep reads it in place — no `python -m devtools.config` hop.
    session.run(
        "uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", LAYER, external=True
    )
    # Dependency hygiene — deptry (config in [tool.deptry]); env-aware via `--with` so it reads installed
    # dist metadata (transitive detection). Blocks on undeclared/unused/transitive imports.
    session.run("uv", "run", "--with", "deptry", "--group", "dev", "deptry", ".", external=True)
    # ADVISORY explorers — recurring magic literals + radon cyclomatic complexity. Ranked reports, always
    # exit 0 (the fixed complexity gate is ruff C901; there is no honest universal magic-literal ceiling).
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.magic_literals", LAYER, external=True)
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.complexity", LAYER, external=True)
    # Self-scaffolding (advisory): the scaffold maps its OWN guardrail engines — archmap --check flags a
    # stale committed docs/architecture/graph.json. Regenerate with `python -m devtools.archmap devtools`.
    # success_codes swallows the exit-1-on-drift so it reports without blocking (doc-gen, not a gate).
    session.run(
        "uv", "run", "--group", "dev", "python", "-m", "devtools.archmap", LAYER, "--check",
        external=True, success_codes=[0, 1],
    )


@nox.session(venv_backend="none")
def test(session: nox.Session) -> None:
    """The per-engine mirror tests (the analyzers' own guardrails)."""
    session.run("uv", "run", "--group", "dev", "pytest", "tests", "-q", external=True)
