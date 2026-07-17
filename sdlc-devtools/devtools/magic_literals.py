"""Magic-literal detector: the non-comparison, cross-file context ruff PLR2004 can't see.

PLR2004 flags a magic value only in a COMPARISON (`x == "foo"`), and by default it even ALLOWS strings
(`allow-magic-value-types` defaults to `["str", "bytes"]`). The same bare literal as a dict key
(`d["foo"]`), an argument (`load("foo")`), an assignment, or a return value is ungated, and ruff never
aggregates across files. This detector owns that gap — the non-comparison, cross-file-frequency signal —
and defers comparison operands to ruff. Two smells:

  1. **recurring string literal** — a short, identifier-shaped string that appears >= THRESHOLD times is
     domain vocabulary (a tag / kind / mode string) masquerading as a literal. It belongs in a `StrEnum`
     or a named constant: one source of truth, typo-proof, case-consistent.
  2. **repeated dict key-set** — a dict literal whose keys are all constant strings, whose exact key SET
     is built in >= 2 places, is an implicit record schema. Nothing enforces every construction site uses
     the same keys, so a typo/missing key drifts silently -> it wants a dataclass / TypedDict.

Frequency is a heuristic (some repeats are legitimately strings/dicts — column names, framework API vocab,
path segments; prose/messages have spaces so they're never tokens, and f-strings are JoinedStr not
Constant so they're never counted). Because a legitimate non-enum-able floor is real, there is no honest
universal ceiling — 0 is too strict and any N is arbitrary — so this is an ADVISORY explorer: it prints the
ranked StrEnum/dataclass candidates and always exits 0. The reviewer decides. A repo that wants to enforce
a literal budget adds a legislated `[tool.magic_literals]` config knob at that point, not speculatively.

    python -m devtools.magic_literals mypackage    # advisory report, always exit 0
"""

from __future__ import annotations

import argparse
import ast
import logging
import re
from collections import defaultdict

from devtools._common import Trees

log = logging.getLogger("devtools.magic_literals")

# A "vocabulary token": identifier-shaped, short, no spaces/paths/format — i.e. a domain value, not prose,
# a log message (has spaces), an f-string (a JoinedStr, not a Constant, so never counted), or a path.
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{1,24}$")
_STRING_THRESHOLD = 4  # a token appearing this many times is vocabulary, not incidental
_KEYSET_MIN_SIZE = 2  # a record needs >= 2 keys to be a schema worth a type
_KEYSET_MIN_SITES = 2  # a key-set built in this many places is a reused (drift-prone) schema
_STOP = {"store_true", "store_false", "append"}  # argparse action literals (framework, not domain vocab)


class MagicLiterals:
    """Recurring-string-token + repeated-dict-key-set detection over the scanned packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def _is_token(value: object) -> bool:
        """A string worth counting: an identifier-shaped VALUE token (not prose/path/message/framework)."""
        return isinstance(value, str) and value not in _STOP and bool(_TOKEN.match(value))

    @staticmethod
    def _excluded_value_ids(tree: ast.AST) -> set[int]:
        """ids of Constant nodes NOT in a plain value position — owned by other smells/tools, so this detector
        skips them: dict KEYS + subscript indices (`d["field"]`, schema field refs → the key-set smell) and
        COMPARISON operands (`x == "foo"` → ruff PLR2004). Collected in ONE walk with a per-node dispatch."""
        excluded: set[int] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                excluded |= {id(k) for k in n.keys if k is not None}
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
                excluded.add(id(n.slice))
            elif isinstance(n, ast.Compare):
                excluded |= {id(op) for op in (n.left, *n.comparators) if isinstance(op, ast.Constant)}
        return excluded

    @staticmethod
    def _string_literals(tree: ast.AST) -> list[str]:
        """Identifier-shaped string constants in a VALUE position — the value/arg-position recurrence ruff
        can't see across files. Dict keys, subscript indices, and comparison operands are excluded (owned by
        the key-set smell + ruff PLR2004; see `_excluded_value_ids`). Docstrings aren't tokens."""
        excluded = MagicLiterals._excluded_value_ids(tree)
        return [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and MagicLiterals._is_token(n.value) and id(n) not in excluded
        ]

    @staticmethod
    def _key_sets(tree: ast.AST) -> list[tuple[frozenset[str], int]]:
        """(key-set, lineno) for each dict literal whose keys are all constant strings (>= min size)."""
        out = []
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Dict)
                and n.keys
                and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in n.keys)
            ):
                keys = frozenset(k.value for k in n.keys)  # type: ignore[union-attr]
                if len(keys) >= _KEYSET_MIN_SIZE:
                    out.append((keys, n.lineno))
        return out

    def scan_strings(self) -> list[tuple[str, int]]:
        """(token, count) for identifier-shaped strings appearing >= threshold across the packages, high first."""
        counts: dict[str, int] = defaultdict(int)
        for _, tree in Trees(self.packages).walk():
            for value in self._string_literals(tree):
                counts[value] += 1
        return sorted(((s, c) for s, c in counts.items() if c >= _STRING_THRESHOLD), key=lambda sc: -sc[1])

    def scan_key_sets(self) -> list[tuple[int, tuple[str, ...], list[str]]]:
        """(n_sites, sorted-keys, locations) for constant-string-key dict schemas built in >= min sites."""
        sites: dict[frozenset[str], list[str]] = defaultdict(list)
        for path, tree in Trees(self.packages).walk():
            for keys, lineno in self._key_sets(tree):
                sites[keys].append(f"{path}:{lineno}")
        rows = [
            (len(locs), tuple(sorted(keys)), locs) for keys, locs in sites.items() if len(locs) >= _KEYSET_MIN_SITES
        ]
        return sorted(rows, key=lambda r: -r[0])

    @staticmethod
    def report(strings: list[tuple[str, int]], key_sets: list[tuple[int, tuple[str, ...], list[str]]]) -> str:
        """The two ranked tables: recurring string tokens (StrEnum candidates) + repeated dict schemas."""
        lines = [f"{len(strings)} recurring string literals (>= {_STRING_THRESHOLD}x -> StrEnum/constant candidate):"]
        lines.extend(f"  {c:>3}x  {s!r}" for s, c in strings)
        lines.append(
            f"{len(key_sets)} repeated dict key-sets (>= {_KEYSET_MIN_SITES} sites -> dataclass/TypedDict candidate):"
        )
        for n, keys, locs in key_sets:
            lines.append(f"  {n:>3} sites  {{{', '.join(keys)}}}")
            lines.extend(f"           {loc}" for loc in locs)
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        prog="python -m devtools.magic_literals",
        description="recurring string literals + repeated dict key-sets (advisory report)",
    )
    ap.add_argument("packages", nargs="+", help="package dirs to scan (>=1 required, no 'src' fallback)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = MagicLiterals(args.packages)
    # ADVISORY: a ranked report of StrEnum/dataclass candidates, always exit 0. There is no honest universal
    # ceiling (0 is too strict — some recurrence is legit vocab; N is arbitrary), so this reports and the
    # reviewer decides. A repo that wants to enforce a budget adds a legislated config knob then, not now.
    log.info("%s", MagicLiterals.report(engine.scan_strings(), engine.scan_key_sets()))


if __name__ == "__main__":
    main()
