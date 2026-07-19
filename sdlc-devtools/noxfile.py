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

nox.options.sessions = ["lint", "test", "cov"]

RUFF = "ruff@0.15.13"
VULTURE = "vulture@2.14"
PYREFLY = "pyrefly==1.1.1"
# devtools imports as `devtools` but the CLI contract is unchanged; the whole package is one layer.
LAYER = "devtools"
# The vendored cytoscape/fcose bundles are third-party code we do not author. Excluded on the CLI rather
# than in devtools/jscpd.json, because that config SHIPS to consumers and this path is ours alone.
JSCPD_IGNORE = "**/archviz/**"
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
    # Advisory, matching the template's posture. It was ABSENT here, and absence is why four files drifted
    # out of format unnoticed — the package can only be told it is clean by a gate that runs (bd iv5).
    session.run("uvx", RUFF, "format", "--check", LAYER, external=True, success_codes=[0, 1])
    # ENFORCED dead code — measured at 0 findings on conf80 AND conf60, so it blocks from day one.
    session.run("uvx", VULTURE, LAYER, "--min-confidence", "80", external=True)
    session.run("uvx", VULTURE, LAYER, "--min-confidence", "60", external=True, success_codes=[0, 3])
    # ADVISORY-with-a-graduation-path: pyrefly strict had never run on the package that makes strict typing
    # a BLOCKING house rule for consumers. First pass took it 52 -> 10. It reports without failing until it
    # reaches 0, then the success_codes swallow comes off and it blocks like everyone else's. Wired-but-
    # advisory is a ratchet with the work visible; ABSENT is indistinguishable from clean, which is the bug.
    session.run("uv", "run", "--with", PYREFLY, "pyrefly", "check", LAYER, external=True, success_codes=[0, 1])
    # ENFORCED duplication — 0.00% on python at the shipped minTokens. Note it does NOT find the 17x main()
    # plumbing (bd 0y9): jscpd is token-based and each main() carries a different argparse description, so
    # they are textually distinct despite being structurally identical. Measured, not assumed.
    session.run(
        "npx", "--yes", "jscpd", LAYER, "--config", "devtools/jscpd.json", "--ignore", JSCPD_IGNORE, external=True
    )
    # god-module / import-cycle / god-file AND test-mirror — the FULL --assert (engines carry their mirrors).
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.graph", LAYER, "--assert", external=True)
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.demeter", LAYER, "--assert", external=True)
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.composition", LAYER, "--assert", external=True)
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.contracts", LAYER, "--assert", external=True)
    session.run("uv", "run", "--group", "dev", "python", "-m", "devtools.envy", LAYER, "--assert", external=True)
    # class-shape: every helper is a method on its engine class, only main() top-level. Config ships in the
    # package (devtools/sgconfig.yml), so ast-grep reads it in place — no `python -m devtools.config` hop.
    session.run(
        "uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", LAYER, external=True
    )
    # Dependency hygiene — deptry (config in [tool.deptry]); env-aware via `--with` so it reads installed
    # dist metadata (transitive detection). Blocks on undeclared/unused/transitive imports.
    session.run("uv", "run", "--with", "deptry", "--group", "dev", "deptry", ".", external=True)
    # The full ADVISORY explorer set the template ships — ranked reports that always exit 0 (the fixed
    # complexity gate is ruff C901; there is no honest universal magic-literal ceiling). All but the first
    # two were absent here, so the package shipped reports it never read about itself.
    for tool in ("magic_literals", "complexity", "lcom", "data_clumps", "state_candidates", "arrows", "calls"):
        session.run("uv", "run", "--group", "dev", "python", "-m", f"devtools.{tool}", LAYER, external=True)
    # Class roles: ADVISORY here and everywhere. 16/13/11 findings across the three consumer repos even
    # after the az9 fix, and those survivors are genuine multi-abstraction files, i.e. real refactoring
    # work rather than a classifier bug. It graduates when a real tree is clean (the shape_contracts rule).
    session.run(
        "uv", "run", "--group", "dev", "python", "-m", "devtools.classes", LAYER, external=True, success_codes=[0, 1]
    )
    # Self-scaffolding (advisory): the scaffold maps its OWN guardrail engines — archmap --check flags a
    # stale committed docs/architecture/graph.json. Regenerate with `python -m devtools.archmap devtools`.
    # success_codes swallows the exit-1-on-drift so it reports without blocking (doc-gen, not a gate).
    session.run(
        "uv",
        "run",
        "--group",
        "dev",
        "python",
        "-m",
        "devtools.archmap",
        LAYER,
        "--check",
        external=True,
        success_codes=[0, 1],
    )


@nox.session(venv_backend="none")
def test(session: nox.Session) -> None:
    """The per-engine mirror tests (the analyzers' own guardrails)."""
    session.run("uv", "run", "--group", "dev", "pytest", "tests", "-q", external=True)


@nox.session(venv_backend="none")
def cov(session: nox.Session) -> None:
    """Coverage with a floor — the last gate the template shipped that this package did not run (bd iv5).

    The floor is the template's own default (80), NOT a number fitted to what devtools happens to score.
    Measured at 82% when wired, so it blocks with real headroom rather than being set to whatever passed.
    """
    session.run(
        "uv", "run", "--group", "dev", "pytest", "tests", "-q", "--cov", "--cov-report=term-missing", external=True
    )
    session.run("uv", "run", "--group", "dev", "coverage", "report", "--fail-under=80", external=True)
    # Advisory 95% target — coverage exits 2 when under, which success_codes swallows (mirrors the template).
    session.run(
        "uv", "run", "--group", "dev", "coverage", "report", "--fail-under=95", external=True, success_codes=[0, 2]
    )
