from __future__ import annotations

import re
import sys
from functools import cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from .config import Config, glob_match
from .corpus import GitUnavailable, git, package_of, read_tracked
from .findings import Finding
from .markdown import (
    HEADING_RE,
    INLINE_CODE_RE,
    MD_LINK_RE,
    is_external,
    split_lines,
    unfenced_lines,
)
from .scaffold import MARKERS


PATH_RE = re.compile(r'`([\w][\w./@-]*\.[A-Za-z0-9]{1,5})`')
ALLOW_RE = re.compile(r'<!--\s*docs:\s*allow\s+stale-file-ref\s*-->')
CHECKBOX_RE = re.compile(r'^\s*[-*+]\s+\[ \](?:\s|$)')
CITATION_RE = re.compile(
    r'`(?P<path_a>[\w./-]+\.md)`\'s\s+"(?P<title_a>[^"]+)"'
    r'|"(?P<title_b>[^"]+)"\s+section of\s+`?(?P<path_b>[\w./-]+\.md)`?'
)


def _candidates(root: Path, rel: str, target: str, config: Config) -> list[Path]:
    # Decoded, because a link spells a space `%20` and the file does not.
    target = unquote(target.split('#', 1)[0].strip())
    if not target or is_external(target):
        return []
    if target.startswith('/'):
        return [root / target.lstrip('/')]
    # Repo-root as well as doc-relative: prose naming a path like docs/index.md
    # means the one at the root, not one nested under the citing doc's own
    # directory. Unbackticked here on purpose — it is an example, not a link.
    found = [(root / rel).parent / target, root / target]
    # And the doc's own package: inside services/atabak/docs/, `apps/shops/x.py`
    # is the shorthand for the file under services/atabak/ that the service's
    # own README writes that way.
    package = package_of(rel, config.package_roots)
    if package:
        found.append(root / package / target)
    # Also, with or without package_roots, the nearest project the doc sits in: a monorepo's
    # sub-projects name their files from their own manifest's directory.
    project = _project_of(root, rel)
    if project is not None:
        found.append(project / target)
    return found


# A target past the filesystem's name limit raises from `exists` rather than
# answering no, and so does one with a NUL in it.
def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


@cache
def _has_manifest(directory: Path) -> bool:
    return any((directory / name).is_file() for name in MARKERS)


def _project_of(root: Path, rel: str) -> Path | None:
    # The repo root is a candidate already; only a project below it adds one.
    for parent in PurePosixPath(rel).parents[:-1]:
        if _has_manifest(root / parent):
            return root / parent
    return None


# Every suffix of every tracked path and directory, so a lookup is one set test
# rather than a scan of the tree per reference.
def suffix_index(root: Path) -> frozenset[str]:
    listing = git(root, 'ls-files', '-z')
    names: set[str] = set()
    for path in (line for line in (listing or '').split('\0') if line):
        parts = path.split('/')
        for start in range(len(parts)):
            names.add('/'.join(parts[start:]))
        for end in range(1, len(parts)):
            for start in range(end):
                names.add('/'.join(parts[start:end]))
    return frozenset(names)


def _allowed(lines: list[str], lineno: int) -> bool:
    here = lines[lineno - 1]
    above = lines[lineno - 2] if lineno > 1 else ''
    return bool(ALLOW_RE.search(here) or ALLOW_RE.search(above))


def stale_file_refs(
    root: Path, rel: str, text: str, config: Config,
    suffixes: frozenset[str] | None = None,
) -> list[Finding]:
    rule = config.rule('stale-file-ref', rel)
    if not rule.on:
        return []
    ignore = rule.opts['ignore_patterns']
    lines = split_lines(text)
    out: list[Finding] = []
    # Fenced blocks are skipped: a link in a sample document is sample content.
    for lineno, line in unfenced_lines(text):
        # Inline code is the same: a link shown in backticks is an example, while
        # the backticks are what mark a bare path as a reference below.
        targets = [m.group(1) for m in MD_LINK_RE.finditer(INLINE_CODE_RE.sub('', line))]
        targets += [m.group(1) for m in PATH_RE.finditer(line) if '/' in m.group(1)]
        for target in targets:
            # No candidates means the target is not a file reference at all — a
            # URL or a bare anchor — which is not a stale one.
            candidates = _candidates(root, rel, target, config)
            if not candidates or any(_exists(c) for c in candidates):
                continue
            if any(glob_match(target.split('#', 1)[0], pattern) for pattern in ignore):
                continue
            if suffixes is not None and _bare(unquote(target)) in suffixes:
                continue
            if _allowed(lines, lineno):
                continue
            out.append(
                Finding(rel, lineno, rule.id, rule.severity,
                        f'reference to {target} — no such file',
                        'fix the path or drop the reference')
            )
    return out


# `./x` and `x/` name what `x` does; `../x` climbs out of wherever it was
# written, which no suffix of a tracked path can answer.
def _bare(target: str) -> str:
    target = target.split('#', 1)[0].strip().rstrip('/')
    return '' if target.startswith('..') else target.removeprefix('./')


# Compiled once per marker list rather than once per file scanned.
@cache
def _marker_re(markers: tuple[str, ...]) -> re.Pattern[str]:
    # Not `\b`, which needs a word character beside it: `TODO:` and `@todo` end
    # or start in punctuation and could never match.
    return re.compile(r'(?<!\w)(' + '|'.join(re.escape(m) for m in markers) + r')(?!\w)')


def _lines(text: str, prose: bool):
    return unfenced_lines(text) if prose else enumerate(split_lines(text), start=1)


# `prose` is the caller's word that this is a document: only there is a fence
# sample content, while in source the same characters are code to be read.
def todo_markers(rel: str, text: str, config: Config, prose: bool = True) -> list[Finding]:
    rule = config.rule('todo-marker', rel)
    markers = tuple(rule.opts['markers'])
    # `markers = []` is a valid list of strings, so it reaches here — and an
    # empty alternation compiles to `\b()\b`, which matches at every word
    # boundary. An empty list means "nothing to look for", not "everything".
    if not rule.on or not markers:
        return []
    pattern = _marker_re(markers)
    return [
        Finding(rel, lineno, rule.id, rule.severity, f'{match.group(1)} marker left in place')
        for lineno, line in _lines(text, prose)
        if (match := pattern.search(line))
    ]


def open_checkboxes(rel: str, text: str, config: Config) -> list[Finding]:
    rule = config.rule('open-checkbox', rel)
    if not rule.on:
        return []
    return [
        Finding(rel, lineno, rule.id, rule.severity, 'open checkbox in a shipped doc')
        for lineno, line in unfenced_lines(text)
        if CHECKBOX_RE.match(line)
    ]


def _headings(path: Path) -> set[str]:
    try:
        text = read_tracked(path)
    except OSError:
        return set()
    out = set()
    # Not a heading in a fence: a sample document's `## Install` is not one.
    for _, line in unfenced_lines(text):
        match = HEADING_RE.match(line)
        if match:
            out.add(re.sub(r'[`*_]', '', match.group('title')).strip().lower())
    return out


def section_citations(root: Path, rel: str, text: str, config: Config) -> list[Finding]:
    rule = config.rule('section-citation', rel)
    if not rule.on:
        return []
    out: list[Finding] = []
    # One parse per cited file, not one per citation on every line.
    headings: dict[Path, set[str]] = {}
    for lineno, line in enumerate(split_lines(text), start=1):
        for match in CITATION_RE.finditer(line):
            path = match.group('path_a') or match.group('path_b')
            title = match.group('title_a') or match.group('title_b')
            candidates = _candidates(root, rel, path, config)
            # No candidates at all means the target is not a file reference — a
            # protocol-relative `//host/x.md` reads as one to the pattern above.
            if not candidates:
                continue
            resolved = next((c for c in candidates if _exists(c)), None)
            if resolved is None:
                out.append(
                    Finding(rel, lineno, rule.id, rule.severity,
                            f'cites "{title}" in {path} — no such file')
                )
                continue
            if resolved not in headings:
                headings[resolved] = _headings(resolved)
            if title.strip().lower() not in headings[resolved]:
                out.append(
                    Finding(rel, lineno, rule.id, rule.severity,
                            f'cites "{title}" in {path} — no such section')
                )
    return out


# Git does the matching, against the configured pathspecs, because git is what
# `corpus.walk` enumerates with: `doc_globs = ["docs/"]` is an ordinary spelling
# that no Python glob matcher reads the way git does.
def _changed(root: Path, base: str, patterns: list[str]) -> list[str] | None:
    if not patterns:
        return []
    for spec in (f'{base}...HEAD', base):
        names = git(root, 'diff', '--name-only', '--relative', '-z', spec,
                    '--', *patterns)
        if names is not None:
            return [n for n in names.split('\0') if n]
    return None


def changed_without_docs(root: Path, base: str | None, config: Config) -> list[Finding]:
    rule = config.rule('changed-without-docs')
    if not rule.on or not base:
        return []
    code_names = _changed(root, base, config.code_globs)
    doc_names = _changed(root, base, config.doc_globs)
    if code_names is None and doc_names is None:
        # Every form failed, for every pathspec. Falling back to '' turned a
        # typo into a clean result, so this is an error — unless the clone is
        # shallow, where the ref is genuinely absent rather than misspelled.
        if git(root, 'rev-parse', '--is-shallow-repository') == 'true\n':
            print(f'tahrir: --base {base!r} is outside a shallow clone — '
                  'changed-without-docs skipped', file=sys.stderr)
            return []
        raise GitUnavailable(f'cannot resolve --base {base!r} as a git ref')

    # The skip policy `corpus.walk` applies: an excluded or muted path neither
    # demands a doc nor counts as one. Checking `is_excluded` alone let a commit
    # confined to a `rules = "off"` subtree still ask for documentation.
    def in_policy(name: str) -> bool:
        return not config.is_excluded(name) and not config.rules_muted(name)

    code = [n for n in (code_names or []) if in_policy(n)]
    # No code in the diff, nothing for a doc to have explained. Checking the
    # docs first made a changelog-only commit report "0 file(s) changed".
    if not code:
        return []
    # A doc that is outside the policy is not evidence the policy was met: a
    # CHANGELOG bump used to buy silence for an arbitrarily large code diff.
    docs = [
        n for n in (doc_names or [])
        if not config.is_pattern_exempt(n) and in_policy(n)
    ]
    if docs:
        return []
    return [
        Finding('.', 1, rule.id, rule.severity,
                f'{len(code)} file(s) changed since {base}, no doc changed',
                'confirm the change is invisible to a reader, or update the docs')
    ]
