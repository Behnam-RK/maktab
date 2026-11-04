from __future__ import annotations

import posixpath
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .config import Config, glob_match
from .findings import Finding
from .markdown import (
    BLANK,
    CODE,
    FRONT,
    HEADING,
    MD_LINK_RE,
    TABLE,
    Doc,
    analyze,
    exempt_reason,
    is_external,
    unfenced_lines,
)
from .tokens import Counter


LINK_RE = re.compile(r'\[([^\]]*)\]\([^)]*\)')
PUNCT_RE = re.compile(r'[^a-z0-9 ]+')

# Editors on Windows write one, and left on it hides a heading, front matter or
# an exempt marker on line 1 behind an invisible character.
BOM = '\ufeff'

# Generous for a large repo, finite for a gate that runs in a commit hook.
GIT_TIMEOUT = 30


class GitUnavailable(RuntimeError):
    pass


class Scope(NamedTuple):
    files: tuple[Path, ...] = ()

    # CONTEXT.md names both modes; they were previously distinguished by whether
    # an Optional[list] was None, which made a boolean mode flag travel through
    # five signatures disguised as data.
    @property
    def diff_aware(self) -> bool:
        return bool(self.files)


# No file arguments: strict mode, the whole tracked corpus.
WHOLE_REPO = Scope()


def git(root: Path, *args: str) -> str | None:
    try:
        # utf-8/replace, not `text=True`, which decodes with the locale codec:
        # a non-ASCII path came back as a UnicodeDecodeError. argv and cwd are
        # encoded with the filesystem codec, hence `_fs` -- see ADR-0005.
        result = subprocess.run(
            ['git', *(_fs(arg) for arg in args)], cwd=_on_disk(root),
            capture_output=True, encoding='utf-8', errors='replace',
            timeout=GIT_TIMEOUT,
        )
    except OSError as exc:
        # A missing `git` and a root that does not exist both land here, and
        # both used to surface as a traceback.
        raise GitUnavailable(f'cannot run git in {root}: {exc}') from exc
    except subprocess.TimeoutExpired as exc:
        raise GitUnavailable(f'git {args[0]} timed out after {GIT_TIMEOUT}s') from exc
    return result.stdout if result.returncode == 0 else None


def _scoped_names(root: Path, scope: Scope) -> set[str]:
    # The arguments as `git ls-files` spells them: repo-relative posix. A path
    # outside the root is not in the corpus, so it drops out here.
    base = root.resolve()
    out = set()
    for path in scope.files:
        try:
            out.add(path.resolve().relative_to(base).as_posix())
        except ValueError:
            continue
    return out


def _fs(name: str) -> str:
    # Where the filesystem encoding is not UTF-8, an accented name git reported
    # cannot be encoded back -- neither to stat it nor to hand it to git as an
    # argument -- and it drops out of the corpus unmeasured. See ADR-0005.
    encoding = sys.getfilesystemencoding()
    if encoding.replace('-', '').replace('_', '').lower() == 'utf8':
        return name
    return name.encode('utf-8').decode(encoding, 'surrogateescape')


def _on_disk(path: Path) -> Path:
    return Path(_fs(str(path)))


# Every read of a tracked path goes through here, so no caller has to remember
# that the name it reports and the name it opens can differ.
def read_tracked(path: Path) -> str:
    return _on_disk(path).read_text(encoding='utf-8', errors='replace').removeprefix(BOM)


def tracked(root: Path, patterns: list[str], scope: Scope = WHOLE_REPO) -> list[Path]:
    # An empty glob list means "enumerate nothing". Handed to `git ls-files` it
    # means the opposite — no pathspec at all — so `doc_globs = []` measured
    # every tracked file, source and lockfiles included, against the doc caps.
    if not patterns:
        return []
    # -z, because git otherwise quotes a non-ASCII path as "src/caf\303\251.md"
    # and the is_file() filter below drops it — unmeasured, and silently.

    # `--`, because a glob is data: a pattern starting with a dash would
    # otherwise be read as an option rather than as a pathspec.
    listing = git(root, 'ls-files', '-z', '--', *patterns)
    if listing is None:
        # The one caller where "git failed" and "git listed nothing" differ:
        # swallowing that let a non-repo root pass the gate on everything.

        # Which failure, though: a pathspec git rejects also exits non-zero, and
        # telling someone their repository is not one sends them looking in the
        # wrong place for a typo in `doc_globs`.
        if git(root, 'rev-parse', '--git-dir') is None:
            raise GitUnavailable(
                f'{root} is not a git repository — the gate measures tracked files only'
            )
        raise GitUnavailable(
            f'git rejected the configured patterns {patterns!r} in {root}'
        )
    names = [line for line in listing.split('\0') if line]
    # Narrowed by name before anything touches the filesystem. This used to
    # resolve() every tracked path in the repo to find the handful the
    # pre-commit hook passed in, on every commit that touched any text file.
    if scope.diff_aware:
        wanted = _scoped_names(root, scope)
        names = [n for n in names if n in wanted]
    # is_file(): the index still lists a file deleted in the working tree, and a
    # budget gate must not traceback over someone's in-progress `rm`.
    return [p for n in names if _on_disk(p := root / n).is_file()]


class Walk(NamedTuple):
    files: list[tuple[str, str]]
    exempt: list[str]


# `are_docs` is the caller's answer, not a predicate's: only the caller knows
# whether it handed over `doc_globs` or `code_globs`. Re-deriving it in Python
# read the ordinary pathspec `docs/` as matching nothing.
def walk(
    root: Path,
    patterns: list[str],
    config: Config,
    scope: Scope = WHOLE_REPO,
    are_docs: bool = True,
) -> Walk:
    files: list[tuple[str, str]] = []
    exempt: list[str] = []
    seen: set[str] = set()
    for path in tracked(root, patterns, scope):
        rel = path.relative_to(root).as_posix()
        # One skip policy for every walk. Four call sites stated four slightly
        # different ones, so `*.prompt.md` was exempt from the markdown rules
        # but not from the code analyzer. See CONTEXT.md.
        if rel in seen or config.is_excluded(rel) or config.rules_muted(rel):
            continue
        seen.add(rel)
        if config.is_pattern_exempt(rel):
            exempt.append(f'{rel} (pattern)')
            continue
        text = read_tracked(path)
        reason = exempt_reason(text) if are_docs else None
        if reason is not None:
            exempt.append(f'{rel} (marker: {reason or "no reason given"})')
            continue
        files.append((rel, text))
    return Walk(files, exempt)


# `HEAD:./x` and `--relative` are the cwd-relative spellings. `tracked` lists
# from `--root`, so with a root inside a repo the repo-root-relative default
# looked every path up in the wrong place and read as a brand-new file.
def baseline(root: Path, rel: str, ref: str | None = None) -> str | None:
    ref = ref or 'HEAD'
    text = git(root, 'show', f'{ref}:./{rel}')
    if text is not None:
        return text.removeprefix(BOM)
    # -z here too, for the reason `tracked` gives: without it git quotes a
    # non-ASCII path as "src/caf\303\251.py", which never equals `rel`, so the
    # rename's baseline was lost. With -z: status, old, new, each NUL-terminated.
    status = git(root, 'diff', '--cached', '--find-renames', '--relative', '-z',
                 '--name-status', '--diff-filter=R', ref)
    fields = [f for f in (status or '').split('\0') if f]
    for i in range(0, len(fields) - 2, 3):
        if fields[i].startswith('R') and fields[i + 2] == rel:
            old = git(root, 'show', f'{ref}:./{fields[i + 1]}')
            return None if old is None else old.removeprefix(BOM)
    return None


# What `--base REF` is compared against: where the branch left REF, which is what
# a review sees, not REF's tip. A ref git cannot resolve is an error, as it is for
# `scan`; only in a shallow clone is it genuinely absent, so files read as new.
def base_rev(root: Path, ref: str | None) -> str | None:
    if not ref:
        return None
    if git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}') is None:
        if git(root, 'rev-parse', '--is-shallow-repository') == 'true\n':
            print(f'tahrir: --base {ref!r} is outside a shallow clone — '
                  'files are judged as new', file=sys.stderr)
            return None
        raise GitUnavailable(f'cannot resolve --base {ref!r} as a git ref')
    merged = (git(root, 'merge-base', ref, 'HEAD') or '').strip()
    return merged or ref


def package_of(rel: str, roots: list[str]) -> str | None:
    parts = rel.split('/')
    if len(parts) < 3 or not any(rel.startswith(root.rstrip('/') + '/') for root in roots):
        return None
    return '/'.join(parts[:2])


def doc_code_findings(
    root: Path,
    docs: list[Doc],
    counter: Counter,
    config: Config,
    already_read: dict[str, str] | None = None,
) -> list[Finding]:
    rule = config.rule('doc-code-ratio')
    if not rule.on or not config.package_roots:
        return []
    limit = rule.opts['ratio']
    floor = rule.opts['floor']
    # The one enumeration outside the corpus skip policy, on both halves of the
    # ratio: each is the size of a package, not a list of files to report on, so
    # a muted or exempt file counts and only `[exclude]` removes it. CONTEXT.md.

    # Enumerated rather than read off `docs`, which `corpus.walk` had already
    # stripped of muted and exempt docs — silencing the rule for exactly the
    # bloat a repo is most likely to have muted.
    measured = {doc.rel: doc.tokens for doc in docs}
    for path in tracked(root, config.doc_globs):
        rel = path.relative_to(root).as_posix()
        if rel in measured or config.is_excluded(rel):
            continue
        measured[rel] = analyze(
            rel, read_tracked(path), counter
        ).tokens
    doc_tokens: dict[str, int] = defaultdict(int)
    for rel, tokens in measured.items():
        package = package_of(rel, config.package_roots)
        if package:
            doc_tokens[package] += tokens

    # The caller's walk already read most of it, so go to disk only for the rest.
    read = already_read or {}
    code_tokens: dict[str, int] = defaultdict(int)
    for path in tracked(root, config.code_globs):
        rel = path.relative_to(root).as_posix()
        package = package_of(rel, config.package_roots)
        if package and not config.is_excluded(rel):
            text = read.get(rel)
            if text is None:
                text = read_tracked(path)
            code_tokens[package] += counter.count(text)
    out: list[Finding] = []
    for package, docs_n in sorted(doc_tokens.items()):
        code_n = code_tokens.get(package, 0)
        # `floor` is configurable down to 0, at which point a package with docs
        # and no code divides by zero instead of simply having no ratio.
        if code_n <= 0 or code_n < floor:
            continue
        ratio = docs_n / code_n
        if ratio > limit:
            out.append(
                Finding(package, 1, rule.id, rule.severity,
                        f'{docs_n} doc tokens vs {code_n} code tokens '
                        f'(ratio {ratio:.2f}, over {limit})',
                        'documentation-guide.md: a long doc propping up code that is '
                        'hard to follow means the code needs the work')
            )
    return out


def _blocks(doc: Doc) -> list[tuple[int, str]]:
    skip = {CODE, TABLE, HEADING, FRONT}
    out: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    for seg in doc.segments:
        if seg.kind in skip or seg.kind == BLANK:
            if current:
                out.append((start, ' '.join(current)))
                current = []
            continue
        if not current:
            start = seg.lineno
        current.append(seg.text.strip())
    if current:
        out.append((start, ' '.join(current)))
    return out


def _normalize(text: str) -> str:
    return ' '.join(PUNCT_RE.sub(' ', LINK_RE.sub(r'\1', text).lower()).split())


def duplicate_findings(
    docs: list[Doc], counter: Counter, config: Config
) -> tuple[list[Finding], dict[str, tuple[int, str]]]:
    rule = config.rule('cross-doc-duplicate')
    # Off for the corpus is not off for every file: an override can switch this
    # rule on for one subtree, and returning on the corpus-wide severity alone
    # meant the per-rel resolution below was never reached.
    if not rule.on and not any(config.rule(rule.id, doc.rel).on for doc in docs):
        return [], {}
    minimum = rule.opts['min_tokens']
    seen: dict[str, list[tuple[str, int]]] = defaultdict(list)
    # Counting is the expensive step on the exact path, and a duplicate block is
    # by definition counted more than once — twice per occurrence, before.
    sizes: dict[str, int] = {}
    for doc in docs:
        for lineno, raw in _blocks(doc):
            norm = _normalize(raw)
            if not norm:
                continue
            if norm not in sizes:
                sizes[norm] = counter.count(norm)
            if sizes[norm] >= minimum:
                seen[norm].append((doc.rel, lineno))
    out: list[Finding] = []
    worst: dict[str, tuple[int, str]] = {}
    for norm, places in seen.items():
        rels = {rel for rel, _ in places}
        if len(rels) < 2:
            continue
        size = sizes[norm]
        for rel, lineno in places:
            # Per rel, because the finding is about a file: resolving the
            # severity once for the whole corpus meant a per-glob override could
            # not reach this rule at all.
            local = config.rule('cross-doc-duplicate', rel)
            if not local.on:
                continue
            others = sorted(rels - {rel})
            out.append(
                Finding(rel, lineno, local.id, local.severity,
                        f'~{size} tok block also in {", ".join(others)}',
                        'documentation-guide.md: two docs stating the same rule — '
                        'link, do not copy')
            )
            if size > worst.get(rel, (0, ''))[0]:
                worst[rel] = (size, others[0])
    return out, worst


# A number is short, and is not the year of a date-named slug: `2024-01-15-a.md`
# is not ADR 2024, while `0001-x.md` is ADR 0001.
ADR_NUMBER_RE = re.compile(r'(?!(?:19|20)\d\d-\d{1,2}-)(\d{1,4})-')
UNRELEASED_RE = re.compile(
    r'^##\s+\[?v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\]?\s+[-\u2013\u2014]\s+Unreleased\s*$',
    re.IGNORECASE,
)


def _in_policy(config: Config, rel: str) -> bool:
    return not config.is_excluded(rel) and not config.rules_muted(rel)


# A pull request that adds a duplicate number touches the new file, not the old
# one, so a group is judged by whether any member is in scope.
def adr_findings(root: Path, config: Config, scope: Scope = WHOLE_REPO) -> list[Finding]:
    rule = config.rule('adr-number-collision')
    wanted = _scoped_names(root, scope) if scope.diff_aware else None

    def selected(*names: str) -> bool:
        return wanted is None or any(name in wanted for name in names)

    adr_glob = rule.opts['adr_glob']
    # A slug-named log globs `*.md`, which also takes the index and the template.
    not_adrs = {rule.opts['index'], posixpath.join(posixpath.dirname(rule.opts['index']), 'template.md')}
    # Git pre-selects with its own pathspec dialect, where `*` crosses a `/`; the
    # engine's matcher then decides, so a pattern means here what it means in
    # `[[overrides]]` and `[exclude]`.
    adrs = sorted(
        rel for rel in (p.relative_to(root).as_posix() for p in tracked(root, [adr_glob]))
        if rel not in not_adrs and glob_match(rel, adr_glob) and _in_policy(config, rel)
    )
    out: list[Finding] = []

    holders: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rel in adrs:
        folder, name = posixpath.split(rel)
        number = ADR_NUMBER_RE.match(name)
        if number:
            holders[(folder, number.group(1))].append(rel)
    for (_, number), files in sorted(holders.items()):
        local = config.rule(rule.id, files[0])
        if len(files) < 2 or not local.on or not selected(*files):
            continue
        out.append(
            Finding(files[0], 1, local.id, local.severity,
                    f'ADR number {number} is held by {len(files)} files: {", ".join(files)}',
                    'renumber the later one, and its index row and links with it')
        )
    return out + _adr_index_findings(root, config, adrs, selected)


def _adr_index_findings(
    root: Path,
    config: Config,
    adrs: list[str],
    selected: Callable[..., bool],
) -> list[Finding]:
    rule = config.rule('adr-number-collision')
    index = rule.opts['index']
    path = root / index if index else None
    if path is None or not path.is_file() or not _in_policy(config, index):
        return []
    folder = posixpath.dirname(index)
    adr_glob = rule.opts['adr_glob']
    linked: set[str] = set()
    out: list[Finding] = []
    local = config.rule(rule.id, index)
    for lineno, line in unfenced_lines(read_tracked(path)):
        for match in MD_LINK_RE.finditer(line):
            # An external link or a bare anchor is not a row, and joined onto the
            # folder it would read as a path a permissive `adr_glob` can match.
            if is_external(match.group(1)):
                continue
            link = match.group(1).split('#', 1)[0]
            target = posixpath.normpath(
                link.lstrip('/') if link.startswith('/') else posixpath.join(folder, link)
            )
            linked.add(target)
            if (
                local.on
                and glob_match(target, adr_glob)
                and not (root / target).is_file()
                and selected(index)
            ):
                out.append(
                    Finding(index, lineno, local.id, local.severity,
                            f'index row links {target} — no such file',
                            'fix the row, or drop it if the ADR was renumbered')
                )
    for rel in adrs:
        row = config.rule(rule.id, rel)
        if (
            posixpath.dirname(rel) == folder
            and rel not in linked
            and row.on
            and selected(rel, index)
        ):
            out.append(
                Finding(rel, 1, row.id, row.severity,
                        f'no row for this ADR in {index}',
                        'add the row, newest first')
            )
    return out


def _tag_template(rel: str, rule_opts: dict) -> str:
    for pattern, template in rule_opts['tag_patterns'].items():
        if glob_match(rel, pattern):
            return template
    return rule_opts['default_tag']


# `always_exempt` carries CHANGELOG.md, so `walk` never hands one over: this reads
# them itself, under every other part of the skip policy.
def changelog_findings(
    root: Path, config: Config, scope: Scope = WHOLE_REPO
) -> list[Finding]:
    try:
        return _changelog_findings(root, config, scope)
    except GitUnavailable:
        # The same answer the rest of the engine gives a root with no git: there
        # is nothing to compare a heading against, which is not a finding.
        return []


def _changelog_findings(root: Path, config: Config, scope: Scope) -> list[Finding]:
    headings: list[tuple[str, int, str]] = []
    for path in tracked(root, config.doc_globs, scope):
        rel = path.relative_to(root).as_posix()
        if path.name != 'CHANGELOG.md' or not _in_policy(config, rel):
            continue
        if not config.rule('changelog-unreleased-tagged', rel).on:
            continue
        for lineno, line in unfenced_lines(read_tracked(path)):
            match = UNRELEASED_RE.match(line)
            if match:
                headings.append((rel, lineno, match.group(1)))
    if not headings:
        return []
    listing = git(root, 'tag', '-l')
    tags = set((listing or '').split())
    if not tags:
        print('tahrir: no git tags are visible — changelog-unreleased-tagged cannot tell '
              'a released version from an unreleased one (a CI checkout needs '
              'fetch-tags: true)', file=sys.stderr)
        return []
    out: list[Finding] = []
    for rel, lineno, version in headings:
        rule = config.rule('changelog-unreleased-tagged', rel)
        tag = _tag_template(rel, rule.opts).format(version=version)
        if tag not in tags:
            continue
        stamped = git(root, 'log', '-1', '--format=%ad', '--date=short', f'refs/tags/{tag}', '--')
        date = (stamped or '').strip()
        out.append(
            Finding(rel, lineno, rule.id, rule.severity,
                    f'{version} is marked Unreleased but tag {tag} exists'
                    + (f' ({date})' if date else ''),
                    f'replace "Unreleased" with {date}' if date else 'date the heading')
        )
    return out
