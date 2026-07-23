"""A unit test is SMALL — no external data, no network, no sleep, no unseeded randomness (bd ar6, bd 1j3).

Google's size axis, which is the part of the testing vocabulary that actually travels: a SMALL test runs in
one process and touches nothing it did not create. That is not a performance preference. Each of these
four makes a test able to fail for a reason that has nothing to do with the code under test, and a suite
that can fail for unrelated reasons stops being read — which costs more than the coverage it bought.

    EXTERNAL DATA   an absolute path, or `Path.home()`. The rule the owner states as "a unit test may read
                    only data it created during this test run" — so `tmp_path` and fixtures are fine, and a
                    reader pointed at `D:/data` is an integration test wearing a unit test's name. A 50GB
                    read is the loud version; the quiet version is a suite that passes only on one machine.
    NETWORK         a test whose verdict depends on someone else's uptime.
    SLEEP           the tell of a race being waited out rather than removed. It is also pure wall-clock:
                    a suite of them is slow in a way no machine fixes.
    UNSEEDED RNG    the flake that costs the most to diagnose, because the failing input is gone by the
                    time anyone looks. Seed it and the failure is a permanent, reproducible fact.

SCOPE IS UNIT ONLY, and that is the whole reason this can be strict. An integration test SHOULD read a real
fixture file and an e2e test SHOULD shell out — these are not lesser tests, they answer questions a unit
test cannot, and holding them to this rule would be the gate misunderstanding its own subject. So this
reads the unit tree and nothing else, resolved through the same `test_layout` every other mirror gate uses.

PRECISE BUT INCOMPLETE, deliberately. It sees the LITERAL forms: a hardcoded absolute path, a call to a
known network or sleep entry point, a sampling call in a file that never seeds. A path assembled at runtime
from an environment variable is not caught, and chasing it would mean guessing at values this cannot know.
The common, checkable case is the one worth a gate — the same bargain every engine here makes.

THE SEED RULE IS PER-FILE, not per-call. `random.seed(0)` in a fixture covers the module's tests, so
demanding a seed at each sampling site would fight the fixture pattern the convention encourages. A file
that samples and never seeds anywhere is the finding.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from devtools.plumbing._common import ENCODING
from devtools.plumbing.cli import Cli
from devtools.plumbing.layout import TestLayout
from devtools.plumbing.pyproject import Pyproject

log = logging.getLogger("devtools.hygiene.small")

# Entry points whose trailing name is enough to identify them. Matched on the trailing name because
# `import time; time.sleep(1)` and `from time import sleep; sleep(1)` are the same defect.
SLEEP = frozenset({"sleep"})
# Trailing-name matches — names distinctive enough that the last segment alone identifies a network call,
# whoever imported it. `connect` and `socket` are deliberately NOT here: `connect` is an ordinary domain verb
# (a Qt `signal.connect()`, a `db.connect()` test double) and a bare `socket()` collides just as easily, so
# matching either on the trailing name would report code that never touches a network as if it did — the one
# thing this gate must not do. They are caught on the `socket.` dotted chain instead (bd 5ck).
NETWORK = frozenset({"urlopen", "urlretrieve", "create_connection", "getaddrinfo"})
# Dotted-chain matches. Bare `get`/`post` (requests/httpx) and `connect`/`socket` (the socket module) are all
# too common as domain names to match on the trailing name alone, so they are matched on the full dotted
# chain — `socket.` catches `socket.socket()`, `socket.connect()`, `socket.create_connection()`. A `.connect`
# on a socket held in a variable is genuinely ambiguous and is let through: a missing finding, never a wrong
# one, which is this gate's stated bargain.
NETWORK_CHAINS = ("requests.", "httpx.", "urllib.request.", "aiohttp.", "socket.")
# Sampling entry points. `default_rng` is EXCLUDED — it is the seeded constructor, and flagging the fix
# alongside the fault is how a gate teaches the wrong lesson.
SAMPLERS = frozenset(
    {"random", "randint", "randrange", "choice", "choices", "shuffle", "sample", "uniform", "gauss", "randn", "rand"}
)
SEEDS = frozenset({"seed", "manual_seed", "default_rng", "set_seed", "seed_everything"})
# What turns an absolute string literal into a filesystem READ. Without this the check fires on any string
# that happens to start with a slash, which on this repo was 2 findings and 2 false positives.
FS_ENTRY = frozenset(
    {"Path", "open", "read_text", "read_bytes", "write_text", "listdir", "scandir", "glob", "iglob", "load", "loadtxt"}
)


class SmallTests:
    """Unit tests that reach outside the process — external data, network, sleep, or unseeded randomness."""

    def __init__(self, packages: list[str], test_root: str | None = None) -> None:
        self.packages = packages
        # The unit tree is derived from the SAME `test_layout` the mirror gates read, so "which files are
        # unit tests" has one answer in this repo rather than one per gate.
        self.test_root = Path(test_root) if test_root else TestLayout.of(self._layout()).test_root

    @staticmethod
    def _layout(pyproject: str = "pyproject.toml") -> str:
        return str(Pyproject.structure_cfg(pyproject)["test_layout"])

    def files(self) -> list[Path]:
        """Every unit test module, sorted. Empty when the repo has no unit tree — nothing to check, not an
        error: a fresh generation legitimately has no tests yet and must not open red."""
        return sorted(p for p in self.test_root.rglob("*.py") if "__pycache__" not in p.parts)

    @staticmethod
    def chain(func: ast.expr) -> str:
        """The dotted spelling of a callee — `urllib.request.urlopen` for the chain, `sleep` for a bare name."""
        return ast.unparse(func) if isinstance(func, ast.Attribute | ast.Name) else ""

    @staticmethod
    def trailing(func: ast.expr) -> str:
        """The last name of a callee, so `time.sleep` and a bare imported `sleep` read the same."""
        if isinstance(func, ast.Attribute):
            return func.attr
        return func.id if isinstance(func, ast.Name) else ""

    def calls(self, tree: ast.Module) -> list[tuple[ast.Call, str, str]]:
        """Every call in the module as (node, trailing name, dotted chain) — parsed once, read four ways."""
        return [
            (node, self.trailing(node.func), self.chain(node.func))
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]

    @staticmethod
    def is_absolute(value: object) -> bool:
        """Does this literal name an absolute location — a POSIX root or a Windows drive?

        No length guard on the drive test: a slice is already safe on a short string, so `"C:"[1:3]` is
        `":"` and simply does not match. The guard read as necessary and was only noise.
        """
        return isinstance(value, str) and (value.startswith("/") or value[1:3] in (":/", ":\\"))

    def absolute_paths(self, calls: list[tuple[ast.Call, str, str]]) -> list[ast.Constant]:
        """Absolute literals passed to something that OPENS them.

        The literal alone is not the defect and testing for it alone was wrong: measured on this repo, both
        findings were false — a `/*...*/` comment marker in generated HTML, and a `"/mod.py"` substring
        asserted against a message. Neither touches a filesystem. What makes an absolute path a defect is
        that something READS it, so the entry point is the evidence and the literal is only the argument.

        `Path.home()`/`expanduser` are caught with the other calls; same defect, different syntax.
        """
        return [
            arg
            for node, name, _chain in calls
            if name in FS_ENTRY
            for arg in node.args
            if isinstance(arg, ast.Constant) and self.is_absolute(arg.value)
        ]

    def _findings_in(self, path: Path, tree: ast.Module) -> list[str]:
        """The four smallness defects in one unit test module, in LINE order.

        Sorted because `ast.walk` is breadth-first: `Path('/data/x').read_text()` yields the outer call
        before the inner one, so an unsorted report walks a reader's eye backwards up the file for no reason
        the file itself explains.
        """
        calls = self.calls(tree)
        out = [
            (node.lineno, f"{path.as_posix()}:{node.lineno}: `{chain}` — a unit test must not {why}")
            for node, name, chain in calls
            for why in self._why(name, chain)
        ]
        out += [
            (
                node.lineno,
                f"{path.as_posix()}:{node.lineno}: absolute path {node.value!r} — a unit test may read only "
                f"data it created during this test run; use `tmp_path`",
            )
            for node in self.absolute_paths(calls)
        ]
        sampled = sorted((node.lineno, chain) for node, name, chain in calls if name in SAMPLERS)
        if sampled and not any(name in SEEDS for _node, name, _chain in calls):
            lineno, chain = sampled[0]
            out.append(
                (
                    lineno,
                    f"{path.as_posix()}:{lineno}: `{chain}` samples but nothing in this file seeds — a "
                    f"failure here cannot be reproduced; seed it (`random.seed(0)`, `np.random.default_rng(0)`)",
                )
            )
        return [msg for _lineno, msg in sorted(out)]

    @staticmethod
    def _why(name: str, chain: str) -> list[str]:
        """Why this call is not small — empty when it is fine. A list so one call can only ever be reported
        once per reason, and so the caller stays a comprehension."""
        if name in SLEEP:
            return ["sleep — wall-clock in a suite is a race waited out rather than removed"]
        if name in NETWORK or chain.startswith(NETWORK_CHAINS):
            return ["reach the network — its verdict would depend on someone else's uptime"]
        if chain.endswith("Path.home") or chain.endswith("expanduser"):
            return ["read outside its own fixtures — it would pass only on one machine"]
        return []

    def violations(self) -> list[str]:
        """Every unit test that reaches outside the process."""
        return [
            msg
            for path in self.files()
            for msg in self._findings_in(path, ast.parse(path.read_text(encoding=ENCODING)))
        ]

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.violations()
        return "\n".join([f"unit tests that are not small: {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: log every unit test that reaches outside the process and return an exit code."""
        found = self.violations()
        if found:
            log.error("unit test size — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("unit test size: clean (no external data / network / sleep / unseeded randomness)")
        return 0


def main():
    Cli(
        SmallTests,
        "Unit test size — a unit test touches nothing it did not create.",
        gate="exit 1 on a unit test using external data, the network, sleep, or unseeded randomness",
    ).run()


if __name__ == "__main__":
    main()
