# Pyrefly v1.1 Strict Mode Integration for uv/pyproject.toml Projects

**Date**: 2026-07-18  
**Status**: settled  
**Supersedes**: none

## TL;DR

Pyrefly 1.1.1 (June 2026) wires into `pyproject.toml` via `[tool.pyrefly]` with `preset = "strict"` to enable strict-callable-subtyping, implicit-any, missing-override-decorator, and unused-ignore checks. Official pre-commit hook at `facebook/pyrefly-pre-commit` with id `pyrefly-check`; jaxtyping forward-reference shape strings are partially supported but documented as architecturally limited for cross-function sharing. Untyped deps default to errors; use `ignore-missing-imports` or `replace-imports-with-any` to suppress.

## Question

How do you configure and wire Meta's Pyrefly (stable v1.0/1.1, 2026) as a strict enforcement gate in a uv/pyproject.toml project with pre-commit hooks, and what are the concrete gotchas for jaxtyping, untyped deps, and exact config syntax?

## Findings

### 1. pyproject.toml Configuration — Complete `[tool.pyrefly]` Table

Pyrefly supports two config formats — top-level `pyrefly.toml` (takes precedence) or `[tool.pyrefly]` in `pyproject.toml` [S1]. Here's the complete strict-mode config block:

```toml
[tool.pyrefly]
# Strict mode preset
preset = "strict"

# File inclusion/exclusion
project-includes = ["**/*.py*"]
project-excludes = ["**/node_modules", "**/__pycache__", "**/test_*.py"]
disable-project-excludes-heuristics = false

# Python environment autoconfiguration
python-version = "3.11"
python-platform = "linux"
search-path = ["."]

# Type checking behavior — core strict settings
check-unannotated-defs = true
strict-callable-subtyping = true
infer-return-types = "checked"
permissive-ignores = false

# Import handling
ignore-missing-imports = []  # Empty by default; add untyped deps as ["requests.*", "numpy.*"]
replace-imports-with-any = []

# Error reporting
min-severity = "error"
output-format = "full-text"

# Suppression patterns
enabled-ignores = ["type", "pyrefly"]

# Feature flags for optional integrations
pytorch-efficiency-lints = false
use-ignore-files = true

# Per-path overrides (optional)
[[tool.pyrefly.sub-config]]
matches = "**/tests/**"
check-unannotated-defs = false

[tool.pyrefly.errors]
# Explicit error configuration — any code not listed inherits preset defaults
implicit-any = true
missing-override-decorator = true
unused-ignore = true
strict-callable-subtyping = true
```

**Strict Preset Details** [S2, S3]: The `preset = "strict"` option enables four core checks on top of defaults:

| Error Code | Enabled in Strict | Purpose |
|-----------|------------------|---------|
| `strict-callable-subtyping` | ✓ | Enforces LSP in callable/function signatures (variance strictness) |
| `implicit-any` | ✓ | Flags all implicit `Any` inference (including sub-kinds: implicit-any-in-argument, implicit-any-untyped-* ) |
| `missing-override-decorator` | ✓ | Requires `@override` decorator (PEP 698) on all overriding methods |
| `unused-ignore` | ✓ | Warns when suppression comments (`# type: ignore`) are unnecessary |

All other error kinds (bad-assignment, bad-return, bad-argument-type, etc.) remain at their defaults [S1].

**Config Precedence** [S1]: CLI flags override config file options, which override Pyrefly defaults.

### 2. CLI Invocation

**Command**: `pyrefly check` [S1, S6]

```bash
# Basic check of entire project
pyrefly check

# Check with lower-severity warnings shown
pyrefly check --min-severity warn

# Specify config file explicitly
pyrefly check --config=pyrefly.toml

# Update baseline (snapshot current errors)
pyrefly check --baseline=baseline.json --update-baseline

# With pre-commit, use via hook (see section 3)
```

**Exit Codes** [S1, S5]:
- `0`: No type errors
- `1`: Type errors found (or warnings/info if `--min-severity` includes them)
- `3`: Infrastructure/environment error (e.g., Python not found)
- `101`: Internal Pyrefly panic

**Scope**: `pyrefly check` by default checks whole project matching `project-includes` patterns, respecting `project-excludes` [S1]. To check individual files, pass the file path as an argument [S6].

### 3. Pre-Commit Hook — Official Configuration

**Official Repository**: [facebook/pyrefly-pre-commit](https://github.com/facebook/pyrefly-pre-commit) [S4]

**Hook ID**: `pyrefly-check`

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/facebook/pyrefly-pre-commit
    rev: 1.2.0  # Pin to stable version; v0.42.0+ consolidated to single hook
    hooks:
      - id: pyrefly-check
        name: Pyrefly type check
        pass_filenames: false  # Recommended for full-project checks
        language: system       # Expects pyrefly on PATH
        stages: [pre-commit, pre-push]  # Stages: pre-commit, pre-merge-commit, pre-push, manual
        args: ["--min-severity", "error"]  # Optional: pass CLI flags
```

**Alternative: Managed Installation** [S4]:
```yaml
repos:
  - repo: https://github.com/facebook/pyrefly-pre-commit
    rev: 1.2.0
    hooks:
      - id: pyrefly-check
        pass_filenames: false
        additional_dependencies: ["pyrefly>=1.1"]  # Pre-commit installs pyrefly
```

**Skip Hook Temporarily** [S4]:
```bash
SKIP=pyrefly-check git commit -m "..."
```

### 4. jaxtyping Shape Annotations — Support & Limitations

**Supported**: Pyrefly recognizes jaxtyping syntax as an alternative front-end [S9]. Shape annotations like `Float[Array, "batch n"]` are **translated internally to Pyrefly's native generic syntax and display back in jaxtyping form** [S9].

**Critical Limitation** [S9]: jaxtyping **cannot share symbolic dimensions across variables and functions within a class**. Documentation states:

> "our fully typechecked implementations of real-world models...cannot be faithfully ported to use jaxtyping syntax alone."

This means jaxtyping is suitable for **single-function scope** (e.g., a dataloader function with tensor batch shapes) but breaks down for **hierarchical module composition** where dimension names need to flow through a class hierarchy [S9].

**Forward References & Shape Strings**: Pyrefly does not document specific errors for jaxtyping shape strings (e.g., F722 "syntax in forward annotation" like Ruff). The presence of `enabled-ignores = ["type", "pyrefly"]` [S1] suggests shape string errors can be suppressed if they occur, but official guidance is thin here — **verify with a test before committing to jaxtyping in strict mode** [FLAG: Uncertain].

**Beartype Integration**: Not documented in official Pyrefly docs; assumed compatible as Pyrefly focuses on static types, not runtime validation.

### 5. Untyped Third-Party Dependencies

**Default Behavior**: Pyrefly errors on imports with missing stubs or no `py.typed` marker [S8]. Unlike mypy's lenient `ignore_missing_imports = true` which silently treats untyped modules as `Any`, Pyrefly reports `missing-import` errors and fails builds.

**Configuration Options**:

```toml
[tool.pyrefly]
# Option A: Ignore specific modules entirely (treat as Any)
ignore-missing-imports = ["requests.*", "numpy.*", "scipy"]

# Option B: Replace specific modules with Any
replace-imports-with-any = ["torch"]
```

Difference [S8]: `ignore-missing-imports` suppresses errors and treats the module as `Any` if not found. `replace-imports-with-any` unconditionally replaces a module with `Any` regardless of whether stubs exist.

**Best Practice** [S8]: For optional dependencies, use `TYPE_CHECKING` blocks instead of ignoring, to preserve static analysis:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests  # Type info only; not imported at runtime
    
# At runtime, use conditional import
try:
    import requests
except ImportError:
    requests = None  # type: ignore
```

This allows Pyrefly to see stubs when available without falling back to `Any` prematurely.

### 6. Version & Installation

**Latest Version**: 1.1.1 (released June 2026) [S7, S10]

**Release Cadence** [S2]: Monthly minor versions; patches released more frequently. 1.0.0 stable in May 2026; 1.1 landed June 2026.

**Installation Methods**:

```bash
# With uv (recommended for this project)
uv pip install pyrefly==1.1.1
# or with version constraint
uv pip install "pyrefly>=1.1"

# With pip
pip install pyrefly==1.1.1

# With conda
conda install -c conda-forge pyrefly

# With poetry
poetry add --group dev pyrefly

# Verify installation
pyrefly --version
```

**Pinning in pyproject.toml**:
```toml
[project.optional-dependencies]
dev = ["pyrefly>=1.1,<2"]
```

or in uv.lock after `uv sync`.

### 7. Suppression Syntax

**Inline Comment Syntax** [S1]:

```python
# Standard type-ignore (Pyrefly-compatible)
x: int = "string"  # type: ignore

# Pyrefly-specific ignore (preferred)
x: int = "string"  # pyrefly: ignore

# Suppress only specific error code (syntax below, official docs thin here)
x: int = "string"  # pyrefly: ignore[bad-assignment]

# When permissive-ignores = true, also accept:
x: int = "string"  # pyright: ignore
x: int = "string"  # ty: ignore
```

**File-Level Suppression via Baseline** [S1]:

```bash
# Generate baseline snapshot of current errors
pyrefly check --baseline=baseline.json --update-baseline

# Errors in baseline are ignored on subsequent runs
pyrefly check --baseline=baseline.json
```

Baseline approach is recommended for large legacy codebases to suppress errors gradually without inline comments [S1].

## Open Questions

- **jaxtyping shape-string error behavior**: Does Pyrefly error on invalid shape strings (e.g., `Float[Array, "invalid!"]`)? If so, what's the error code and suppression? [FLAG: Docs silent; needs empirical test]
- **Pydantic v2 integration**: Any special config needed for Pydantic model field inference with strict mode enabled? [Not documented in stable 1.1 release notes]
- **Performance on large codebases (20M+ lines)**: Pyrefly is production-proven on Instagram's 20M-line codebase [S2], but per-project incremental performance characteristics are undocumented.
- **Interaction with beartype runtime checks**: If a function has both Pyrefly strict types + beartype runtime validation, does Pyrefly suppress redundant type guards? [Unlikely but undocumented]

## Sources

- [S1] [Pyrefly Configuration — Official Docs](https://pyrefly.org/en/docs/configuration/) — 2026-07-18
- [S2] [Pyrefly Overview — pydevtools](https://pydevtools.com/handbook/reference/pyrefly/) — 2026-07-18
- [S3] [Pyrefly Strict Preset Details — Web Search](https://pyrefly.org/en/docs/configuration/) — via search results, 2026-07-18
- [S4] [facebook/pyrefly-pre-commit Repository](https://github.com/facebook/pyrefly-pre-commit) — 2026-07-18
- [S5] [Pyrefly Error Kinds Reference — Official Docs](https://pyrefly.org/en/docs/error-kinds/) — 2026-07-18
- [S6] [Pyrefly GitHub Repository](https://github.com/facebook/pyrefly) — 2026-07-18
- [S7] [Pyrefly PyPI Package — Latest Version 1.1.1](https://pypi.org/project/pyrefly/) — 2026-07-18
- [S8] [Pyrefly ignore-missing-imports & TYPE_CHECKING Pattern](https://dev.to/ldrscke/migrate-from-mypy-to-ty-and-pyrefly-4p30) + GitHub issues — 2026-07-18
- [S9] [Pyrefly Tensor Shapes & jaxtyping Support — Official Docs](https://pyrefly.org/en/docs/tensor-shapes/) — 2026-07-18
- [S10] [Pyrefly Installation & Versioning — Official Docs](https://pyrefly.org/en/docs/installation/) — 2026-07-18
