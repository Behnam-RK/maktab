# Documentation Guide

**Code talks; docs are the exception, not the default.** A clear name, type,
and signature should carry most of what a reader needs — reach for a doc only
when the code genuinely can't express it (a cross-cutting rule, a decision's
rationale, an operational runbook). More documentation is not a safety net;
it's more surface area to go stale. `tahrir check` enforces the budgets below —
blocking, in pre-commit and CI.

## Budgets (blocking)

Measured in **weighted tokens**, not lines: prose 1.0, fenced code and tables
0.4, front matter 0. Rewrapping a paragraph barely moves the count, so blank
lines and un-crammed tables are free — a line cap makes them expensive and docs
get squeezed to fit.

| Surface | Soft | Hard | On breach |
|---|---|---|---|
| `.md` file | 1000 | 1400 | the checker names a split, trim or link |
| `README.md` | 2000 | 3000 | as above |
| `docs/adr/*` | 1200 | 2000 | a decision already made — prefer a new ADR |
| Module docstring | — | 0 | delete, unless a runtime surfaces it |
| Docstring | — | runtime-surfaced only | delete otherwise |
| Comment block | 3 lines | — | advisory; relocate if it is narration |

Every threshold is a default; `.docs.toml` overrides any per glob, and
`tahrir --explain <rule>` prints one rule's reasoning and knobs.

Ratios, all advisory: **tokens per heading**, **doc tokens vs code tokens** per
package, and **cross-doc duplication** — the same block in two docs means one
should be a link.

Two advisory checks guard the decision log: `adr-number-collision` (two ADRs on
one number, or an index row and a file that disagree) and
`changelog-unreleased-tagged` (a `## [X.Y.Z] - Unreleased` heading whose git tag
exists; CI must fetch tags). A `status` list on an `[[overrides]]` entry caps a
doc by its `**Status:**` line, so a stub gets a smaller budget than a live ADR.

`tahrir check` is strict with no file arguments (CI) and diff-aware with them (a
`git commit`), where only *new* violations fail. Counting uses tiktoken, falling
back to a relaxed estimate offline, so it never fails what CI would pass.

**In-code boundary test:** would a competent dev make a *wrong edit* without
this line — an ordering trap, an upstream bug, an invariant? Keep it, ≤3 lines.
Would they merely wonder *why*? Delete it, or move the rationale to the doc that
owns it and leave a bare pointer.

**Decision records are banned from code.** "We chose X over Y because Z" and
`# used to do Z` narration belong in [`docs/adr/`](../adr/README.md), not a comment — a
comment states a constraint, not a choice.

**Runtime-surfaced = exempt from the docstring rule**, not from truth: a schema
type/field/resolver, a tool function, or a module whose docstring feeds `--help`.
These *are* the contract; keep them accurate. List your own exempt decorators
under `[python] runtime_surfaced_decorators` — a framework reading an
*attribute* rather than the docstring is not exempt.

### Exemptions

Declare, don't infer — every exemption prints in `tahrir check`'s output:

| Kind | How |
|---|---|
| `*.prompt.md`, `CHANGELOG.md` | unconditional (`[exclude] always_exempt`) |
| A doc with a real diagram/artifact/long snippet | `<!-- docs: exempt — <reason> -->`, first non-blank line (after front matter if present) |
| A whole subtree outside this policy | `[exclude] paths` |

`README.md` is **not** exempt — it has its own larger cap. It is the first doc
an agent reads, so leaving it unmeasured is the biggest hole a policy can have.

## Form

Lead with a table or an index. A structural diagram (ASCII is fine) must
**replace** the prose it would otherwise take to explain — never sit next to it.
Decorative ASCII and emoji stay banned; a diagram earns its place only by
carrying information a paragraph would otherwise carry.

## Where things live

| Kind | Home |
|---|---|
| What a function does | A clear name + types. No docstring. |
| A local constraint | ≤3-line comment above the line. |
| A decision's rationale | `docs/adr/` |
| Cross-module convention | `docs/conventions/*.md` |
| Workflow / process | `docs/workflows/*.md` |
| Operational runbook | `docs/infra/*.md` — command + gotcha + recovery |
| Package mechanics | the package's own `docs/`, so it travels with its tag |
| Domain term | `docs/glossary*.md` |
| Where to find something | `docs/index*.md` |

A topic straddling business rules and internals gets two cross-linked files,
never one mixed file. Create a new doc only when it is not covered elsewhere, is
referenced from ≥2 places, and is convention, decision or mechanics.

## When to update

Docs ship in the same PR as the change they describe: behavior changed →
update; something significant added → add. Outdated docs are worse than none.

## Anti-patterns

- Re-documenting framework behavior — link out instead.
- Mirroring code line-by-line — the code is already there.
- A package's API described in the global `docs/` instead of the package's own.
- A long doc propping up code that's hard to follow — refactor the code.
- Two docs stating the same rule — link, don't copy.
- Backticking an illustrative path — `stale-file-ref` reads it as a claim
  that the file exists. Unbacktick or fence it.
