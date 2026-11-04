# Ledger

The loop's one interface. Local reviewers and the remote `momayez` check run
both feed it, and it is all either end hands on. Its shape is
[ledger.schema.json](ledger.schema.json) (`v1`).

## Header

- `target`: `base_sha`, and `head_sha`, the head this round reviewed. Add
  `repo` and `pr` or `ref` when known; CI can't learn them, and
  `momayezi-post` fills them in.
- `round`, `lenses`, `model`, and `tier`: smart's tier, or `off`.
- `verdict`: `findings` if this round raised or re-raised any finding, else
  `clean`.
- `cited_files`: every file any finding has cited. "Files no finding has
  cited" is measured against it.
- `truncated`: set when a size cap dropped detail. `last_id`: the highest
  id issued, kept when truncation drops findings. `notes`: what a reader must
  know, such as a missing intent brief or a scope fallback.

## Findings

Map each reviewer `M<n>` block to one finding:

- `id`: the ledger id it matches or names in `ref:`, else the next `F<n>`.
- `round`: the round it was first raised. A re-raise keeps it and sets
  `last_round` to the current round.
- `lens`, `severity`, `confidence`, `evidence`, `claim`, `fix`: from the
  block as written.
- `at`: `path`, `line`, and `end_line` for a range.
- `in_diff`: true when `at.line` falls in a changed hunk of `base..head`
  (`git diff -U0 <base> <head> -- <path>`). Only those get inline PR comments.
- `state`: `open → fixed | wont-fix | disputed`. `reason` holds the evidence
  for `wont-fix` and both readings for `disputed`. A `wont-fix` re-raised with
  new evidence gets one more look; if you still decline, it becomes `disputed`.

## Writing and loading

**Out**: one JSON object that matches the schema, and nothing else. It leaves
your context only as the `request_review` argument or a `--json` final
message, never as a file.

**In** (a `--ledger` file or a remote review): check it against the schema.
Keep every finding's id, round, state and reason. Number new findings after
the larger of `last_id` and the highest id. When merging a remote ledger, new
ids are new findings. For an id you already hold, your state and reason win,
unless its `last_round` is this round: then it was raised again, and you
decide it again as a new finding. A re-raised `wont-fix` gets one more look.
