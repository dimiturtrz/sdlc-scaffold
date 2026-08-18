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


# Scaffold-owned python that is NOT a test, so it meets the house bar with no carve-out at all — the tests
# ignore list exists because asserts and magic numbers are idiomatic IN A TEST, and a release script is not
# one. Was gated by nothing (bd muz); the T201 prints it opened at are now `logging`, as devtools' own
# entrypoints already were.
_OWN_SCRIPTS = ("sync_version.py",)
# Every scaffold-owned .py outside the devtools package, which gates itself (sdlc-devtools/noxfile.py). The
# generated project's tree is `template/`'s business and is proven by the e2e, not from here.
_OWN_PYTHON = ("tests", *_OWN_SCRIPTS)


def test_scaffold_own_scripts_pass_house_ruff_without_the_tests_carve_out():
    """The full house select on the non-test scripts — a SEPARATE run from the tests one on purpose.

    Folding them into that invocation would have been one line shorter and wrong: `--ignore` is per-run, so
    the tests carve-out (S101, PLR2004, FBT, SLF001, …) would have silently applied to a release script that
    has no claim to it, gating it at a weaker bar than the file it edits.
    """
    ruff = f"ruff@{copier_default('ruff_version')}"
    select = copier_default("ruff_select")
    result = subprocess.run(  # noqa: S603 (controlled arg list — no shell/untrusted input)
        ["uvx", ruff, "check", *_OWN_SCRIPTS, "--select", select],  # noqa: S607 (uvx on PATH)
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"scaffold scripts must pass the FULL house bar:\n{result.stdout}\n{result.stderr}"


def test_scaffold_own_code_is_ruff_formatted():
    """`ruff format --check` on the scaffold's own python — the check it ships to consumers as ENFORCED.

    Wired because it was not, and three files had drifted (bd 0t5): `sync_version.py` was gated by nothing at
    all, and `tests/` was ruff CHECKed by the test above while nothing ever looked at its formatting. Since
    09f6bf8 a consumer cannot merge an unformatted tree, so the scaffold failing its own shipped gate is the
    defect — the standard-setter is the one repo that must not need the exemption.

    Enforced from the start rather than advisory: the graduation bar is a clean tree, the three files were
    formatted in the same commit that added this, and an advisory format check is precisely what let those
    three drift in the package half (bd iv5 -> 0t5).
    """
    ruff = f"ruff@{copier_default('ruff_version')}"
    result = subprocess.run(  # noqa: S603 (controlled arg list — no shell/untrusted input)
        ["uvx", ruff, "format", "--check", *_OWN_PYTHON],  # noqa: S607 (uvx on PATH)
        cwd=str(REPO),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"scaffold must pass the format gate it ships:\n{result.stdout}\n{result.stderr}"
