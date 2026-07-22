"""Gates about coupling between objects: reach-through, feature envy, composition cycles, use-contracts,
property purity.

Grouped by analytical DOMAIN, not by co-use — these modules do not import one another (they wire to
`plumbing` and read the `graph` model). That is the grouping the yfv bead and CLAUDE.md name as filing by
KIND, and it is here by an explicit owner decision (bd 5hg, 2026-07-22) that for the GATES a domain layout is
"obvious to a maintainer" and worth emptying the root for. Do not revert it as a principle violation: the
no-kind-bucket rule still holds for TYPES and for the co-use subsystems (`plumbing`, `graph`); it is lifted
here, deliberately, for the gate set.
"""
