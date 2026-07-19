# SPEC — the scaffold contract

Single source of truth for the template's gate contract: exact names, values, and mechanics.
Derived from the 3 real repos (cardiac-seg / mindscape / synthscape), read-only reference.

## Design model

**What a gate defends.** Every gate protects one or more of **four structural properties** — Correctness ·
Consistency · Minimality · Structure — each at a **radius** = the minimum code a check must READ to fire
(R1 unit / R2 module / R3 system, the structural mirror of the test pyramid). Plus an orthogonal **Security**
axis (ruff `S` · pip-audit). Three deliberate calls: **Minimality** is pure removal (delete/dedupe — the
economy axis); **Structure** absorbs both old *Simplicity* (split the over-complex) and *Cohesion*
(extract the missing object / LCOM) — every *reshape* fix, intra-unit up to the graph, is one shape axis; and
**Completeness** (math sense: every required subcase proven) is **absent** — it needs a requirements spec this
scaffold has no access to, so coverage floors test-presence under Correctness, not requirement-completeness.
The property↔tool map is many-to-many. The README owns that taxonomy (the *why*); this file owns the
*what-exactly* (names, values, mechanics).

A **gate** = engine + parameters + invocation. Two axes decide delivery:
- **engine owner**: vendored (ruff/vulture/coverage/ast-grep/jscpd) → pinned version; ours
  (`graph.py`, the class-shape tools) → shipped code, unit-tested in `tests/unit/`.
- **param locality**: PORTABLE (house style, same everywhere → shared SUPERSET block, template-owned),
  LOCAL-SLOT (project facts: paths/source/thresholds → stays in repo, `# >>> LOCAL-SLOT` marked), or
  ANSWER (asked at copy time, recorded in `.copier-answers.yml`, replayed on update).

**Superset rule**: a portable param that is harmless-when-unused (ignore-lists, exclude-lines) is
shipped as the UNION of the 3 repos. Do NOT thin it to make a gate pass.

**RULE vs FACT — the convergence law (bd o70, owner decision).** The end-state guardrail set is the UNION
of every repo's rules, not a 2/3 majority. Two kinds of thing, and only one is per-repo:
- **RULES** — ruff select codes, the gate inventory, pep8-naming (`N`). UNION base, byte-identical across
  all repos. There are **no per-repo rule slots** (a `base_select + local_extra` split is explicitly
  REJECTED — it lets a repo keep NOT running a code a sibling runs, i.e. a dodge). A code any repo enforces
  is house bar for all; each repo FIXES up to it the hard way (no suppression, no threshold-drop; k8c).
- **FACTS** — deps, scan paths (`packages` + the per-gate scope slots), pep8 ignore-**names** VOCAB, vulture
  domain FPs, `[tool.structure]` thresholds. Additive per-repo LOCAL-SLOTs. `monai` ≠ `mne` is a fact, not
  a loosened rule. This is where legitimate divergence lives — and only here.

For the full breakdown of every rule by **General vs Specific** and **Authored / Generated / Evolved** (and
the decide-or-advisory threshold rule), see [`RULE_INVENTORY.md`](RULE_INVENTORY.md).

A new gate follows the same law: if any repo runs it, it enters the BASE (ml-specific gates ride
`enable_ml`, e.g. shape_contracts). There are no permanent repo-local *gates* either — union forbids them.

**Guardrails, not architecture**: the scaffold imposes NO layering. Gates target the `packages` the
project declares; directional layer contracts (import-linter) are opt-in, never shipped.

## copier.yml — prompt surface + EXACT var names (freeze)

Asked at copy time:

| var | type | default | meaning |
|---|---|---|---|
| `project_name` | str | (ask) | repo/folder name, kebab-case (e.g. `sample-proj`) |
| `packages` | str | `project_name` snake_cased | comma-list of packages the guardrails target (e.g. `core,neuroscan,neuroviz`) |
| `domain` | enum | `ml` | `ml` = numpy dep + ML-workflow gitignore (data/`paths.yaml`/MLflow/`runs/`) + data-skip CI env; `none` = domain-neutral |
| `coverage_floor` | int | 80 | `coverage report --fail-under` value |
| `author` | str | `project_name` | copyright holder for the generated MIT `LICENSE` (bd c64 — a scaffold with no LICENSE leaves every gen all-rights-reserved) |
| `lint_paths` / `jscpd_paths` | str | `packages` (space-joined) | R1 hygiene scan scope (ruff / jscpd) — Enter to accept, or widen to a viewer/tests tree. ASKED (not computed) so a non-default value persists + survives `copier update` (bd fsl) |
| `data_env_var` | str (ml only) | `{PROJECT_UPPER}_DATA` | ml data-skip CI env var NAME — asked for `domain=ml` only, persisted so a repo's real name (e.g. `CARDIAC_DATA`) survives update instead of reverting to the derived default (bd skr GAP3a / fsl) |
| `repo_url` | str | `""` | the repo's own git remote — README clone line + the source for the DERIVED architecture Pages link. Blank skips both. The CONSUMER repo, distinct from the scaffold URL in the devtools pin |
| `archviz_pages` | bool | `false` | opt-in: ship the sole-owner staged Pages deploy workflow (`/architecture/` main + `/preview/` dev + root redirect). Off = no workflow (compose into an existing Pages deploy instead — see README) |

That's the whole prompt surface. **The quality gates + beads are NON-optional (no toggles): arch-fitness,
import-linter, ast-grep, jscpd, class-shape, beads are always shipped** — the house bar (bd rji). Their
template blocks render unconditionally — the inert `{% if enable_X %}` guards were removed (bd 9nq); the
only in-file gating left is `use_import_linter` (import-linter self-gates on >1 package) and `enable_ml`
(domain). The **template ships ZERO package code** (bd r2w) — only guardrails; a fresh gen is empty, you
write the first module.

Domain: `domain=ml` (default) makes this an ML-project scaffold (numpy + data-outside-repo + MLflow).
`domain=none` = neutral Python guardrail scaffold. **Doc-layer convention** (documented in the generated
`CLAUDE.md`/`AGENTS.md`, not shipped as folders — no speculative dirs) is `domain=ml`-only in full:
`learning/<date>_<topic>.md` (study ramp), `research/` (external field synthesis), and
`interpretations/<task>/<date>_<topic>.md` (sense-making of *our own* results, `converging/` for cross-task) —
a study ramp presumes a field to study, so a neutral tool gets none of them, nor the `paths.yaml`/data-outside-repo
bullet. The ruff `extend-exclude` default gates all three to ml (only `docs` is always excluded). `pydantic`,
`docs/PLAN.md`+`ROADMAP.md` ship regardless (house conventions, a later trim).

Computed / never asked (`when: false`, one home in copier.yml): `enable_ml` (=`domain == 'ml'`),
`use_import_linter` (=`packages` has >1), plus:

| var | value | used for |
|---|---|---|
| `ruff_select` | curated ENFORCED union (below) | rendered into pyproject/ci/nox/pre-commit + parsed by the E2E conftest |
| `ruff_advisory_select` | `` (empty) | extra codes for the advisory whole-tree `--statistics` run (`--extend-select`, guarded off when empty); E501/SLF001 graduated into the enforced union (bd 4c2/8ex reopened) so nothing rides here now |
| `ruff_version` / `vulture_version` / `nox_version` / `deptry_version` / `precommit_version` / `pyrefly_version` | pins (below) | single-sourced into ci/nox/pre-commit + conftest |
| `devtools_ref` | scaffold release tag (e.g. `v1.14.0`) | the `sdlc-devtools` git-dep pin in the generated `pyproject.toml`'s `devtools` extra — bumped per release so `copier update` re-renders one pin line (bd p99) |
| `repo_slug` | `OWNER/REPO` parsed from `repo_url` (https or scp/ssh github remote), else `""` | README CI + license badges; the base for `pages_url` |
| `pages_url` | `https://OWNER.github.io/REPO` from `repo_slug` (empty if unparsed) | the README architecture-link base — `{pages_url}/architecture/`, rendered only when `archviz_pages` (sole-owner site); compose consumers add their own |

## Gate inventory

| # | gate | engine | portable params | local-slot / answer |
|---|---|---|---|---|
| 1 | ruff lint (enforced) | vendored ruff | `line-length`, `select` (=`ruff_select`), `ignore`, `per-file-ignores` | `extend-exclude` (slot); scope=`lint_paths` (R1 hygiene, default `packages`, widenable — 9mu). The enforced CLI passes `--ignore F722` iff `enable_ml` — an explicit `--select` bypasses pyproject `ignore`, so the jaxtyping waiver is repeated on the CLI (else a fresh ml gen red-CIs on its own config; bd skr GAP1) |
| 2 | ruff format --check (advisory) | vendored ruff | (never blocks) | — |
| 3 | vulture dead-code | vendored vulture | `min_confidence`, `ignore_decorators`, `ignore_names` core | `paths`, `exclude` (slot) |
| 4 | coverage floor | vendored coverage/pytest-cov | `exclude_lines`, `show_missing` | `source`, `omit` (slot); `fail-under`=`coverage_floor` (answer) |
| 5 | arch fitness | OURS `graph.py --assert` | (mechanism; `--no-test-mirror` skips the mirror check for a test-less tree) | `[tool.structure]` thresholds (slot) |
| 5b | test-mirror (part of #5) | OURS `graph.py` `unmirrored()` + `omit.py` | `__init__`/`__main__` exempt | `[tool.coverage] omit` shells exempt |
| 5c | class roles / one-subject-per-file (part of #5, ENFORCED) | OURS `classes.py` `ClassIndex` | role rules (no config) | Blocks when a file defines >1 **PRIMARY** class — two subjects sharing a module. A class is a **SATELLITE** (never counted) when it is an ERROR (own name or a base ends in `Error`/`Exception` — reliable because the shipped select carries pep8-naming `N818`, so one gate makes the other's heuristic sound), a DATACLASS or ENUM (value/config object, `@dataclass` and `@dataclass(...)` both), or a SUBCLASS OF A SAME-FILE class (a local specialisation). Zero primaries is fine (a pure error/config module). The containment tier the typed class graph is built on (bd 4bl.1) |
| 6 | ast-grep module-shape | vendored ast-grep + our `sg-rules` | rule yml | scan paths = `packages` |
| 7 | jscpd DRY | vendored jscpd | `jscpd.json` threshold | scope=`jscpd_paths` (R1 hygiene, default `packages`, widenable to a web-TS dir — 9mu) |
| 8 | class-shape explorers | OURS lcom/data_clumps/state_candidates | (advisory, always exit 0) | scan paths = `packages` |
| 9 | import-linter (self-gates on >1 pkg) | vendored import-linter | (mechanism) | `[tool.importlinter]` contracts (LOCAL-SLOT) |
| 10 | magic-literals (ADVISORY) | OURS `magic_literals.py` | `_STRING_THRESHOLD`/key-set mins | scan paths = `packages`; ranked StrEnum/dataclass-candidate report, always exit 0. No config knob — there is no honest universal ceiling (0 too strict, N arbitrary), so it stays advisory; a repo that needs a budget adds a legislated knob then (0sx) |
| 11 | shape-contracts (ENFORCED; ML-only) | OURS `shape_contracts.py --assert` | builtin `ndarray`/`Tensor` + jaxtyping vocab | ships iff `enable_ml`; `[tool.shape_contracts] array_aliases` (slot). GRADUATED advisory->blocking (bd vip.4) — a fresh gen has 0 boundaries so `--assert` passes; a bare array/tensor boundary then fails |
| 12 | deptry dependency-hygiene (ENFORCED) | vendored deptry (`deptry_version`) | DEP001 undeclared / DEP002 unused / DEP003 transitive | `[tool.deptry] extend_exclude=noxfile`; `per_rule_ignores.DEP002` = shipped starters (pytest/pytest-cov/sdlc-devtools always; numpy/jaxtyping/beartype iff ml + pydantic) in the `deptry-unused` slot — deptry skips `tests/`, so tooling/starter deps read as unused until wired (85l.2). Runs env-aware (`uv run --with deptry`) to read installed dist metadata |
| 13 | pip-audit known-CVE (NIGHTLY) | vendored pip-audit (`pip_audit_version`) | PyPA advisory DB; `--skip-editable` drops the git-pinned devtools | its OWN `audit.yml` workflow (cron + `workflow_dispatch`) + opt-in `nox -s audit`, NOT the per-PR ci.yml — advisories change under you, so a scheduled scan that fails on a known vuln is the honest cadence (85l.3). Security/supply-chain is an axis ORTHOGONAL to the four structural properties |
| 14 | complexity (ADVISORY) | OURS `complexity.py` on `radon` CC (a package lib dep) | radon McCabe CC | ranked CC report + current max, always exit 0. The FIXED complexity gate is ruff `C901`/`PLR09xx` (CC>10, legislated in `ruff_select`); this just surfaces the ranking as reviewer signal (0sx). Supersedes `analytics.py`'s McCabe proxy |
| 15 | archmap architecture autoviz (ADVISORY / doc-gen) | OURS `archmap.py` on grimp | (mechanism — nodes/edges derived from `packages`, no config) | scan paths = `packages`. Emits `docs/architecture/graph.json` (nodes with containment `parent` + `descendants`, import edges weighted by import count) — the committed, deterministic **diff-truth** — plus a self-contained interactive **cytoscape viewer** (`index.html`, vendored libs inlined, gitignored + regenerated) that folds/expands packages to any depth (a folded pair = ONE arrow labelled the summed count) and focuses a module's neighbourhood. Wired 3 ways (2vt.4/m5c.5, c80): manual `nox -s archmap` regen, a **pre-push** REGEN hook (regenerates + stages + blocks the push if graph.json drifted — keeps the committed diff-truth current so the deployed page is fresh, no manual regen; pre-push not per-commit so commits stay fast), and a CI advisory `--check` (`continue-on-error`, `::warning::` on a stale graph.json, the backstop). **Publishing** is one-repo-one-Pages-site: a repo gets exactly one Pages URL, so archmap picks ONE of two modes (clf). SOLE-OWNER — opt-in `archviz_pages` ships a **GitHub Pages** deploy workflow that owns a staged site: `/architecture/` = main, `/architecture/preview/` = dev (rebuilt from `origin/dev`, guarded so a no-dev repo skips it), `/` redirects. COMPOSE — a repo that already deploys Pages leaves `archviz_pages` off and folds the archmap build into its existing workflow as an `/architecture/` subpath (isolated `uv run --no-project --with sdlc-devtools@<tag>` → `write_viewer`; `../synthscape` is the reference). graph.json stays committed either way. DOC-GEN — visualizes structure, does NOT enforce it; import-linter stays the directional gate. Superseded the static mermaid mirror-tree of v1.5.0 (epic m5c) |
| 16 | pyrefly type-check (ENFORCED) | vendored pyrefly (`pyrefly_version`) | `preset="strict"` (strict-callable-subtyping + implicit-any + missing-override + unused-ignore) + `check-unannotated-defs` | `[tool.pyrefly]`; the `pyrefly-ignore-imports` slot (untyped deps with no py.typed → treated as Any, parallel to the deptry/vulture fact-vocab slots) + a `tests/**` sub-config carve-out (pytest injects unannotated fixture params). Runs env-aware (`uv run --with pyrefly`, like deptry) so it reads installed dep stubs; scope=`lint_paths`. The R1 type-grade **Correctness** leg ruff's lint codes can't reach — annotations PRESENT (a bare param fails implicit-any-parameter) AND CHECKED (a mismatch fails bad-return / bad-argument-type). A fresh gen's seed is fully typed (0 errors), so it BLOCKS from day one as a regression guard, no advisory ratchet |
| 17 | class arrows (ADVISORY) | OURS `arrows.py` `ClassArrows` | (no config) | Decomposes an import edge into WHY it exists: `inherits` (is-a, from bases), `holds` (has-a — a field's type, from class-body/`self.x: T`/an `__init__` param kept as state/`self.x = T(...)`), `references` (API depends-on — signature types the class does NOT hold). Resolution is annotation-driven and PRECISE-BUT-INCOMPLETE: a name resolves via the file's own classes then its imports; anything else (builtin, third-party, dynamic) is dropped rather than guessed — never a wrong edge, sometimes a missing one. ROLL-UP invariant (unit-tested): project an arrow to its files and a CROSS-file arrow rides a real grimp import, while an INTRA-file arrow collapses to a self-loop the import graph cannot represent. `calls` is Batch 2 and `holds` is its fuel. Advisory report for now; the gates land in bd 4bl.4 |
| 18 | law of demeter (ENFORCED) | OURS `demeter.py` `Demeter` | `[tool.structure] demeter_max_depth` (default 2) | Blocks a chain that reaches THROUGH a field into a stranger: `self.store.get(k)` is 2 hops (reach your own field, then talk to it) and passes; `self.store.config.name` is 3 and fails — this class is now coupled to a type it never declared. NOT counted: chains rooted at an imported MODULE (`np.linalg.norm`) or an imported CLASS (`Path.home()`) — a dotted namespace path, not a walk across objects; nor chains rooted in a call (no name to attribute it to). Reported once per chain, not per prefix. The one architecture smell needing no graph — it is visible inside a single expression (R1). Raise the ceiling for data-navigation-heavy trees (AST/JSON walking), where depth is reading a structure, not coupling |
| 19 | call arrows (ADVISORY) | OURS `calls.py` `CallArrows` | (no config) | The BEHAVIOURAL arrow: who calls whom, plus a `via=construct` tag for who builds whom. Resolved to the **DECLARED** receiver type, never the concrete — `self._store.get(k)` where `_store: Store` is an edge to **Store**, the contract the code committed to, even though a `MemoryStore` runs at runtime. Chasing the concrete would invent an edge the source never states. The concrete coupling is not lost, it is filed where it belongs: a concrete is CONSTRUCTED at a wiring site, so the two cuts partition it — `calls` reaches the INTERFACE (behavioural contract), `construct` reaches the CONCRETE (the site that chose it). A receiver resolves from declared types already in scope (a field via the shared field map, a parameter via its annotation, a local via its constructor); a call on a returned value or a reflective lookup resolves to nothing and emits no edge. Self-edges dropped; results deduped. Shares `resolve.py` with the structural arrows. Advisory report for now; the gates land in bd 4bl.4 |
| 20 | composition cycles (ENFORCED) | OURS `composition.py` `CompositionCycles` | (no config) | Blocks a cycle in the `holds` subgraph — A owns a B that owns an A, so neither can be constructed, tested, or reasoned about alone. This is one tier BELOW graph.py's import-cycle gate and catches what that gate structurally cannot: two classes composing each other INSIDE one module roll up to a file self-loop, so there is no import cycle at all. The `holds` subset is SOUND (a field's declared type is stated in the source, not inferred), so it blocks rather than advises. Each mutually-composing group is reported once |
| 21 | forbidden-USE contracts (ENFORCED) | OURS `contracts.py` `UseContracts` | `[[tool.arch.forbidden]]` (LOCAL-SLOT: `arch-contracts`) | Directional rules over the DECOMPOSED arrows (inherits / holds / references / calls / construct) rather than imports. import-linter can only say "must not IMPORT" — the rule people actually mean, approximated by the one edge it can see, so it fires on a type-only import and stays silent about a dependency reached through an inherited base. A contract here states "must not USE", and `kinds` can target ONE arrow: **"nothing outside the composition root may CONSTRUCT a concrete"** is expressible and simply is not expressible over imports. Prefix-matched by module, directional, deduped. NO contracts configured = nothing to check, so a fresh gen is green and ratchets. The GATE is universal; the LAYERS are a per-repo FACT (hence the slot) |
| 22 | feature envy (ENFORCED) | OURS `envy.py` `FeatureEnvy` | `[tool.structure] feature_envy_min` (default 4) | Fowler's smell at the granularity it lives — the METHOD. `arrows.py`/`calls.py` aggregate per CLASS, which is right for "does this class depend on that one" but blind here: a class can be perfectly coupled while ONE of its methods belongs elsewhere. Counts, per method, members touched on its OWN object versus on a SINGLE foreign class — spreading calls across several collaborators is orchestration, a different (often correct) shape, so envy is judged against one class only. Just the OUTERMOST link of a chain counts, so `self._store.get(k)` is one access to Store rather than also one to self. Receivers resolve as in `calls.py` (field type / param annotation / local constructor); an unresolvable receiver is not counted, so the ratio is computed only over accesses we understand. VALUE OBJECTS ARE NEVER THE TARGET: a SATELLITE (dataclass/enum/error, per gate 5c) is excluded, because reading a value object field-by-field is what it is FOR and the implied fix (move the method onto it) is usually impossible. `feature_envy_min` is the floor below which the ratio is noise — raise it for delegator-heavy repos (mappers/serializers/visitors) rather than weakening the rule |

import-linter is a shipped gate (all 3 house repos run it): it enforces DIRECTIONAL forbidden-import
contracts — a one-way `core -> trainer` import is no cycle, so it passes `graph.py` but must fail here.
The GATE is universal; the CONTRACTS are project-local (kernel-independence starter + slot). It is the ONE
gate that self-gates: shipped only when `packages` has >1 entry (nothing to forbid in a single package),
via the computed `use_import_linter`. Every other gate is unconditional (no toggle). jscpd is ENFORCED
(blocks over threshold) in ci+nox — the cardiac/mindscape majority — not a commit hook (Node).

**Generated-but-tracked collapse (bd izdo).** The shipped `.gitattributes` keeps generated files that stay
committed from cluttering a PR. Three tiers from two knobs — `linguist-generated=true` (GitHub: collapse in
Files-changed, expandable; drop from the language bar) and the git pair `-diff` (binary → no textual diff
anywhere) + `merge=union` (keep-both on conflict, safe ONLY for line-oriented wholesale-regenerated files;
corrupts structured JSON/TOML). Defaults: `.beads/issues.jsonl` = tier 1 (`-diff` + `linguist` + `union` —
a huge churny state file re-exported each session, never hand-read); `docs/architecture/graph.json` = tier 3
(`linguist` only — generated, but its diff is the architecture-erosion signal so it stays reachable, and a
JSON object can't be union-merged). A `# >>> LOCAL-SLOT: generated-tracked paths` region documents all three
tiers for a consumer's own generated-tracked files (RESULTS.json, sync markers, run logs). The scaffold
dogfoods the same two rules in its own root `.gitattributes`.

**CI repo-step slots (bd skr GAP3).** `ci.yml` carries two `# >>> LOCAL-SLOT` regions — `ci-lint-steps`
(lint job) and `ci-test-steps` (tests job) — empty by default, so a consumer whose CI is a SUPERSET of the
base (a viewer-coverage floor, an un-silenced advisory family, `shape_contracts --assert` as a blocking step
for a boundary-clean repo graduating ahead of the base) rides those steps on slots instead of forking the
workflow. Mechanism identical across repos; only the slot CONTENTS are a per-repo FACT.

**Engines require ≥1 package (bd skr GAP2).** Every `devtools/*.py` gate takes `packages` as `nargs="+"` —
a no-arg invocation is an argparse usage error, NOT a silent scan of a phantom `src/` (which made
`shape_contracts --assert` vacuously PASS). The rendered runners always pass `packages` explicitly.

**The analyzers are a package (bd p99).** As of v1.2.0 the engines are NOT vendored into a consumer — they
live in the `sdlc-devtools/` package (imported as `devtools`), consumed by a git dependency pinned by
scaffold tag in the generated `pyproject.toml`'s `devtools` extra
(`sdlc-devtools @ git+…@{{ devtools_ref }}#subdirectory=sdlc-devtools`). An engine improvement is a
one-line `devtools_ref` bump on `copier update` — no analyzer source diff in the consumer's PRs (the churn
this fixed). The package is extraction-ready — [`SPLIT.md`](SPLIT.md) enumerates every scaffold↔package
seam and the checklist to lift it into its own repo. The ast-grep rules + the ast-grep/jscpd config ship INSIDE the package and are located from
the install via `python -m devtools.config sgconfig|jscpd` (external CLIs need a filesystem path). All
`python -m devtools.*` gate invocations run with `--extra devtools`. A generated project keeps only a
`devtools/README.md` usage doc (no `__init__.py`, so it's a namespace portion that never shadows the
installed package).

**Release API-diff (bd 85l.6).** Consumers pin the package by tag, so a removed/changed public object is a
breaking change they inherit on a `devtools_ref` bump. The scaffold's own `.github/workflows/api-diff.yml`
runs `griffe check devtools -s sdlc-devtools -a <prev-tag>` on every `v*` tag — advisory (an intended break
gets a major/minor bump, not a blocked release), but it forces the releaser to acknowledge the diff.

**Dogfooding — the engines eat their FULL bar (bd dud + vip 16y/p99 + uo0.2).** The package owns its gate
set in its OWN standalone `sdlc-devtools/noxfile.py` — `cd sdlc-devtools && uvx nox` runs the full bar with
ZERO scaffold dependency (extraction-ready: lift the dir, keep the noxfile). The scaffold CI drives that
same noxfile (`tests/e2e/test_dogfood.py`, cwd=`sdlc-devtools/`, one `uvx nox` call), so the gate LOGIC has
one home and CI validates the standalone target too. No carve-outs: the package pytest (per-engine mirror
tests + the config-locator test) + ruff union + `graph --assert`
(god-module/cycle/god-file **and test-mirror**) + ast-grep class-shape + deptry + advisory explorers
(`magic_literals` / `complexity` / class-shape — reports, exit 0). The noxfile's tool pins + ruff select are duplicated from copier.yml on purpose — a
standalone package cannot read the scaffold answer file; that duplication is the split seam (scaffold =
policy source, package = its own pinned copy). The engines are CLASSES with a thin `main()` (the only top-level function ast-grep exempts)
and each carries a per-engine mirror test under `sdlc-devtools/tests/unit/devtools/`, so the analyzers pass
the same in-a-class + test-mirror rules they impose. Still excluded: jscpd (its config/threshold are shaped
for a project root; the shared file-walk/config-read live in `_common.py`) and the advisory-everywhere
class-shape smell explorers. SCAFFOLD-side only — never gate `devtools/` in a generated
project's own run (template-owned = a finding there is unfixable without hand-editing regenerated code).

## PORTABLE SUPERSET VALUES

### ruff (`[tool.ruff]` + `[tool.ruff.lint]`)
```toml
line-length = 120
# select = ruff_select (copier.yml, single source) — the UNION of all house repos' codes (bd o70): every
# code ANY repo enforces is here, byte-identical across repos. Not "majority" — union (no dodging a code a
# sibling runs). vip.2 LANDED cardiac's ratchet whole (the furthest-advanced repo = the union): N +
# E741-3 + PLR0124/1714/PLW3301 + RUF005-046/012 + C408/420 + PERF401/PLW0108/E731 + E402/ICN001 +
# S101/603/607/PTH123, on top of the narrow floor + SIM. Each repo FIXES up to the base (mindscape's
# 383 N-hits are fixed, not exempted). S101 = no-assert-in-prod (stripped under `python -O`; all 3 honor it,
# tests carve it out). DELIBERATELY OUT (owner, on record): UP (annotation churn), E701/702 (dense `a; b`
# compaction is house style), W (formatter owns it).
# E501 + SLF001 ENFORCED (bd 4c2/8ex, owner 2026-07-16 — graduated advisory->gate). E501: line-length 120
# is a legislated absolute, the gate just enforces it (a genuine long line takes `# noqa: E501`). SLF001: a
# real reach-in signal — the earlier "conflicts with the py-top-level-function ast-grep gate" claim was
# debunked (that gate only forces "helpers on a class", not static/private/class-name calls; `self._helper`
# satisfies it and never trips SLF001, so no rule forces the FP shape). Tests carve SLF001 out (privates
# under test). Both ship clean on a fresh gen, so they block regressions from day one. An op-namespace repo
# updating past v1.12 sees a wall of SLF001 from stateless @staticmethod + Cls._helper sibling calls; the
# compliant fix is @classmethod + cls._helper (external callers unchanged) — recipe in docs/UPGRADING.md (b8i).
select = ["F","B","I","T201","FBT","BLE001","S101","S110","C901","PLR0912","PLR0913","PLR0915","PLR2004","PLC0415","RUF100","N","E741","E742","E743","PLR0124","PLR1714","PLW3301","RUF012","RUF005","RUF007","RUF010","RUF022","RUF046","C408","C420","SIM","PERF401","PLW0108","E731","E402","ICN001","S603","S607","PTH123","E501","SLF001"]
ignore = []                              # + "F722" iff enable_ml (jaxtyping shape strings — bd vip.1)
[tool.ruff.lint.pep8-naming]             # N is universal; ignore-names VOCAB is a FACT (LOCAL-SLOT)
ignore-names = []                        # ML default: ["X*","Y*","B","C","H","W","F"]; repo adds its idioms
[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]                 # re-export facades
"tests/**"    = ["S101","PLR2004","FBT","SLF001","N801","N802","N803","N806","N812","PLR0913"]  # tests: asserts, fixtures, mock-class case, privates-under-test
# + LOCAL-SLOT per-file-ignores for repo-specific file carve-outs
```
`extend-exclude` is LOCAL-SLOT.

### vulture (`[tool.vulture]`)
```toml
min_confidence = 60
ignore_names = ["model_config"]          # + LOCAL-SLOT domain names per project
ignore_decorators = ["@model_validator","@field_validator","@field_serializer","@model_serializer","@computed_field"]
```
`paths`/`exclude` LOCAL-SLOT (rendered over `packages`).

### coverage (`[tool.coverage.report]`)
```toml
show_missing = true
exclude_lines = [
    "pragma: no cover", "if __name__ == .__main__.:", "if TYPE_CHECKING:",
    "raise NotImplementedError", "^\\s*\\.\\.\\.$", "@(abc\\.)?abstractmethod",
]
```
`[tool.coverage.run] source`/`omit` LOCAL-SLOT (rendered over `packages`). `fail-under` = `coverage_floor`.

### [tool.structure] defaults (graph.py reads these — LOCAL-SLOT so per-repo tuning survives update)
```toml
bottleneck_degree = 8    # fan-in AND fan-out both over this = god-module
file_max = 750           # god-file line ceiling
file_min = 0             # advisory line floor — 0 = OFF (no honest universal floor)
betweenness_max = 0.10   # advisory chokepoint threshold
test_layout = "mirror"   # test-existence layout: "mirror" (strict path-mirror) | "flat" (anywhere under tests/) | "off"
```

## LOCAL-SLOT convention (the seam)

In `pyproject.toml.jinja`, every local-slot region is wrapped so `copier update` and humans see the
boundary; portable superset blocks carry NO marker (template owns them, regenerated on update):
```toml
# >>> LOCAL-SLOT: <name> — edit freely, the template will not overwrite intent here
... project-specific values ...
# <<< LOCAL-SLOT: <name>
```
Slots: `ruff-exclude`, `vulture-scan`, `coverage-scan`, `arch-thresholds`, `import-contracts`.

### Per-gate scope (bd vip.3 — minimal forking, maximal-abstract identical set)

Real repos scan DIFFERENT package sets per gate (cardiac-seg: vulture + import-linter include `cardioview`;
coverage + ruff don't. mindscape: hygiene widens to a quarantined `baselines/`). Rather than a per-gate
`packages` map (prompt-surface + fork bloat), scope divergence rides **existing slots**, and the abstract
gate set stays identical:
- **arch (graph.py / ast-grep / jscpd) + ruff** scan `packages` — the owned/architected set, via CLI. Not
  slotted: widening these beyond `packages` is intentionally NOT templated (a repo conforms, it doesn't fork
  — cardiac-seg lints its arch set, not its quarantined baselines).
- **vulture** is config-driven — `[tool.vulture] paths` (the `vulture-scan` slot); NO CLI package args in
  nox/CI/pre-commit. A repo widens the dead-code scan there.
- **coverage** — `[tool.coverage.run] source` (the `coverage-scan` slot).
- **import-linter** — `root_packages` lives inside the `import-contracts` slot (layering scope is repo-owned;
  a viewer with layer rules but outside the arch set is added there).

Result: a repo overrides at most ONE slot per divergent gate; a conforming repo (synthscape) renders
identically (every scope = `packages`). No new questions, no new slots.

## Pinned tool versions (single-sourced in copier.yml, `when: false`)
- ruff `0.15.13` · vulture `2.16` · nox `2026.7.11` · deptry `0.25.1` · pip-audit `2.10.1` · pre-commit `4.6.0` · pyrefly `1.1.1`
- ast-grep via `uvx --from ast-grep-cli ast-grep` · jscpd via `npx --yes jscpd` (config located via
  `python -m devtools.config`)
- the analyzers themselves: `sdlc-devtools` package pinned by `devtools_ref` (the `devtools` extra pulls it
  + its transitive `grimp`/`networkx`)

## No example code shipped — the template ships ZERO package code (bd r2w)

A fresh generation has an empty `tests/unit/` and no package source — only the gate config + the pinned
`sdlc-devtools` dep + a `devtools/README.md` usage doc.
A brand-new project has nothing to lint/cover yet; you write the first module + its mirror test, then the
gates go green (never weakened for the empty case — you bring the first module).

The demo the gates need to be exercised is OWNED BY THE E2E, not the template: `tests/e2e/conftest.py`
`seed_example()` injects an astgrep-compliant leaf class (`{pkg}/math_ops.py`) + an intra-package edge
(`{pkg}/pipeline.py`, the edge graph.py chews) + strict-mirror unit tests into a generated project before
running the gates. That keeps the template code-less while still proving every gate bites on real code.

Anti-shortcut: gate failures are fixed in the TEMPLATE config (or the e2e seed), then regenerate — never
hand-patch generated output.

## Copier mechanics

- `_subdirectory: template` → only `template/` is rendered; scaffold-meta at repo root is never seen.
- `.jinja` files are Jinja-rendered and lose the suffix. Static files are copied verbatim. The analyzer
  engines are no longer in the template (they ship as the `sdlc-devtools` package, bd p99) — the only
  `template/devtools/` file is `README.md.jinja` (a usage doc).
- **No conditional files/dirs.** Every gate is always shipped, so nothing is excluded by feature: `_exclude`
  is just the housekeeping list (`.git`/`.venv`/`__pycache__`/`*.pyc`). NO `{% if %}` in filenames. (In-file
  gating survives only for `use_import_linter` and `enable_ml`, as `{% if %}` blocks inside a file, never
  as a file/dir name.)
- **No variable folders.** The template ships zero package code, so there is no `{{ package_name }}/` dir —
  the generated `tests/unit/` is empty and the consumer creates package dirs themselves.
- TOML + Jinja: `{{` collides. For literal braces in TOML use `{% raw %}` or `{{ "{{" }}`. Watch the
  coverage regex and any f-string-like content.
