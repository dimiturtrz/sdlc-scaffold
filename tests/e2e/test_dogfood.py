"""Dogfood — the devtools PACKAGE meets the FULL bar it enforces (bd dud + vip 16y/p99 + uo0.2).

The engines live in the `sdlc-devtools/` package (imported as `devtools`) and own their gate set in their
OWN standalone noxfile (sdlc-devtools/noxfile.py) — ruff + import-graph arch-fitness (god-module / cycle /
god-file / test-mirror) + ast-grep class-shape + deptry + advisory explorers + the per-engine mirror tests, zero
carve-outs. This e2e drives that noxfile from the scaffold CI, so a single command validates BOTH that the
analyzers pass their own bar AND that the standalone gate target works with no scaffold dependency (uo0.2).
The gate LOGIC has one home (the package noxfile); this file only asserts it runs green.
"""

import pytest
from conftest import NOX, REPO, run

pytestmark = pytest.mark.slow

PKG = REPO / "sdlc-devtools"


def test_package_self_gate_clean():
    # `uvx nox` in the package dir = its full lint+test bar; no scaffold test code imported (uo0.2).
    run(["uvx", NOX], PKG)
