"""Shared scaffold-metadata helpers for the test suites (single home for the copier.yml readers)."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # tests/_meta.py -> scaffold root


def copier_default(key: str) -> str:
    """A `when: false` constant's default read straight from copier.yml — the single source of truth
    for pinned versions + the ruff select. Regex-parsed to avoid a PyYAML dependency in the test env."""
    text = (REPO / "copier.yml").read_text(encoding="utf-8")
    match = re.search(rf'^{key}:\n(?:  .*\n)*?  default: "([^"]+)"', text, re.M)
    if match is None:
        msg = f"copier.yml: no default found for {key!r}"
        raise RuntimeError(msg)
    return match.group(1)
