"""The pyproject `[tool.*]` reader — one home for 'read my config section'.

Every config-driven engine previously re-opened pyproject.toml; this is that read in exactly one place,
so the config-location policy (which file, what happens when it is absent) lives once.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from devtools.plumbing._common import ENCODING

# [tool.structure] is ONE section read by SEVERAL engines, so its key space belongs here rather than to any
# one of them. graph.py owning the list privately meant its validator saw demeter's and envy's keys as
# typos — the section has no single owner, so neither can the schema.
STRUCTURE_DEFAULTS: dict[str, int | float | str] = {
    # graph.py — import-graph fitness thresholds
    "bottleneck_degree": 8,
    "file_max": 750,
    "file_min": 0,
    "betweenness_max": 0.10,
    "main_sequence_max": 0.0,  # advisory main-sequence distance ceiling; 0 = OFF
    "test_layout": "mirror",
    # demeter.py — reach-through chain ceiling
    "demeter_max_depth": 2,
    # envy.py — foreign-access floor before a method counts as envious
    "feature_envy_min": 4,
}


class Pyproject:
    """Reader for a `[tool.<section>]` table from pyproject.toml — the shared config-load primitive."""

    @staticmethod
    def table(value: object) -> dict[str, object]:
        """A TOML value narrowed to a table, or {} — for chaining into a nested section."""
        return value if isinstance(value, dict) else {}

    @staticmethod
    def str_list(value: object) -> list[str]:
        """A TOML value narrowed to a list of strings, dropping anything else.

        TOML is untyped to us, so every read hands back `object`. Narrowing HERE, once, is what stops each
        engine assuming a shape it never checked — the same reason structure_cfg validates rather than
        trusting the section. Silent about non-strings on purpose: unlike a threshold, a stray entry in a
        glob/alias list cannot make a gate quietly pass at a value nobody set.
        """
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @staticmethod
    def str_of(value: object, default: str = "") -> str:
        """A TOML value narrowed to a string, or `default`."""
        return value if isinstance(value, str) else default

    @staticmethod
    def rows(value: object) -> list[dict[str, object]]:
        """A TOML array-of-tables narrowed to a list of tables — e.g. [[tool.arch.forbidden]]."""
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    @staticmethod
    def structure_cfg(pyproject: str = "pyproject.toml") -> dict[str, int | float | str]:
        """[tool.structure], merged onto defaults, with every override VALIDATED.

        An unknown key or a wrong-typed value raises rather than being dropped. A silently-ignored override
        is a config's worst failure mode: `bottlneck_degree = 20` would leave the gate on its default and
        the repo would read as passing at a threshold nobody set — the silent-typo shape that
        `contracts.malformed` exists to stop.
        """
        cfg = dict(STRUCTURE_DEFAULTS)
        bad = []
        for key, value in Pyproject.tool_section("structure", pyproject).items():
            if key not in STRUCTURE_DEFAULTS:
                bad.append(f"unknown key {key!r} (known: {', '.join(sorted(STRUCTURE_DEFAULTS))})")
                continue
            want = type(STRUCTURE_DEFAULTS[key])
            # a float threshold accepts an int (`betweenness_max = 0`); bool is an int subclass and never valid
            allowed = (float, int) if want is float else (want,)
            if isinstance(value, bool) or not isinstance(value, allowed):
                bad.append(f"{key!r} must be {want.__name__}, got {type(value).__name__} ({value!r})")
            else:
                cfg[key] = value
        if bad:
            msg = "[tool.structure] is malformed — a dropped override would read as a passing repo:\n  " + "\n  ".join(
                bad
            )
            raise ValueError(msg)
        return cfg

    @staticmethod
    def tool_section(section: str, pyproject: str = "pyproject.toml") -> dict[str, object]:
        """The `[tool.<section>]` table (empty dict if the file or section is absent). One config home."""
        p = Path(pyproject)
        if not p.exists():
            return {}
        return tomllib.loads(p.read_text(encoding=ENCODING)).get("tool", {}).get(section, {})
