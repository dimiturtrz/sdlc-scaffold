"""Unit tests for devtools/magic_literals.py — recurring string vocab + repeated dict key-sets.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import sys

import pytest

from devtools.hygiene import magic_literals
from devtools.hygiene.magic_literals import MagicLiterals

# A value-position token appearing >= 4x is vocabulary; 3x is incidental. Both live in one snippet so the
# threshold is asserted as a BOUNDARY rather than as two unrelated verdicts.
_HOT_AND_COLD = "".join(f"def f{i}():\n    return g('widget')\n" for i in range(4)) + "".join(
    f"def c{i}():\n    return g('gadget')\n" for i in range(3)
)
# The SAME token 4x, but every occurrence sits in a context owned elsewhere.
_DEFERRED = (
    "def a(x, d):\n"
    "    if x == 'kind':\n"  # comparison operand -> ruff PLR2004
    "        return d['kind']\n"  # subscript -> a field reference, not a value
    "    return {'kind': 1}\n"  # dict key -> the key-set smell, not a value token
    "def b(x):\n"
    "    return x == 'kind'\n"  # comparison operand again
)
# Prose has spaces and an f-string is a JoinedStr rather than a Constant, so neither is ever a token; a
# path segment and an argparse action are shape- and stop-list-excluded respectively.
_NON_TOKENS = "".join(
    f"def f{i}(p):\n    log('this is a message')\n    q = f'{{p}}x'\n    r = 'a/b/c'\n    add(action='store_true')\n"
    for i in range(4)
)


@pytest.mark.parametrize(
    ("name", "src", "expected"),
    [
        ("ml_tokens", _HOT_AND_COLD, {"widget": 4}),
        ("ml_excluded", _DEFERRED, {}),
        ("ml_nontokens", _NON_TOKENS, {}),
    ],
)
def test_scan_strings(write_pkg, tmp_path, name, src, expected):
    """Which repeated strings count as domain vocabulary — and, mostly, which do not.

    The exclusions are the substance: this detector exists to own the gap ruff leaves (non-comparison,
    cross-file), so a token counted in a comparison would double-report something PLR2004 already owns, and
    a counted dict key would double-report the key-set smell below.
    """
    pkg = write_pkg(tmp_path, name, src)
    assert dict(MagicLiterals([pkg]).scan_strings()) == expected


def test_scan_strings_ranks_by_count(write_pkg, tmp_path):
    """Highest first — the report is a WORK QUEUE, and a reviewer reading top-down must meet the strongest
    StrEnum candidate first rather than whichever token the walk happened to reach."""
    src = "".join(f"def f{i}():\n    return g('rare')\n" for i in range(4))
    src += "".join(f"def h{i}():\n    return g('common')\n" for i in range(9))
    pkg = write_pkg(tmp_path, "ml_rank", src)
    assert MagicLiterals([pkg]).scan_strings() == [("common", 9), ("rare", 4)]


def test_scan_key_sets(write_pkg, tmp_path):
    """A constant-string key-set built in >= 2 places is an implicit record schema.

    The single-site and one-key cases are the boundaries that keep this from firing on every dict literal
    in the repo: one construction site cannot drift out of step with itself, and a one-key dict is not a
    record worth a dataclass.
    """
    src = "def a():\n    return {'x': 1, 'y': 2}\ndef b():\n    return {'x': 3, 'y': 4}\n"
    rows = MagicLiterals([write_pkg(tmp_path, "ml_keysets", src)]).scan_key_sets()
    assert len(rows) == 1
    n_sites, keys, locs = rows[0]
    assert (n_sites, keys) == (2, ("x", "y")), "the key-set is reported sorted, with its site count"
    assert len(locs) == 2 and all(":" in loc for loc in locs), "and every site is located file:line"

    solo = write_pkg(tmp_path, "ml_solo", "def a():\n    return {'x': 1, 'y': 2}\n")
    assert MagicLiterals([solo]).scan_key_sets() == [], "a single construction site is not a reused schema"
    tiny = "def a():\n    return {'x': 1}\ndef b():\n    return {'x': 2}\n"
    assert MagicLiterals([write_pkg(tmp_path, "ml_tiny", tiny)]).scan_key_sets() == [], "one key is not a record"
    dynamic = "def a(k):\n    return {k: 1, 'y': 2}\ndef b(k):\n    return {k: 3, 'y': 4}\n"
    assert MagicLiterals([write_pkg(tmp_path, "ml_dyn", dynamic)]).scan_key_sets() == [], (
        "a non-constant key means the key SET is not knowable statically, so there is nothing to compare"
    )


def test_report(write_pkg, tmp_path):
    """The uniform explorer view: both ranked tables, computed by the engine from packages alone.

    THREE report shapes across the engines is what made a shared CLI impossible (bd 0y9) — instance,
    static-taking-rows, and static-taking-an-artifact — so the contract asserted here is that `report()`
    takes nothing and still produces the full text.
    """
    src = "".join(f"def f{i}():\n    return g('widget')\n" for i in range(4))
    src += "def a():\n    return {'x': 1, 'y': 2}\ndef b():\n    return {'x': 3, 'y': 4}\n"
    text = MagicLiterals([write_pkg(tmp_path, "ml_report", src)]).report()
    assert "1 recurring string literals" in text, "the string table leads with its count"
    assert "'widget'" in text and "4x" in text, "and names the token with its frequency"
    assert "1 repeated dict key-sets" in text, "the key-set table follows with its own count"
    assert "{x, y}" in text and "2 sites" in text, "and names the schema with its site count"

    empty = MagicLiterals([write_pkg(tmp_path, "ml_report_empty", "def a():\n    return 1\n")]).report()
    assert "0 recurring string literals" in empty and "0 repeated dict key-sets" in empty, (
        "an advisory explorer always prints both tables — a missing section reads as a crash, not as clean"
    )


def test_magic_literals_main_requires_packages(monkeypatch):
    """`main()` is argparse plumbing and exempt from the mirror, but the vacuous-run guard is worth pinning:
    a no-arg invocation must be a usage error, not a scan of nothing that prints an empty report."""
    monkeypatch.setattr(sys, "argv", ["devtools.magic_literals"])
    with pytest.raises(SystemExit) as exc:
        magic_literals.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
