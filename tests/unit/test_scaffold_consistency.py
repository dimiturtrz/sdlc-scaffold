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


_RUNNERS = {
    "ci.yml": "template/.github/workflows/ci.yml.jinja",
    "noxfile": "template/noxfile.py.jinja",
    "pre-commit": "template/.pre-commit-config.yaml.jinja",
}


def _enforced_gates(text: str) -> set[str]:
    """The devtools engines this runner invokes as a GATE (`--assert`), by module name.

    Windowed rather than line-based on purpose: ci.yml puts the module and `--assert` on one line, while a
    formatted nox `session.run(...)` spreads them over several.
    """
    return {
        match.group(1)
        for match in re.finditer(r"devtools\.(\w+)", text)
        if "--assert" in text[match.start() : match.start() + 250]
    }


def test_every_enforced_gate_is_wired_into_all_three_runners():
    """A gate wired into only SOME runners is INVISIBLE: a missing gate cannot fail, so the e2e — which
    proves gates BITE — stays green while that gate silently never runs there.

    This is not hypothetical: the demeter nox step was lost to a stray `git checkout` of the template
    noxfile and would have shipped wired into ci + pre-commit but not nox, with every test still passing.
    The expected set is derived from the files themselves, so it cannot drift out of date.
    """
    found = {label: _enforced_gates(Path(path).read_text(encoding="utf-8")) for label, path in _RUNNERS.items()}
    everywhere = set.intersection(*found.values())
    missing = {label: sorted(gates - everywhere) for label, gates in found.items() if gates - everywhere}
    assert not missing, "enforced gates must run in EVERY runner; these are wired in only some:\n  " + "\n  ".join(
        f"{label}: only there -> {gates}" for label, gates in missing.items()
    )
