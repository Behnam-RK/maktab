from __future__ import annotations

import re

from .config import WARN, Config
from .findings import Finding
from .markdown import LIST_RE, PROSE, TABLE, Doc, unfenced_lines


URL_RE = re.compile(r'(https?://\S+|`[^`]+`)')


def _preamble(doc: Doc) -> int:
    return max(0, doc.tokens - sum(s.tokens for s in doc.sections))


def _split_point(doc: Doc, hard: int) -> tuple[str, int, int] | None:
    tops = [i for i, s in enumerate(doc.sections) if s.level == 2]
    best = None
    for i in tops:
        head = _preamble(doc) + sum(s.tokens for s in doc.sections[:i])
        tail = sum(s.tokens for s in doc.sections[i:])
        if not head or not tail or head > hard or tail > hard:
            continue
        if min(head, tail) < doc.tokens * 0.25:
            continue
        if best is None or abs(head - tail) < abs(best[1] - best[2]):
            best = (doc.sections[i].title, head, tail)
    return best


def _slug(title: str) -> str:
    text = re.sub(r'[`*_]', '', title).strip().lower()
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', text)).strip('-') or 'part-two'


def _heaviest(doc: Doc, n: int = 3) -> list[str]:
    top = sorted(doc.sections, key=lambda s: -s.tokens)[:n]
    return [
        f'{"#" * s.level} {s.title}  —  {s.tokens} tok, L{s.start}-{s.end}' for s in top
    ]


def _folder(rel: str) -> str:
    # rsplit on a root-level file returns the filename, which would send someone
    # to a path like README.md/examples/.
    return rel.rsplit('/', 1)[0] if '/' in rel else '.'


def hint_for(
    doc: Doc, hard: int, duplicate_tokens: int, duplicate_with: str, config: Config
) -> str:
    over = doc.tokens - hard
    folder = _folder(doc.rel)
    biggest_fence = max(doc.fences, key=lambda f: f[3], default=None)
    if biggest_fence and biggest_fence[3] >= 20:
        start, end, lang, span = biggest_fence
        fence_tokens = sum(s.code_tokens for s in doc.sections) or over
        if fence_tokens >= over:
            name = f'{folder}/examples/{_slug(lang or "example")}'
            return (
                f'move the {lang or "code"} block at L{start}-{end} ({span} lines) out to '
                f'{name} and link to it'
            )
    if duplicate_tokens >= over and duplicate_with:
        return (
            f'~{duplicate_tokens} tok of this also appears in {duplicate_with} — '
            f'replace this copy with a link (documentation-guide.md: link, don\'t copy)'
        )
    split = _split_point(doc, hard)
    if split:
        title, head, tail = split
        return (
            f'split at "## {title}": {doc.rel} keeps ~{head} tok, '
            f'{folder}/{_slug(title)}.md takes ~{tail} tok — leave a one-line link behind'
        )
    if len(doc.sections) > 1:
        top = max(doc.sections, key=lambda s: s.tokens)
        # A "section" holding ~the whole doc is really an unstructured doc, and
        # naming it back to the author is no advice at all.
        if doc.tokens * 0.4 <= top.tokens < doc.tokens * 0.9:
            share = round(100 * top.tokens / doc.tokens)
            return (
                f'cut ~{over + round(over * 0.1)} tok from "{"#" * top.level} {top.title}" '
                f'({top.tokens} tok, {share}% of the doc, L{top.start}-{top.end})'
            )
    heads = len(doc.sections)
    threshold = config.rule('wall-of-text', doc.rel).opts['tokens_per_heading']
    if not heads or doc.tokens / max(heads, 1) > threshold:
        return (
            'no section boundary to split on — add "## " headings, then re-run and '
            'this checker will name the split point'
        )
    return 'no single fix stands out; heaviest sections: ' + '; '.join(_heaviest(doc))


# A fence without an info string is weighed as prose, so its lines arrive as
# PROSE segments; they are still literal text that no rewrap may touch.
def _fenced(doc: Doc) -> set[int]:
    text = '\n'.join(seg.text for seg in doc.segments)
    unfenced = {lineno for lineno, _ in unfenced_lines(text)}
    return {seg.lineno for seg in doc.segments if seg.lineno not in unfenced}


def _list_items(doc: Doc, fenced: set[int]) -> list[tuple[int, set[int], int]]:
    items: list[tuple[int, set[int], int]] = []
    start, members, length = 0, set(), 0
    for seg in doc.segments:
        prose = seg.kind == PROSE and seg.lineno not in fenced
        opens = prose and LIST_RE.match(seg.text)
        continues = members and prose and seg.text[:1] in (' ', '\t')
        if opens or not continues:
            if members:
                items.append((start, members, length))
            start, members, length = 0, set(), 0
        if opens:
            start, members, length = seg.lineno, {seg.lineno}, len(seg.text.strip())
        elif continues:
            members.add(seg.lineno)
            length += 1 + len(seg.text.strip())
    if members:
        items.append((start, members, length))
    return items


def _format_findings(doc: Doc, config: Config) -> list[Finding]:
    out: list[Finding] = []
    item_rule = config.rule('list-item-long', doc.rel)
    cell_rule = config.rule('table-cell-crammed', doc.rel)
    line_rule = config.rule('prose-line-long', doc.rel)
    item_max = item_rule.opts['max_chars']

    # A wrapped bullet is many short lines, so the per-line cap cannot see a
    # crammed item; measure the joined item and report only the sharper finding.
    fenced = _fenced(doc)
    long_items = [item for item in _list_items(doc, fenced) if item[2] > item_max]
    in_long_item = {line for _, members, _ in long_items for line in members}
    if item_rule.on:
        for start, _, length in long_items:
            out.append(
                Finding(doc.rel, start, item_rule.id, item_rule.severity,
                        f'list item is {length} chars (over {item_max})')
            )
    # Blank-line placement is deliberately NOT checked: GFM renders a heading or
    # paragraph followed directly by a list, table or fence correctly, so a rule
    # there would police idiomatic style rather than catch corruption.
    cell_max = cell_rule.opts['max_chars']
    line_max = line_rule.opts['max_chars']
    for seg in doc.segments:
        if cell_rule.on and seg.kind == TABLE:
            cells = [c.strip() for c in seg.text.strip().strip('|').split('|')]
            if any(len(c) > cell_max for c in cells):
                out.append(
                    Finding(doc.rel, seg.lineno, cell_rule.id, cell_rule.severity,
                            f'table cell over {cell_max} chars')
                )
        if (line_rule.on and seg.kind == PROSE and seg.lineno not in in_long_item
                and seg.lineno not in fenced):
            bare = URL_RE.sub('', seg.text)
            if len(seg.text) > line_max and len(bare) > line_max:
                out.append(
                    Finding(doc.rel, seg.lineno, line_rule.id, line_rule.severity,
                            f'prose line is {len(seg.text)} chars (over {line_max})')
                )
    return out


def _structure_findings(doc: Doc, config: Config) -> list[Finding]:
    wall = config.rule('wall-of-text', doc.rel)
    frag = config.rule('over-fragmented', doc.rel)
    floor = wall.opts['floor']
    if doc.tokens <= floor or not config.structure_enabled(doc.rel):
        return []
    heads = len(doc.sections)
    if wall.on:
        if heads == 0:
            return [
                Finding(doc.rel, 1, wall.id, wall.severity,
                        f'{doc.tokens} tok with no headings',
                        'add "## " headings so the doc can be navigated and split')
            ]
        tph = doc.tokens / heads
        if tph > wall.opts['tokens_per_heading']:
            return [
                Finding(doc.rel, 1, wall.id, wall.severity,
                        f'{round(tph)} tok per heading '
                        f'(over {wall.opts["tokens_per_heading"]})',
                        'add "## " headings to break up the longest sections')
            ]
    if heads == 0:
        return []
    tph = doc.tokens / heads
    if (
        frag.on
        and heads >= frag.opts['min_headings']
        and tph < frag.opts['tokens_per_heading']
    ):
        return [
            Finding(doc.rel, 1, frag.id, frag.severity,
                    f'{heads} headings at {round(tph)} tok each',
                    'merge the thinnest sections into their neighbours')
        ]
    return []


def findings_for(
    doc: Doc,
    config: Config,
    counter_grace: float = 1.0,
    duplicate_tokens: int = 0,
    duplicate_with: str = '',
    baseline_tokens: int | None = None,
) -> list[Finding]:
    if doc.exempt_reason is not None or config.rules_muted(doc.rel):
        return []
    soft, hard = config.caps_for(doc.rel, doc.status)
    soft, hard = round(soft * counter_grace), round(hard * counter_grace)
    hard_rule = config.rule('over-hard-cap', doc.rel)
    soft_rule = config.rule('over-soft-cap', doc.rel)
    out: list[Finding] = []
    if doc.tokens > hard:
        if hard_rule.on:
            # Diff-aware: touching an already-oversized doc must not demand fixing
            # it wholesale, but growing it further must still fail.
            regressed = baseline_tokens is None or doc.tokens > baseline_tokens
            severity = hard_rule.severity if regressed else WARN
            out.append(
                Finding(doc.rel, 1, hard_rule.id, severity,
                        f'{doc.tokens} weighted tokens '
                        f'(hard cap {hard}, over by {doc.tokens - hard})'
                        + ('' if regressed else ' — pre-existing, not regressed'),
                        hint_for(doc, hard, duplicate_tokens, duplicate_with, config))
            )
    elif doc.tokens > soft and soft_rule.on:
        out.append(
            Finding(doc.rel, 1, soft_rule.id, soft_rule.severity,
                    f'{doc.tokens} weighted tokens '
                    f'(soft cap {soft}, {hard - doc.tokens} to spare)')
        )
    out += _structure_findings(doc, config)
    out += _format_findings(doc, config)
    return out

