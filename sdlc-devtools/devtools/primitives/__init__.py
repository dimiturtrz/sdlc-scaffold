"""The shared structural read-models the gates are built ON — extracted once, consumed many times.

`classes` (the class/method/field index), `calls` (the behavioural call arrows) and `arrows` (the
structural dependency arrows) are the three modules OTHER engines import: archmap and graph read all three,
contracts reads arrows+calls, composition reads arrows, envy reads classes. They are the only fan-in hub in
the analyzer set — every other engine wires to `plumbing`, not to a sibling — so this folder RECORDS a
layering the import graph already has (bd yfv.2), it does not impose one.

FIRE TOGETHER, WIRE TOGETHER: grouped because they are USED together by the gates above, not because they
are alike. They are also engines in their own right (each ships a `main()` and an advisory report), so the
move renames `python -m devtools.arrows|calls` to `devtools.primitives.arrows|calls` — a copier re-render in
consumers (bd 72g), not a hand-migration. `Cli.tool` resolves the subpackage segment so the help header and
logger name stay honest.
"""
