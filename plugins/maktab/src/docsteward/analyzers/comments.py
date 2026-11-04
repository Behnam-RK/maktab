from __future__ import annotations

import re
from pathlib import PurePosixPath

from ..config import Config
from ..findings import Finding
from ..markdown import split_lines
from .blocks import comment_block_findings


BLOCK_OPEN, BLOCK_CLOSE = '/*', '*/'

# One left-to-right scan: the first construct claims its text, so a quote, an
# arithmetic expression or a trailing comment hides a later `<<`. The heredoc
# alternative owns a quoted tag; `<<<` is a here-string; `<<-`, `<<~` indent.
SHELL_TOKEN_RE = re.compile(
    r"""
    "[^"]*" | '[^']*'
    | \$?\(\((?:[^()]|\([^()]*\))*\)\)
    | (?<!<)<<(?!<)[-~]?\s*(?P<quote>['"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)
    | (?P<comment>\s\#)
    """,
    re.VERBOSE,
)


def _heredoc_tag(line: str, prefix: str) -> str | None:
    # Only shell-family files use `#`, and only they carry heredocs whose body
    # would otherwise read as a wall of own-line comments.
    if prefix != '#':
        return None
    for match in SHELL_TOKEN_RE.finditer(line):
        if match.group('comment'):
            return None
        if match.group('tag'):
            return match.group('tag')
    return None


def comment_runs(source: str, prefix: str, cap: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = length = previous = 0
    heredoc: str | None = None
    in_block = False
    lines = split_lines(source)
    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if heredoc is not None:
            if stripped == heredoc:
                heredoc = None
            continue
        if in_block:
            in_block = BLOCK_CLOSE not in stripped
            continue
        if prefix == '//' and stripped.startswith(BLOCK_OPEN):
            # A /** JSDoc */ block is not a line-comment run; skip it whole.
            in_block = BLOCK_CLOSE not in stripped[len(BLOCK_OPEN) :]
            continue
        # A comment that mentions `<<EOF`, own-line or trailing, opens nothing;
        # reading it as a heredoc hid every later run. A tag with no terminator
        # line after it opens nothing either, or it would hide the whole file.
        tag = None if stripped.startswith(prefix) else _heredoc_tag(raw, prefix)
        if tag is not None and any(rest.strip() == tag for rest in lines[lineno:]):
            heredoc = tag
            continue
        # A shebang is only a shebang on line 1. Excluding it everywhere let a
        # mid-file `#!` split one long run into two short ones, so it *hid* the
        # finding rather than adding a false one.
        shebang = lineno == 1 and stripped.startswith('#!')
        counts = stripped.startswith(prefix) and not shebang
        if counts:
            if length and lineno == previous + 1:
                length += 1
            else:
                if length > cap:
                    runs.append((start, length))
                start, length = lineno, 1
            previous = lineno
    if length > cap:
        runs.append((start, length))
    return runs


# `baseline` is part of the analyzer contract so the dispatch can be a table.
# No rule here is baseline-sensitive: the demotion of a pre-existing violation
# only applies to docstrings, which are Python's.
def findings_for(
    rel: str, source: str, baseline: str | None, config: Config
) -> list[Finding]:
    rule = config.rule('comment-block', rel)
    if not rule.on or not config.comments_enabled:
        return []
    prefix = config.comment_prefix(PurePosixPath(rel).suffix)
    if not prefix:
        return []
    runs = comment_runs(source, prefix, rule.opts['max_lines'])
    return comment_block_findings(rel, rule, runs)
