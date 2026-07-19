"""Guards that non-rendered scaffold-root files stay in sync with copier.yml's single source.

`.pre-commit-hooks.yaml` (the remote-delivery manifest) is NOT jinja-rendered, so its pinned tool
versions can silently drift from copier.yml when a version is bumped. This guard fails the drift.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
from _meta import copier_default  # noqa: E402  (shared copier.yml reader, one home)


def test_pre_commit_hooks_versions_match_single_source():
    hooks = (REPO / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    ruff_v, vulture_v = copier_default("ruff_version"), copier_default("vulture_version")
    assert f"ruff@{ruff_v}" in hooks, f"manifest must pin ruff@{ruff_v}"
    assert f"vulture@{vulture_v}" in hooks, f"manifest must pin vulture@{vulture_v}"
    # no stray pin at a different version may sneak in
    assert set(re.findall(r"ruff@([0-9.]+)", hooks)) == {ruff_v}, "stray ruff version in the manifest"
    assert set(re.findall(r"vulture@([0-9.]+)", hooks)) == {vulture_v}, "stray vulture version in the manifest"


def test_python_template_lines_fit_the_line_limit():
    """A python TEMPLATE cannot be ruff-formatted (jinja tags are not valid python), so an over-long line
    only surfaces ~80s later when the e2e runs `ruff format --check` on a GENERATED project. This catches
    it in milliseconds instead.

    Only jinja-FREE lines are checked, and that is exact rather than approximate: a substitution such as
    `{{ pyrefly_version }}` only ever SHRINKS (to `1.1.1`), so a line with no tags renders at its own
    length. Bit me twice — the pyrefly and demeter nox steps (bd 4bl.1 / 4bl.5)."""
    limit = 120
    offenders = []
    for template in Path("template").rglob("*.py.jinja"):
        for lineno, line in enumerate(template.read_text(encoding="utf-8").splitlines(), start=1):
            if "{{" in line or "{%" in line or len(line) <= limit:
                continue
            offenders.append(f"{template.as_posix()}:{lineno} ({len(line)} > {limit})")
    assert not offenders, "jinja-free template lines must render within the ruff line limit:\n  " + "\n  ".join(
        offenders
    )
