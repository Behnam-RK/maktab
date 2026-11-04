# Repo overrides seen in practice

- **No decision records in code, at any length.** A shrink pass banned
  comparative rationale from comments outright; a 2-line "chose X over Y
  because Z" still moved to the decision log with a pointer. Only constraint
  comments stayed. See `extraction.md`.
- **Existing ADRs folded.** The same pass merged small, *genuinely related*
  existing entries into shared files as subsections (each keeping its own
  Status/Date/anchor, which that repo's convention had). That is disk organization of an existing log; new
  decisions are still one per ADR. Relatedness is the bar, not size.
