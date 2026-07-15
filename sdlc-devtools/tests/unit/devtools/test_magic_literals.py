"""Unit tests for devtools/magic_literals.py — recurring string vocab + repeated dict key-sets + ratchet."""

import sys

import pytest

from devtools.magic_literals import MagicLiterals


def test_magic_literals_flags_recurring_token(write_pkg, tmp_path):
    # a value-position token appearing >= 4x is vocabulary; 3x is incidental
    hot = "".join(f"def f{i}():\n    return g('widget')\n" for i in range(4))
    cold = "".join(f"def c{i}():\n    return g('gadget')\n" for i in range(3))
    pkg = write_pkg(tmp_path, "ml_tokens", hot + cold)
    strings = dict(MagicLiterals([pkg]).scan_strings())
    assert strings == {"widget": 4}, f"only the >=4x token is vocabulary, got {strings}"


def test_magic_literals_defers_comparison_key_and_subscript(write_pkg, tmp_path):
    # the SAME token 4x but all in contexts owned elsewhere (comparison=ruff, dict key + subscript=schema)
    src = (
        "def a(x, d):\n"
        "    if x == 'kind':\n"  # comparison operand -> ruff PLR2004
        "        return d['kind']\n"  # subscript -> field ref
        "    return {'kind': 1}\n"  # dict key -> key-set smell, not a value token
        "def b(x):\n"
        "    return x == 'kind'\n"  # comparison operand again
    )
    pkg = write_pkg(tmp_path, "ml_excluded", src)
    assert MagicLiterals([pkg]).scan_strings() == [], "tokens only in comparison/key/subscript are deferred"


def test_magic_literals_finds_repeated_key_set(write_pkg, tmp_path):
    # the same constant-string key-set built in 2 sites = an implicit record schema
    src = "def a():\n    return {'x': 1, 'y': 2}\ndef b():\n    return {'x': 3, 'y': 4}\n"
    pkg = write_pkg(tmp_path, "ml_keysets", src)
    rows = MagicLiterals([pkg]).scan_key_sets()
    assert len(rows) == 1
    n_sites, keys, _ = rows[0]
    assert n_sites == 2
    assert keys == ("x", "y")
    # a single construction site is not a reused schema
    solo = write_pkg(tmp_path, "ml_solo", "def a():\n    return {'x': 1, 'y': 2}\n")
    assert MagicLiterals([solo]).scan_key_sets() == []


def test_magic_literals_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.magic_literals"])
    with pytest.raises(SystemExit) as exc:
        from devtools import magic_literals

        magic_literals.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
