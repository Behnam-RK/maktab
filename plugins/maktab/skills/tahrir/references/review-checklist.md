# Review checklist (per documentation surface)

Apply only what the change touches.

Run the doc pass on every review, including one whose PR touches no `.md`
file: a doc that contradicts the merged code is a bug, and the code change is
what made it one.

Blocking, and fixed in the same PR: the change alters documented behaviour; it
adds something significant (service, endpoint, pattern, config key, env var);
or a new developer would be misled by the current docs once it merges.
Everything else is a suggestion. Minimal, truthful edits only.

## In-code: docstrings

- Docstrings only where name + signature + types can't carry the meaning; one
  that paraphrases the name is noise — remove it, fix the name.
- The docstring matches the current signature — no renamed/removed parameters
  described, no missing new ones.
- It describes current behavior, not a past version. Watch for "currently only
  supports X" lines after X stopped being the only case.
- A docstring over ~3 lines is an extraction candidate unless
  runtime-surfaced.
- Examples inside docstrings still run / parse and still reflect the real API.
- Conform to the project's existing docstring style (Google / NumPy / reST /
  plain) — detect it from neighbouring files, don't switch styles.

## In-code: inline comments

- Each comment passes the value test: it explains *why*, a constraint, a
  gotcha, or intent — not *what* the code already says.
- No comment contradicts the code beside it (the most dangerous kind of rot).
- "Magic number" / default-value comments still match the actual values.
- Section banners and "next steps" / "TODO" / "WHERE TO BUILD NEXT" comments
  reflect what's actually still pending — remove items that are now done,
  point relocated work to its new home.
- Commented-out code is removed unless there's an explicit, justified reason
  kept in a note.

## Prose: README / overview

- The one-line description and feature list still describe what the project
  does now.
- The file map / module list matches the actual files and their roles.
- Quickstart / run commands still work (correct filenames, flags, entry
  points).
- Status / roadmap reflects what's built vs pending; move completed items out
  of "next".
- Cross-references (to the decision log, a spec, other docs) resolve.

## Prose: decision log / ADRs

- New significant decisions are recorded: the decision, the options
  considered, *which were rejected and why*, and the rationale.
- Changed decisions: the old entry is marked `Superseded` (kept, not deleted)
  and a new entry added; statuses elsewhere updated to match.
- Open questions that got answered are moved to `Resolved` / `Decided` in
  place, noting how — not deleted.
- The set of items still marked "Open" genuinely matches reality.
- Entry format and status vocabulary match the log's existing convention.

## Prose: changelog

- A line exists for each user-facing or API-facing change in this PR.
- Entries are grouped/labelled per the project's convention (e.g. Added /
  Changed / Fixed / Removed, or a commit-type prefix).
- Wording is concrete ("renamed `resolve` to `resolve_encounter`"), not vague
  ("improved code").

## Prose: examples / quickstart / API reference

- Sample code and command lines still reflect the real, current API and run
  without error.
- Documented parameters, defaults, and return shapes match the implementation.
- Removed or renamed features are no longer referenced as if present.

## Extraction & dedupe

- An inline comment block over ~10 lines, or a docstring over ~3 lines
  (non-API), that carries an algorithm, business rule, decision rationale, or
  domain vocabulary is *relocated*, not truncated — moved to the doc that owns
  that knowledge, with a pointer left at the code site.
- The pointer resolves and the moved content wasn't merely deleted.
- Extracted (and pre-existing) in-code prose isn't duplicated in a prose doc —
  one source of truth; folded in and pointed at.

## Consistency sweep (do last)

- Every doc reference to a filename or symbol resolves to something that
  exists.
- Terminology is consistent across docs (the same concept isn't called three
  different things).
- The scanner's candidate list has shrunk after your edits; remaining items
  are intentionally left (and, if so, flagged in the report).
