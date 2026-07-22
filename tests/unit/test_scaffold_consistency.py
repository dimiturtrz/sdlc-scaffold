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
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))
from _meta import copier_default  # noqa: E402  (shared copier.yml reader, one home)

# The `{{ version }}` substitutions the python templates read, resolved from copier.yml so the rendered
# output is pinned to exactly what a consumer receives.
_PINNED_VERSIONS = ("ruff_version", "vulture_version", "deptry_version", "pyrefly_version", "pip_audit_version")
_CAPTURE = {"capture_output": True, "text": True, "cwd": REPO, "check": False}
_TEMPLATE_PYPROJECT = (REPO / "template" / "pyproject.toml.jinja").read_text(encoding="utf-8")


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


def test_the_readme_headline_version_matches_the_package():
    """The README front page names a version, and nothing watched it — it sat at v1.2 while the package
    reached 1.20.0, an eighteen-version drift claiming a feature set that had been superseded twice over.
    Compared at major.minor, since the README describes a release rather than a patch (bd ztw)."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    package = (REPO / "sdlc-devtools" / "pyproject.toml").read_text(encoding="utf-8")
    claimed = re.search(r"^\*\*v([0-9]+\.[0-9]+)", readme, re.M)
    actual = re.search(r'^version = "([0-9]+\.[0-9]+)', package, re.M)
    assert claimed and actual, "README must open with **vX.Y** and the package must declare a version"
    assert claimed.group(1) == actual.group(1), (
        f"README claims v{claimed.group(1)} but sdlc-devtools is {actual.group(1)} — "
        "the front page describes the shipped release, so it cannot lag it"
    )


def test_the_shipped_devtools_pin_matches_the_package_version():
    """`devtools_ref` is the ONLY thread joining a consumer to an analyzer release — it renders into every
    generated pyproject as `sdlc-devtools @ git+...@{ref}`. copier.yml already STATES the rule ("Must track
    the tag the matching sdlc-devtools/ was published at"); nothing enforced it, so the pin shipped naming a
    v1.20.0 tag that did not exist, and any `copier update` would have written a project whose `uv sync`
    cannot resolve its own analyzers.

    The e2e cannot catch this by construction: it injects a `[tool.uv.sources]` override so a generated
    project builds the LOCAL package instead of fetching the ref. That is right for testing unreleased code,
    and it is precisely why the pin is never resolved by anything the suite runs — so it is checked here.

    Only that the two AGREE. Whether the tag is published is release-time, and `release.yml` settles it by
    deriving the tag from this same version on merge.
    """
    package = (REPO / "sdlc-devtools" / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', package, re.M)
    assert version, "sdlc-devtools/pyproject.toml must declare a version"
    pin, expected = copier_default("devtools_ref"), f"v{version.group(1)}"
    assert pin == expected, (
        f"copier.yml ships devtools_ref={pin!r} but sdlc-devtools is {version.group(1)} (expected "
        f"{expected!r}) — every generated project would pin analyzers from the wrong release"
    )


def test_the_template_only_calls_engines_the_pinned_release_actually_has():
    """The template invokes `python -m devtools.<mod>`; `devtools_ref` decides WHICH devtools a consumer
    installs. If the template starts calling a module newer than that pin, `copier update` hands them a
    runner that dies with ModuleNotFoundError on the next lint.

    Not hypothetical: batching the gates behind `devtools.run` (bd f9y.3) landed while devtools_ref still
    pointed at v1.20.0, which predates run.py. Nothing caught it — the version-agreement test passes when
    all three homes say 1.20.0, and the e2e cannot see it because it overrides the pin with the
    working-tree package, so it tests the template against code no consumer has yet.

    Skipped when the pinned tag does not exist, because that is a RELEASE in progress: this PR bumps the
    version and merging cuts the tag from this very tree, so the modules are there by construction.
    """
    referenced = {
        match.group(1)
        for path in _RUNNERS.values()
        # anchored on `-m`, so only a real invocation counts — `"-m", "devtools.run"` and
        # `python -m devtools.graph.fitness` both match, while prose naming a module does not. `[\w.]+` spans
        # the subpackage (bd 5hg): a gate lives at a DOTTED path now, so `\w+` would capture only the folder.
        for match in re.finditer(r"-m[\"',\s]+devtools\.([\w.]+)", Path(path).read_text(encoding="utf-8"))
    }
    ref = copier_default("devtools_ref")
    probe = ["git", "rev-parse", "-q", "--verify", ref]
    if subprocess.run(probe, **_CAPTURE).returncode != 0:  # noqa: S603 (fixed git probe)
        pytest.skip(f"{ref} is not cut yet — this tree becomes it on merge")
    missing = sorted(
        module
        for module in referenced
        if subprocess.run(  # noqa: S603 (fixed git probe)
            # dotted module -> path: `graph.fitness` lives at `graph/fitness.py` in the pinned tree.
            ["git", "cat-file", "-e", f"{ref}:sdlc-devtools/devtools/{module.replace('.', '/')}.py"],  # noqa: S607
            **_CAPTURE,
        ).returncode
        != 0
    )
    assert not missing, (
        f"the template calls devtools.{{{','.join(missing)}}} but the pinned {ref} does not ship them — "
        f"a consumer's `copier update` would install a runner it cannot execute. Bump the version so the "
        f"pin names the release that contains them."
    )


def test_every_structure_key_the_template_ships_is_known_to_the_reader():
    """[tool.structure] is validated on load — an unknown key RAISES so a typo cannot silently leave a gate
    at its default. That makes this relationship load-bearing: a key added to the template but not to
    Pyproject.STRUCTURE_DEFAULTS would raise on every consumer's next run, turning a new setting into a
    crash. The section is read by graph, demeter AND envy, so no single engine owns the schema — which is
    exactly how the first version of that validator rejected demeter's and envy's keys as typos.
    """
    sys.path.insert(0, str(REPO / "sdlc-devtools"))
    from devtools.plumbing.pyproject import STRUCTURE_DEFAULTS  # noqa: PLC0415 (the package is a sibling, not a dep)

    section = re.search(r"^\[tool\.structure\]\n(.*?)(?=^\[)", _TEMPLATE_PYPROJECT, re.S | re.M)
    assert section, "the template no longer ships a [tool.structure] section"
    shipped = set(re.findall(r"^([a-z_]+) *=", section.group(1), re.M))
    unknown = shipped - set(STRUCTURE_DEFAULTS)
    assert not unknown, f"template ships [tool.structure] keys the reader rejects: {sorted(unknown)}"


def test_the_type_checker_targets_the_python_floor_the_project_promises():
    """`requires-python` and `[tool.pyrefly] python-version` must name the same version.

    pyrefly does NOT derive its target from requires-python. Left unset it checks against its own default,
    so a repo declaring 3.11 was type-checked as 3.12+ — `from typing import override` passed the gate and
    would then ImportError at runtime on the version the project claims to support. A checker aimed at a
    NEWER interpreter than you ship is worse than no checker there, because it reports confidence it does
    not have. Verified against the pinned pyrefly: python-version 3.11 errors on that import, 3.12 does not,
    and omitting the key reproduces neither (bd 166).
    """
    text = _TEMPLATE_PYPROJECT
    floor = re.search(r'^requires-python = ">=([0-9.]+)"', text, re.M)
    target = re.search(r'^python-version = "([0-9.]+)"', text, re.M)
    assert floor and target, "both requires-python and [tool.pyrefly] python-version must be present"
    assert floor.group(1) == target.group(1), (
        f"requires-python floor is {floor.group(1)} but pyrefly targets {target.group(1)} — "
        "the type checker must aim at the OLDEST interpreter the project promises"
    )


_RUNNERS = {
    "ci.yml": "template/.github/workflows/ci.yml.jinja",
    "noxfile": "template/noxfile.py.jinja",
    "pre-commit": "template/.pre-commit-config.yaml.jinja",
}


def _enforced_gates(text: str) -> set[str]:
    """The devtools engines this runner invokes as a GATE, by module name.

    TWO invocation forms, because bd f9y.3 added a batch runner:

        python -m devtools.demeter ... --assert     one process per gate
        python -m devtools.run ... --gate a,b,c     one process for many

    A detector that knew only the first would go BLIND to every batched gate the moment a runner adopted
    the runner — and a gate this cannot SEE is indistinguishable from a gate that is not wired, which is
    the exact failure the test below exists to catch. So the detector learns the form; it is not relaxed.

    Windowed rather than line-based on purpose: ci.yml puts the module and `--assert` on one line, while a
    formatted nox `session.run(...)` spreads them over several.

    Jinja tags are stripped FIRST because a conditional gate lives inside the list it belongs to —
    `"...,contracts{% if enable_ml %},shape_contracts{% endif %}"` — and reading the raw text stops the
    match dead at the brace, hiding the ML gate in exactly the runner that batches it.
    """
    text = re.sub(r"{%.*?%}", "", text, flags=re.S)
    # `[\w.]+` not `\w+`: a gate now lives at a DOTTED path (`devtools.coupling.demeter`), so the capture must
    # span the subpackage or it would collapse every coupling gate to the folder name `coupling` (bd 5hg).
    single = {
        match.group(1)
        for match in re.finditer(r"devtools\.([\w.]+)", text)
        if match.group(1) != "run" and "--assert" in text[match.start() : match.start() + 250]
    }
    batched = {
        name
        for match in re.finditer(r"--gate[\"',\s]+([\w,.]+)", text)
        for name in match.group(1).split(",")
        if name
    }
    return single | batched


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


def test_the_scaffolds_own_workflows_invoke_only_real_devtools_modules():
    """The scaffold's OWN CI (dogfood) invokes devtools by module path, and NOTHING checked those paths.

    That gap shipped a broken `architecture/deploy` when `devtools.archmap` moved to `devtools.graph.archmap`
    (bd 5hg): the deploy job invoked the old path, and no PR check could see it — deploy runs on push-to-main,
    not on the PR, and the gate-wiring guard above covers the TEMPLATE runners a CONSUMER receives, not these
    self-scaffolding workflows. A `python -m devtools.<x>` in a scaffold workflow must resolve to a real module
    file in the sibling package, so the next module move cannot break a workflow silently again.
    """
    pkg = REPO / "sdlc-devtools" / "devtools"
    own = [*(REPO / ".github" / "workflows").glob("*.yml"), REPO / ".pre-commit-hooks.yaml"]
    invoked = {
        (f.name, module)
        for f in own
        for module in re.findall(r"python -m (devtools\.[\w.]+)", f.read_text(encoding="utf-8"))
    }
    missing = sorted(
        f"{wf}: {mod}" for wf, mod in invoked if not (pkg / Path(*mod.split(".")[1:])).with_suffix(".py").exists()
    )
    assert not missing, "scaffold workflows invoke devtools modules that do not exist:\n  " + "\n  ".join(missing)
