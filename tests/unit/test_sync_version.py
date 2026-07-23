"""The version-sync writer derives copier.yml's pin + the README headline from sdlc-devtools' version, so
the release version is bumped in ONE home rather than three held equal by hand (bd v3c.3)."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import sync_version  # noqa: E402  (repo-root script, imported after the path insert)


def test_repo_is_in_sync_with_the_package_version():
    """The mechanism, run against the real tree: copier.yml's pin and the README token already match the
    source. This is what fails a PR that bumped pyproject but forgot to run the writer."""
    assert sync_version.drift(sync_version.package_version()) == [], "run `python sync_version.py`"


def test_write_derives_both_copies_and_leaves_prose_untouched(tmp_path, monkeypatch):
    """A bump propagates to BOTH copies from the source, and nothing else moves: an unrelated `default:` in
    copier.yml and every README paragraph but the top one are preserved. Driven through a real tree so the
    file-rewriting IS what is tested, not a restatement of the regexes."""
    pkg = tmp_path / "sdlc-devtools" / "pyproject.toml"
    pkg.parent.mkdir()
    pkg.write_text('[project]\nname = "x"\nversion = "9.9.9"\n', encoding="utf-8")
    copier = tmp_path / "copier.yml"
    copier.write_text(
        'other_ref:\n  type: str\n  default: "keep-me"\n'
        'devtools_ref:\n  type: str\n  default: "v1.0.0"\n  when: false\n',
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text(
        "# title\n\n**v1.0** — newest, hand-written prose\n\n**v0.9** — older release\n", encoding="utf-8"
    )

    monkeypatch.setattr(sync_version, "_PACKAGE", pkg)
    monkeypatch.setattr(
        sync_version, "_DERIVED", ((copier, sync_version._sync_copier), (readme, sync_version._sync_readme))
    )

    version = sync_version.package_version()
    assert version == "9.9.9", "the source is read, not guessed"
    assert sorted(sync_version.drift(version)) == sorted([copier.as_posix(), readme.as_posix()]), "both are stale"

    changed = sync_version.write(version)
    assert sorted(changed) == sorted([copier.as_posix(), readme.as_posix()]), "both were rewritten"
    assert sync_version.drift(version) == [], "...and are now in sync"

    copier_text = copier.read_text(encoding="utf-8")
    assert 'devtools_ref:\n  type: str\n  default: "v9.9.9"' in copier_text, "the pin tracks the FULL version"
    assert 'default: "keep-me"' in copier_text, "no other default line is touched"

    readme_text = readme.read_text(encoding="utf-8")
    kept = readme_text.startswith("# title\n\n**v9.9** — newest, hand-written prose")
    assert kept, "token -> major.minor, prose kept"
    assert "**v0.9** — older release" in readme_text, "older release paragraphs are left alone"

    assert sync_version.write(version) == [], "a second run is a no-op — writing is idempotent"
