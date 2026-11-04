from __future__ import annotations

import ast
import io
import tokenize

from ..config import WARN, Config, decorator_matches
from ..findings import Finding
from ..markdown import split_lines
from .blocks import comment_block_findings


MODULE_SCOPE = '<module>'

# PEP 723 inline metadata: uv reads it, so it is config in comment syntax.
PEP723_OPEN, PEP723_CLOSE = '# /// script', '# ///'

Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _dotted(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    parts: list[str] = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return '.'.join(reversed(parts))


def _is_runtime_surfaced(node: Definition, patterns: list[str]) -> bool:
    return any(
        decorator_matches(_dotted(d), pattern)
        for d in node.decorator_list
        for pattern in patterns
    )


def _module_doc_is_cli_help(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.Name) and n.id == '__doc__' for n in ast.walk(tree))


# Keyed by name and line: a property's getter and setter share a name, and a
# dict on the name alone kept whichever came last.
def _docstrings(tree: ast.Module) -> dict[tuple[str, int], str]:
    found: dict[tuple[str, int], str] = {}
    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc is not None:
        found[MODULE_SCOPE, tree.body[0].lineno] = module_doc

    def visit(node: ast.AST, prefix: str):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, Definition):
                qname = f'{prefix}.{child.name}' if prefix else child.name
                doc = ast.get_docstring(child, clean=False)
                if doc is not None:
                    found[qname, child.lineno] = doc
                visit(child, qname)
            else:
                visit(child, prefix)

    visit(tree, '')
    return found


def _exempt_qnames(tree: ast.Module, patterns: list[str]) -> set[tuple[str, int]]:
    exempt: set[tuple[str, int]] = set()

    def visit(node: ast.AST, prefix: str, inherited: bool):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, Definition):
                qname = f'{prefix}.{child.name}' if prefix else child.name
                own = _is_runtime_surfaced(child, patterns)
                if inherited or own:
                    exempt.add((qname, child.lineno))
                visit(child, qname, isinstance(child, ast.ClassDef) and (own or inherited))
            else:
                visit(child, prefix, inherited)

    visit(tree, '', False)
    return exempt


def _script_metadata_lines(source: str) -> set[int]:
    lines = split_lines(source)
    try:
        opened = next(i for i, ln in enumerate(lines, 1) if ln.rstrip() == PEP723_OPEN)
        closed = next(
            i for i, ln in enumerate(lines, 1) if i > opened and ln.rstrip() == PEP723_CLOSE
        )
    except StopIteration:
        return set()
    return set(range(opened, closed + 1))


def comment_runs(source: str, cap: int) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    metadata = _script_metadata_lines(source)
    start = 0
    length = 0
    previous = 0
    try:
        stream = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in stream:
            if tok.type != tokenize.COMMENT:
                continue
            line = tok.start[0]
            if line in metadata:
                continue
            # Own-line only: a trailing `x = 1  # why` is not a comment block, and
            # tokenize already excludes `#` inside strings.
            own_line = tok.line.lstrip()
            shebang = line == 1 and own_line.startswith('#!')
            if own_line.startswith('#') and not shebang:
                if length and line == previous + 1:
                    length += 1
                else:
                    if length > cap:
                        runs.append((start, length))
                    start, length = line, 1
                previous = line
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Nothing, not the partial runs found before the error. A file that does
        # not parse cannot be judged, and `_docstring_findings` already says so
        # by returning [] — two policies on one broken file is worse than either.
        return []
    if length > cap:
        runs.append((start, length))
    return runs


def _docstring_findings(
    rel: str, source: str, baseline: str | None, config: Config
) -> list[Finding]:
    rule = config.rule('docstring', rel)
    if not rule.on:
        return []
    try:
        tree = ast.parse(source, filename=rel)
    except SyntaxError:
        return []

    old_names: set[str] = set()
    old_texts: set[str] = set()
    if baseline is not None:
        try:
            previous = _docstrings(ast.parse(baseline, filename=rel))
        except SyntaxError:
            previous = {}
        old_names = {qname for qname, _ in previous}
        old_texts = set(previous.values())

    strict = baseline is None
    exempt = _exempt_qnames(tree, config.runtime_surfaced)
    out: list[Finding] = []
    for (qname, line), doc in _docstrings(tree).items():
        if (qname, line) in exempt:
            continue
        allowed = config.module_docstring_cap if qname == MODULE_SCOPE else config.docstring_cap
        if allowed and len(doc.splitlines()) <= allowed:
            continue
        if qname == MODULE_SCOPE:
            if config.cli_help_exempts_module and _module_doc_is_cli_help(tree):
                continue
            message = 'module docstring present — delete (not runtime-surfaced)'
        else:
            message = f'{qname} has a docstring — not runtime-surfaced, delete'
        # Text as well as qualified name: renaming a function (or its parent
        # class) must not turn a year-old docstring into a new violation.
        demoted = not strict and (qname in old_names or doc in old_texts)
        severity = WARN if demoted else rule.severity
        out.append(
            Finding(rel, line, rule.id, severity,
                    message + (' (pre-existing)' if demoted else ''))
        )
    return out


def findings_for(
    rel: str, source: str, baseline: str | None, config: Config
) -> list[Finding]:
    # The kill switch lives here, mirroring `comments_enabled`, so the dispatch
    # does not have to know that one analyzer has one.
    if not config.python_enabled:
        return []
    out = _docstring_findings(rel, source, baseline, config)
    rule = config.rule('comment-block', rel)
    if rule.on:
        out += comment_block_findings(rel, rule, comment_runs(source, rule.opts['max_lines']))
    return out
