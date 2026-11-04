# Worked cases

- **Renamed function** (`resolve` → `resolve_encounter`): update its docstring
  if behavior changed, grep docs/comments/README for the old name, add a
  changelog line. Nothing unrelated.
- **Resolved open question**: mark the decision-log item `Resolved` with how;
  delete the dead TODO that pointed at it.
- **New config knob**: short inline note on what it does and why the default is
  sane; add to the README/spec where config is documented; one changelog line.
- **40-line module docstring on a locking algorithm**: package mechanics → move
  to `<pkg>/docs/locks.md`, leave `# See docs/locks.md`, dedupe first. `Extracted:`.
- **48-line comment duplicating the glossary**: fold new detail into
  `CONTEXT.md`, delete the comment, the term name is the pointer. `Deduped:`.
- **Session swapped Celery for a Postgres-backed queue**, reasoning only in the
  conversation: draft an ADR (why Celery's ops burden stopped paying; rejected:
  stay, SQS, DB; trade-off: fewer moving parts, lower throughput ceiling), show
  it, write on approval.
- **Diff adds a new auth strategy, no ADR**: don't invent rationale. Flag it,
  draft the verifiable parts, ask the author why alternatives lost.
- **Clean pass**: report "no doc changes needed" with a one-line reason.
