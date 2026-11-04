---
name: tahrir
description: "Keep docs true to code and capture decisions as ADRs. Use when code changed and READMEs, docstrings, comments, changelogs or ADRs may be stale (PRs, reviews, renames, resolved TODOs, 'update the docs', 'doc review'), when a decision is made or asked about ('record this decision', 'we chose X over Y', 'why did we pick X?'), or to set a repo up for tahrir ('set up tahrir', 'configure the doc gate'). Not for authoring new end-user docs."
argument-hint: "[pass|adr|why|setup] [target] [--base REF]"
---

# Tahrir — docs & ADR steward

Two jobs, one surface (READMEs, ADRs, changelogs, docstrings, comments):
keep existing docs honest after code changes, and record hard-to-reverse
decisions.

Arguments: `$ARGUMENTS`. A leading mode runs that job: `pass` → Steward pass,
`adr` → Decision capture, `why <X>` → its lookup, `setup` →
[references/setup.md](references/setup.md). No mode: pick by the request.

## Options

From the user's plugin settings; a blank or unsubstituted value takes the default.

- **Proactivity** `${user_config.tahrir_proactivity}` (default `suggest`). Unasked,
  after code changes: `eager` offers a pass; `suggest` says in one line what
  looks stale and waits; `on-request` stays silent; `off` is `on-request` and
  also mutes the doc-gate hook. A mode or an explicit ask always runs.
- **Consent** `${user_config.tahrir_steward_consent}` (default `apply`): `propose`
  lists the planned edits and waits for a yes before step 3.
- **Setup profile** `${user_config.tahrir_setup_profile}` (default `default`): what setup proposes.
- No `.docs.toml` and not `on-request` or `off`: offer `/maktab:tahrir setup` once per session.

## Rules

- **Repo policy is binding.** A documentation guide, code-style doc,
  `AGENTS.md` or `CONTRIBUTING.md` that states thresholds or rules overrides
  every default here and every option above. Match its voice, docstring style
  and ADR layout. Real cases: `references/overrides.md`.
- **Truth first.** A doc contradicting the code is a defect: fix or delete it.
- **Why over what.** Keep intent, constraints, trade-offs, gotchas; delete
  narration of what the code shows. A docstring that paraphrases the name is a
  naming failure — fix the name. A block long because the code is tangled is a
  refactor signal: flag the code, don't polish the prose.
- **One source of truth.** Check for an existing doc before writing; fold
  duplicates in and point at them.
- **History is append-only.** Changed decisions are *Superseded* (linking the
  replacement), answered questions *Resolved* with how — never deleted.
- **Minimal diff.** Touch only what is stale or missing. A clean pass is valid.
- **Runtime-surfaced docstrings** (MCP/tool descriptions, CLI `--help`,
  GraphQL descriptions) are API: exempt from trimming, not from truth.

## Steward pass

0. **Conventions.** Find the repo's doc rules. Defaults if none: docstrings
   only where name + signature + types can't carry meaning (exported APIs,
   subclass contracts, side effects, non-trivial module headers; `_private`
   only when non-obvious). Comment blocks over **3 lines**: reread; over
   **10** (docstring over ~3) carrying real knowledge: *relocate*, don't truncate.
1. **Scope.** Changed files: `git diff --name-only <mb>` (committed and
   uncommitted work) plus `git ls-files -o --exclude-standard` (untracked);
   `<mb>` is `git merge-base HEAD <base>`, `<base>` being `--base`, else the
   default branch. Note added/renamed/removed symbols and config. Run
   `tahrir scan [--base <ref>] [--json] [--root <path>]` — advisory leads,
   repo-wide (`--base` only feeds `changed-without-docs`, off by default), so
   keep those on changed files; exit 0 (2: broken config). `tahrir check` is the blocking gate on the same `.docs.toml`;
   `tahrir --explain <rule>` explains one rule.
2. **Review** each surface: does it match the code, is anything new
   unrecorded, stale or redundant? Checklist: `references/review-checklist.md`.
   On ADRs: advance statuses, link supersessions, fix outgrown rationale; you
   may relocate rationale already written in code. A decision recorded
   *nowhere* goes to Decision capture.
3. **Edit.** Append docstrings (non-obvious symbols only), config docs,
   changelog lines. Update stale prose and cross-references. Extract long
   knowledge-bearing blocks to their owning doc, leaving a pointer plus ≤3-line
   why; read `references/extraction.md` first. Dedupe. Trim narration, dead
   roadmap items, resolved TODOs.
4. **Verify.** References resolve, "open" items match reality, every
   superseded ADR links a live replacement, examples still run; rescan.
5. **Report**, always: `references/report.md`. Worked cases:
   `references/examples.md`.

A repo-wide "shrink the docs" ask: read `references/shrink-pass.md` first.

## Decision capture

Drafted, then written only after explicit approval. The bar is *hard to
reverse*, not *important*; unsure → ask.

- **Explicit** ("record this", "let's go with X"): draft it.
- **Implicit** (libraries compared and concluded, schema, API shape, auth,
  deployment chosen by weighing options): *suggest* an ADR, wait for yes.
- **"Why did we pick X?"**: show the matching ADR's **Decision:** and
  **Why:**; no ADR dir → ask whether to start one; no match → offer to record it.
- Never invent rationale from a diff alone: draft what you can verify, ask
  the author for the rest.

Repo convention first; format, naming, index, lifecycle: `references/adr.md` (read before
drafting or editing any ADR).
