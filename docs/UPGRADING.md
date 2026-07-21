# Upgrading — adopter migration notes

`copier update` fetches the newest scaffold tag and re-renders the gate config. Most updates are
transparent. When a gate **graduates** (advisory → enforced) a repo can suddenly go red on pre-existing code
that was always non-compliant — that is the ratchet working, not a regression. This file is the recipe per
such change, so an adopter fixes the code the intended way instead of carving the gate back out (which
defeats the update for everyone downstream).

Entries are keyed by the version that introduced the change, newest first.

---

## v1.12 — `SLF001` (private-member access) is now an enforced ruff gate

**What you'll see.** After `copier update` past v1.12, `ruff` fails with a wall of `SLF001 Private member
accessed: _foo` — often dozens to hundreds of hits, concentrated in the op-namespace helper classes the
`py-top-level-function` ast-grep gate already mandates. On mindscape this was **102 hits across ~30 files**.

**Why it is not a rule bug.** `SLF001` and the op-namespace mandate are **independent axes**.
`py-top-level-function` only requires *a helper lives on a class* — it says nothing about static-vs-instance,
private naming, or how you call a sibling. The wall of hits comes from **one self-imposed style**: a stateless
`@staticmethod` calling a sibling private as `Cls._helper()`. A `@staticmethod` has no `self`, so a same-class
call must name the class; `ruff` does no class-scope analysis, so it reads `Cls._helper` as an outside
reach-in and flags it. Genuine cross-class reaches (`OtherCls._private`) are flagged too — and *those* are
real. The fix keeps the compliant idiom clean and lets the real reaches surface.

**Do not** carve `SLF001` back out tree-wide in the `per-file-ignores` LOCAL-SLOT — that silences the real
reaches too and forfeits the gate.

**The recipe** (validated on mindscape PR #66: 102 → 0 with no per-file carve, `nox -s lint` green with
`SLF001` enforced + `shape_contracts --assert`, 332 tests passing). Apply in order — it parallelizes across
files and ruff self-verifies each step:

1. **`@staticmethod` → `@classmethod`; same-class sibling calls `Cls._x` → `cls._x`.** `cls` is allowlisted,
   so same-class access goes clean. The class stays **stateless** (no instance, no state — `cls` is the class
   object, not `self`). **External callers do not change** — a `@classmethod` is still called `Cls.method(x)`.
   This clears the bulk of the hits mechanically.
2. **Module-level `def main()` → `@classmethod main(cls)` on its class; the entrypoint guard calls
   `Cls.main()`.** A free `main` reaching into a class's privates is the same pattern one level up.
3. **Genuine cross-module shared privates → promote to public API.** These are the *real* reach-ins the rule
   exists to catch. Rename `_thing` → `thing` and expose it deliberately. Note: a newly-public **array/tensor**
   boundary then needs a jaxtyping shape if `shape_contracts` runs with `--assert` (ml repos) — type it.
4. **Library-private monkeypatches** (reaching into a third-party lib's `_internal` on purpose) → keep a
   per-line `# noqa: SLF001`. This is the honest, localized exception; it does not spread.

**Result.** The compliant op-namespace idiom is `@classmethod` + `cls._helper`; SLF001 stays fully enforced;
the only surviving hits are deliberate `# noqa`. See [`SPEC.md`](SPEC.md) for why SLF001 is a gate.

---

## v1.24.0 — the method-level test mirror, unit-test size, and the `bare` layout

Two new **blocking** gates ship in `nox -s lint`, in CI, and in the batch runner. Both are clean on a fresh
generation, so a new project ratchets from day one. An **existing** repo will very likely open red — that is
the point of the gate, and the paragraph below is how to land it without a big-bang conversion.

The convention, the trade-off, and the case *against* it are in [`UNIT_TESTS.md`](UNIT_TESTS.md).

### `mirror.py` — every public method has a `test_<method>` that calls it and asserts

`graph.py`'s existing mirror asks whether a module **has a test file**. One smoke test satisfies that for a
module of twenty methods. `mirror.py` asks the question people mean, per method.

Findings come in three kinds and cost wildly different amounts, so the message tells you which:

| the message says | what it is | the fix |
|---|---|---|
| `...is not named 'test_x'; rename it` | a test already calls it and asserts | rename (and merge, if several) |
| `reached by N other module(s)` | a contract with no test | write the test |
| `called only inside its own file` | public by naming accident | add the underscore |

The third is not noise — on this repo 15 of 119 findings were methods that were never meant to be public.

**Landing it on an existing repo.** Do not convert everything at once. In order of preference:

1. Set `test_layout = "off"` in `[tool.structure]`, land the update, then turn it back on and work the list
   down. This is the honest temporary state and it disables **both** mirrors, so say so in a ticket.
2. Take the `rename it` findings first — they are mechanical and usually most of the list. On this repo they
   were 60 of 119.
3. Use `# devtools-ignore: test-mirror` on individual methods for the genuine residue. **The list is the
   signal**: short is fine, growing means the convention is pointing at something.

**Ambiguity.** Two classes in one module can share a method name. The gate then demands the qualified
`test_<class>_<method>` and names the exact function in the message. The qualified form is always accepted.

**Exempt by kind:** `main()`, `@property` (read as an attribute, so a call cannot be demanded), private
methods, and methods of private classes. An override of a same-module base is one polymorphic contract
covered by the base's test, not a second obligation.

### `small.py` — a unit test touches nothing it did not create

No external data root, no network, no sleep, no unseeded RNG. **Unit tests only** — an integration test
SHOULD read a real fixture and an e2e SHOULD shell out; the gate reads the unit tree and nothing else.

Absolute paths are only flagged when passed to something that opens them, so a `"/mod.py"` substring
assertion or a `/*...*/` marker in generated HTML is not a finding.

The usual fixes: `tmp_path` instead of a data root, a fake at the I/O boundary instead of the network,
removing the race instead of sleeping through it, and `random.seed(0)` / `np.random.default_rng(0)` once per
file (the seed rule is per-file, so a seed in a fixture covers the module).

### `test_layout = "bare"` — optional, and not the default

A fourth layout: `tests/unit/<pkg>/store.py` mirrors `<pkg>/store.py` — the same name, so the mirror is
visible in the path rather than reconstructed by the reader. `test_` is a pytest discovery mechanism, not a
convention.

**The default stays `"mirror"`.** Switching costs a red file-level gate on every module at once, and that is
not a cost the scaffold gets to spend for you. If you want it:

1. `test_layout = "bare"` in `[tool.structure]`
2. `python_files = ["*.py"]` under `[tool.pytest.ini_options]` — **required**. Without it pytest collects
   nothing and the suite reports green while running zero tests. `mirror.py` fails on this config rather
   than passing, because an uncollected suite must not be able to look clean.
3. Consider `python_classes = []` if you have no test classes — otherwise pytest tries to collect any
   imported `Test*` production class.
4. Drop the prefix from every mirror file.

`sdlc-devtools` itself made this move; the conversion immediately caught a test asserting
`python -m devtools.test_cli`, a module that has never existed.
