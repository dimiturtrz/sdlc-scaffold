"""Guards that non-rendered scaffold-root files stay in sync with copier.yml's single source.

`.pre-commit-hooks.yaml` (the remote-delivery manifest) is NOT jinja-rendered, so its pinned tool
versions can silently drift from copier.yml when a version is bumped. This guard fails the drift.
"""

import itertools
import re
import subprocess
import sys
from pathlib import Path

import jinja2

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
from _meta import copier_default  # noqa: E402  (shared copier.yml reader, one home)

# The `{{ version }}` substitutions the python templates read, resolved from copier.yml so the rendered
# output is pinned to exactly what a consumer receives.
_PINNED_VERSIONS = ("ruff_version", "vulture_version", "deptry_version", "pyrefly_version", "pip_audit_version")
_CAPTURE = {"capture_output": True, "text": True, "cwd": REPO, "check": False}


def test_pre_commit_hooks_versions_match_single_source():
    hooks = (REPO / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    ruff_v, vulture_v = copier_default("ruff_version"), copier_default("vulture_version")
    assert f"ruff@{ruff_v}" in hooks, f"manifest must pin ruff@{ruff_v}"
    assert f"vulture@{vulture_v}" in hooks, f"manifest must pin vulture@{vulture_v}"
    # no stray pin at a different version may sneak in
    assert set(re.findall(r"ruff@([0-9.]+)", hooks)) == {ruff_v}, "stray ruff version in the manifest"
    assert set(re.findall(r"vulture@([0-9.]+)", hooks)) == {vulture_v}, "stray vulture version in the manifest"


# Every {% if %} switch in the python templates. Rendering the full matrix (2^n) is what makes this exact:
# a branch nobody generates locally is still a branch a consumer gets.
_TEMPLATE_SWITCHES = ("enable_ml", "use_import_linter", "ruff_advisory_select")


def _render(template: Path, switches: dict) -> str:
    """The template as a consumer would receive it, for one branch combination.

    The context is CONCRETE, not copier's own defaults: `packages` and friends default to jinja expressions
    (`{{ project_name.replace('-', '_') }}`) that copier resolves itself. Resolving them here would test
    copier, which the e2e already does — this test is about the FORMAT of the python that comes out.
    """
    context = {
        "project_name": "demo",
        "packages": "demo",
        "lint_paths": "demo",
        "jscpd_paths": "demo",
        "coverage_floor": "80",
        **{key: copier_default(key) for key in _PINNED_VERSIONS},
        **switches,
    }
    source = template.read_text(encoding="utf-8")
    return jinja2.Template(source, keep_trailing_newline=True).render(**context)


def test_python_templates_render_exactly_as_ruff_would_format_them(tmp_path):
    """A python TEMPLATE cannot itself be ruff-formatted (jinja tags are not valid python), so drift in its
    OUTPUT used to surface ~90s later when the e2e formatted a generated project. This renders every branch
    combination and checks the result directly, in milliseconds.

    It supersedes an earlier heuristic that only compared jinja-free lines against the 120 limit. That
    caught one direction — a line too LONG — and was blind to the opposite: a call wrapped across lines that
    ruff would JOIN because the single-line form fits. Which is exactly what shipped three times (the
    pyrefly, demeter and envy nox steps); the joined envy form is 120 chars, fitting by one character.

    Both directions are covered because `ruff format --check` is the real formatter and `--select E501`
    catches the long line ruff cannot split (a long string literal), which formatting alone leaves alone.

    DELIBERATELY STRICTER than what a consumer's own gates enforce. Their blocking `ruff check` runs over
    lint_paths (the package dirs), so a generated `noxfile.py` is only ever seen by the ADVISORY whole-tree
    run and can carry a violation forever as report noise. These are files WE author and ship, so they are
    held to the enforced bar here — which is how this test's first run found a 125-char line reachable only
    when use_import_linter is on, a branch no e2e combo generates.
    """
    templates = sorted(Path("template").rglob("*.py.jinja"))
    assert templates, "no python templates found — the glob or the layout moved"

    rendered = {}
    for template in templates:
        for combination in itertools.product([False, True], repeat=len(_TEMPLATE_SWITCHES)):
            switches = dict(zip(_TEMPLATE_SWITCHES, combination, strict=True))
            # ruff_advisory_select is read BOTH as a switch and as a value, so its "on" state needs a code
            name = "-".join(k for k, on in switches.items() if on) or "none"
            variant = {**switches, "ruff_advisory_select": "ARG" if switches["ruff_advisory_select"] else ""}
            path = tmp_path / f"{template.name.removesuffix('.py.jinja')}__{name}.py"
            path.write_text(_render(template, variant), encoding="utf-8")
            rendered[path.name] = f"{template.as_posix()} [{name}]"

    # the PINNED ruff, so this agrees with what CI enforces rather than with whatever is on PATH
    ruff = ["uvx", f"ruff@{copier_default('ruff_version')}"]
    fmt = subprocess.run([*ruff, "format", "--check", "--line-length", "120", tmp_path], **_CAPTURE)  # noqa: S603
    lint = subprocess.run(  # noqa: S603
        [*ruff, "check", "--select", "E501", "--line-length", "120", "--no-cache", tmp_path], **_CAPTURE
    )
    assert fmt.returncode == 0 and lint.returncode == 0, (
        "a rendered template does not match what ruff would produce. Variants map to sources as:\n  "
        + "\n  ".join(f"{name} <- {src}" for name, src in sorted(rendered.items()))
        + f"\n--- ruff format ---\n{fmt.stdout}{fmt.stderr}\n--- E501 ---\n{lint.stdout}{lint.stderr}"
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
