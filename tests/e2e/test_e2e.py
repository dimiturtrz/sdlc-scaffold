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
    assert_bites,
    example_pkg,
    generate,
    seed_example,
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
    # the gates are always-on now — every gate's files always ship
    assert (path / "devtools" / "sgconfig.yml").exists()
    assert (path / "devtools" / "jscpd.json").exists()
    for tool in ("lcom.py", "data_clumps.py", "state_candidates.py", "magic_literals.py"):
        assert (path / "devtools" / tool).exists()
    # beads is always wired -> the CLAUDE/AGENTS beads section is always present
    assert "bd (beads)" in (path / "CLAUDE.md").read_text()
    assert "bd (beads)" in (path / "AGENTS.md").read_text()
    # import-linter only ships with >1 package (these combos are single-package -> absent even when enabled)
    assert "[tool.importlinter]" not in (path / "pyproject.toml").read_text()
    # domain=ml: numpy dep + ML-workflow gitignore present iff the ML domain
    ml = answers["domain"] == "ml"
    pyproject_text = (path / "pyproject.toml").read_text()
    assert ('"numpy"' in pyproject_text) == ml
    assert ("/mlruns/" in (path / ".gitignore").read_text()) == ml
    # domain=ml doc layers: learning (study ramp) + research + interpretations convention + the
    # data/paths.yaml bullet are ALL ML-only. A domain-neutral project has no doc-ramp convention + no leak.
    claude = (path / "CLAUDE.md").read_text()
    assert ("interpretations/" in claude) == ml
    assert ("paths.yaml" in claude) == ml
    assert ('"research"' in pyproject_text) == ml
    assert ('"learning"' in pyproject_text) == ml, "learning is a study-ramp convention — ML domain only"


def test_multi_package_renders_into_gates(scaffold, tmp_path_factory):
    """A multi-package `packages` list must render into EVERY gate target (nox/ci/pyproject).

    Render-only: the phantom second package has no folder, so gates aren't run — this proves the
    list-splitting, which is what a real core/neuroscan/neuroviz repo relies on.
    """
    out = tmp_path_factory.mktemp("multi") / "proj"
    generate(scaffold, out, {"project_name": "multi", "packages": "pkg_a,pkg_b", "domain": "none", "coverage_floor": "80"})
    noxfile = (out / "noxfile.py").read_text()
    assert 'LAYERS = ["pkg_a", "pkg_b"]' in noxfile
    # graph.py needs the devtools extra (grimp/networkx) — nox must pull it, matching CI (not plain uv run)
    assert '"uv", "run", "--extra", "devtools", "python", "-m", "devtools.graph"' in noxfile
    ci = (out / ".github" / "workflows" / "ci.yml").read_text()
    assert "check pkg_a pkg_b --select" in ci
    assert "--assert pkg_a pkg_b" in ci
    pyproject = (out / "pyproject.toml").read_text()
    assert 'source = ["pkg_a", "pkg_b"]' in pyproject
    assert 'include = ["pkg_a*", "pkg_b*"]' in pyproject
    # import-linter ships with >1 package: root_packages = the list + kernel-independence starter contract
    assert "[tool.importlinter]" in pyproject
    assert 'root_packages = ["pkg_a", "pkg_b"]' in pyproject
    assert 'source_modules = ["pkg_a"]' in pyproject
    assert 'forbidden_modules = ["pkg_b"]' in pyproject


def test_template_ships_no_package_code(scaffold, tmp_path_factory):
    """The template ships ZERO package code (bd r2w) — only guardrails. A fresh gen has no `<pkg>/*.py`."""
    out = tmp_path_factory.mktemp("empty") / "proj"
    generate(scaffold, out, {"project_name": "empty", "packages": "myapp", "domain": "none", "coverage_floor": "80"})
    assert not (out / "myapp").exists(), "no package code ships — the project brings its own"
    assert list((out / "tests" / "unit").glob("*.py")) == [], "no shipped unit tests either"
    # guardrails ARE shipped
    assert (out / "noxfile.py").exists()
    assert (out / "devtools" / "graph.py").exists()
    assert (out / "pyproject.toml").exists()


def test_gitignore_artifact_dirs_are_root_anchored(scaffold, tmp_path_factory):
    """/data/ (etc.) must ignore only the ROOT artifact dir, not a source package like core/data/ (bd hhy):
    an unanchored `data/` silently untracked a nested package's tests -> local green, CI red."""
    out = tmp_path_factory.mktemp("gi") / "proj"
    generate(scaffold, out, {**COMBOS["base"], "project_name": "gi", "packages": "core", "domain": "ml"})
    (out / "core" / "data").mkdir(parents=True)
    (out / "core" / "data" / "thing.py").write_text("X = 1\n")
    (out / "data").mkdir()
    (out / "data" / "big.bin").write_text("blob\n")
    git_init_commit(out)
    nested = run(["git", "check-ignore", "core/data/thing.py"], out, check=False)
    assert nested.returncode != 0, "a source package core/data/ must NOT be gitignored"
    root = run(["git", "check-ignore", "data/big.bin"], out, check=False)
    assert root.returncode == 0, "the ROOT data/ artifact dir must still be ignored"


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
    run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml",
         *layers(name)],
        path,
    )


def test_jscpd(project):
    name, path = project
    if not has_node():
        pytest.skip("node/npx not available")
    run(["npx", "--yes", "jscpd", *layers(name), "--config", "devtools/jscpd.json"], path)


def test_class_shape_smells(project):
    name, path = project
    # advisory explorers — must run clean (exit 0); findings are fine, they never block
    for tool in ("state_candidates", "lcom", "data_clumps"):
        run(["uv", "run", "python", "-m", f"devtools.{tool}", *layers(name)], path)


def test_magic_literals_advisory_runs_clean(project):
    name, path = project
    # advisory report (no --max-* ceilings) — always exit 0, like the class-shape explorers
    run(["uv", "run", "python", "-m", "devtools.magic_literals", *layers(name)], path)


# ---- gates, via the runners ------------------------------------------------------------------------

def test_nox_gates(project):
    _, path = project
    if not has_node():
        pytest.skip("nox lint runs jscpd which needs node")
    run(["uvx", NOX, "-s", "lint", "test", "cov"], path)


def test_precommit_all_hooks(project):
    # no node needed: jscpd is CI+nox only, never a commit hook; every pre-commit hook is uvx/uv-run
    _, path = project
    run(["uvx", PRECOMMIT, "run", "--all-files"], path)


# ---- the optional gates actually BITE --------------------------------------------------------------

GRAPH_ASSERT = ["uv", "run", "python", "-m", "devtools.graph", "--assert", "full_pkg"]


@pytest.fixture(scope="module")
def full_project(scaffold, tmp_path_factory):
    out = tmp_path_factory.mktemp("inject")
    generate(scaffold, out, COMBOS["full"])
    seed_example(out, "full_pkg")  # template ships no code — seed the demo the inject tests mutate
    git_init_commit(out)
    run(["uv", "sync", "--extra", "dev", "--extra", "devtools"], out)
    return out


def _append(path, text):
    """Mutate: append `text` to a file; return a restore callable (for assert_bites)."""
    original = path.read_text()
    path.write_text(original + text)
    return lambda: path.write_text(original)


ASTGREP_SCAN = ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml", "full_pkg"]


def test_astgrep_catches_top_level_function(full_project):
    assert_bites(
        full_project,
        ASTGREP_SCAN,
        lambda p: _append(p / "full_pkg" / "math_ops.py", "\n\ndef sneaky_top_level():\n    return 1\n"),
    )


def test_astgrep_catches_decorated_top_level_function(full_project):
    # a DECORATED free function is a decorated_definition wrapping the def — the 2nd rule branch must catch it
    assert_bites(
        full_project,
        ASTGREP_SCAN,
        lambda p: _append(
            p / "full_pkg" / "math_ops.py",
            "\n\nfrom functools import cache\n\n\n@cache\ndef sneaky_decorated():\n    return 1\n",
        ),
    )


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
    assert_bites(
        full_project,
        GRAPH_ASSERT,
        lambda p: _append(
            p / "full_pkg" / "math_ops.py",
            "\n\nfrom full_pkg.pipeline import Pipeline as _Cycle  # noqa: E402, F401\n",
        ),
    )
    assert run(GRAPH_ASSERT, full_project).returncode == 0, "passes again once reverted"


def test_graph_assert_catches_unmirrored(full_project):
    # a new LOGIC module with no tests/unit/full_pkg/test_<name>.py mirror must block
    def mutate(p):
        orphan = p / "full_pkg" / "orphan.py"
        orphan.write_text("class Orphan:\n    @staticmethod\n    def go():\n        return 1\n")
        return orphan.unlink

    result = assert_bites(full_project, GRAPH_ASSERT, mutate)
    assert "test mirror" in (result.stdout + result.stderr)
    assert run(GRAPH_ASSERT, full_project).returncode == 0, "passes again once reverted"


# magic_literals is advisory by default; passing --max-strings opts into the count-ratchet, which BITES.
MAGIC_RATCHET = ["uv", "run", "python", "-m", "devtools.magic_literals", "full_pkg", "--max-strings", "0"]


def test_magic_literals_ratchet_bites(full_project):
    # the clean seed has no recurring identifier-vocab -> passes even at a zero ceiling
    assert run(MAGIC_RATCHET, full_project).returncode == 0, "clean seed is under the zero string ceiling"
    # inject a token repeated >=4x in value position -> a recurring literal over the ceiling (AST-only, so
    # the undefined `_use` never runs). Restores before asserting (assert_bites), keeping the fixture clean.
    inject = "\n" + "\n".join(f"def _m{i}():\n    return _use('widget')\n" for i in range(4)) + "\n"
    result = assert_bites(full_project, MAGIC_RATCHET, lambda p: _append(p / "full_pkg" / "math_ops.py", inject))
    assert "ratchet exceeded" in (result.stdout + result.stderr)
    assert run(MAGIC_RATCHET, full_project).returncode == 0, "passes again once reverted"


def test_import_linter_catches_upward_import(scaffold, tmp_path_factory):
    # a real 2-package project: kern (kernel, packages[0]) + app; contract forbids kern -> app
    out = tmp_path_factory.mktemp("il") / "proj"
    generate(scaffold, out, {"project_name": "il", "packages": "kern,app", "domain": "none", "coverage_floor": "80"})
    seed_example(out, "kern")  # kernel (packages[0]); template ships no code
    # add the second package `app` (downward edge app -> kern is fine)
    (out / "app").mkdir()
    (out / "app" / "__init__.py").write_text("")
    (out / "app" / "thing.py").write_text(
        "from kern.math_ops import MathOps\n\n\nclass Thing:\n    @staticmethod\n    def go() -> float:\n        return MathOps.mean([1.0])\n"
    )
    (out / "tests" / "unit" / "app").mkdir(parents=True)
    (out / "tests" / "unit" / "app" / "test_thing.py").write_text(
        "from app.thing import Thing\n\n\ndef test_go():\n    assert Thing.go() == 1.0\n"
    )
    git_init_commit(out)
    # clean: the kernel imports nothing above it
    run(["uvx", "--from", "import-linter", "lint-imports"], out)
    # inject an UPWARD import (kernel imports the app package) -> kernel-independence contract violated
    kernel = out / "kern" / "math_ops.py"
    original = kernel.read_text()
    kernel.write_text(original + "\n\nfrom app.thing import Thing as _Up  # noqa: E402, F401\n")
    bad = run(["uvx", "--from", "import-linter", "lint-imports"], out, check=False)
    kernel.write_text(original)
    assert bad.returncode != 0, "import-linter must FAIL when the kernel imports a higher package"


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
    # anchor on "docs" — always in the exclude list (learning/research/interpretations are domain=ml only)
    pyproject.write_text(text.replace('"docs"]', '"docs", "MY_LOCAL_DIR"]', 1))
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
