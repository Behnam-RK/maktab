from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from .tokens import Counter


PROSE, HEADING, CODE, TABLE, FRONT, BLANK = 'prose', 'heading', 'code', 'table', 'front', 'blank'

# Code and tables are reference material: pricing them at full rate makes
# deleting a worked example the cheapest way to pass, which is the failure mode
# this whole gate exists to avoid.
WEIGHT = {PROSE: 1.0, HEADING: 1.0, CODE: 0.4, TABLE: 0.4, FRONT: 0.0, BLANK: 0.0}

FENCE_RE = re.compile(r'^(?P<indent>[ \t]*)(?P<mark>`{3,}|~{3,})(?P<info>.*)$')
# A closing run of `#` is a closer only after whitespace: `## Learning C#` is
# titled "Learning C#".
HEADING_RE = re.compile(r'^[ \t]{0,3}(?P<hashes>#{1,6})\s+(?P<title>.*?)(?:\s+#+)?\s*$')
LINE_BREAK_RE = re.compile(r'\r\n|\r|\n')
LIST_RE = re.compile(r'^[ \t]*([-*+]|\d+[.)])\s+')
# Any URI scheme, in any case -- not a list of the ones seen so far, which let
# `ftp:`, `ssh:` and `HTTPS:` targets through as files to go and look for. No dot
# in the scheme, or `README.md:12` would read as one.
SCHEME_RE = re.compile(r'[A-Za-z][A-Za-z0-9+-]*:')
INLINE_CODE_RE = re.compile(r'(`+)(?:(?!\1).)+?\1')
MD_LINK_RE = re.compile(
    r"""\[[^\]]*\]\(\s*<?((?:[^()>\s]|\([^()\s]*\))+)>?\s*(?:"[^"]*"|'[^']*')?\)"""
)
STATUS_LINE_RE = re.compile(r'^\s*\*\*Status(?::\*\*|\*\*:)\s*(?P<value>.*?)\s*$')
FRONT_STATUS_RE = re.compile(r'^status:\s*(?P<value>.*?)\s*$')

# `doc-budget:` is the pre-rename spelling. Both are accepted forever: a repo
# that adopts the tool must not have to rewrite markers before its first run.
EXEMPT_MARKERS = ('<!-- docs: exempt', '<!-- doc-budget: exempt')


class Segment(NamedTuple):
    kind: str
    lineno: int
    text: str


class Section(NamedTuple):
    level: int
    title: str
    start: int
    end: int
    tokens: int
    code_tokens: int


class Doc(NamedTuple):
    rel: str
    tokens: int
    lines: int
    segments: list[Segment]
    sections: list[Section]
    exempt_reason: str | None
    fences: list[tuple[int, int, str, int]]
    status: str | None = None


# `str.splitlines` also breaks on U+2028, U+0085 and form feed, which Markdown
# and every editor's line numbers treat as ordinary characters.
def split_lines(text: str) -> list[str]:
    parts = LINE_BREAK_RE.split(text)
    if parts[-1] == '':
        parts.pop()
    return parts


# A link target that names no file: a URL of any scheme, a bare anchor, or a
# protocol-relative `//host`.
def is_external(target: str) -> bool:
    return target.startswith(('#', '//')) or bool(SCHEME_RE.match(target))


# A backtick fence cannot carry a backtick in its info string, or it is inline
# code (```a``` b) that happens to start a line.
def opens_fence(line: str) -> re.Match[str] | None:
    opener = FENCE_RE.match(line)
    if opener and opener.group('mark')[0] == '`' and '`' in opener.group('info'):
        return None
    return opener


# Up to three spaces of indent close a fence, however deep it opened (a list item
# nests it), and the closer carries no info string.
def _closes(line: str, mark: str, indent: int) -> bool:
    body = line.lstrip()
    run = len(body) - len(body.lstrip(mark[0]))
    return (
        run >= len(mark)
        and not body[run:].strip()
        and len(line) - len(body) <= max(indent, 3)
    )


def front_matter_end(lines: list[str]) -> int:
    if not lines or lines[0].strip() != '---':
        return 0
    # Without a closing fence this is a thematic break, not front matter. Opening
    # one anyway would price the whole document at zero and void the gate.
    return next((i for i, ln in enumerate(lines[1:], 2) if ln.strip() == '---'), 0)


def segment(text: str) -> list[Segment]:
    lines = split_lines(text)
    out: list[Segment] = []
    mark = ''
    indent = 0
    discounted = False
    front_end = front_matter_end(lines)
    in_front = False
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if i == 1 and front_end:
            in_front = True
            out.append(Segment(FRONT, i, line))
            continue
        if in_front:
            out.append(Segment(FRONT, i, line))
            in_front = stripped != '---'
            continue
        if mark:
            out.append(Segment(CODE if discounted else PROSE, i, line))
            if _closes(line, mark, indent):
                mark = ''
            continue
        opener = opens_fence(line)
        if opener:
            mark = opener.group('mark')
            indent = len(opener.group('indent'))
            # A bare fence would otherwise let prose buy the code discount.
            discounted = bool(opener.group('info').strip())
            out.append(Segment(CODE if discounted else PROSE, i, line))
            continue
        if not stripped:
            out.append(Segment(BLANK, i, line))
        elif stripped.startswith('|'):
            out.append(Segment(TABLE, i, line))
        elif HEADING_RE.match(line):
            out.append(Segment(HEADING, i, line))
        else:
            out.append(Segment(PROSE, i, line))
    return out


def fences(segments: list[Segment]) -> list[tuple[int, int, str, int]]:
    out: list[tuple[int, int, str, int]] = []
    start: int | None = None
    mark, indent, lang, last = '', 0, '', 0
    for seg in segments:
        if seg.kind != CODE:
            continue
        last = seg.lineno
        if start is None:
            # A code segment outside a fence is the line that opens one.
            opener = opens_fence(seg.text)
            assert opener is not None
            start = seg.lineno
            mark = opener.group('mark')
            indent = len(opener.group('indent'))
            lang = opener.group('info').strip()
            continue
        # The opener's own mark closes it, the same test `segment` applies. Any
        # fence-shaped line used to close it, so a ``` inside a ```` block split
        # one fence into two bogus ones and desynchronised everything after.
        if _closes(seg.text, mark, indent):
            out.append((start, seg.lineno, lang, seg.lineno - start + 1))
            start = None
    if start is not None and last > start:
        # Unclosed at EOF: the fence runs to the end of the file. Dropping it
        # hid the largest block in exactly the document most likely to be long.
        out.append((start, last, lang, last - start + 1))
    return out


# Numbered lines outside every fenced block. A rule that reads prose wants the
# prose: inside a fence the same characters are sample content, and a link there
# points at nothing by design.
def unfenced_lines(text: str) -> Iterator[tuple[int, str]]:
    mark, indent = '', 0
    for lineno, line in enumerate(split_lines(text), start=1):
        if mark:
            if _closes(line, mark, indent):
                mark = ''
            continue
        opener = opens_fence(line)
        if opener:
            mark, indent = opener.group('mark'), len(opener.group('indent'))
            continue
        yield lineno, line


def _weigh(segments: list[Segment], counter: Counter) -> int:
    grouped: dict[str, list[str]] = {}
    for seg in segments:
        grouped.setdefault(seg.kind, []).append(seg.text)
    total = 0.0
    for kind, texts in grouped.items():
        if WEIGHT[kind]:
            total += counter.count('\n'.join(texts)) * WEIGHT[kind]
    return round(total)


def _sections(segments: list[Segment], counter: Counter, last_line: int) -> list[Section]:
    heads = [s for s in segments if s.kind == HEADING]
    if not heads:
        return []
    out: list[Section] = []
    for idx, head in enumerate(heads):
        end = heads[idx + 1].lineno - 1 if idx + 1 < len(heads) else last_line
        body = [s for s in segments if head.lineno <= s.lineno <= end]
        match = HEADING_RE.match(head.text)
        out.append(
            Section(
                level=len(match.group('hashes')) if match else 1,
                title=match.group('title') if match else head.text.strip(),
                start=head.lineno,
                end=end,
                tokens=_weigh(body, counter),
                code_tokens=_weigh([s for s in body if s.kind == CODE], counter),
            )
        )
    return out


def exempt_reason(text: str) -> str | None:
    lines = split_lines(text)
    for line in lines[front_matter_end(lines) :]:
        stripped = line.strip()
        if not stripped:
            continue
        marker = next((m for m in EXEMPT_MARKERS if stripped.startswith(m)), None)
        if marker:
            # Remove the terminator once, then the separator — not as character
            # sets, which ate any reason ending in `-` or `>`.
            body = stripped[len(marker) :]
            if body.endswith('-->'):
                body = body[:-3]
            return body.strip().lstrip('—-').strip()
        return None
    return None


# Front matter wins over a body line: it is the machine-readable spelling, and a
# doc carrying both has said which one it means.
def doc_status(text: str) -> str | None:
    lines = split_lines(text)
    end = front_matter_end(lines)
    # `end` is the closing fence's 1-based line, 0 when there is no front matter;
    # an unguarded `lines[1:-1]` would read the whole body as front matter.
    for line in lines[1 : end - 1] if end else []:
        match = FRONT_STATUS_RE.match(line)
        if match:
            return match.group('value').strip('\'"') or None
    for _, line in unfenced_lines(text):
        match = STATUS_LINE_RE.match(line)
        if match:
            return match.group('value') or None
    return None


def analyze(rel: str, text: str, counter: Counter) -> Doc:
    segs = segment(text)
    lines = len(split_lines(text))
    return Doc(
        rel=rel,
        tokens=_weigh(segs, counter),
        lines=lines,
        segments=segs,
        sections=_sections(segs, counter, lines),
        exempt_reason=exempt_reason(text),
        fences=fences(segs),
        status=doc_status(text),
    )
