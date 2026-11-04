# House format

One format for every shaping doc. Above the divider is the **body**: short,
at product altitude, complete on its own. Below it are **appendices**: detail,
mechanism, history. Leave out any section with nothing to say. Appendix
letters stay fixed, so a v1 starts at Appendix B.

## Skeleton

```markdown
| | |
|---|---|
| **Status** | one of: Draft for review, Shape agreed (owner accepted every decision) |
| **Owner** | who decides |
| **Author** | who wrote it |
| **Reviewers** | who must read it |
| **Decide by** | date or milestone, or unknown |
| **Supersedes** | link to the previous version, or — |
| **Project** | Linear project |

## Headline and ask
Two or three sentences: what changes, why it matters now, and the ask —
**Decide**, **Approve** or **Inform** (name what).

## Problem
**P1 — <short name>.** One short paragraph: who feels it and what it costs.

## Solution
The approach in a paragraph or two: what users or the team see before and
after. Then:

| Problem | Resolved by |
|---|---|
| P1 | D1, D3 |
| P2 | deferred: why |
| P3 | out of scope: why |

**Missing:** what remains of anything built but not released.

## Decisions
| # | Decision | In plain terms |
|---|---|---|
| D1 | what was chosen | what it means for the reader |

### Open: D4 — <question>
| Option | Benefit | Cost |
|---|---|---|
| A (recommended) | … | … |
| B | … | … |

Why one option is recommended, or the fact still needed to pick one.
**Owner:** name · **Decide by:** date or unknown

## Risks
| Risk | Affects | Lasting? | Mitigation |
|---|---|---|---|

## Out of scope
- Boundaries a reader might otherwise assume are included.

---

## Appendix A — What changed from vN-1 (revisions only)
| Comment (author) | Answer | Change in vN |
|---|---|---|

## Appendix B — Engineering detail
## Appendix C — Rejected alternatives
## Appendix D — Glossary
```

## Rules

**Altitude.** The body names no classes, services, endpoints, flags, files,
tables or code. Say what a user or the team notices, by the product's own
names. Sentence test: if a PM would decide the same way without it, it goes
to an appendix or nowhere. Appendix B holds the mechanism, linked PRs and ADRs.

**The body stands alone.** A reader who stops at the divider can still judge
and decide. Appendices explain how; nothing in the body may rest on a fact
that appears only there. When the body needs depth, one sentence and a
pointer: "see Appendix B".

**Decisions.** Each decision is Decided or Open. Only the owner's yes turns
Open into Decided; until then a suggestion stays a suggestion. The Decisions
table lists the Decided ones: what was chosen and what it means in plain
terms; the alternatives that lost go to Appendix C, one line each with why.
Each Open decision gets its own `###` section with its options and their
costs. Mark an option recommended only if you can cite why; if you can't, name
the fact you would need. In v1 number D#s in reading order, Decided first,
then Open. Later versions keep every number; new decisions take the next free
one.

**Candor.** Say plainly whether each part is live, built but not released, or
only planned. For anything built but not released, add a `Missing:` line under
Solution naming what remains; an Open decision names its own gaps and needs no
such line. The Risks table columns are four facts every risk must fill; leave
none blank. If the news is bad and it is the main point, the headline says
so. Anything you could not check is marked as an assumption.

**Concise.** No fixed word count; every sentence earns its place. One
paragraph per problem, one row per Decided decision. No history of how the
work was done, no closing summary, no restating the headline.

**Language.** Simple English unless asked otherwise: plain words and short
sentences, the exact technical term where one exists, the same term for the
same thing throughout. A glossary entry only where a reader would stall.

**Revisions.** vN is a full document, not a diff. Appendix A answers every
comment thread on vN-1, including those that changed nothing (say why). A
fresh draft over an existing doc keeps the D# numbers but has no Appendix A.
