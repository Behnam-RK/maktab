from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter as Tally
from pathlib import Path

from . import __version__, corpus, markdown, scanner
from .analyzers import findings_for as analyze_code
from .config import (
    FAIL, RULE_DEFAULTS, WARN, Config, ConfigError, find_config, load as load_config,
)
from .corpus import GitUnavailable
from .findings import Finding
from .rules import findings_for as markdown_findings_for
from .scaffold import DEFAULT_ADR_DIR, init_repo
from .tokens import Counter, ExactCountUnavailable, resolve as resolve_counter


ROOT_ENV = ('DOCS_ROOT', 'DOC_BUDGET_ROOT')

# Findings whose subject is a whole document, package or repository. Their line
# is always 1, so printing it is noise — but the test has to be the rule, not
# the line, because a docstring on a symbol defined at line 1 is a real location.
WHOLE_SUBJECT_RULES = (
    'over-hard-cap', 'over-soft-cap', 'wall-of-text', 'over-fragmented',
    'doc-code-ratio', 'changed-without-docs',
)


def _default_root() -> Path:
    for name in ROOT_ENV:
        value = os.environ.get(name)
        if value:
            return Path(value).resolve()
    return Path.cwd().resolve()


def _collect(walked: corpus.Walk, counter: Counter) -> list[markdown.Doc]:
    return [markdown.analyze(rel, text, counter) for rel, text in walked.files]


def _baseline_tokens(root: Path, rel: str, counter: Counter, ref: str | None) -> int | None:
    previous = corpus.baseline(root, rel, ref)
    return None if previous is None else markdown.analyze(rel, previous, counter).tokens


# A scoped run reports on its files but indexes the whole corpus: a block copied
# from an unchecked doc is still a duplicate. Walked only when the rule is on.
def _duplicates(
    root: Path, docs: list[markdown.Doc], config: Config, counter: Counter,
    scope: corpus.Scope,
) -> tuple[list[Finding], dict[str, tuple[int, str]]]:
    if not scope.diff_aware or not any(
        config.rule('cross-doc-duplicate', d.rel).on for d in docs
    ):
        return corpus.duplicate_findings(docs, counter, config)
    everything = _collect(corpus.walk(root, config.doc_globs, config), counter)
    found, worst = corpus.duplicate_findings(everything, counter, config)
    scoped = {d.rel for d in docs}
    return [f for f in found if f.rel in scoped], worst


def _markdown_findings(
    root: Path,
    docs: list[markdown.Doc],
    config: Config,
    counter: Counter,
    scope: corpus.Scope,
    code: list[tuple[str, str]],
    ref: str | None,
) -> list[Finding]:
    dupes, worst = _duplicates(root, docs, config, counter, scope)
    out: list[Finding] = []
    for doc in docs:
        size, other = worst.get(doc.rel, (0, ''))
        base = _baseline_tokens(root, doc.rel, counter, ref) if scope.diff_aware else None
        out += markdown_findings_for(doc, config, counter.grace, size, other, base)
    out += dupes
    if not scope.diff_aware:
        out += corpus.doc_code_findings(root, docs, counter, config, dict(code))
    return out


def _code_findings(
    root: Path, config: Config, scope: corpus.Scope, code: list[tuple[str, str]],
    ref: str | None,
) -> list[Finding]:
    out: list[Finding] = []
    for rel, source in code:
        base = corpus.baseline(root, rel, ref) if scope.diff_aware else None
        out += analyze_code(rel, source, base, config)
    return out


# The docs and the code the caller already walked, not a third walk of its own:
# every file the scanner wants has been enumerated and read twice by the time it
# runs, under the same skip policy it would have applied itself.
def _scanner_findings(
    root: Path,
    config: Config,
    base_ref: str | None,
    docs: list[tuple[str, str]],
    code: list[tuple[str, str]],
) -> list[Finding]:
    out: list[Finding] = []
    seen: set[str] = set()
    # One listing for the run, and only when a repo asked for it.
    suffixes = (
        scanner.suffix_index(root)
        if config.rules['stale-file-ref'].opts['resolve_by_suffix']
        else None
    )
    # Which list a file arrived in is what makes it a doc — the doc walk first,
    # so a file both glob lists enumerate is judged as one.
    for rel, text, is_doc in [*((r, x, True) for r, x in docs),
                              *((r, x, False) for r, x in code)]:
        if rel in seen:
            continue
        seen.add(rel)
        out += scanner.todo_markers(rel, text, config, prose=is_doc)
        out += scanner.section_citations(root, rel, text, config)
        if is_doc:
            out += scanner.open_checkboxes(rel, text, config)
            # Documents only: a backticked path in prose claims the file
            # exists, while the same characters in source are fixture data or
            # an example, which this suite alone builds a dozen of.
            out += scanner.stale_file_refs(root, rel, text, config, suffixes)
    out += scanner.changed_without_docs(root, base_ref, config)
    return out


def _analyze(
    root: Path,
    config: Config,
    counter: Counter,
    scope: corpus.Scope,
    base_ref: str | None = None,
) -> tuple[list[Finding], list[markdown.Doc], list[str]]:
    # Two walks, and every consumer is handed one of them: the doc-code ratio
    # needs the same files the analyzers do, and the scanner wants both — all
    # under the one skip policy `walk` applies.
    walked = corpus.walk(root, config.doc_globs, config, scope)
    walked_code = corpus.walk(root, config.code_globs, config, scope, are_docs=False)
    code = walked_code.files
    docs = _collect(walked, counter)
    # Both walks' exemptions, not just the doc walk's: `always_exempt` matches
    # code as well, and dropping that half of the list meant a file the gate had
    # skipped appeared nowhere at all — neither measured nor accounted for.
    listed = set(walked.exempt)
    exempt = walked.exempt + [e for e in walked_code.exempt if e not in listed]
    # The baseline a scoped run compares against: HEAD unless `--base` says
    # otherwise, resolved once rather than once per file.
    ref = corpus.base_rev(root, base_ref) if scope.diff_aware else None
    findings = _markdown_findings(root, docs, config, counter, scope, code, ref)
    findings += _code_findings(root, config, scope, code, ref)
    findings += _scanner_findings(root, config, base_ref, walked.files, code)
    findings += corpus.adr_findings(root, config, scope)
    findings += corpus.changelog_findings(root, config, scope)
    findings.sort(key=lambda f: (f.severity != FAIL, f.rel, f.line))
    return findings, docs, exempt


# One answer for both severities: a whole-document rule carries no useful line
# whether it failed or warned, and only the FAIL branch used to know that.
def _where(finding: Finding) -> str:
    if finding.rule in WHOLE_SUBJECT_RULES:
        return finding.rel
    return f'{finding.rel}:{finding.line}'


def _render(
    findings: list[Finding],
    exempt: list[str],
    counter: Counter,
    docs: list[markdown.Doc],
    verbose: bool,
    scoped: bool,
):
    failures = [f for f in findings if f.severity == FAIL]
    warnings = [f for f in findings if f.severity == WARN]
    print(f'doc budget — counter: {counter.name}, weighted (code & tables x0.4)')
    if not counter.exact:
        print(f'  counts are ESTIMATED (tiktoken unavailable) — caps relaxed {counter.grace:g}x')
    sys.stdout.flush()

    for finding in failures:
        print(f'\nFAIL  {_where(finding)}', file=sys.stderr)
        print(f'      {finding.message}', file=sys.stderr)
        if finding.hint:
            print(f'      -> {finding.hint}', file=sys.stderr)
    # Failures go to stderr and warnings to stdout, so without a flush between
    # them a terminal shows the two blocks interleaved in an arbitrary order.
    sys.stderr.flush()

    if scoped or verbose:
        for finding in warnings:
            hint = f'  -> {finding.hint}' if finding.hint else ''
            print(f'WARN  {_where(finding)}  {finding.message}{hint}')
    elif warnings:
        tally = Tally(f.rule for f in warnings)
        print(f'  {len(docs)} docs, {len(exempt)} exempt')
        for rule, count in tally.most_common():
            print(f'  {count:>4}  {rule}')
        print('  tahrir check --verbose  to list them')

    if failures:
        sys.stdout.flush()
        print(f'\n{len(failures)} failure(s), {len(warnings)} warning(s).', file=sys.stderr)
    else:
        print(f'\n0 failures, {len(warnings)} warnings, {len(exempt)} exempt.')


def _as_json(
    findings: list[Finding], docs: list[markdown.Doc], exempt: list[str],
    counter: Counter, config: Config,
) -> str:
    readme_soft, readme_hard = config.caps_for('README.md')
    return json.dumps({
        'counter': counter.name,
        'exact': counter.exact,
        'caps': {'soft': config.soft, 'hard': config.hard,
                 'readme_soft': readme_soft, 'readme_hard': readme_hard},
        'exempt': exempt,
        'docs': [{'rel': d.rel, 'tokens': d.tokens, 'lines': d.lines,
                  'sections': len(d.sections)} for d in docs],
        'findings': [f._asdict() for f in findings],
    }, indent=2)


# From a subdirectory the config sits above the working directory, and a root
# without it measures nothing while printing "0 failures". Returns the root and
# where a relative file argument starts.
def _locate_root(explicit: Path | None) -> tuple[Path, Path]:
    if explicit is not None or any(os.environ.get(name) for name in ROOT_ENV):
        root = explicit.resolve() if explicit else _default_root()
        return root, root
    # No answer given: the nearest `.docs.toml` up to the repo's top, else here.
    here = Path.cwd().resolve()
    try:
        top = corpus.git(here, 'rev-parse', '--show-toplevel')
    except GitUnavailable:
        return here, here
    ceiling = Path(top.strip()).resolve() if top and top.strip() else here
    for candidate in (here, *here.parents):
        if find_config(candidate) is not None:
            return candidate, here
        if candidate == ceiling:
            break
    return here, here


def _resolve_scope(anchor: Path, files: list[Path]) -> corpus.Scope:
    return corpus.Scope(tuple(p if p.is_absolute() else anchor / p for p in files))


# A file the run cannot measure used to vanish from it without a word, and an
# empty result reads as a pass. Not an error: a hook hands over staged deletions.
def _unmeasured(root: Path, scope: corpus.Scope, typed: list[Path]) -> list[str]:
    names: dict[str, Path] = {}
    out: list[str] = []
    for path, arg in zip(scope.files, typed):
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            out.append(f'{arg}: outside the root {root} — not measured')
            continue
        if path.is_dir():
            out.append(f'{arg}: is a directory — name the files')
        elif not path.exists():
            out.append(f'{arg}: no such file')
        else:
            names[rel] = arg
    listed = corpus.git(root, 'ls-files', '-z', '--', *names) if names else ''
    tracked = set((listed or '').split('\0'))
    if listed is not None:
        out += [f'{arg}: not tracked by git — not measured'
                for rel, arg in names.items() if rel not in tracked]
    return out


def _run(args, scan: bool) -> int:
    root, anchor = _locate_root(args.root)
    try:
        config = load_config(root, args.config, args.profile)
    except ConfigError as exc:
        print(f'tahrir: {exc}', file=sys.stderr)
        return 2
    if scan:
        config = config.for_scan()

    scope = _resolve_scope(anchor, args.files)
    try:
        counter = resolve_counter(require_exact=args.require_exact)
    except ExactCountUnavailable as exc:
        print(f'tahrir: exact token counts required but unavailable — {exc}', file=sys.stderr)
        return 2

    try:
        findings, docs, exempt = _analyze(
            root, config, counter, scope, args.base
        )
    except GitUnavailable as exc:
        print(f'tahrir: {exc}', file=sys.stderr)
        return 2
    failures = [f for f in findings if f.severity == FAIL]
    if scope.diff_aware:
        for problem in _unmeasured(root, scope, args.files):
            print(f'tahrir: {problem}', file=sys.stderr)

    if args.as_json:
        print(_as_json(findings, docs, exempt, counter, config))
    else:
        _render(findings, exempt, counter, docs, args.verbose, scope.diff_aware)
    return 0 if scan else (1 if failures else 0)


def _explain(rule_id: str) -> int:
    if rule_id not in RULE_DEFAULTS:
        print(f'tahrir: unknown rule {rule_id!r}', file=sys.stderr)
        print('known rules: ' + ', '.join(sorted(RULE_DEFAULTS)), file=sys.stderr)
        return 2
    defaults = dict(RULE_DEFAULTS[rule_id])
    severity = defaults.pop('severity')
    # Not .get(): a rule with no help used to print a blank line, and the table
    # that held the prose lived in a different module from the one validated
    # against, so nothing could notice.
    print(f'{rule_id}  (default severity: {severity})')
    print(f'  {defaults.pop("help")}')
    if defaults:
        print('  knobs: ' + ', '.join(f'{k} = {v!r}' for k, v in defaults.items()))
    print(f'\n  to change it in .docs.toml:\n  [rules.{rule_id}]')
    print(f'  severity = "{severity}"   # fail | warn | off')
    return 0


def _add_analysis_args(parser: argparse.ArgumentParser):
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--json', action='store_true', dest='as_json')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--root', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--profile')
    parser.add_argument(
        '--base', metavar='REF',
        help='git ref to compare against: with files, the baseline a pre-existing '
             'violation is judged by (default HEAD, so a staged change is measured '
             'against the commit it will land on); also what changed-without-docs diffs',
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='tahrir', description='Documentation budget gate')
    # Without this there is no way to tell a stale install from a stale pin, and
    # `tahrir init` hands adopters a pin derived from this very number.
    parser.add_argument('--version', action='version', version=f'tahrir {__version__}')
    parser.add_argument('--explain', metavar='RULE')
    sub = parser.add_subparsers(dest='command')

    # The two commands take different flags, and `_run` serves both. Declaring
    # each command's absent flag as a default keeps the namespace one shape,
    # rather than having the caller guess with getattr.
    check = sub.add_parser('check', help='blocking gate; exit 1 on failure')
    _add_analysis_args(check)
    check.add_argument('--require-exact', action='store_true')

    scan = sub.add_parser('scan', help='advisory report; no finding blocks')
    _add_analysis_args(scan)
    scan.set_defaults(require_exact=False)

    init = sub.add_parser('init', help='scaffold config and convention docs')
    init.add_argument('--root', type=Path)
    init.add_argument('--profile', default='default')
    init.add_argument('--lang', help='comma-separated; default: detected')
    init.add_argument('--force', action='store_true')
    init.add_argument('--no-docs', action='store_true', help='--no-guide and --no-adr')
    init.add_argument('--no-guide', action='store_true')
    init.add_argument('--no-adr', action='store_true',
                      help='keep an existing decision log; write no ADR templates')
    init.add_argument('--adr-dir', help=f"default: the kept config's, else {DEFAULT_ADR_DIR}")
    init.add_argument('--exclude', action='append', metavar='GLOB')
    init.add_argument('--doc-gate', action=argparse.BooleanOptionalAction)
    init.add_argument('--routing-doc', metavar='PATH')
    init.add_argument('--check', action='store_true', dest='drift_check')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.explain:
        return _explain(args.explain)
    if args.command == 'init':
        return init_repo(
            (args.root.resolve() if args.root else _default_root()),
            profile=args.profile,
            lang=args.lang,
            force=args.force,
            write_guide=not (args.no_docs or args.no_guide),
            write_adr=not (args.no_docs or args.no_adr),
            drift_check=args.drift_check,
            exclude=args.exclude,
            doc_gate=args.doc_gate,
            routing_doc=args.routing_doc,
            adr_dir=args.adr_dir,
        )
    if args.command == 'scan':
        return _run(args, scan=True)
    if args.command == 'check':
        return _run(args, scan=False)
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
