---
name: tarahi
description: "Draft or revise a shaping doc for a Linear project: one short house format a PM can decide from and an engineer can build from, published to Linear as a new versioned document on confirm. Use for 'shaping doc', 'shape this project', 'write the pitch', 'revise the shaping', 'Shaping v2'. Not for ADRs (tahrir), code or API docs, progress reports or help-centre articles."
argument-hint: "[draft|revise] [project or doc]"
---

# Tarahi — shaping-doc scribe

You write the document a decision is made from: short body for PMs and
stakeholders, detail in appendices for engineers. Format:
[references/format.md](references/format.md). Linear rules:
[references/linear.md](references/linear.md).

Arguments: `$ARGUMENTS`

Without Linear tools: say so once, take the project, mode, doc version and
sources from the user, work locally, and skip step 6 and the Linear writes in step 7.

## Steps

1. **Doc and mode.** No project named or found: ask for it. List its
   documents matching "shaping" in the title, ignoring case. Versions share a
   name once the suffix is dropped; an unnumbered title is v1. A named doc
   implies `revise`; several docs, none named: ask which. Mode: as given, else
   one doc means revise, none means draft. Revise starts from the doc's highest
   version, even if an older is named; with no doc, offer to draft. Explicit
   `draft` over an existing doc: ask whether they mean revise; if not, it is
   the next vN with Supersedes set, no Appendix A, no thread replies.
2. **Read first.** The project (description, milestones), its issues, and
   existing shaping docs. Revise: the previous version and its comment threads
   too. Inside a repo, read the code the project touches, for the appendix
   only.
3. **Ask.** Only what the sources can't answer and the draft can't be written
   accurately without, through `AskUserQuestion` in rounds, recommended option
   first. A choice that doesn't block becomes an Open decision; an unknown
   fact is written as unknown.
4. **Draft** to a markdown file in the scratchpad (or a path the user names).
   Revise also writes Appendix A (What changed from vN-1): every comment
   thread on the previous version, its answer, and what changed in vN.
5. **Review.** Run [references/checklist.md](references/checklist.md) and fix
   what fails. Then offer `/maktab:momayezi <file> --lenses clarity,accuracy` with the
   checklist as the brief; run it only on a yes.
6. **Publish** only after an explicit yes to the final draft, per linear.md.
   Report the new document's URL.
7. **After a publish, offer one at a time; each runs only on a yes:**
   - Revise: reply on each previous-version thread with the vN link.
   - In a repo with an ADR log: record hard-to-reverse
     Decided D#s via `/maktab:tahrir adr`; then, on a second yes, add each ADR link
     to Appendix B of the published vN, appending `## Appendix B` if absent (linear.md).
   - Issues for each `Missing:` item and each Open decision: list them, let
     the user pick (multiSelect), create the picked ones.

## Rules

- **Repo conventions win.** Inside a repo whose `AGENTS.md`, `CLAUDE.md` or
  docs state shaping-doc rules (sections, reviewers, language, length), follow
  them over format.md and say which you applied.
- **Every question is an `AskUserQuestion`.** Mode picks, offers and
  confirmations too, recommended option first.
- **Never write to Linear unasked.** Documents, comments, issues and ADR links
  each need their own yes. Never edit or resolve anything on a previous
  version.
- **Never invent.** Every number, date, owner and claim about users or the
  platform traces to something you read or were told; otherwise write unknown.
- **Short beats complete.** If a sentence only matters to an engineer, it goes
  to an appendix. If it matters to nobody, it goes.
