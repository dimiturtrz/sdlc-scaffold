"""Shared machinery the engines run ON, not analyzers themselves — no `report()`, no findings, no CLI.

This subpackage IS the boundary that used to be a hand-kept `PLUMBING` frozenset in run.py: `run.py` derives
that set by walking this directory, so membership is a fact about the tree rather than a list that can drift
from it (the failure mode bd 2wt names — `layout` was added to the literal by hand during PR #30, and
forgetting it would have made the interface test demand an engine's verbs of a config strategy).

FIRE TOGETHER, WIRE TOGETHER: these eight are grouped because the engines USE them together — tree walk,
name resolution, the pyproject reader, the CLI dispatcher, the test-layout — not because they are alike.
Nothing outside imports them by a `python -m devtools.<tool>` path (they own no `main()`), so giving them a
home moves no documented contract.
"""
