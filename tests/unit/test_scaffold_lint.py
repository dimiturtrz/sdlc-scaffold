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
from _meta import copier_default, per_file_ignores_for_tests  # noqa: E402  (shared copier.yml reader, one home)


def test_scaffold_own_code_passes_house_ruff():
    ruff = f"ruff@{copier_default('ruff_version')}"
    select = copier_default("ruff_select")
    # The `tests/**` carve-out is READ from the template (tests_per_file_ignores), not restated here — a hand
    # copy already drifted, dropping SLF001 and holding the scaffold's own tests STRICTER than consumers by
    # accident (bd 1gj). One home means the two move together.
    tests_ignore = per_file_ignores_for_tests()
    result = subprocess.run(  # noqa: S603 (controlled arg list — no shell/untrusted input)
        ["uvx", ruff, "check", "tests", "--select", select, "--ignore", tests_ignore],  # noqa: S607 (uvx on PATH)
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"scaffold must pass its own house ruff bar:\n{result.stdout}\n{result.stderr}"
