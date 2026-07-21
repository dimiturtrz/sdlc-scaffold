"""Unit tests for devtools/_common.py — the shared encoding constant (its one remaining job).

The walk / name-reduction / pyproject-reader primitives that used to live here moved to `trees.py`,
`names.py` and `pyproject.py` when the class-roles gate named this module for what it was: three
subjects sharing a file. What is left is the SSOT constant, guarded here so a stray re-declaration
elsewhere is a visible change rather than a silent divergence.
"""

from devtools import _common


def test_encoding_is_utf8():
    assert _common.ENCODING == "utf-8", "the one text encoding every engine reads/writes with"


def test_common_declares_no_classes():
    """It is a constants home now — a class landing back here means the split is eroding."""
    assert [n for n in vars(_common) if isinstance(vars(_common)[n], type)] == []
