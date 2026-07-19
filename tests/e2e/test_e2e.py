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
    NPX,
    PIP_AUDIT,
    PRECOMMIT,
    PYREFLY,
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
    # every seeded module ships, each at its STRICT mirror path (tests/unit/<pkg>/test_<name>.py)
    for module in ("math_ops", "pipeline", "types", "errors", "memory_store", "repository", "service"):
        assert (path / pkg / f"{module}.py").exists(), f"seed module {module} missing"
        assert (path / "tests" / "unit" / pkg / f"test_{module}.py").exists(), f"mirror for {module} missing"
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


def test_seed_exercises_every_arrow_kind(project):
    """A0 (bd 4bl.6): the fixture must carry every relationship the class-graph gates read, so the later
    batches can assert on REAL arrows. Guards the seed against being thinned back out."""
    name, path = project
    pkg = example_pkg(name)
    src = {
        m: (path / pkg / f"{m}.py").read_text() for m in ("types", "errors", "memory_store", "repository", "service")
    }
    # inherits — INTRA-file (both errors in one module) and CROSS-file (memory_store -> errors)
    assert "class KeyMissingError(StoreError)" in src["errors"], "intra-file inherits pair"
    assert "class CapacityError(StoreError)" in src["memory_store"], "cross-file inherits"
    assert f"from {pkg}.errors import StoreError" in src["memory_store"], "cross-file inherits rides an import"
    # holds — fields typed as the CONTRACT (never a concrete) and as the config satellite
    assert "def __init__(self, store: Store)" in src["repository"], "holds the Store contract"
    assert "def __init__(self, config: StoreConfig)" in src["memory_store"], "holds its config"
    # calls — resolve to the INTERFACE; MemoryStore satisfies Store STRUCTURALLY, never subclassing it
    assert "self._store.get(key)" in src["repository"] and "self._store.put(key, value)" in src["repository"]
    assert "class MemoryStore:" in src["memory_store"], "satisfies Store structurally (no subclassing)"
    # constructs — the CONCRETE is wired in exactly one place (the service), never held by name elsewhere
    assert "Repository(MemoryStore(config))" in src["service"], "construct -> concrete at the wiring site"
    # node roles — a primary class plus its satellite config share one file
    assert "class StoreConfig:" in src["types"] and "class Store(Protocol):" in src["types"]


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
    # 4c2/8ex reopened: E501 (line-length 120 is legislated) + SLF001 (real reach-in signal; the old
    # ast-grep-conflict claim was debunked — no rule forces the tripping shape) are ENFORCED in the union.
    enforced_select = pyproject_text[pyproject_text.index("select = [") : pyproject_text.index("select = [") + 900]
    assert '"E501"' in enforced_select, "E501 must be in the enforced select (graduated to gate — 4c2)"
    assert '"SLF001"' in enforced_select, "SLF001 must be in the enforced select (graduated to gate — 8ex)"
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
    # c80: archmap regen moved to the PRE-PUSH stage (fast commits; refresh once before the deploying push) and
    # blocks the push if graph.json drifted, so the committed diff-truth stays current with no manual regen.
    assert "python -m devtools.archmap" in precommit_text, "archmap regen present (c80)"
    assert "regenerated & staged; commit it and push again" in precommit_text, "archmap blocks on drift (c80)"
    assert precommit_text.count("stages: [pre-push]") >= 2, "archmap + unit-tests both ride pre-push (c80/cma)"
    # cma: fast unit suite bound to the PRE-PUSH stage (shift-left the CI test gate). Push-only, unit-only.
    assert "id: unit-tests" in precommit_text, "the pre-push unit-tests hook ships (cma)"
    assert "stages: [pre-push]" in precommit_text, "unit-tests runs at the pre-push stage, not commit (cma)"
    assert "pytest tests/unit" in precommit_text, "the pre-push hook runs the fast unit suite (cma)"
    nox_text = (path / "noxfile.py").read_text()
    assert "def archmap(" in nox_text, "the manual archmap regen session ships in noxfile (2vt.4)"
    # i5q: the pyrefly strict type gate — [tool.pyrefly] config + wired into all three runners, ENFORCED.
    # The R1 type-grade Correctness leg; env-aware (`uv run --with pyrefly`) so it reads installed dep stubs.
    assert "[tool.pyrefly]" in pyproject_text, "the pyrefly strict type config ships (i5q)"
    assert 'preset = "strict"' in pyproject_text, "pyrefly runs the strict preset (i5q)"
    assert "check-unannotated-defs = true" in pyproject_text, "strict requires annotations everywhere (i5q)"
    assert "pyrefly check" in ci_text, "the pyrefly type gate is wired into CI (i5q)"
    assert "pyrefly check" in precommit_text, "the pyrefly type gate ships as a pre-commit hook (i5q)"
    assert '"pyrefly", "check"' in nox_text, "the pyrefly type gate runs in nox lint (i5q)"
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
    # 4c2/8ex reopened: E501+SLF001 graduated into the enforced select, so the advisory --statistics run
    # carries NO --extend-select (ruff_advisory_select is empty). The enforced select is asserted above.
    assert "--extend-select" not in ci_text, "advisory ruff has no --extend-select (surface empty, 4c2/8ex)"
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
    run([NPX, "--yes", "jscpd", *layers(name), "--config", config_path(path, "jscpd")], path)


def test_class_shape_smells(project):
    name, path = project
    # advisory explorers — must run clean (exit 0); findings are fine, they never block
    for tool in ("state_candidates", "lcom", "data_clumps"):
        run(["uv", "run", "--extra", "devtools", "python", "-m", f"devtools.{tool}", *layers(name)], path)


def test_composition_and_contracts_enforced_run_clean(project):
    """A4 (bd 4bl.4). The seed's object graph is acyclic, and a fresh gen configures no contracts — both
    gates start green and ratchet."""
    name, path = project
    for engine in ("composition", "contracts"):
        run(["uv", "run", "--extra", "devtools", "python", "-m", f"devtools.{engine}", *layers(name), "--assert"], path)


def test_a_use_contract_can_forbid_construction_alone(full_project):
    """A4: the precision an IMPORT rule cannot express. The seed's Service both CONSTRUCTS a concrete
    MemoryStore and uses the Store contract; a `kinds = ["construct"]` contract must catch the former
    while an equivalent import-level rule could only say "service imports memory_store"."""
    contract = (
        '\n[[tool.arch.forbidden]]\nname = "only wiring may construct a concrete store"\n'
        'source = "full_pkg.service"\nforbidden = ["full_pkg.memory_store"]\nkinds = ["construct"]\n'
    )
    cmd = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.contracts", "full_pkg", "--assert"]
    result = assert_bites(full_project, cmd, lambda p: _append(p / "pyproject.toml", contract))
    text = result.stdout + result.stderr
    assert "--construct-->" in text, "the finding names the arrow KIND, not just a dependency"
    assert run(cmd, full_project).returncode == 0, "green again once the contract is removed"


def test_demeter_enforced_runs_clean(project):
    """A5 (bd 4bl.5). The seed reaches its own fields and stops (`self._store.get(key)` = 2 hops), so the
    gate is green from day one and ratchets — a fresh gen has no code at all."""
    name, path = project
    run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.demeter", *layers(name), "--assert"], path)


def test_arrows_advisory_decomposes_the_seed(project):
    """A2 (bd 4bl.2): the arrow report decomposes an import edge into WHY it exists. The fixture was built
    to carry each kind, so assert the REAL arrows appear — not merely that the explorer exits 0."""
    name, path = project
    pkg = example_pkg(name)
    result = run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.arrows", *layers(name)], path)
    text = result.stdout + result.stderr
    assert f"{pkg}.errors.KeyMissingError -> {pkg}.errors.StoreError" in text, "intra-file inherits"
    assert f"{pkg}.memory_store.CapacityError -> {pkg}.errors.StoreError" in text, "cross-file inherits"
    # the architectural fact an import edge cannot express: the repository holds the CONTRACT, not a concrete
    assert f"{pkg}.repository.Repository -> {pkg}.types.Store" in text, "holds the Store contract"
    assert f"{pkg}.memory_store.MemoryStore -> {pkg}.types.StoreConfig" in text, "holds its config"
    assert f"{pkg}.service.Service -> {pkg}.repository.Repository" in text, "holds a constructed field"


def test_calls_advisory_splits_contract_from_concrete(project):
    """A3 (bd 4bl.3): the partition the design rests on. A behavioural call resolves to the DECLARED type
    (the contract), while the CONCRETE shows up only where it is constructed — at the wiring site."""
    name, path = project
    pkg = example_pkg(name)
    result = run(["uv", "run", "--extra", "devtools", "python", "-m", "devtools.calls", *layers(name)], path)
    text = result.stdout + result.stderr
    contract, concrete = text.split("construct -> the concrete")
    # the repository calls the Store CONTRACT — never the MemoryStore that actually runs
    assert f"{pkg}.repository.Repository -> {pkg}.types.Store" in contract, "call lands on the interface"
    assert f"{pkg}.memory_store.MemoryStore" not in contract, "a call never reaches the concrete impl"
    # ...and the concrete is reached exactly once, by the class that wires it
    assert f"{pkg}.service.Service -> {pkg}.memory_store.MemoryStore" in concrete, "construct -> concrete"


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


def test_archmap_diff_reports_what_moved(project):
    """B5 (bd 433.5): the changelog view. The gates say what is FORBIDDEN; this says what MOVED, in REAL
    dependency terms — a reviewer sees which arrow KIND appeared, not that a JSON file changed."""
    name, path = project
    pkg = example_pkg(name)
    archmap = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.archmap", *layers(name)]
    run(archmap, path)
    baseline = path / "base.json"
    graph = json.loads((path / "docs" / "architecture" / "graph.json").read_text())
    # a baseline WITHOUT the holds arrows: the diff must then report them as added, naming the kind
    thinned = {"nodes": graph["nodes"], "edges": [e for e in graph["edges"] if e["kind"] != "holds"]}
    baseline.write_text(json.dumps(thinned))
    result = run([*archmap, "--diff", str(baseline)], path)
    text = result.stdout + result.stderr
    assert "holds" in text and f"{pkg}.repository.Repository" in text, f"the moved arrow is named: {text}"
    # ...and it is ADVISORY — a changelog explains, it does not block
    assert result.returncode == 0


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
    generate(scaffold, off / "p", {"project_name": "pg", "packages": "pg", "domain": "none"})  # pages default off
    assert not (off / "p" / ".github" / "workflows" / "pages.yml").exists(), "default (false) omits pages.yml"


def test_readme_repo_url_badges_and_arch_link(scaffold, tmp_path_factory):
    # 0hp: repo_url drives README CI + license badges (owner/repo slug) and, with archviz_pages, the live
    # architecture-viewer link (derived https://OWNER.github.io/REPO/architecture/). scp/ssh remotes parse too.
    on = tmp_path_factory.mktemp("readme_on")
    generate(
        scaffold,
        on / "p",
        {
            "project_name": "pg",
            "packages": "pg",
            "domain": "none",
            "archviz_pages": "true",
            "repo_url": "git@github.com:me/pg.git",
        },
    )
    readme = (on / "p" / "README.md").read_text(encoding="utf-8")
    assert "github.com/me/pg/actions/workflows/ci.yml/badge.svg" in readme, "CI badge from the parsed slug"
    assert "license-MIT-blue" in readme, "license badge"
    assert "https://me.github.io/pg/architecture/" in readme, "live viewer link derived from repo_url + archviz_pages"
    assert "git clone git@github.com:me/pg.git" in readme, "clone line uses repo_url verbatim"

    # No repo_url -> no badges, no clone line, no live link (blank-safe).
    bare = tmp_path_factory.mktemp("readme_bare")
    generate(scaffold, bare / "p", {"project_name": "pg", "packages": "pg", "domain": "none", "archviz_pages": "true"})
    r2 = (bare / "p" / "README.md").read_text(encoding="utf-8")
    assert "badge.svg" not in r2 and "github.io" not in r2 and "git clone" not in r2, "blank repo_url renders nothing"

    # repo_url but archviz_pages off (compose case) -> badges yes, live link NO (consumer folds it in themselves).
    comp = tmp_path_factory.mktemp("readme_compose")
    generate(
        scaffold,
        comp / "p",
        {"project_name": "pg", "packages": "pg", "domain": "none", "repo_url": "https://github.com/me/pg"},
    )
    r3 = (comp / "p" / "README.md").read_text(encoding="utf-8")
    assert "badge.svg" in r3, "badges still render (repo_url set)"
    assert "github.io" not in r3, "no auto live-link without archviz_pages (compose case)"


def test_deptry_enforced_runs_clean(project):
    name, path = project
    # ENFORCED dependency hygiene. A fresh gen ships starter deps (pydantic + ml numpy/jaxtyping/beartype)
    # and CLI/plugin deps (sdlc-devtools, pytest-cov) that no source imports yet — all ignored via
    # [tool.deptry] (DEP002 slot) so the gate is GREEN on a fresh gen, biting only on a NEW undeclared import.
    run(["uv", "run", "--with", DEPTRY, "deptry", "."], path)


def test_pyrefly_enforced_runs_clean(project):
    name, path = project
    # ENFORCED static type gate (i5q). The seed (MathOps/Pipeline) is fully annotated + type-correct, so a
    # fresh gen passes with 0 errors — it blocks from day one as a regression guard (no advisory ratchet).
    # Env-aware (`uv run --with pyrefly`) so it resolves the installed dep stubs (pydantic/numpy py.typed).
    run(["uv", "run", "--with", PYREFLY, "pyrefly", "check", *layers(name)], path)


def test_shape_contracts_enforced_runs_clean(project):
    name, path = project
    if COMBOS[name]["domain"] != "ml":
        pytest.skip("the shape gate is wired ML-only (the engine ships in the package regardless)")
    # GRADUATED to blocking (vip.4) — the base runs it with --assert; the seed has no array boundaries so it
    # exits 0. A bare boundary would fail (see test_shape_contracts_assert_catches_bare_boundary).
    run(
        ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.shape_contracts", *layers(name), "--assert"],
        path,
    )


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


def test_gitattributes_marks_generated_tracked(project):
    # izdo: generated-but-tracked files collapse in PRs so churn/erosion diffs don't clutter the page.
    _, path = project
    lines = (path / ".gitattributes").read_text().splitlines()
    beads = next(ln for ln in lines if ln.startswith(".beads/issues.jsonl"))
    graph = next(ln for ln in lines if ln.startswith("docs/architecture/graph.json"))
    # tier 1 — beads state: fully hidden + auto-merged (a line file re-exported wholesale each session)
    assert "-diff" in beads and "linguist-generated=true" in beads and "merge=union" in beads
    # tier 3 — graph.json: collapsed but expandable; NO -diff/union (its diff is the erosion signal, and a
    # JSON object can't be union-merged without corrupting it)
    assert "linguist-generated=true" in graph and "-diff" not in graph and "merge=union" not in graph
    assert any("LOCAL-SLOT: generated-tracked paths" in ln for ln in lines), "consumer slot ships (izdo)"


# The pre-push unit hook is a distinct STAGE (`--all-files` above runs commit-stage hooks only), so it needs
# `--hook-stage pre-push` — which also proves pre-commit accepts the stage wiring.
PREPUSH_UNIT = ["uvx", PRECOMMIT, "run", "unit-tests", "--hook-stage", "pre-push", "--all-files"]


def test_prepush_unit_hook_blocks_broken_contract(full_project):
    # cma: the pre-push hook runs tests/unit so a broken test CONTRACT is caught locally before the push, not
    # after CI. The clean seed passes; renaming the public method the mirror test calls keeps lint green (an
    # attribute call ruff can't see across modules) but breaks pytest — so the hook must block the push.
    run(PREPUSH_UNIT, full_project)  # clean seed -> the pre-push unit hook passes
    assert_bites(
        full_project,
        PREPUSH_UNIT,
        lambda p: _replace(p / "full_pkg" / "math_ops.py", "def mean(", "def mean_x("),
    )


PREPUSH_ARCHMAP = ["uvx", PRECOMMIT, "run", "archmap", "--hook-stage", "pre-push", "--all-files"]


def _add_module(root):
    """Mutate: add a new package module (new node + import edge) so the architecture graph changes; return a
    restore that removes it AND resets the hook-regenerated graph.json back to the committed baseline."""
    f = root / "full_pkg" / "extra.py"
    f.write_text(
        "from full_pkg.math_ops import MathOps\n\n\n"
        "class Extra:\n"
        "    @classmethod\n"
        "    def use(cls) -> float:\n"
        "        return MathOps.mean([1.0])\n"
    )

    def restore():
        f.unlink()
        run(["git", "checkout", "--", "docs/architecture/graph.json"], root, check=False)
        run(["git", "reset", "--", "docs/architecture/graph.json"], root, check=False)

    return restore


def test_prepush_archmap_regenerates_and_blocks_on_drift(full_project):
    # c80: the pre-push archmap hook regenerates graph.json and BLOCKS the push if it drifted, so the committed
    # diff-truth (and the /architecture/ page it feeds) stays current without a manual `nox -s archmap`.
    run(PREPUSH_ARCHMAP, full_project, check=False)  # first run creates graph.json (was untracked)
    run(["git", "add", "docs/architecture/graph.json"], full_project)
    run(["git", "commit", "-m", "baseline graph.json", "--no-verify"], full_project)
    run(PREPUSH_ARCHMAP, full_project)  # graph matches source -> hook passes
    assert_bites(full_project, PREPUSH_ARCHMAP, _add_module)  # drift -> regen differs -> push blocked


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


def _replace(path, old, new):
    """Mutate: substitute `old`->`new` in a file; return a restore callable (for assert_bites)."""
    original = path.read_text()
    assert old in original, f"mutate target {old!r} not found in {path}"
    path.write_text(original.replace(old, new))
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


def test_pyrefly_catches_type_error(full_project):
    # the type gate bites (i5q): a return that doesn't match the declared type is bad-return — a defect ruff's
    # lint codes can't see (it needs cross-annotation type inference). Strict also forces annotations, so a
    # bare param would fail implicit-any-parameter; a bad return is the cleaner single-signal injection.
    assert_bites(
        full_project,
        ["uv", "run", "--with", PYREFLY, "pyrefly", "check", "full_pkg"],
        lambda p: _append(
            p / "full_pkg" / "math_ops.py",
            "\n\nclass TypeBug:\n    @staticmethod\n    def bad(x: int) -> str:\n        return x + 1\n",
        ),
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
    try:
        result = run(
            [NPX, "--yes", "jscpd", "full_pkg", "--config", config_path(full_project, "jscpd")],
            full_project,
            check=False,
        )
    finally:
        # RESTORE IN finally: `full_project` is module-scoped, so if the runner raises (e.g. npx is on PATH
        # but not executable) an un-restored injection leaks into every later test — a duplicated class left
        # in math_ops.py reads as a second PRIMARY and fails the roles gate, three tests downstream.
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


DEMETER_ASSERT = ["uv", "run", "--extra", "devtools", "python", "-m", "devtools.demeter", "full_pkg", "--assert"]


def test_demeter_catches_a_reach_through(full_project):
    # A5 (bd 4bl.5): walking THROUGH a field into a stranger (`r._store.config.namespace`, 3 hops) couples
    # this class to a type it never declared. Talking to your OWN field is 2 hops and stays clean.
    result = assert_bites(
        full_project,
        DEMETER_ASSERT,
        lambda p: _append(
            p / "full_pkg" / "repository.py",
            "\n\nclass Wreck:\n    def go(self, r: Repository) -> str:\n        return r._store.config.namespace\n",
        ),
    )
    assert "reaches 3 deep" in (result.stdout + result.stderr), "the gate names the depth it found"
    assert run(DEMETER_ASSERT, full_project).returncode == 0, "passes again once reverted"


def test_graph_assert_catches_two_primary_classes(full_project):
    # One file = one SUBJECT (bd 4bl.1): a second INDEPENDENT class in a module blocks. The idiomatic
    # companions stay clean and the seed proves it — types.py ships a Store contract beside its StoreConfig
    # dataclass, errors.py an error family, memory_store.py a class beside its CapacityError; all pass.
    result = assert_bites(
        full_project,
        GRAPH_ASSERT,
        lambda p: _append(
            p / "full_pkg" / "repository.py", "\n\nclass Unrelated:\n    def go(self) -> int:\n        return 1\n"
        ),
    )
    assert "class roles" in (result.stdout + result.stderr), "the roles gate names itself in the failure"
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
        "from kern.math_ops import MathOps\n\n\n"
        "class Thing:\n"
        "    @staticmethod\n"
        "    def go() -> float:\n"
        "        return MathOps.mean([1.0])\n"
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
