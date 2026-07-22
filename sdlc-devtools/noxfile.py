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
    "E402,ICN001,S603,S607,PTH123,TID251,E501,SLF001,PGH003,PGH004"
)
# The package ships gates but never linted its OWN ~300 unit tests (bd a19) — LAYER is the package alone. The
# `tests/**` carve-out is the template's, mirrored here by hand for the same standalone reason SELECT is: a
# tests-only gate cannot read the scaffold's copier.yml. Asserts/magic/bool-args/mock-PascalCase/privates-
# under-test/fixture-params are idiomatic in tests; the real-bug + import-order + dead-code gates still bite.
TESTS = "tests"
TESTS_IGNORE = "F722,F821,S101,PLR2004,FBT,SLF001,N801,N802,N803,N806,N812,PLR0913"


@nox.session(venv_backend="none")
def lint(session: nox.Session) -> None:
    """ruff + arch-fitness (--assert) + ast-grep class-shape + magic-literal ratchet — the enforced bar."""
    session.run("uvx", RUFF, "check", LAYER, "--select", SELECT, "--ignore", "F722,F821", external=True)
    # The test suite meets the SAME house bar, minus the tests carve-out — symmetry with the scaffold half,
    # which lints its own tests via test_scaffold_lint.py. Was unlinted entirely (bd a19).
    session.run("uvx", RUFF, "check", TESTS, "--select", SELECT, "--ignore", TESTS_IGNORE, external=True)
    # Advisory, matching the template's posture. It was ABSENT here, and absence is why four files drifted
    # out of format unnoticed — the package can only be told it is clean by a gate that runs (bd iv5).
    session.run("uvx", RUFF, "format", "--check", LAYER, external=True, success_codes=[0, 1])
    # ENFORCED dead code — measured at 0 findings on conf80 AND conf60, so it blocks from day one.
    session.run("uvx", VULTURE, LAYER, "--min-confidence", "80", external=True)
    session.run("uvx", VULTURE, LAYER, "--min-confidence", "60", external=True, success_codes=[0, 3])
    # ENFORCED — GRADUATED advisory -> blocking (bd dun.2). pyrefly strict had never run on the package that
    # makes strict typing a blocking house rule for consumers; it opened at 52 errors and is now at 0, so the
    # success_codes swallow came off. The package selling the rule is now held to it exactly like a consumer.
    session.run("uv", "run", "--with", PYREFLY, "pyrefly", "check", LAYER, external=True)
    # ENFORCED duplication — 0.00% on python at the shipped minTokens. Note it does NOT find the 17x main()
    # plumbing (bd 0y9): jscpd is token-based and each main() carries a different argparse description, so
    # they are textually distinct despite being structurally identical. Measured, not assumed.
    session.run(
        "npx", "--yes", "jscpd", LAYER, "--config", "devtools/jscpd.json", "--ignore", JSCPD_IGNORE, external=True
    )
    # EVERY python analyzer, in ONE process (bd f9y.3). Twelve `python -m devtools.X` calls paid to start an
    # interpreter and import devtools twelve times over, for analysis that is a fraction of the cost; the
    # batch runner pays it once and shares one parse of the tree between the engines that resolve names.
    # Measured here: 1855ms -> 673ms. Which engines GATE and which merely report stays right here, in the
    # runner config, because that is a per-repo policy decision and not something the runner should infer.
    session.run(
        "uv", "run", "--group", "dev", "python", "-m", "devtools.run", LAYER,
        # god-module / import-cycle / god-file / test-mirror, then the arrow-level gates
        "--gate", "graph,demeter,purity,composition,contracts,envy,astgrep,mirror,small",
        # ADVISORY explorers — ranked reports that never fail. `classes` is here rather than under --gate
        # for the reason it is advisory everywhere: its survivors are genuine multi-abstraction files, i.e.
        # refactoring work rather than a classifier bug. It graduates when a real tree reaches zero.
        "--report", "magic_literals,complexity,lcom,data_clumps,state_candidates,arrows,calls,classes",
        external=True,
    )
    # (class-shape — every helper a method on its engine class, only main() top-level — rides the batch run
    # above as `astgrep`. It shells out to the vendored CLI, but it answers the same two verbs as the AST
    # engines, so there is no reason for the runner to know the difference or for this file to re-encode
    # the invocation a third time.)
    # Dependency hygiene — deptry (config in [tool.deptry]); env-aware via `--with` so it reads installed
    # dist metadata (transitive detection). Blocks on undeclared/unused/transitive imports.
    session.run("uv", "run", "--with", "deptry", "--group", "dev", "deptry", ".", external=True)
    # (the advisory explorer set — magic_literals / complexity / lcom / data_clumps / state_candidates /
    # arrows / calls, plus class-roles — now rides the single batch run above rather than seven more
    # interpreter starts. Class roles stays ADVISORY here and everywhere: 16/13/11 findings across the
    # three consumer repos even after the az9 fix, and those survivors are genuine multi-abstraction files,
    # i.e. real refactoring work rather than a classifier bug. It graduates when a real tree is clean.)
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
