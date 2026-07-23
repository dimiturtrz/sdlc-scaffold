"""Derive the release version's two downstream copies from the ONE source, instead of hand-typing three.

`sdlc-devtools/pyproject.toml`'s `version` is the single source release.yml cuts a tag from. Two other files
must state the same version and used to be edited by hand beside it:

    copier.yml   devtools_ref: "v{X.Y.Z}"   what every generated project pins its analyzers to
    README.md    **v{X.Y}**                 the front-page headline (major.minor — it names a release)

Agreement was CHECKED by two tests, but agreement is not correctness: the same fact written three times can
be wrong in all three at once (bd v3c.3). So this WRITES the two copies from the source — bump pyproject,
run `python sync_version.py`, and the pin and the token move with it because nobody types them. The README's
release PROSE is still authored by hand (no tool writes that); only the `**vX.Y**` token is machine-owned,
and it is always the first one in the file, structurally separate from the paragraph it opens.

    python sync_version.py           # write the two copies from pyproject (the bump-time command)
    python sync_version.py --check   # report drift and exit 1 (the CI/backstop form; writes nothing)

The existing consistency tests stay as an independent backstop; this is the mechanism they now guard.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
_PACKAGE = REPO / "sdlc-devtools" / "pyproject.toml"
_COPIER = REPO / "copier.yml"
_README = REPO / "README.md"

_ENCODING = "utf-8"


def package_version() -> str:
    """The full `X.Y.Z` version sdlc-devtools declares — the single source the other two derive from."""
    match = re.search(r'^version = "([^"]+)"', _PACKAGE.read_text(encoding=_ENCODING), re.M)
    if match is None:
        raise SystemExit(f"{_PACKAGE.as_posix()}: no `version = \"...\"` to derive from")
    return match.group(1)


def _sync_copier(text: str, version: str) -> str:
    """copier.yml's `devtools_ref` default set to `v{X.Y.Z}` — the consumer pin tracks the exact release.

    Anchored on the `devtools_ref:` block so no other `default:` line is touched; the pattern mirrors the one
    `tests/_meta.copier_default` reads with, so the writer and the reader cannot disagree about the shape.
    """
    return re.sub(r'(devtools_ref:\n(?:  .*\n)*?  default: ")[^"]*(")', rf"\g<1>v{version}\g<2>", text, count=1)


def _sync_readme(text: str, version: str) -> str:
    """The README's leading `**vX.Y**` token set to the package's MAJOR.MINOR — the headline names a release,
    not a patch. Only the FIRST token is rewritten (the newest release paragraph always sits at the top), so
    the hand-written prose after it, and every older version paragraph below, are untouched."""
    major_minor = ".".join(version.split(".")[:2])
    return re.sub(r"^\*\*v\d+\.\d+\*\*", f"**v{major_minor}**", text, count=1, flags=re.M)


# The derivations, as (file, transform) — one home, so `write` and `--check` walk the exact same set.
_DERIVED = ((_COPIER, _sync_copier), (_README, _sync_readme))


def drift(version: str) -> list[str]:
    """The files whose derived content differs from what the source implies — empty when everything is in
    sync. What `--check` reports and what `write` is about to change."""
    stale = []
    for path, transform in _DERIVED:
        current = path.read_text(encoding=_ENCODING)
        if transform(current, version) != current:
            stale.append(path.as_posix())
    return stale


def write(version: str) -> list[str]:
    """Rewrite every derived copy from the source; return the ones that actually changed."""
    changed = []
    for path, transform in _DERIVED:
        before = path.read_text(encoding=_ENCODING)
        after = transform(before, version)
        if after != before:
            path.write_text(after, encoding=_ENCODING)
            changed.append(path.as_posix())
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(prog="python sync_version.py", description=__doc__)
    ap.add_argument("--check", action="store_true", help="report drift and exit 1 instead of writing")
    args = ap.parse_args()
    version = package_version()
    if args.check:
        stale = drift(version)
        if stale:
            print(f"version drift from sdlc-devtools {version} — run `python sync_version.py`:")
            print("\n".join(f"  {path}" for path in stale))
            raise SystemExit(1)
        print(f"version in sync: copier.yml pin + README headline both track {version}")
        return
    changed = write(version)
    print(f"synced to {version}" + (": " + ", ".join(changed) if changed else " (already in sync)"))


if __name__ == "__main__":
    main()
