"""Shared scaffold-metadata helpers for the test suites (single home for the copier.yml readers)."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # tests/_meta.py -> scaffold root


def copier_default(key: str) -> str:
    """A `when: false` constant's default read straight from copier.yml — the single source of truth
    for pinned versions + the ruff select. Regex-parsed to avoid a PyYAML dependency in the test env."""
    text = (REPO / "copier.yml").read_text(encoding="utf-8")
    # `[^"]*` not `[^"]+`: an EMPTY default is a real, meaningful value — ruff_advisory_select is `""`
    # whenever every advisory code has graduated into the enforced union. With `+` this raised "no default
    # found", which reads as a malformed copier.yml, and made `_assert_advisory_surface`'s else-branch
    # (the one asserting no `--extend-select` is emitted) unreachable.
    match = re.search(rf'^{key}:\n(?:  .*\n)*?  default: "([^"]*)"', text, re.M)
    if match is None:
        msg = f"copier.yml: no default found for {key!r}"
        raise RuntimeError(msg)
    return match.group(1)


def per_file_ignores_for_tests() -> str:
    """The `tests/**` per-file-ignores carve-out read straight from the template — the single source of
    truth, so the scaffold's own test bar cannot silently drift STRICTER (or looser) than the one it ships.
    Returned comma-joined for `ruff --ignore`. Missing it is a malformed template, not an empty carve-out."""
    text = (REPO / "template" / "pyproject.toml.jinja").read_text(encoding="utf-8")
    match = re.search(r'^"tests/\*\*"\s*=\s*\[([^\]]*)\]', text, re.M)
    if match is None:
        msg = "template/pyproject.toml.jinja: no `tests/**` per-file-ignores found"
        raise RuntimeError(msg)
    return ",".join(re.findall(r'"([^"]+)"', match.group(1)))
