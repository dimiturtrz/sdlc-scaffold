"""Guards that non-rendered scaffold-root files stay in sync with copier.yml's single source.

`.pre-commit-hooks.yaml` (the remote-delivery manifest) is NOT jinja-rendered, so its pinned tool
versions can silently drift from copier.yml when a version is bumped. This guard fails the drift.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _copier_default(key: str) -> str:
    text = (REPO / "copier.yml").read_text(encoding="utf-8")
    match = re.search(rf'^{key}:\n(?:  .*\n)*?  default: "([^"]+)"', text, re.M)
    assert match, f"copier.yml: no default for {key!r}"
    return match.group(1)


def test_pre_commit_hooks_versions_match_single_source():
    hooks = (REPO / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    ruff_v, vulture_v = _copier_default("ruff_version"), _copier_default("vulture_version")
    assert f"ruff@{ruff_v}" in hooks, f"manifest must pin ruff@{ruff_v}"
    assert f"vulture@{vulture_v}" in hooks, f"manifest must pin vulture@{vulture_v}"
    # no stray pin at a different version may sneak in
    assert set(re.findall(r"ruff@([0-9.]+)", hooks)) == {ruff_v}, "stray ruff version in the manifest"
    assert set(re.findall(r"vulture@([0-9.]+)", hooks)) == {vulture_v}, "stray vulture version in the manifest"
