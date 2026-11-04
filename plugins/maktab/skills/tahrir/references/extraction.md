# Extraction routing

Move a long, knowledge-bearing in-code block to the doc that owns that kind of
knowledge; leave a one-line pointer (plus ≤3-line why only if the local reader
needs it). Match the repo's real layout; default mapping:

| The block documents… | Extract to |
|---|---|
| Mechanics/API of a shared library or package | that package's docs (`<pkg>/docs/…`) |
| A product/business rule or domain flow | the service's business docs |
| An implementation detail (algorithm, data structure) | the service's internals docs |
| A domain term | the glossary (e.g. `CONTEXT.md`) |
| Rationale for a hard-to-reverse decision | the decision log / ADRs |

No home for a category yet → create one lazily (only with real content),
following the repo's documented layout; never a parallel structure. Dedupe
against what exists first. Verify the pointer resolves and the content moved
rather than vanished.

**"No decision records in code" repos.** By default a *short* comparative
why-comment ("chose X over Y because Z") may stay. A repo that states this rule
means it at any length: comparative, trade-off or historical framing moves out
on sight, leaving at most a bare pointer. *Constraint* comments ("do X or Y
breaks") still stay. Don't apply this stricter bar where the repo hasn't stated
it.
