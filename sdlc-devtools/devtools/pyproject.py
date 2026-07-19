"""The pyproject `[tool.*]` reader — one home for 'read my config section'.

Every config-driven engine previously re-opened pyproject.toml; this is that read in exactly one place,
so the config-location policy (which file, what happens when it is absent) lives once.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from devtools._common import ENCODING


class Pyproject:
    """Reader for a `[tool.<section>]` table from pyproject.toml — the shared config-load primitive."""

    @staticmethod
    def tool_section(section: str, pyproject: str = "pyproject.toml") -> dict:
        """The `[tool.<section>]` table (empty dict if the file or section is absent). One config home."""
        p = Path(pyproject)
        if not p.exists():
            return {}
        return tomllib.loads(p.read_text(encoding=ENCODING)).get("tool", {}).get(section, {})
