"""Forbidden-USE contracts — directional rules over ANY arrow kind (bd 4bl.4).

import-linter can say "domain must not IMPORT infra". That is the rule people actually mean approximated
by the only edge it can see. An import is the coarse OR of every reason one module needs another, so the
contract fires on a type-only import and stays silent about a dependency reached through an inherited
base — it is both too loud and too quiet.

This states the rule people mean: "domain must not USE infra", over the decomposed arrows —

    inherits · holds · references · calls · construct

so a contract can be as precise as the intent. "Nothing outside the composition root may CONSTRUCT a
concrete" is expressible here and simply is not expressible over imports.

Contracts live in `[[tool.arch.forbidden]]`, project-local (the RULE is universal, the LAYERS are a
per-repo fact):

    [[tool.arch.forbidden]]
    name = "domain must not use infra"
    source = "myapp.domain"
    forbidden = ["myapp.infra"]
    kinds = ["calls", "holds", "construct"]   # optional; omit to forbid EVERY kind

No contracts configured = nothing to check, so a fresh project starts green and ratchets.

Run: `python -m devtools.contracts [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import argparse
import logging

from devtools.arrows import HOLDS, INHERITS, REFERENCES, ClassArrows
from devtools.calls import CALLS, CONSTRUCT, CallArrows
from devtools.pyproject import Pyproject

log = logging.getLogger("devtools.contracts")

_KINDS = {INHERITS, HOLDS, REFERENCES, CALLS, CONSTRUCT}  # the vocabulary a contract's `kinds` may name


class UseContracts:
    """Directional forbidden-USE contracts evaluated over every arrow kind."""

    def __init__(self, packages: list[str], contracts: list[dict[str, object]] | None = None) -> None:
        self.packages = packages
        self.contracts = contracts if contracts is not None else self.load_contracts()

    @staticmethod
    def load_contracts(pyproject: str = "pyproject.toml") -> list[dict[str, object]]:
        """The `[[tool.arch.forbidden]]` contracts, or [] when none are configured."""
        return list(Pyproject.tool_section("arch", pyproject).get("forbidden", []))

    @staticmethod
    def malformed(contracts: list[dict[str, object]]) -> list[str]:
        """Contracts that cannot fire, reported as CONFIG errors rather than silently passing.

        A misspelled `kinds` entry, or a missing `source`/`forbidden`, matches no arrow — so the gate goes
        green and the rule it was meant to enforce is quietly off. That is the same failure mode as a gate
        wired into only some runners: something that cannot fire looks identical to something clean. So an
        unusable contract is an ERROR here, not a silent no-op.
        """
        out = []
        for contract in contracts:
            name = contract.get("name", "unnamed contract")
            out.extend(
                f"{name}: missing `{required}` — the contract can never fire"
                for required in ("source", "forbidden")
                if not contract.get(required)
            )
            if unknown := sorted(set(contract.get("kinds", [])) - _KINDS):
                out.append(f"{name}: unknown kind(s) {unknown} — expected any of {sorted(_KINDS)}")
        return out

    def edges(self) -> list[tuple[str, str, str]]:
        """Every arrow, structural and behavioural, as (source, target, kind) with `construct` split out."""
        structural = ClassArrows(self.packages).edges()
        behavioural = [(s, d, CONSTRUCT if via else kind) for s, d, kind, via in CallArrows(self.packages).edges()]
        return structural + behavioural

    @staticmethod
    def _under(qualified: str, prefix: str) -> bool:
        """Is this class inside the given module prefix? (`a.b.C` is under `a` and under `a.b`.)"""
        return qualified == prefix or qualified.startswith(f"{prefix}.")

    def violations(self) -> list[str]:
        """Every arrow that a configured contract forbids."""
        edges = self.edges() if self.contracts else []
        out = []
        for contract in self.contracts:
            name = contract.get("name", "unnamed contract")
            source = contract.get("source", "")
            targets = contract.get("forbidden", [])
            kinds = set(contract.get("kinds", []))
            for src, dst, kind in edges:
                if kinds and kind not in kinds:
                    continue
                if self._under(src, source) and any(self._under(dst, t) for t in targets):
                    out.append(f"{name}: {src} --{kind}--> {dst}")
        return sorted(set(out))

    def run_assert(self) -> int:
        """The gate: fail on a malformed contract FIRST (it would otherwise pass by never firing), then on
        any forbidden use."""
        if broken := self.malformed(self.contracts):
            log.error("forbidden-use contracts — MALFORMED (%d):\n  %s", len(broken), "\n  ".join(broken))
            return 1
        found = self.violations()
        if found:
            log.error("forbidden-use contracts — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("forbidden-use contracts: clean (%d configured)", len(self.contracts))
        return 0


def main():
    parser = argparse.ArgumentParser(description="Forbidden-USE contracts over the typed class arrows.")
    parser.add_argument("packages", nargs="+", help="root packages to scan")
    parser.add_argument("--assert", action="store_true", dest="assert_", help="gate: exit 1 on a forbidden use")
    args = parser.parse_args()
    engine = UseContracts(args.packages)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.assert_:
        raise SystemExit(engine.run_assert())
    found = engine.violations()
    log.info("forbidden-use (%d contracts): %d\n%s", len(engine.contracts), len(found), "\n".join(found))


if __name__ == "__main__":
    main()
