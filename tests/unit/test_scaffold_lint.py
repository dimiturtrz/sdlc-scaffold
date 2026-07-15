"""Repo eats its own dogfood — the scaffold's OWN Python meets the house ruff bar (bd uo0.3).

The scaffold is the standard-setter, so its own test/meta code (`tests/`, `_meta.py`) is held to the same
curated ruff select it ships to consumers (single-sourced from copier.yml). This runs as a fast unit gate
(no generation), separate from the slow e2e. The `tests/**` carve-out mirrors the template's own
per-file-ignores (template/pyproject.toml.jinja) — asserts are the point of a test, magic numbers and
FBT-style bool args are idiomatic there. The devtools PACKAGE has its OWN gate (sdlc-devtools/noxfile.py,
uo0.2); this covers the SCAFFOLD half of the monorepo.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
from _meta import copier_default  # noqa: E402  (shared copier.yml reader, one home)

# Mirrors template/pyproject.toml.jinja [tool.ruff.lint.per-file-ignores] "tests/**": asserts/magic/bool
# args/naming are idiomatic in tests; the real-bug + import-order + dead-code gates still apply.
TESTS_IGNORE = "S101,PLR2004,FBT,N801,N802,N803,N806,N812,PLR0913"


def test_scaffold_own_code_passes_house_ruff():
    ruff = f"ruff@{copier_default('ruff_version')}"
    select = copier_default("ruff_select")
    result = subprocess.run(  # noqa: S603 (controlled arg list — no shell/untrusted input)
        ["uvx", ruff, "check", "tests", "--select", select, "--ignore", TESTS_IGNORE],  # noqa: S607 (uvx on PATH)
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"scaffold's own code must pass the house ruff bar:\n{result.stdout}\n{result.stderr}"
