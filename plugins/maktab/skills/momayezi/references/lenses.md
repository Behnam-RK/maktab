# Lenses

Pass a reviewer its lens name and the brief below verbatim.

## Picking

By changed paths only, so the same list gives the same lenses here and in CI.
`--lenses` overrides and is never trimmed. Otherwise, from the target's
`git diff --name-only <base> [<head>]` (plus untracked files locally), run
each rule below as `… | rg -qi '<pattern>'` (exit 0 = a path matches):

```
prose     \.(md|mdx|rst|txt|adoc)$
security  auth|secret|token|crypt|passw|credential|shell|exec|sql|migrat|parse|\.sh$|\.github/workflows/|(^|/)(infra|deploy)/|terraform|\.tf$|dockerfile|compose\.ya?ml$
test      (^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$|_spec\.rb$|conftest\.py$
source    \.(py|pyi|js|jsx|mjs|cjs|ts|tsx|go|rs|rb|java|kts?|swift|c|cc|cpp|h|hpp|cs|php|scala|exs?|sh)$
docs      \.(md|mdx|rst)$|(^|/)docs?/|(^|/)(cli|cmd|bin)(/|\.)|config|settings|\.(toml|ya?ml|ini|cfg)$|(^|/)(api|public)/|openapi|\.proto$|(^|/)__init__\.py$|(^|/)index\.(js|ts|mjs)$|package\.json$
```

1. **Kind**: prose if every path matches `prose` (`rg -vqi` finds none
   that doesn't), code if none does, else mixed.
2. **Defaults**: code: correctness, spec-fit. Prose: accuracy, clarity.
   Mixed: correctness, accuracy. Prose and mixed add spec-fit when the intent
   brief states a requirement.
3. **Added** (code and mixed): security when `security` matches; tests when
   a path matches `source` but not `test` (`rg -i '<source>' | rg -vqi
   '<test>'`) and no path matches `test`; docs when `docs` matches.
   Performance and simplicity come only from `--lenses`.
4. **Cap**: keep the first `max_reviewers` (smart's tier count, if lower) in
   this order: security, correctness, accuracy, spec-fit, tests, docs, clarity.

## correctness

Does it do what it claims on every reachable path? Off-by-one, wrong
condition, null/empty/error paths, races, resource leaks, broken invariants,
wrong API use. Not: style, naming, design preference.
Critical: wrong output or crash on a normal path. Major: bug on a plausible path.

## security

Untrusted input reaching shell, SQL, paths, HTML, deserialisers; authz checks
missing or bypassable; secrets in code or logs; unsafe defaults. Not:
theoretical attacks needing access the attacker already has.
Critical: exploitable from outside. Major: exploitable with a plausible foothold.

## spec-fit

Hold the target against the intent brief line by line: every requirement met,
no constraint broken, nothing out-of-scope added. Not: requirements the brief
does not state.
Major: requirement unmet or constraint broken. Minor: scope creep.

## simplicity

Code or structure that is harder than the problem: needless layers, single-use
abstractions, duplicated logic, dead code, configuration for fixed values.
Not: rewriting working code into your preferred shape.
Major only when the complexity hides a bug or blocks the stated goal; else minor.

## tests

New or changed behaviour without a test that would fail if it broke; tests
that assert nothing, mock the thing under test, or pass for the wrong reason.
Not: coverage numbers, test style.
Major: a changed critical path is untested. Minor: edge case untested.

## performance

Work that scales worse than it needs to on realistic input: N+1 queries,
quadratic loops over unbounded data, repeated IO in loops, blocking calls on
hot paths. Not: micro-optimisation without a hot path.
Major: user-visible on realistic input. Minor: wasteful but bounded.

## docs

Do the docs still match the changed code? READMEs, docstrings, comments,
changelogs, ADRs and `--help` text that describe a renamed, removed or changed
symbol, flag or config key; a new public surface or a settled decision with no
record. If `command -v tahrir` succeeds, run
`tahrir scan --json`: its leads are repo-wide (`--base` only feeds the
`changed-without-docs` rule, off by default), so keep those on files or symbols
the target touches, and verify each against the code before reporting it.
Not: style, length, or docs for unchanged code.
Major: a reader acting on the doc would fail. Minor: stale or missing prose that misleads nobody.

## accuracy

Every factual claim checked against its source: code, docs, the conversation,
cited URLs. Wrong names, stale behaviour, commands that would fail, numbers
that don't add up. Not: wording.
Major: a reader acting on it would fail. Minor: misleading but recoverable.

## clarity

Can the intended reader act on it without asking? Missing steps, undefined
terms, ambiguous instructions, buried key point, contradictions between
sections. Not: tone, length preference.
Major: ambiguity that leads to the wrong action. Minor: friction.
