"""Dogfood — the devtools PACKAGE's engines meet the FULL bar they enforce (bd dud + vip 16y/p99).

The engines now live in the `sdlc-devtools/` package (imported as `devtools`). This runs the package's own
gate set from the scaffold CI, so the monorepo gates its analyzers with the same checks it ships to
consumers — ruff + graph `--assert` (god-module/cycle/god-file AND test-mirror) + ast-grep class-shape +
magic-literals, zero carve-outs — plus the package's own pytest (the per-engine mirror tests). Config
(sgconfig/sg-rules/jscpd) ships inside the package, so the ast-grep run reads it in place.
"""

import pytest

from conftest import REPO, RUFF, SELECT, run

pytestmark = pytest.mark.slow

PKG = REPO / "sdlc-devtools"
# After the _common.py extraction the engines legitimately repeat exactly two value-position tokens —
# 'utf-8' (read_text encoding) and 'packages' (the shared CLI positional). Freeze that floor; a 3rd bites.
MAGIC_MAX_STRINGS = "2"
MAGIC_MAX_KEY_SETS = "0"


def _engine(*args):
    """Invoke a devtools engine ON the package's own devtools/ (cwd=package so `devtools` imports)."""
    return run(["uv", "run", "--group", "dev", "python", "-m", *args], PKG)


def test_package_pytest():
    # the per-engine mirror tests (the analyzers' own guardrails) — 56 cases incl the config locator.
    run(["uv", "run", "--group", "dev", "pytest", "tests", "-q"], PKG)


def test_package_ruff_clean():
    run(["uvx", RUFF, "check", "devtools", "--select", SELECT, "--ignore", "F722,F821"], PKG)


def test_package_arch_fitness_clean():
    # god-module / import-cycle / god-file AND test-mirror — the FULL --assert (engines carry their mirrors).
    _engine("devtools.graph", "devtools", "--assert")


def test_package_class_shape_clean():
    # ast-grep house rule — every helper is a method on its engine class; only main() is top-level. Config
    # ships in the package, so it reads in place.
    run(["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", "devtools"], PKG)


def test_package_magic_under_ceiling():
    _engine("devtools.magic_literals", "devtools", "--max-strings", MAGIC_MAX_STRINGS, "--max-key-sets", MAGIC_MAX_KEY_SETS)
