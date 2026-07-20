"""Run the packaged ast-grep rules over the root packages — the module-shape gate, without a shell.

ast-grep is an EXTERNAL CLI and needs a filesystem path to its config, which the runners used to supply
with shell substitution:

    bash -c 'uvx --from ast-grep-cli ast-grep scan -c "$(python -m devtools.config sgconfig)" pkgs'

That `$(…)` is the only reason the hook needed `bash`, and on Windows the bash pre-commit selects cannot
reliably find `uv`/`uvx` on its PATH — so the scaffold's own primary dev platform could not run the one
gate that required a shell. The substitution is a lookup this package can already do (`Config.path`), so
doing it here removes the shell instead of working around it.

WHY THIS IS AN ENGINE and not a two-line script: it answers `report()` / `run_assert()` like every other
gate, so a runner drives it without knowing that this one happens to shell out to a vendored binary while
the others walk an AST. The subprocess is an implementation detail of THIS engine, not a second category
of gate the callers have to special-case.

Run: `python -m devtools.astgrep [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import logging
import subprocess

from devtools.cli import Cli
from devtools.config import Config

log = logging.getLogger("devtools.astgrep")

# The vendored CLI, invoked exactly as the runners do. `uvx` resolves it per-run, so no repo-level install.
SCAN = ("uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c")


class AstGrep:
    """The packaged ast-grep rule set, scanned over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def scan(self) -> subprocess.CompletedProcess[str]:
        """Run `ast-grep scan` with the INSTALLED config path — the lookup the shell used to do."""
        command = [*SCAN, str(Config.path("sgconfig")), *self.packages]
        return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603

    @staticmethod
    def findings(done: subprocess.CompletedProcess[str]) -> str:
        """One scan's output as text.

        ast-grep writes diagnostics to stdout and its own errors to stderr; both matter to a reader, and
        dropping either would hide a broken rule file behind an empty finding list.
        """
        return "\n".join(part for part in (done.stdout.strip(), done.stderr.strip()) if part) or "ast-grep: clean"

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        return self.findings(self.scan())

    def run_assert(self) -> int:
        """The gate: ast-grep's own exit code. `error`-severity rules fail it; `warning` ones do not, which
        is how an advisory rule (py-dynamic-attr) rides the same scan as the blocking ones.

        Scans ONCE and formats that same result — calling `report()` here would pay for a second full scan
        of the tree just to render the failure it already has in hand.
        """
        done = self.scan()
        if done.returncode:
            log.error("ast-grep — BLOCKING:\n%s", self.findings(done))
            return 1
        log.info("ast-grep: clean (module shape)")
        return 0


def main():
    Cli(AstGrep, "ast-grep module shape — the packaged rule set.", gate="exit 1 on a rule violation").run()


if __name__ == "__main__":
    main()
