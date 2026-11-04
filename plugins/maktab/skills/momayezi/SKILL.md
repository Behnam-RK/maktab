---
name: momayezi
description: "Run a review ↔ fix loop: you edit, fresh read-only reviewer subagents (normally on a model at least as strong as yours) critique each round, until clean, capped or stalled. Works on a diff, files, a plan, a spec or a doc. Use when the user asks for it — 'review loop', 'review and fix until clean', 'keep reviewing', 'get this reviewed by opus', 'momayezi this' — never on your own after ordinary edits."
argument-hint: "[target] [--lenses a,b] [--model m] [--max-rounds n] [--max-reviewers n] [--smart|--no-smart] [--verify] [--no-exec] [--reviewer remote [--remote-timeout s]] [--review-only …]"
---

# Momayezi — review ↔ fix loop

You are the **editor**: you own every change and the ledger. Reviewers are
`maktab:momayez` subagents: read-only, fresh each round, and they return
findings in the format their definition fixes. Rounds run without stopping for
the user, who hears from you at the announcement, if no gate is found, and at
the end.

Arguments: `$ARGUMENTS`

**Modes.** `--review-only` (one CI round, no edits): follow
[references/review-only.md](references/review-only.md) instead.
`--reviewer remote` (the `momayez` check run reviews): read
[references/remote.md](references/remote.md) before Setup.

## Setup

1. **Target.** What the user named (files, a doc, a ref range). Default: the
   diff of the current branch against its base plus uncommitted changes. Its
   kind (code, prose, mixed) comes from lenses.md "Picking".
2. **Smart sizing.** On with `--smart`, or `${user_config.momayezi_smart}` = `on`
   unless `--no-smart`. [references/smart.md](references/smart.md) then sets
   wave size, model and cap (steps 5–6), ahead of config; explicit flags win.
3. **Intent brief.** From the conversation, ticket or spec, write once:
   goal, requirements, constraints, out-of-scope. Pinned for every round;
   never rewritten to fit a finding.
4. **Lenses.** By changed paths, per "Picking" in
   [references/lenses.md](references/lenses.md), capped at `--max-reviewers`,
   else `${user_config.momayezi_max_reviewers}` (2 if blank or unsubstituted).
5. **Reviewer model.** Order: `haiku < sonnet < opus < fable`. Take the
   stronger of your own model and the configured floor
   `${user_config.momayezi_reviewer_model}` (`opus` if blank or unsubstituted). Smart's
   `sonnet` pick (smart.md) replaces that; `--model` beats all. Pass it as the
   Agent `model` parameter on every reviewer spawn.
6. **Cap.** `--max-rounds`, else `${user_config.momayezi_max_rounds}` (3 if blank or
   unsubstituted).
7. **Gate** (code only). Find it per [references/gate.md](references/gate.md).
   Record its baseline; a red one is reported and excluded from the stop
   check, not fixed silently. Prose: no gate, `n/a`.
8. **Announce** in one block, then start round 1 without waiting:

```
Momayezi: <target>
Smart:   <tier> (<n> lines, <f> files, <risky|plain>) | off
Intent:  <goal> | reqs: … | constraints: … | out: …
Lenses:  <a, b> on <model>   Cap: <n>   Gate: <command> (<green|red|none>) | n/a
Reviewer: local | remote (commits and pushes each round to <branch>)
```

## A round

1. **Spawn** one reviewer per lens, each fresh, in waves of at most the
   reviewer cap (Setup step 4); smart never raises it. One message per wave,
   each finishing before the next. Prompt each with the intent brief, its lens brief from lenses.md, the
   target, from round 2 the ledger, and with `--no-exec` `Execution: off`
   (the verifier's too). Scope:
   - Round 1 and the capped round: the full target.
   - Other rounds: the last fix diff (regressions) and files no finding has
     cited.
2. **Filter.** Drop findings below confidence 80 unless critical. Merge
   duplicates across lenses. A finding matching a ledger entry keeps that id;
   a `wont-fix` re-raised without new evidence is dropped. New findings get
   the next ledger id (`F1`, `F2`, …).
3. **Verify** (only with `--verify`): one more reviewer spawn, same model,
   given the surviving findings by ledger id, to answer each `confirmed` or
   `refuted` with one line of evidence (the `momayez` agent, Verify mode). Drop
   refuted ones.
4. **Decide each finding yourself.** Open the cited line. Real and ≥minor: fix
   it, smallest change, with a test where the project has a test harness and
   the defect is testable. Wrong: mark `wont-fix` with the evidence (the line,
   test or rule that refutes it). Real but a product choice the brief doesn't
   settle: mark `disputed` for the user. Nits: record, don't fix.
5. **Gate.** Re-run it. Red beyond the baseline's failures: fix or revert this round's
   fixes first.
6. **Report the round** in one line:
   `Round n: <k> findings (c/M/m/nit) · fixed <x> · wont-fix <y> · disputed <z> · gate <green|red|n/a> · <continuing|stopping: reason>`

## Ledger

Kept in your context, typed per [references/ledger.md](references/ledger.md);
nothing is written to disk.

## Stop

After each round, stop at the first that holds:

- **Clean**: no new critical or major findings this round, gate not red.
- **Cap**: this was round `max_rounds`.
- **Stall**: nothing fixed and nothing new: every surviving finding is a
  ledger entry.

Minor findings are fixed but don't keep the loop alive.

## Final report

```
## Momayezi — <target>
Rounds:    <n> on <model>, lenses <a, b> — stopped: <clean|cap|stall|remote unavailable>
Reviewer:  local | remote (<n> requests)
Gate:      <command> — <green|red> (baseline <green|red>) | n/a
Fixed:     F1 <severity> <path:line> — <claim>
Won't fix: F4 <path:line> — <claim> — <evidence>
Disputed:  F6 <path:line> — <claim> — <both readings>
Uncited:   <target files no finding cited, or none>
Nits:      <count>
```

Omit empty lines except `Gate` and `Uncited` (not examined, not found clean). Then:

1. **Disputed** findings: one question each, with both readings.
2. **Nits**: `AskUserQuestion`, multiSelect, up to four nits per question (with
   more than eight, offer "fix all" / "pick" / "none" first). Fix the chosen
   ones, re-run the gate, and say it's done.
