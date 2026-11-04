# ADRs

## Format

The ADR directory is the one `.docs.toml` names in
`[rules.adr-number-collision] adr_glob` (default `docs/adr/`); call it `<dir>`.
**The repo's convention wins.** Read `<dir>/README.md` and `<dir>/template.md`
first and follow them for the file name (a number, or a slug, possibly under a
domain subfolder), the header, how code and other ADRs refer to one
(`ADR-0007`, `ADR: <slug>`) and whether there is an index. No convention and no
ADRs → write the shape `tahrir init` scaffolds. A consistent log beats a
canonical one.

Fallback shape:

```markdown
## ADR-NNNN: Title

**Status:** Proposed | Adopted | Deprecated | Superseded by ADR-NNNN

**Decision:** What we decided.

**Why:** Context, constraints, trade-offs.

**Rejected:** Alternatives considered and why they lost, if any.

**Trade-off:** What gets harder, and why that's accepted.
```

Anything beyond these fields explains the code, not the choice.

## Capture steps

1. **Init (first time only).** No ADR directory → ask before creating one. With
   consent, `tahrir init` (`--adr-dir` for a log elsewhere) writes
   `<dir>/README.md` (index) and `template.md`; hand-write only where it hasn't run. Never create files without consent.
2. **Convention.** Read `<dir>/README.md` and `template.md`; what they say
   overrides the fallback shape, name, references and index below.
3. **One decision per new ADR.** Three settled things = three ADRs.
4. **Context** — what forced it, which constraints. Verify against the code,
   not just the conversation.
5. **Rejected** — what was genuinely considered and why each lost. Without it
   you've recorded an outcome, not a decision.
6. **Trade-off** — honestly.
7. **Name** — per the convention. Numbered: scan existing ADRs and increment;
   watch for gaps and numbers claimed on other branches. Slugged: a short
   kebab-case slug unique in the log, which is the ADR's identity; never add a
   number.
8. **Confirm, then write** — show the full draft; write the file (fallback
   `<dir>/NNNN-decision-title.md`) only after explicit approval. Declined →
   discard, leave no file.
9. **Index** — only if the repo has one: add its row in the same change.

```markdown
| ADR | Title | Status | File |
|---|---|---|---|
| 0001 | Use Next.js as frontend framework | Adopted | [0001-use-nextjs.md](0001-use-nextjs.md) |
```

## Quality

Do: be specific ("Prisma ORM", not "an ORM"); record rationale and rejected
alternatives; state consequences honestly; under a 2-minute read; present tense.

Don't: record trivia (naming, formatting); write essays (a **Why:** over ~10
lines explains code, not choice); omit alternatives; backfill an old decision
without saying in **Why:** when it was really made (the fallback has no Date
field, so it reads as decided on its commit date); let superseded entries lack a replacement link.

## Lifecycle

`Proposed → Adopted → [Deprecated | Superseded by <ADR ref>]`. Superseded links
its replacement and the replacement links back, both in **Status:** text
(`Superseded by ADR-0009`; `Adopted; supersedes ADR-0003`). Never edit an accepted
decision's substance — supersede it.

## With other agents

Planners: suggest capture once a proposal is actually decided, not before.
Reviewers: a PR with an architecture change and no ADR is a `Flagged:` line,
not a silent auto-write.
