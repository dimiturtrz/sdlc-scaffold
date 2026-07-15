"""Locate the packaged ast-grep / jscpd config files (shipped as package DATA next to the engines).

External CLIs (ast-grep, jscpd) need a filesystem PATH to their config, which used to force the config to
be vendored under a repo's `devtools/`. Now that devtools is an installed package, a consumer resolves the
installed path instead: `ast-grep scan -c "$(python -m devtools.config sgconfig)" <packages>` and
`npx jscpd <packages> --config "$(python -m devtools.config jscpd)"`. `sgconfig.yml`'s `ruleDirs: [sg-rules]`
is relative to the config file, so the packaged rules resolve alongside it — no repo-local copy needed."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import ClassVar


class Config:
    """Resolver for the config files shipped beside the engines (one home; no vendored repo copy)."""

    _FILES: ClassVar[dict[str, str]] = {"sgconfig": "sgconfig.yml", "jscpd": "jscpd.json"}

    @staticmethod
    def path(name: str) -> Path:
        """The installed filesystem path of a packaged config file, by short name (`sgconfig` / `jscpd`)."""
        fname = Config._FILES.get(name)
        if fname is None:
            raise SystemExit(f"unknown config {name!r} (known: {', '.join(sorted(Config._FILES))})")
        p = Path(__file__).resolve().parent / fname
        if not p.exists():
            raise SystemExit(f"packaged config {fname} missing at {p} (broken install?)")
        return p


def main():
    ap = argparse.ArgumentParser(
        prog="python -m devtools.config", description="print the installed path of a packaged config file"
    )
    ap.add_argument("name", choices=sorted(Config._FILES), help="which config to locate")
    args = ap.parse_args()
    print(Config.path(args.name))  # noqa: T201 — printing the path IS the contract (for shell `$(...)`)


if __name__ == "__main__":
    main()
