# Report format

End every pass with this (pasteable as a PR comment). One line per item; omit
empty sections. Nothing to change → say so with a one-line reason.

```
## Doc review
Updated:   <file> — <what changed and why>
Appended:  <file> — <new docstring / changelog line>
Recorded:  <ADR ref> — <decision captured; index updated if the repo has one>
Extracted: <code site> → <doc> — <what moved; pointer left behind>
Deduped:   <doc> — <duplicate folded in from where>
Trimmed:   <file> — <stale comment / resolved TODO removed>
Flagged:   <needs the author: e.g. "unrecorded decision, ADR proposed but not approved", "code is convoluted; doc can't fix it">
```
