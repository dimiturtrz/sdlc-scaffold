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
        text = file.read_text(encoding="utf-8", errors="ignore")
        # `${{ github.ref }}` is a GitHub Actions expression, not leftover jinja.
        if "{%" in text or ("{{" in text and "github.ref" not in text):
            leftovers.append(str(file.relative_to(path)))
    assert not leftovers, f"[{name}] leftover jinja in {leftovers}"


def test_expected_layout(project):
    name, path = project
    answers = COMBOS[name]
    assert (path / "core" / "math_ops.py").exists()
    assert (path / answers["package_name"] / "pipeline.py").exists()
    assert (path / "devtools" / "graph.py").exists()
    # toggles gate file presence
    viewer_dir = path / answers.get("viewer_name", "__none__")
    assert viewer_dir.exists() == (answers["has_viewer"] == "true")
    assert (path / "devtools" / "sgconfig.yml").exists() == (answers["enable_astgrep"] == "true")
    assert (path / "devtools" / "jscpd.json").exists() == (answers["enable_jscpd"] == "true")


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
    name, path = project
    cmd = ["uv", "run", "pytest", "tests"]
    if COMBOS[name]["has_viewer"] == "true":
        cmd.append("--ignore=tests/viewer")
    cmd += ["--cov", "-q"]
    run(cmd, path)
    run(["uv", "run", "coverage", "report", "--fail-under=80"], path)


def test_viewer_coverage_lane(project):
    name, path = project
    if COMBOS[name]["has_viewer"] != "true":
        pytest.skip("no viewer")
    run(
        ["uv", "run", "pytest", "tests/viewer", "--cov=" + COMBOS[name]["viewer_name"], "-q"],
        path,
        env={"COVERAGE_FILE": ".coverage.viewer"},
    )


def test_import_linter(project):
    _, path = project
    run(["uvx", "--from", "import-linter", "lint-imports"], path)


def test_graph_assert_all_layers(project):
    name, path = project
    run(["uv", "run", "python", "-m", "devtools.graph", "--assert", *layers(name)], path)


def test_astgrep(project):
    name, path = project
    if COMBOS[name]["enable_astgrep"] != "true":
        pytest.skip("astgrep off")
    run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml",
         "core", COMBOS[name]["package_name"]],
        path,
    )


def test_jscpd(project):
    name, path = project
    if COMBOS[name]["enable_jscpd"] != "true":
        pytest.skip("jscpd off")
    if not has_node():
        pytest.skip("node/npx not available")
    run(["npx", "--yes", "jscpd", "core", COMBOS[name]["package_name"], "--config", "devtools/jscpd.json"], path)


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
    target = full_project / "core" / "math_ops.py"
    original = target.read_text()
    target.write_text(original + "\n\ndef sneaky_top_level():\n    return 1\n")
    result = run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", "core", "full_pkg"],
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
    core = full_project / "core" / "math_ops.py"
    pkg = full_project / "full_pkg" / "pipeline.py"
    core_orig, pkg_orig = core.read_text(), pkg.read_text()
    core.write_text(core_orig + block)
    pkg.write_text(pkg_orig + block)
    result = run(
        ["npx", "--yes", "jscpd", "core", "full_pkg", "--config", "devtools/jscpd.json"],
        full_project,
        check=False,
    )
    core.write_text(core_orig)
    pkg.write_text(pkg_orig)
    assert result.returncode != 0, "jscpd must FAIL on an injected duplicated block"


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
