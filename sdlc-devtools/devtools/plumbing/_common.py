"""The one text encoding every engine reads/writes source + config with.

This module held three unrelated primitives (the tree walk, dotted-name resolution, the pyproject reader)
until the class-roles gate (bd 4bl.1) named it for what it was: three SUBJECTS sharing a module. They now
live in `trees.py`, `names.py` and `pyproject.py` — one subject each. What is left is the shared constant
they all need, kept here as its single source of truth rather than redeclared per engine.
"""

from __future__ import annotations

ENCODING = "utf-8"
