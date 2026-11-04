# Tarahi

Writes shaping docs for Linear projects. A shaping doc is the one a decision
is made from: a short body PMs and stakeholders can judge in minutes, with the
engineering detail in appendices. Tarahi drafts v1, revises to vN from the
review comments, and publishes each version as a new Linear document, only
when you say so.

Part of the [maktab](../README.md) plugin; publishing also needs
`/plugin install linear@claude-plugins-official`. Without the Linear plugin it still drafts, to a local markdown file, and
says publishing is unavailable.

## Use

```
/maktab:tarahi [draft|revise] [project or doc]
```

Or ask: "write the shaping doc for the checkout redesign", "revise the
search shaping from the comments". With no mode it revises the project's existing
shaping doc, or drafts one if there is none.

It reads the project, its issues, earlier versions and, inside a repo, the
code; then asks only what the sources can't answer and the draft can't do without, as multiple-choice
questions. Open choices land in the doc as Open decisions; unknown facts are
written as unknown.

## What it writes

A properties header (status, owner, author, reviewers, decide-by, supersedes,
project), then headline and ask, problems (P#), solution, decisions (D#,
Decided and Open with options, owner and date), risks, and out of scope. The
body names no code. Detail goes below a divider: what changed from the
previous version with the review responses (revisions only), engineering detail,
rejected alternatives, glossary. The format and its
rules: [format.md](../skills/tarahi/references/format.md). Run inside a repo whose
`AGENTS.md`, `CLAUDE.md` or docs state shaping conventions, and those win.

## Linear writes

Each needs its own yes:

- **Publish:** a new document `<Project> — Shaping vN` on the project.
  Earlier versions are never edited.
- **Replies:** on a revision, a reply on each thread of the previous version
  pointing to vN. Threads are never resolved.
- **Issues:** one per `Missing:` item or Open decision, picked from a list.
- **ADR links:** after tahrir records ADRs, one edit to the version just
  published adds their links to Appendix B, creating it if absent. It is the only edit a published
  version gets.

## Hand-offs

- **momayezi:** offered before publishing, with tarahi's final review checklist
  as the reviewers' brief.
- **tahrir:** in a repo with an ADR log, offered after
  publishing to record the hard-to-reverse decisions as ADRs. Linking them
  from the doc's engineering appendix is a separate yes.
