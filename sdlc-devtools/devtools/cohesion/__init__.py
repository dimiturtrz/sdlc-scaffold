"""Gates about the shape of a single class: cohesion (LCOM4), data clumps, mutable-state candidates,
cyclomatic complexity.

Grouped by analytical DOMAIN (bd 5hg) — see `coupling/__init__.py` for why a by-kind gate layout is
sanctioned here despite the general no-kind-bucket rule. These four ask "is this class doing too much, or
holding too much, in one place"; a maintainer reaches for them together.
"""
