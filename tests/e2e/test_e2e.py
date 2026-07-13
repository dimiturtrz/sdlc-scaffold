"""End-to-end test of the sdlc-scaffold: generate real projects, run every gate, prove gates bite.

Codifies the manual verification: (1) each toggle combo renders clean, (2) every gate runs GREEN via
solo + nox + pre-commit, (3) the optional gates actually CATCH violations, (4) `copier update` heals a
portable-rule change while preserving a project-local edit.

Run:  cd sdlc-scaffold && uv run pytest            (Linux/WSL; jscpd steps skip if node is absent)
"""

import pytest

from conftest import (
    COMBOS,
    COPIER,
    PRECOMMIT,
    RUFF,
    SELECT,
    VULTURE,
    NOX,
    example_pkg,
    generate,
    git_init_commit,
    has_node,
    layers,
    make_scaffold,
    run,
)

pytestmark = pytest.mark.slow


# ---- rendering -------------------------------------------------------------------------------------

def test_no_leftover_jinja(project):
    name, path = project
    leftovers = []
    for file in path.rglob("*"):
        if file.suffix not in {".py", ".toml", ".yml", ".yaml", ".md"}:
            continue
        if ".venv" in file.parts or ".git" in file.parts:
            continue
        # our shipped devtools tools are STATIC Python that legitimately contains f-string braces `{{`.
        if "devtools" in file.parts and file.suffix == ".py":
            continue
        text = file.read_text(encoding="utf-8", errors="ignore")
        # `${{ github.ref }}` is a GitHub Actions expression, not leftover jinja.
        if "{%" in text or ("{{" in text and "github.ref" not in text):
            leftovers.append(str(file.relative_to(path)))
    assert not leftovers, f"[{name}] leftover jinja in {leftovers}"


def test_expected_layout(project):
    name, path = project
    answers = COMBOS[name]
    pkg = example_pkg(name)
    assert (path / pkg / "math_ops.py").exists()
    assert (path / pkg / "pipeline.py").exists()
    # example tests ship at their STRICT mirror path (tests/unit/<pkg>/test_<name>.py)
    assert (path / "tests" / "unit" / pkg / "test_math_ops.py").exists()
    assert (path / "tests" / "unit" / pkg / "test_pipeline.py").exists()
    assert (path / "devtools" / "graph.py").exists()
    assert (path / "devtools" / "omit.py").exists()
    assert (path / "devtools" / "README.md").exists()
    # toggles gate file presence
    assert (path / "devtools" / "sgconfig.yml").exists() == (answers["enable_astgrep"] == "true")
    assert (path / "devtools" / "jscpd.json").exists() == (answers["enable_jscpd"] == "true")
    class_shape = answers["enable_class_shape_smells"] == "true"
    for tool in ("lcom.py", "data_clumps.py", "state_candidates.py"):
        assert (path / "devtools" / tool).exists() == class_shape
    # beads section is present in CLAUDE.md/AGENTS.md iff enable_beads
    beads = answers["enable_beads"] == "true"
    assert ("bd (beads)" in (path / "CLAUDE.md").read_text()) == beads
    assert ("bd (beads)" in (path / "AGENTS.md").read_text()) == beads


def test_multi_package_renders_into_gates(scaffold, tmp_path_factory):
    """A multi-package `packages` list must render into EVERY gate target (nox/ci/pyproject).

    Render-only: the phantom second package has no folder, so gates aren't run — this proves the
    list-splitting, which is what a real core/neuroscan/neuroviz repo relies on.
    """
    out = tmp_path_factory.mktemp("multi") / "proj"
    generate(scaffold, out, {
        "project_name": "multi",
        "packages": "pkg_a,pkg_b",
        "ship_example": "true",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "true",
        "enable_jscpd": "true",
        "enable_class_shape_smells": "true",
        "coverage_floor": "80",
    })
    assert 'LAYERS = ["pkg_a", "pkg_b"]' in (out / "noxfile.py").read_text()
    ci = (out / ".github" / "workflows" / "ci.yml").read_text()
    assert "check pkg_a pkg_b --select" in ci
    assert "--assert pkg_a pkg_b" in ci
    pyproject = (out / "pyproject.toml").read_text()
    assert 'source = ["pkg_a", "pkg_b"]' in pyproject
    assert 'include = ["pkg_a*", "pkg_b*"]' in pyproject
    # the demo package ships under the FIRST entry
    assert (out / "pkg_a" / "math_ops.py").exists()


def test_ship_example_false_omits_demo(scaffold, tmp_path_factory):
    """ship_example=false drops the demo package + its unit tests — the repo-adoption path."""
    out = tmp_path_factory.mktemp("adopt") / "proj"
    generate(scaffold, out, {
        "project_name": "adopt",
        "packages": "myapp",
        "ship_example": "false",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "false",
        "enable_jscpd": "false",
        "enable_class_shape_smells": "false",
        "coverage_floor": "80",
    })
    assert not (out / "myapp").exists(), "demo package must be absent when ship_example=false"
    assert not (out / "tests" / "unit" / "myapp").exists()
    # guardrails still shipped
    assert (out / "noxfile.py").exists()
    assert (out / "devtools" / "graph.py").exists()


# ---- gates, solo -----------------------------------------------------------------------------------

def test_ruff(project):
    name, path = project
    run(["uvx", RUFF, "check", *layers(name), "--select", SELECT], path)


def test_ruff_format(project):
    _, path = project
    run(["uvx", RUFF, "format", "--check", "."], path)


def test_vulture_conf80(project):
    _, path = project
    run(["uvx", VULTURE, "--min-confidence", "80"], path)


def test_coverage_floor(project):
    _, path = project
    run(["uv", "run", "pytest", "tests", "--cov", "-q"], path)
    run(["uv", "run", "coverage", "report", "--fail-under=80"], path)


def test_graph_assert_all_layers(project):
    name, path = project
    run(["uv", "run", "python", "-m", "devtools.graph", "--assert", *layers(name)], path)


def test_astgrep(project):
    name, path = project
    if COMBOS[name]["enable_astgrep"] != "true":
        pytest.skip("astgrep off")
    run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml",
         *layers(name)],
        path,
    )


def test_jscpd(project):
    name, path = project
    if COMBOS[name]["enable_jscpd"] != "true":
        pytest.skip("jscpd off")
    if not has_node():
        pytest.skip("node/npx not available")
    run(["npx", "--yes", "jscpd", *layers(name), "--config", "devtools/jscpd.json"], path)


def test_class_shape_smells(project):
    name, path = project
    if COMBOS[name]["enable_class_shape_smells"] != "true":
        pytest.skip("class-shape off")
    # advisory explorers — must run clean (exit 0); findings are fine, they never block
    for tool in ("state_candidates", "lcom", "data_clumps"):
        run(["uv", "run", "python", "-m", f"devtools.{tool}", *layers(name)], path)


# ---- gates, via the runners ------------------------------------------------------------------------

def test_nox_gates(project):
    name, path = project
    if COMBOS[name]["enable_jscpd"] == "true" and not has_node():
        pytest.skip("nox lint runs jscpd which needs node")
    run(["uvx", NOX, "-s", "lint", "test", "cov"], path)


def test_precommit_all_hooks(project):
    name, path = project
    if COMBOS[name]["enable_jscpd"] == "true" and not has_node():
        pytest.skip("pre-commit jscpd hook needs node")
    run(["uvx", PRECOMMIT, "run", "--all-files"], path)


# ---- the optional gates actually BITE --------------------------------------------------------------

@pytest.fixture(scope="module")
def full_project(scaffold, tmp_path_factory):
    out = tmp_path_factory.mktemp("inject")
    generate(scaffold, out, COMBOS["full"])
    git_init_commit(out)
    run(["uv", "sync", "--extra", "dev", "--extra", "devtools"], out)
    return out


def test_astgrep_catches_top_level_function(full_project):
    target = full_project / "full_pkg" / "math_ops.py"
    original = target.read_text()
    target.write_text(original + "\n\ndef sneaky_top_level():\n    return 1\n")
    result = run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", "full_pkg"],
        full_project,
        check=False,
    )
    target.write_text(original)
    assert result.returncode != 0, "ast-grep must FAIL on an injected top-level function"


def test_jscpd_catches_duplication(full_project):
    if not has_node():
        pytest.skip("node/npx not available")
    block = (
        "\n\nclass DupForJscpd:\n"
        "    @staticmethod\n"
        "    def weighted(values: list[float], weights: list[float]) -> float:\n"
        "        total = 0.0\n"
        "        wsum = 0.0\n"
        "        for value, weight in zip(values, weights, strict=True):\n"
        "            total += value * weight\n"
        "            wsum += weight\n"
        "        if wsum == 0.0:\n"
        '            msg = "zero"\n'
        "            raise ValueError(msg)\n"
        "        return total / wsum\n"
    )
    mod = full_project / "full_pkg" / "math_ops.py"
    pkg = full_project / "full_pkg" / "pipeline.py"
    mod_orig, pkg_orig = mod.read_text(), pkg.read_text()
    mod.write_text(mod_orig + block)
    pkg.write_text(pkg_orig + block)
    result = run(
        ["npx", "--yes", "jscpd", "full_pkg", "--config", "devtools/jscpd.json"],
        full_project,
        check=False,
    )
    mod.write_text(mod_orig)
    pkg.write_text(pkg_orig)
    assert result.returncode != 0, "jscpd must FAIL on an injected duplicated block"


def test_graph_assert_catches_cycle(full_project):
    # math_ops <- pipeline already; add math_ops -> pipeline to close an import cycle
    target = full_project / "full_pkg" / "math_ops.py"
    original = target.read_text()
    target.write_text(original + "\n\nfrom full_pkg.pipeline import Pipeline as _Cycle  # noqa: E402, F401\n")
    result = run(
        ["uv", "run", "python", "-m", "devtools.graph", "--assert", "full_pkg"],
        full_project,
        check=False,
    )
    target.write_text(original)
    assert result.returncode != 0, "graph --assert must FAIL on an injected import cycle"
    # and it passes again once reverted
    ok = run(["uv", "run", "python", "-m", "devtools.graph", "--assert", "full_pkg"], full_project)
    assert ok.returncode == 0


def test_graph_assert_catches_unmirrored(full_project):
    # a new LOGIC module with no tests/unit/full_pkg/test_<name>.py mirror must block
    orphan = full_project / "full_pkg" / "orphan.py"
    orphan.write_text("class Orphan:\n    @staticmethod\n    def go():\n        return 1\n")
    result = run(
        ["uv", "run", "python", "-m", "devtools.graph", "--assert", "full_pkg"],
        full_project,
        check=False,
    )
    orphan.unlink()
    assert result.returncode != 0, "graph --assert must FAIL on a logic module lacking its mirror test"
    assert "test mirror" in (result.stdout + result.stderr)
    ok = run(["uv", "run", "python", "-m", "devtools.graph", "--assert", "full_pkg"], full_project)
    assert ok.returncode == 0


# ---- versioned rollout: drift heals, local slot survives -------------------------------------------

def test_copier_update_heals_portable_preserves_local(tmp_path):
    scaffold = tmp_path / "scaf"
    scaffold.mkdir()
    make_scaffold(scaffold)  # tags v0.1.0

    project = tmp_path / "proj"
    generate(scaffold, project, COMBOS["base"])
    git_init_commit(project)

    # 1. hand-edit a LOCAL-SLOT in the generated project
    pyproject = project / "pyproject.toml"
    text = pyproject.read_text()
    assert "LOCAL-SLOT: ruff-exclude" in text
    pyproject.write_text(text.replace('"research"]', '"research", "MY_LOCAL_DIR"]', 1))
    run(["git", "commit", "-aqm", "local edit"], project)

    # 2. tighten a PORTABLE rule in the template, tag v0.2.0
    template_pp = scaffold / "template" / "pyproject.toml.jinja"
    template_pp.write_text(template_pp.read_text().replace("file_max = 750", "file_max = 500"))
    run(["git", "commit", "-aqm", "v0.2.0 ratchet"], scaffold)
    run(["git", "tag", "v0.2.0"], scaffold)

    # 3. update
    run(["uvx", COPIER, "update", "--defaults", "--trust"], project)

    answers = (project / ".copier-answers.yml").read_text()
    result = (project / "pyproject.toml").read_text()
    assert "_commit: v0.2.0" in answers, "pin should advance"
    assert "file_max = 500" in result, "portable change should flow in"
    assert "MY_LOCAL_DIR" in result, "local-slot edit must survive the 3-way merge"
    assert not list(project.rglob("*.rej")), "no merge conflicts expected"
