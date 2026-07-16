"""End-to-end test of the sdlc-scaffold: generate real projects, run every gate, prove gates bite.

Codifies the manual verification: (1) each toggle combo renders clean, (2) every gate runs GREEN via
solo + nox + pre-commit, (3) the optional gates actually CATCH violations, (4) `copier update` heals a
portable-rule change while preserving a project-local edit.

Run:  cd sdlc-scaffold && uv run pytest            (Linux/WSL; jscpd steps skip if node is absent)
"""

import json

import pytest
from conftest import (
    COMBOS,
    COPIER,
    DEPTRY,
    NOX,
    PIP_AUDIT,
    PRECOMMIT,
    RUFF,
    SELECT,
    VULTURE,
    assert_bites,
    config_path,
    example_pkg,
    generate,
    git_init_commit,
    has_node,
    layers,
    make_scaffold,
    run,
    seed_example,
    use_local_devtools,
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
    pkg = example_pkg(name)
    assert (path / pkg / "math_ops.py").exists()
    assert (path / pkg / "pipeline.py").exists()
    # example tests ship at their STRICT mirror path (tests/unit/<pkg>/test_<name>.py)
    assert (path / "tests" / "unit" / pkg / "test_math_ops.py").exists()
    assert (path / "tests" / "unit" / pkg / "test_pipeline.py").exists()
    # the analyzers are an INSTALLED package now (sdlc-devtools, pinned by tag) — not vendored source,
    # and neither is the ast-grep/jscpd config (located from the install via `python -m devtools.config`).
    pyproject_dep = (path / "pyproject.toml").read_text()
    assert not (path / "devtools" / "graph.py").exists(), "engines ship as a package, not vendored .py"
    assert not (path / "devtools" / "sgconfig.yml").exists(), "ast-grep config ships inside the package"
    assert "sdlc-devtools @ git+" in pyproject_dep, "the devtools git-dep is pinned in the devtools extra"
    assert "#subdirectory=sdlc-devtools" in pyproject_dep, "pinned to the package subdirectory"
    # the project-local gate-usage doc still ships (invocation + @shapecheck + import-linter guidance)
    assert (path / "devtools" / "README.md").exists()
    # beads is always wired -> the CLAUDE/AGENTS beads section is always present
    assert "bd (beads)" in (path / "CLAUDE.md").read_text()
    assert "bd (beads)" in (path / "AGENTS.md").read_text()
    # import-linter only ships with >1 package (these combos are single-package -> absent even when enabled)
    assert "[tool.importlinter]" not in (path / "pyproject.toml").read_text()


def test_domain_gating(project):
    """domain=ml gates the ML-only bundle: numpy/typing deps, doc layers, shape config, naming vocab."""
    name, path = project
    answers = COMBOS[name]
    # domain=ml: numpy dep + ML-workflow gitignore present iff the ML domain
    ml = answers["domain"] == "ml"
    pyproject_text = (path / "pyproject.toml").read_text()
    assert ('"numpy"' in pyproject_text) == ml
    assert ("/mlruns/" in (path / ".gitignore").read_text()) == ml
    # domain=ml doc layers: learning (study ramp) + research + interpretations convention + the
    # data/paths.yaml bullet are ALL ML-only. A domain-neutral project has no doc-ramp convention + no leak.
    claude = (path / "CLAUDE.md").read_text()
    # the scaffolding provenance + "template-owned, don't hand-edit" note ships regardless of domain
    assert "## Scaffolding" in claude, "generated CLAUDE.md must carry the template-owned scaffolding note"
    assert ("interpretations/" in claude) == ml
    assert ("paths.yaml" in claude) == ml
    assert ('"research"' in pyproject_text) == ml
    assert ('"learning"' in pyproject_text) == ml, "learning is a study-ramp convention — ML domain only"
    # ML-typing bundle (vip.1): jaxtyping+beartype deps, the F722 ignore, the shape gate engine + config,
    # and the @shapecheck helper note all ship IFF the ML domain (meaningless off a tensor codebase).
    # shape_contracts ships in the package unconditionally; the ml-gating is at the WIRING level — a ml
    # project's ci/nox/pre-commit carry the shape --assert step, a domain-neutral one doesn't (asserted below).
    assert ('"jaxtyping"' in pyproject_text) == ml
    assert ('"beartype"' in pyproject_text) == ml
    assert ('"F722"' in pyproject_text) == ml, "F722 ignore is ML-only (jaxtyping shape strings)"
    assert ('"F821"' in pyproject_text) == ml, "F821 ignore is ML-only (single-axis jaxtyping shapes — kqk)"
    assert ("[tool.shape_contracts]" in pyproject_text) == ml
    assert ("jaxtyped(typechecker=" in (path / "devtools" / "README.md").read_text()) == ml, (
        "the @shapecheck helper snippet is ML-only"
    )
    # N (pep8-naming) is a UNIVERSAL rule -> the block always ships; only its ignore-names VOCAB is ML-flavored
    assert "[tool.ruff.lint.pep8-naming]" in pyproject_text, "N is universal — the naming block always ships"
    assert ('"X*"' in pyproject_text) == ml, "the tensor-idiom naming allowlist is ML-only"


def test_select_and_ci_wiring(project):
    """The union ruff select, the enforced/advisory split, the base gates, and the CI step wiring."""
    name, path = project
    answers = COMBOS[name]
    pkg = example_pkg(name)
    ml = answers["domain"] == "ml"
    pyproject_text = (path / "pyproject.toml").read_text()
    # union ruff select (vip.2): cardiac's ratchet is the base — N/PTH123/S101 are enforced in EVERY combo
    assert "select = [" in pyproject_text
    for code in ('"N"', '"PTH123"', '"PERF401"', '"ICN001"', '"S101"'):
        assert code in pyproject_text, f"union select must carry {code} (cardiac ratchet + S101)"
    # 4c2/8ex: E501 (cosmetic) + SLF001 (conflicts with the op-namespace ast-grep gate) are DEMOTED from
    # the enforced union to the advisory surface — reported, never blocking. (ci --extend-select checked below.)
    enforced_select = pyproject_text[pyproject_text.index("select = [") : pyproject_text.index("select = [") + 900]
    assert '"E501"' not in enforced_select, "E501 must NOT be in the enforced select (advisory only — 4c2)"
    assert '"SLF001"' not in enforced_select, "SLF001 must NOT be in the enforced select (advisory only — 8ex)"
    # x3b: instability / main-sequence coupling gate threshold ships in [tool.structure] (advisory, OFF at 0)
    assert "main_sequence_max" in pyproject_text, "the instability/main-sequence gate threshold ships (x3b)"
    # 0sx: magic_literals + complexity ship NO config — they are advisory explorers, not ratcheted gates.
    # No legislated knob is added until a repo needs one (the ratchet was removed as the wrong mechanism).
    assert "[tool.magic_literals]" not in pyproject_text, "magic-literals is advisory — no config knob (0sx)"
    assert "[tool.complexity]" not in pyproject_text, "complexity is advisory — no config knob (0sx)"
    # 85l.2: deptry dependency-hygiene gate — [tool.deptry] config ships, the DEP002 starter-ignore carries
    # the shipped deps (pytest/sdlc-devtools always; numpy/jaxtyping/beartype iff ml) so a fresh gen is green.
    assert "[tool.deptry]" in pyproject_text, "deptry dependency-hygiene gate config ships (85l.2)"
    # 9mu: ruff enforced + jscpd default to the arch set but are hygiene-widenable (lint_paths/jscpd_paths)
    ci_text = (path / ".github" / "workflows" / "ci.yml").read_text()
    assert "deptry ." in ci_text, "the deptry gate is wired into CI (85l.2)"
    assert "devtools.complexity" in ci_text, "complexity runs in CI (advisory block; 0sx)"
    # 2vt.4: archmap (architecture autoviz) wired into all three runners — CI advisory --check, a pre-commit
    # regen hook, and a manual nox regen session. Doc-gen/advisory; import-linter stays the directional gate.
    assert "devtools.archmap" in ci_text and "--check" in ci_text, "archmap --check runs in CI (advisory; 2vt.4)"
    precommit_text = (path / ".pre-commit-config.yaml").read_text()
    assert "id: archmap" in precommit_text, "the archmap regen hook ships in pre-commit (2vt.4)"
    nox_text = (path / "noxfile.py").read_text()
    assert "def archmap(" in nox_text, "the manual archmap regen session ships in noxfile (2vt.4)"
    assert f"check {pkg} --select" in ci_text, "ruff enforced scans lint_paths (= packages by default)"
    # skr GAP1: an explicit --select BYPASSES pyproject [tool.ruff.lint] ignore, so the enforced-lint CLI
    # repeats the ml F722 waiver (jaxtyping dim strings) — else a fresh ml gen red-CIs on its own config.
    assert ("--ignore F722,F821" in ci_text) == ml, "enforced-lint CLI waives F722+F821 iff ml (skr GAP1 + kqk)"
    # skr GAP3a: the data-skip env uses the per-repo data_env_var NAME (default project-derived), ml-only.
    proj_upper = answers["project_name"].upper().replace("-", "_")
    assert (f"{proj_upper}_DATA: /tmp/nodata" in ci_text) == ml, "ml CI sets the derived data-skip env (skr GAP3a)"
    # skr GAP3b: ci repo-step LOCAL-SLOTs let a consumer superset ride on slots, not a fork (both domains).
    assert "LOCAL-SLOT: ci-lint-steps" in ci_text, "the ci-lint-steps slot ships (skr GAP3)"
    assert "LOCAL-SLOT: ci-test-steps" in ci_text, "the ci-test-steps slot ships (skr GAP3)"
    # 4c2/8ex: E501+SLF001 ride the advisory --statistics surface (reported, never a merge gate).
    assert "--extend-select E501,SLF001" in ci_text, "E501/SLF001 surface via advisory --statistics (4c2/8ex)"
    # vip.4: shape_contracts GRADUATED advisory->blocking — a ml gen carries an ENFORCED --assert step (a
    # fresh gen has 0 boundaries so it passes); a domain-neutral gen has no shape gate at all.
    assert ("shape_contracts {} --assert".format(pkg) in ci_text) == ml, "ml ci enforces shape --assert (vip.4)"
    # c64: a generated project gets an MIT LICENSE carrying the author copyright (default = project_name).
    license_text = (path / "LICENSE").read_text()
    assert "MIT License" in license_text and answers["project_name"] in license_text, (
        "generated LICENSE ships with the author copyright (c64)"
    )
    # nzs: the doc STARTERS carry ML-research framing (metric/baseline table, evidence->stats->method
    # derivation) only for the ML domain; a domain-neutral project gets generic success-criteria wording.
    plan = (path / "docs" / "PLAN.md").read_text()
    assert ("Headline metrics" in plan) == ml, "the metric/baseline table is ML-research framing (nzs)"
    assert ("public evidence" in plan) == ml, "the evidence->stats->method derivation is ML-only"
    assert ("Success criteria" in plan) == (not ml), "a domain-neutral plan gets generic success criteria"
    assert ("Headline-metric harness" in (path / "docs" / "ROADMAP.md").read_text()) == ml


def test_multi_package_renders_into_gates(scaffold, tmp_path_factory):
    """A multi-package `packages` list must render into EVERY gate target (nox/ci/pyproject).

    Render-only: the phantom second package has no folder, so gates aren't run — this proves the
    list-splitting, which is what a real core/neuroscan/neuroviz repo relies on.
    """
    out = tmp_path_factory.mktemp("multi") / "proj"
    generate(
        scaffold, out, {"project_name": "multi", "packages": "pkg_a,pkg_b", "domain": "none", "coverage_floor": "80"}
    )
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
    # per-gate scope (vip.3): arch (graph/ast-grep/jscpd) + ruff scan `packages`; vulture + coverage +
    # import-linter roots scope via their LOCAL-SLOTs so a repo can widen ONE gate without forking the set.
    assert 'VULTURE, "--min-confidence"' in noxfile, "nox vulture is config-driven (no CLI packages)"
    assert "check pkg_a pkg_b --select" in ci, "ruff keeps the CLI package scope (the arch/owned set)"
    slot = pyproject.index("LOCAL-SLOT: import-contracts")
    assert pyproject.index("root_packages", 0) > slot, "import-linter root_packages must sit inside the slot"
    # import-linter ships with >1 package: root_packages = the list + kernel-independence starter contract
    assert "[tool.importlinter]" in pyproject
    assert 'root_packages = ["pkg_a", "pkg_b"]' in pyproject
    assert 'source_modules = ["pkg_a"]' in pyproject
    assert 'forbidden_modules = ["pkg_b"]' in pyproject


def test_hygiene_scope_widens_ruff_and_jscpd(scaffold, tmp_path_factory):
    """9mu: ruff + jscpd (R1 hygiene) can scan WIDER than the arch set — a repo widens lint_paths/jscpd_paths
    to keep a viewer + tests linted, without graph.py/ast-grep (R2/R3) leaving the package set."""
    out = tmp_path_factory.mktemp("hygiene") / "proj"
    generate(
        scaffold,
        out,
        {
            "project_name": "h",
            "packages": "core",
            "domain": "none",
            "coverage_floor": "80",
            "lint_paths": "core viewer tests",
            "jscpd_paths": "core viewer/web/src",
        },
    )
    ci = (out / ".github" / "workflows" / "ci.yml").read_text()
    nox = (out / "noxfile.py").read_text()
    # ruff enforced + jscpd take the WIDE scope
    assert "check core viewer tests --select" in ci, "ruff enforced scans the widened lint_paths"
    assert "jscpd core viewer/web/src --config" in ci, "jscpd scans the widened jscpd_paths"
    assert 'LINT_LAYERS = ["core", "viewer", "tests"]' in nox
    assert 'JSCPD_LAYERS = ["core", "viewer/web/src"]' in nox
    # arch gates (graph / ast-grep) STAY on the package arch set — hygiene widens, structure does not
    assert "--assert core" in ci and 'sgconfig)" core' in ci, "arch gates keep the package set, not the wide scope"


def test_template_ships_no_package_code(scaffold, tmp_path_factory):
    """The template ships ZERO package code (bd r2w) — only guardrails. A fresh gen has no `<pkg>/*.py`."""
    out = tmp_path_factory.mktemp("empty") / "proj"
    generate(scaffold, out, {"project_name": "empty", "packages": "myapp", "domain": "none", "coverage_floor": "80"})
    assert not (out / "myapp").exists(), "no package code ships — the project brings its own"
    # the devtools engine tests are SCAFFOLD-side only — a consumer gets the engines, never their tests
    # (those test template/devtools/*.py, not consumer code — bd d9x reversed the v1.1.0 vendoring).
    assert not (out / "tests" / "unit" / "devtools").exists(), "devtools engine tests are never shipped"
    assert list((out / "tests" / "unit").rglob("test_*.py")) == [], "no shipped unit tests — the project brings its own"
    # the engines are an installed package, not vendored source — no devtools/*.py ships
    assert not (out / "devtools" / "graph.py").exists(), "engines ship as the sdlc-devtools package, not source"
    assert "sdlc-devtools @ git+" in (out / "pyproject.toml").read_text(), "the pinned devtools git-dep ships"
    # the gate runners + config ARE shipped
    assert (out / "noxfile.py").exists()
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
    run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.graph", "--assert", *layers(name)], path)


def test_astgrep(project):
    name, path = project
    cfg = config_path(path, "sgconfig")  # located from the installed package (no vendored devtools/)
    run(["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", cfg, *layers(name)], path)


def test_jscpd(project):
    name, path = project
    if not has_node():
        pytest.skip("node/npx not available")
    run(["npx", "--yes", "jscpd", *layers(name), "--config", config_path(path, "jscpd")], path)


def test_class_shape_smells(project):
    name, path = project
    # advisory explorers — must run clean (exit 0); findings are fine, they never block
    for tool in ("state_candidates", "lcom", "data_clumps"):
        run(["uv", "run", "--extra", "devtools", "python", "-m", f"devtools.{tool}", *layers(name)], path)


def test_magic_literals_advisory_runs_clean(project):
    name, path = project
    # ADVISORY explorer (0sx) — ranked report, always exit 0, no config, no gate.
    run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.magic_literals", *layers(name)], path)


def test_audit_workflow_rendered(project):
    name, path = project
    # 85l.3: the nightly security scan ships as its OWN workflow (not the per-PR ci.yml) — scheduled cron +
    # manual dispatch, running pip-audit. Advisories change under you, so it's nightly, never a PR gate.
    audit = (path / ".github" / "workflows" / "audit.yml").read_text()
    assert "schedule:" in audit and "cron:" in audit, "audit runs on a nightly schedule, not per-PR"
    assert "pip-audit" in audit, "the audit workflow runs pip-audit (PyPA CVE scan)"


def test_pip_audit_runs_clean(project):
    name, path = project
    # a fresh gen's declared deps carry no known CVE, so the nightly is green from day one. --skip-editable
    # drops the git-pinned sdlc-devtools (no PyPI release to look up). Real run (hits the advisory DB).
    run(["uv", "run", "--with", PIP_AUDIT, "pip-audit", "--skip-editable"], path)


def test_complexity_advisory_runs_clean(project):
    name, path = project
    # ADVISORY explorer (0sx) — radon CC ranked report, always exit 0. ruff C901 is the FIXED complexity gate.
    run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.complexity", *layers(name)], path)


def test_archmap_generates_site_and_check_bites(project):
    name, path = project
    archmap = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.archmap", *layers(name)]
    # doc-gen (m5c): archmap emits graph.json (diff-truth) + a self-contained interactive viewer; --check
    # must be GREEN on the fresh output.
    run(archmap, path)
    graph = path / "docs" / "architecture" / "graph.json"
    index = path / "docs" / "architecture" / "index.html"
    assert graph.exists(), "archmap writes the committed graph.json"
    data = json.loads(graph.read_text(encoding="utf-8"))
    assert set(data) == {"nodes", "edges"} and data["nodes"], "graph.json carries nodes + edges"
    assert index.exists(), "archmap writes the interactive viewer alongside"
    html = index.read_text(encoding="utf-8")
    assert "<script src=" not in html, "the viewer is self-contained (no external script)"
    assert "fetch('./graph.json')" in html, "the viewer hydrates the sibling graph.json"
    run([*archmap, "--check"], path)

    # ...and the --check stale gate BITES when the committed graph.json drifts from the real graph (m5c.4)
    def tamper(_):
        original = graph.read_text(encoding="utf-8")
        graph.write_text('{"nodes": [], "edges": []}\n', encoding="utf-8")
        return lambda: graph.write_text(original, encoding="utf-8")

    assert_bites(path, [*archmap, "--check"], tamper)


def test_archviz_pages_workflow_gated(scaffold, tmp_path_factory):
    # opt-in (m5c.5): archviz_pages=true ships the Pages deploy workflow; the default (false) omits it via a
    # conditional filename that renders empty. graph.json/viewer emit regardless — only the deploy is gated.
    on = tmp_path_factory.mktemp("pages_on")
    generate(scaffold, on / "p", {"project_name": "pg", "packages": "pg", "domain": "none", "archviz_pages": "true"})
    pages = on / "p" / ".github" / "workflows" / "pages.yml"
    assert pages.exists(), "archviz_pages=true ships pages.yml"
    txt = pages.read_text(encoding="utf-8")
    assert "deploy-pages" in txt and "devtools.archmap" in txt, "the Pages workflow regenerates + deploys"
    # clf.3: it ships the STAGED pattern — main at /architecture/, dev at /architecture/preview/ (guarded so a
    # repo with no dev branch skips cleanly), and a root redirect. Packages ({{ pkgs }}) render into the build.
    assert "_site/architecture" in txt, "main view -> /architecture/"
    assert "_site/architecture/preview" in txt, "dev view -> /architecture/preview/"
    assert "git archive origin/dev" in txt and "rev-parse --verify" in txt, "dev preview built from origin/dev, guarded"
    assert "url=./architecture/" in txt, "root redirects to the stable view"
    assert "devtools.archmap pg" in txt, "the packages answer renders into the archmap invocation"

    off = tmp_path_factory.mktemp("pages_off")
    generate(scaffold, off / "p", {"project_name": "pg", "packages": "pg", "domain": "none"})  # archviz_pages default false
    assert not (off / "p" / ".github" / "workflows" / "pages.yml").exists(), "default (false) omits pages.yml"


def test_deptry_enforced_runs_clean(project):
    name, path = project
    # ENFORCED dependency hygiene. A fresh gen ships starter deps (pydantic + ml numpy/jaxtyping/beartype)
    # and CLI/plugin deps (sdlc-devtools, pytest-cov) that no source imports yet — all ignored via
    # [tool.deptry] (DEP002 slot) so the gate is GREEN on a fresh gen, biting only on a NEW undeclared import.
    run(["uv", "run", "--with", DEPTRY, "deptry", "."], path)


def test_shape_contracts_enforced_runs_clean(project):
    name, path = project
    if COMBOS[name]["domain"] != "ml":
        pytest.skip("the shape gate is wired ML-only (the engine ships in the package regardless)")
    # GRADUATED to blocking (vip.4) — the base runs it with --assert; the seed has no array boundaries so it
    # exits 0. A bare boundary would fail (see test_shape_contracts_assert_catches_bare_boundary).
    run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.shape_contracts", *layers(name), "--assert"], path)


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

GRAPH_ASSERT = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.graph", "--assert", "full_pkg"]


@pytest.fixture(scope="module")
def full_project(scaffold, tmp_path_factory):
    out = tmp_path_factory.mktemp("inject")
    generate(scaffold, out, COMBOS["full"])
    seed_example(out, "full_pkg")  # template ships no code — seed the demo the inject tests mutate
    use_local_devtools(out)  # resolve the devtools git-dep to the working-tree package (test-only)
    git_init_commit(out)
    run(["uv", "sync", "--extra", "dev", "--extra", "devtools"], out)
    return out


def _append(path, text):
    """Mutate: append `text` to a file; return a restore callable (for assert_bites)."""
    original = path.read_text()
    path.write_text(original + text)
    return lambda: path.write_text(original)


def astgrep_scan(cfg):
    """The ast-grep scan of full_pkg, config located from the installed package (per-project path)."""
    return ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", cfg, "full_pkg"]


SHAPE_ASSERT = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.shape_contracts", "--assert", "full_pkg"]


def test_shape_contracts_assert_catches_bare_boundary(full_project):
    # advisory by default; --assert opts into the blocking ratchet. A public method with a bare
    # np.ndarray boundary (no jaxtyping shape) must fail it — the ML shape gate bites (vip.1).
    assert_bites(
        full_project,
        SHAPE_ASSERT,
        lambda p: _append(
            p / "full_pkg" / "math_ops.py",
            "\n\nclass Boundary:\n    def seg(self, x: np.ndarray) -> np.ndarray:\n        return x\n",
        ),
    )


def test_deptry_catches_undeclared_import(full_project):
    # dependency hygiene bites: a source import of an undeclared 3rd-party package is DEP001 (imported but
    # missing from the dependency definitions) — the exact drift the gate exists to catch.
    assert_bites(
        full_project,
        ["uv", "run", "--with", DEPTRY, "deptry", "."],
        lambda p: _append(p / "full_pkg" / "math_ops.py", "\n\nimport requests  # undeclared\n"),
    )


def test_astgrep_catches_top_level_function(full_project):
    assert_bites(
        full_project,
        astgrep_scan(config_path(full_project, "sgconfig")),
        lambda p: _append(p / "full_pkg" / "math_ops.py", "\n\ndef sneaky_top_level():\n    return 1\n"),
    )


def test_astgrep_catches_decorated_top_level_function(full_project):
    # a DECORATED free function is a decorated_definition wrapping the def — the 2nd rule branch must catch it
    assert_bites(
        full_project,
        astgrep_scan(config_path(full_project, "sgconfig")),
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
        ["npx", "--yes", "jscpd", "full_pkg", "--config", config_path(full_project, "jscpd")],
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


def test_copier_update_preserves_nondefault_fact_vars(tmp_path):
    """fsl (P1): a non-default lint_paths / data_env_var must PERSIST in .copier-answers.yml and SURVIVE
    `copier update` — a when:false computed var is neither stored nor honored on the update path, so a
    widened lint scope / custom data-env name was silently lost (tests errored instead of skipping)."""
    scaffold = tmp_path / "scaf"
    scaffold.mkdir()
    make_scaffold(scaffold)  # tags v0.1.0

    project = tmp_path / "proj"
    generate(scaffold, project, {**COMBOS["full"], "lint_paths": "core viewer tests", "data_env_var": "CUSTOM_DATA"})
    git_init_commit(project)

    # the FACT values are asked (when:true) -> persisted in the answers file
    answers = (project / ".copier-answers.yml").read_text()
    assert "lint_paths: core viewer tests" in answers, "non-default lint_paths must persist (fsl)"
    assert "data_env_var: CUSTOM_DATA" in answers, "non-default data_env_var must persist (fsl)"

    # bump a portable rule, tag v0.2.0
    tp = scaffold / "template" / "pyproject.toml.jinja"
    tp.write_text(tp.read_text().replace("file_max = 750", "file_max = 500"))
    run(["git", "commit", "-aqm", "v0.2.0"], scaffold)
    run(["git", "tag", "v0.2.0"], scaffold)

    run(["uvx", COPIER, "update", "--defaults", "--trust"], project)

    # the FACTS SURVIVE the update (the whole point of fsl)
    ci = (project / ".github" / "workflows" / "ci.yml").read_text()
    assert "check core viewer tests --select" in ci, "widened lint_paths survives copier update (fsl)"
    assert "CUSTOM_DATA: /tmp/nodata" in ci, "custom data_env_var survives copier update (fsl)"
    answers2 = (project / ".copier-answers.yml").read_text()
    assert "lint_paths: core viewer tests" in answers2 and "data_env_var: CUSTOM_DATA" in answers2
    assert "file_max = 500" in (project / "pyproject.toml").read_text(), "portable rule still flows in"
