# ML Project Template Scaffold Comparison: The Owner's 7-Ingredient Pattern vs. Existing Frameworks

**Date**: 2026-07-17
**Status**: settled
**Supersedes**: none

## TL;DR

The owner's combination — enforced 3-tier package layering + Adapter/Registry data pattern + pydantic+OmegaConf config + MLflow-sqlite tracker + (fit,score) evaluation harness with sync_numbers single-source-of-truth + comprehensive SDLC gates — does **not exist as an integrated whole** in any existing off-the-shelf template. Lightning-Hydra-Template + Cookiecutter-Data-Science are closest on individual ingredients but lack the architecture enforcement and evaluation spine. The biggest novelty is the evaluation harness + sync_numbers pattern; no major template provides a canonical mechanism to render numbers from one RESULTS.json into human documentation.

## Question

Does the pattern the owner independently built across three ML repos (a 7-ingredient scaffold combining package architecture, data adapters, config, tracking, evaluation, guardrails, and reproducibility conventions) already exist as an integrated template, or is it a novel combination with significant gaps in the existing ecosystem?

## Findings

### Feature Matrix: Candidates vs. 7 Ingredients

| Candidate | 1. 3-Tier Layering | 2. Adapter/Registry Data | 3. Config Stack | 4. Experiment Tracking | 5. Evaluation Harness | 6. SDLC Guardrails | 7. Reproducibility | Coverage |
|-----------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **cookiecutter-data-science** | ✗ | ✗ | ◐ | ✗ | ✗ | ◐ | ◐ | 3/7 |
| **Lightning-Hydra-Template** | ✗ | ✗ | ✓ | ◐ | ✗ | ◐ | ◐ | 2.5/7 |
| **MLflow Recipes** | ✗ | ◐ | ◐ | ✓ | ◐ | ✗ | ◐ | 2.5/7 |
| **Kedro** | ✗ | ◐ | ◐ | ✗ | ✗ | ◐ | ◐ | 2.5/7 |
| **ZenML** | ✗ | ✗ | ◐ | ◐ | ✗ | ✗ | ◐ | 1.5/7 |
| **Metaflow** | ✗ | ✗ | ✗ | ◐ | ✗ | ✗ | ◐ | 1/7 |
| **DVC** | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | 1/7 |
| **Guild AI** | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ◐ | 1/7 |
| **PyTorch Template** (victoresque) | ✗ | ✗ | ◐ | ✗ | ✗ | ◐ | ✗ | 1/7 |
| **MONAI Bundle** | ✗ | ◐ | ◐ | ✗ | ✗ | ✗ | ◐ | 1.5/7 |

Legend: ✓ = covers, ◐ = partial/tangential, ✗ = absent

---

## Detailed Analysis: The 3 Closest Candidates

### 1. Lightning-Hydra-Template (ashleve) — Coverage: 2.5/7
**Strongest on**: Config (ingredient 3), experiment tracking integration (ingredient 4 partial)

**What it provides** [S1]:
- Hydra-powered configuration: hierarchical YAML configs, command-line overrides via `hydra.run.dir`, structured configs with type safety
- Integration with multiple experiment loggers: MLflow, Weights & Biases, Neptune, Comet, TensorBoard, CSV
- Dynamic instantiation of models/datasets from config paths (reduces boilerplate)
- Pre-commit hooks (Black, isort) and GitHub Actions CI

**What's missing**:
1. **No 3-tier package layering**: Source code lives in `src/`, no enforced separation between core/science/ui layers, no import-linter gate
2. **No Adapter/Registry data pattern**: Relies on Lightning DataModule abstraction; no recipe-keyed dataset registry or `processed/<dataset>/<key>/` convention
3. **No evaluation harness**: No `(fit_fn, score_fn)` abstraction or aggregation mechanism
4. **No sync_numbers pattern**: No single source of truth for metrics → human docs
5. **Limited SDLC gates**: Only Black/isort pre-commit; missing ruff, ast-grep, jscpd, import-linter, coverage gates
6. **No explicit reproducibility conventions**: No `runs/<name>/` provenance tracking, no `external/` git checkout pattern

**Verdict**: Strong foundation for config + tracking integration, but lacks architectural enforcement and evaluation spine. Would require adding 4-5 ingredients to match the owner's pattern.

---

### 2. Cookiecutter-Data-Science (DrivenData) — Coverage: 3/7
**Strongest on**: Directory structure (reproducibility partial), development guardrails (partial)

**What it provides** [S2]:
- Standardized directory layout: separates `data/{raw,interim,processed,external}`, `notebooks`, `models`, `src`, `tests`
- Development tooling: supports pytest/unittest, ruff/flake8+black+isort linting, multiple dependency managers (uv, poetry, conda, etc.)
- Modular code scaffolds: pre-generated `src/` files for config, data handling, features, modeling, visualization
- mkdocs documentation template

**What's missing**:
1. **No 3-tier package layering**: Flat `src/` module, no architectural enforcement, no import-linter
2. **No Adapter/Registry data pattern**: Data directory organization is positional, not pattern-based; no Registry for "add dataset = one line"
3. **No structured config system**: Optional `config.py` but no Hydra/OmegaConf, no CLI integration with argparse
4. **No experiment tracking**: Not built-in; would need external MLflow/W&B setup
5. **No evaluation harness or sync_numbers**: No canvas for (fit_fn, score_fn) or metrics→docs rendering
6. **Partial SDLC guardrails**: Linting/pre-commit optional; no comprehensive gate (missing ruff enforcement, ast-grep, jscpd, coverage, import-linter)
7. **Reproducibility partial**: Good data separation, but no `runs/` provenance, no `external/` checkout convention, no explicit "data outside repo" enforcement

**Verdict**: Excellent directory discipline and linting scaffolding, but fundamentally a directory template, not an architectural pattern. Adds structure but not guardrails or evaluation machinery.

---

### 3. Kedro — Coverage: 2.5/7
**Strongest on**: Data catalog (ingredient 2 partial), SDLC guardrails (partial), reproducibility

**What it provides** [S3]:
- **Data Catalog**: Lightweight connectors for loading/saving data across formats (CSV, Parquet, SQL, cloud storage, HDFS)
- **Pipeline abstraction**: Automatic dependency resolution between pure Python functions, visualization via Kedro-Viz
- **Coding standards**: Integrated pytest, ruff linting, Sphinx documentation, logging
- **Deployment flexibility**: Supports single/distributed deployment, integrations with Argo, Prefect, Kubeflow, AWS Batch, Databricks
- **Project template**: Based on Cookiecutter-Data-Science

**What's missing**:
1. **No 3-tier package layering**: Node-based pipeline, no package hierarchy, no import-linter
2. **Different data pattern (not Adapter/Registry)**: Data Catalog is explicit loading/saving machinery; not the Protocol/Adapter/name→instance pattern the owner uses. Catalog is configuration-driven, not code-driven dataset registration
3. **No structured config system**: Project config is basic YAML; no Hydra/OmegaConf integration, no pydantic hparams co-location
4. **No built-in experiment tracking**: Requires external MLflow; no opinionated wrapper (the owner's Tracker wrapper over MLflow-sqlite)
5. **No evaluation harness**: Pipeline is DAG-based; no (fit_fn, score_fn) abstraction or evaluation Harness aggregation
6. **No sync_numbers pattern**: Numbers stay in MLflow runs; no single RESULTS.json rendering to docs
7. **Partial SDLC**: ruff, pytest, but not comprehensive gates (missing ast-grep, jscpd, import-linter, coverage enforcement); partial reproducibility focus

**Verdict**: Excellent for pipelines and data lineage, but treats data as a configuration catalog, not a code-driven registry. Missing config stack, tracking wrapper, and evaluation spine.

---

## The Biggest Gaps: What No Template Provides

### Gap 1: Enforced 3-Tier Package Layering + import-linter
**Unique challenge**: The owner uses `import-linter` to mechanically enforce directional imports (core → science, science ↔ viewer, but viewer ✗ core/science). This creates a hard architectural boundary.

**What exists**:
- Hydra-Lightning uses `src/` but with no layer separation
- Kedro uses node functions, no package hierarchy
- Cookiecutter-Data-Science has flat `src/`
- No template bundles import-linter or architecture enforcement

**Why it matters**: Prevents circular dependencies and keeps infrastructure concerns (core) separate from learning machinery (science). Most templates rely on conventions (READMEs, code review) rather than CI gates.

---

### Gap 2: Adapter/Protocol/Registry Data Pattern
**Unique challenge**: The owner treats datasets as first-class code objects (Adapter classes) behind a Protocol, registered in a Registry. Adding a dataset = one file + one Registry line. Recipe-keyed cache at `processed/<dataset>/<key>/`.

**What exists**:
- Kedro has **Data Catalog** (configuration-driven loading/saving), not code-driven registration
- Hydra-Lightning uses Lightning DataModules (abstraction, not registration)
- Cookiecutter-Data-Science has directory structure (raw/interim/processed), not a Registry pattern
- No template implements Protocol-based adapters with automatic registration

**Why it matters**: Decouples dataset *logic* from *configuration*. A new dataset doesn't require touching config files; it's pure Python. The Registry pattern is common in ML frameworks (PyTorch modules, HuggingFace), but rarely applied to data *loading*.

---

### Gap 3: Evaluation Harness with sync_numbers → RESULTS.json
**Unique challenge**: The owner abstracts evaluation as `(fit_fn, score_fn)` tuples fed to a Harness that aggregates results. A `sync_numbers.py` renders from one canonical RESULTS.json into human markdown/docs.

**What exists**:
- MLflow Recipes has **Steps** (compose operations) but not (fit, score) contract
- Kedro has pipeline nodes (DAGs), not evaluation abstraction
- Model cards (Amazon SageMaker, Google Model Card Toolkit) store JSON metadata, but don't sync back to docs [S4]
- Papers-with-Code style: render metrics from JSON, but not integrated into a template
- No template provides **single-source-of-truth rendering** from a RESULTS.json canonical source

**Why it matters**: Splits model development (metrics in RESULTS.json) from communication (metrics rendered in docs). One source of truth for numbers prevents copy-paste errors and staleness. The sync_numbers.py pattern is genuinely novel—most templates leave numbers scattered in notebooks, MLflow, and ad-hoc markdown.

---

### Gap 4: Comprehensive SDLC Static-Analysis Gates
**Unique challenge**: The owner bundles ruff, import-linter, ast-grep, jscpd, dead-code, complexity, coverage, dependency-hygiene, tensor-shape-contracts into one CI + pre-commit gate via a copier template + installed analyzer package.

**What exists**:
- Lightning-Hydra: Black + isort pre-commit
- Cookiecutter-Data-Science: Optional ruff/flake8 + black + isort
- Kedro: ruff + pytest, but no import-linter, ast-grep, jscpd, or coverage enforcement
- Most templates have *some* linting; none bundle a comprehensive ratcheting gate [S5]

**Why it matters**: Prevents drift. Once the codebase is clean, subsequent violations are caught before merge. Most teams apply linting reactively (fix issues in old code), not proactively (prevent new issues). The owner's approach is gates-first.

---

### Gap 5: Reproducibility Conventions (runs/ provenance, external/ checkouts, ONNX parity)
**What exists**:
- DVC excels at data versioning [S6], not at experiment provenance
- Metaflow tracks artifacts automatically, but doesn't enforce `runs/<name>/ provenance` convention
- No template has `external/` git checkout pattern for dependencies (most vendor or pip-install)
- ONNX export/deploy parity is domain-specific, rarely templated

**Why it matters**: Audit trail. A run is reproducible only if you can reconstruct the data, code, and environment. The owner's `runs/<name>/config.json` pattern and `external/` convention make this explicit and checked by CI.

---

## Honest Verdict: Novelty Assessment

### What's Genuinely Novel (The Combination)
The owner's pattern is **novel as a combination**. Individual ingredients exist:
- Config: Hydra ✓ (Lightning-Hydra does this)
- Data handling: Registries and Adapters are common in ML frameworks, not commonly applied to datasets ✓ (Partial novelty)
- Experiment tracking: MLflow ✓ (standard)
- SDLC gates: ruff, pre-commit, mypy ✓ (standard)

**But the ensemble** — a copier template that installs an analyzer package, bundles all 7 ingredients, enforces them via CI + pre-commit, and makes them interdependent — does not exist.

### Closest Existing Combination
**Lightning-Hydra-Template + MLflow + ruff pre-commit** covers ~3/7. Adding:
- Cookiecutter-Data-Science's directory structure (+1 for reproducibility)
- DVC for data versioning (+0.5 for reproducibility, different from the owner's approach)

...still leaves **evaluation harness, sync_numbers, 3-tier layering, and Adapter/Registry pattern** unimplemented.

### Specific Pieces Worth Noting (Prior Art)
- **Model cards** (Amazon SageMaker, Google): JSON-based model metadata [S4]. Closest to sync_numbers, but one-directional (metadata → docs) and cloud-specific, not a rendering pattern.
- **Registry pattern** in ML: PyTorch Modules, HuggingFace Transformers use registries. The owner applies this to *datasets*, which is rarer.
- **Evaluation harness**: DVC pipelines, Kedro nodes, and MLflow Steps all express composition. The owner's `(fit_fn, score_fn) → Harness` is minimal and modular; existing patterns are more verbose.

---

## Open Questions

- Does the Adapter/Protocol/Registry pattern scale to dynamic dataset discovery (e.g., dataset served from an API, not a file)?
- How does the 3-tier layering handle shared utilities between science and viewer (e.g., visualization code used by both)?
- Can sync_numbers.py render to non-markdown formats (HTML, Jupyter, interactive dashboards) without code duplication?
- Is the copier template portable to other packaging tools (e.g., uv workspaces, PEP 735 manifest groups)?

---

## Sources

- [S1] ashleve/lightning-hydra-template README & docs: https://github.com/ashleve/lightning-hydra-template
- [S2] Cookiecutter Data Science (DrivenData): https://cookiecutter-data-science.drivendata.org/ and https://github.com/drivendataorg/cookiecutter-data-science
- [S3] Kedro: https://kedro.org/ and https://github.com/kedro-org/kedro
- [S4] Amazon SageMaker Model Cards: https://aws.amazon.com/blogs/machine-learning/integrate-amazon-sagemaker-model-registry-with-model-cards/ and Google Model Card Toolkit: https://research.google/blog/introducing-the-model-card-toolkit-for-easier-model-transparency-reporting/
- [S5] Ruff (Astral): https://docs.astral.sh/ruff/ and pre-commit hooks: https://github.com/astral-sh/ruff-pre-commit
- [S6] DVC (Data Version Control): https://dvc.org/ and https://github.com/iterative/dvc
- MLflow Recipes: https://mlflow.org/docs/latest/recipes/
- MLflow Tracking with SQLite: https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/
- ZenML: https://www.zenml.io/ and https://github.com/zenml-io/zenml
- Metaflow (Netflix): https://metaflow.org/ and https://github.com/Netflix/metaflow
- Guild AI: https://www.guild.ai/ and https://github.com/guildai/guildai
- PyTorch Template (victoresque): https://github.com/victoresque/pytorch-template
- MONAI Bundle: https://docs.monai.io/en/latest/bundle_intro.html and https://github.com/Project-MONAI/model-zoo
- MLOps Design Patterns: https://applyingml.com/resources/patterns/
