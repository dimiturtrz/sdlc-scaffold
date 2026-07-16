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
