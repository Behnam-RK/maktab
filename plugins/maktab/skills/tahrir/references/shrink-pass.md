# Shrink-pass mode

For an explicit repo-wide volume reduction ("shrink the docs"), not a routine
pass: keep only what's load-bearing, and prove it with a number.

- **Enforce the budget.** No blocking check for the repo's thresholds → propose
  one (`tahrir check` in pre-commit/CI) so the numbers hold after the session.
- **Boundary test** (when the repo has none): would a competent dev make a
  *wrong edit* without this line (ordering trap, upstream bug, invariant,
  non-obvious failure)? Keep. Would they merely wonder *why*? Delete, or move
  the rationale to its owning doc with at most a bare pointer.
- **Exemptions are declared, never inferred**: an in-file marker with a reason,
  e.g. `<!-- docs: exempt — <reason> -->`.
- **Mechanical checks block; judgment stays advisory.** Line counts and
  docstring presence can block; "narration vs load-bearing why" is flagged,
  never auto-deleted.
- **Runtime-surfaced docstrings**: diff the generated artifact (exported
  schema, tool descriptions) before/after; don't cut them for length.
