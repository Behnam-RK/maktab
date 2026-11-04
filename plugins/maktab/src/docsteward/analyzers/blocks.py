from __future__ import annotations

from ..config import Rule
from ..findings import Finding


# Both analyzers find comment runs their own way but report the same rule with
# the same wording, and that wording was copy-pasted with nothing pinning it.
def comment_block_findings(rel: str, rule: Rule, runs: list[tuple[int, int]]) -> list[Finding]:
    cap = rule.opts['max_lines']
    return [
        Finding(rel, start, rule.id, rule.severity,
                f'comment block of {length} lines (advisory cap {cap})')
        for start, length in runs
    ]
