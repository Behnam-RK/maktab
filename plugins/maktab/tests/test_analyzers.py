from __future__ import annotations

from textwrap import dedent


from docsteward.analyzers import comments, findings_for, python
from docsteward.config import FAIL, OFF, WARN, Config


def strict(**python_opts):
    return Config({'profile': 'strict', 'python': python_opts})


def check(source, config=None, baseline=None, rel='pkg/mod.py'):
    return findings_for(rel, dedent(source), baseline, config or strict())


def names(found):
    return [f.message.split(' ')[0] for f in found]


# --- docstrings ---------------------------------------------------------------


def test_docstrings_are_off_by_default():
    assert check('def f():\n    """Doc."""\n', Config()) == []


def test_docstring_fails_under_strict():
    [finding] = check('''
        def f():
            """Doc."""
    ''')
    assert finding.rule == 'docstring'
    assert finding.severity == FAIL
    assert finding.line == 2  # the `def` line; dedent keeps the leading newline
    assert finding.message == 'f has a docstring — not runtime-surfaced, delete'


def test_nested_names_are_qualified():
    found = check('''
        class A:
            """A."""
            def m(self):
                """M."""
                def inner():
                    """I."""
    ''')
    assert names(found) == ['A', 'A.m', 'A.m.inner']


def test_module_docstring():
    [finding] = check('"""Module."""\nx = 1\n')
    assert finding.line == 1
    assert finding.message.startswith('module docstring present')


def test_module_docstring_used_as_cli_help_is_exempt():
    source = '"""Usage: tool [opts]"""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n'
    assert check(source) == []
    assert len(check(source, strict(cli_help_exempts_module=False))) == 1


def test_module_docstring_is_reported_on_its_own_line():
    [finding] = check('# header\n\n"""Doc."""\n')
    assert (finding.rel, finding.line) == ('pkg/mod.py', 3)


def test_a_property_getter_and_setter_each_keep_their_docstring():
    found = check('''
        class A:
            @property
            def x(self):
                """Get."""

            @x.setter
            def x(self, value):
                """Set."""
    ''')
    assert [(f.line, f.message.split(' ')[0]) for f in found] == [(4, 'A.x'), (8, 'A.x')]


def test_a_surfaced_setter_does_not_exempt_the_getter():
    source = '''
        class A:
            @property
            def x(self):
                """Get."""

            @x.setter
            def x(self, value):
                """Set."""
    '''
    found = check(source, strict(runtime_surfaced_decorators=['*.setter']))
    assert [f.line for f in found] == [4]


def test_docstring_cap_allows_short_docstrings():
    source = '''
        def short():
            """One line."""

        def long():
            """One.

            Two.
            """
    '''
    assert names(check(source, strict(docstring_cap=1))) == ['long']


def test_module_docstring_cap_is_separate():
    source = '"""One.\nTwo."""\n\ndef f():\n    """Doc."""\n'
    found = check(source, strict(module_docstring_cap=2))
    assert names(found) == ['f']


def test_runtime_surfaced_decorators_exempt():
    source = '''
        import strawberry

        @strawberry.type
        class Query:
            """Shown in the schema."""
            def field(self):
                """Inherited from the class."""

        @mcp.tool()
        def run():
            """Shown to the model."""
            def helper():
                """Not inherited through a function."""

        def plain():
            """Not surfaced."""
    '''
    found = check(source, strict(runtime_surfaced_decorators=['strawberry', '*.tool']))
    assert names(found) == ['run.helper', 'plain']


def test_decorators_with_no_dotted_name_surface_nothing():
    source = '''
        @make()()
        def called():
            """Decorated by a call of a call."""

        @table[0]
        def indexed():
            """Decorated by a subscript."""

        @mcp.tool
        def run():
            """Shown to the model."""
    '''
    found = check(source, strict(runtime_surfaced_decorators=['make', 'table', '*.tool']))
    assert names(found) == ['called', 'indexed']


def test_baseline_demotes_pre_existing_docstrings():
    old = 'def f():\n    """Old."""\n'
    new = 'def f():\n    """Old."""\n\ndef g():\n    """New."""\n'
    found = check(new, baseline=old)
    assert [(f.message.split(' ')[0], f.severity) for f in found] == [('f', WARN), ('g', FAIL)]
    assert found[0].message.endswith('(pre-existing)')


def test_an_unparseable_baseline_judges_every_docstring_as_new():
    found = check('def f():\n    """Old."""\n', baseline='def f(:\n    """Old."""\n')
    assert [(f.message.split(' ')[0], f.severity) for f in found] == [('f', FAIL)]
    assert not found[0].message.endswith('(pre-existing)')


def test_baseline_follows_a_renamed_function_by_text():
    found = check('def renamed():\n    """Old."""\n', baseline='def f():\n    """Old."""\n')
    assert [f.severity for f in found] == [WARN]


def test_unparseable_python_is_skipped():
    assert check('def f(:\n    """Doc."""\n') == []


def test_python_disabled():
    assert check('def f():\n    """Doc."""\n# a\n# b\n# c\n# d\n', strict(enabled=False)) == []


# --- python comment blocks ----------------------------------------------------


def block(n, indent=''):
    return ''.join(f'{indent}# line {i}\n' for i in range(n))


def test_python_comment_block_over_the_cap():
    [finding] = check('x = 1\n' + block(4), Config())
    assert finding.rule == 'comment-block'
    assert finding.severity == WARN
    assert finding.line == 2
    assert finding.message == 'comment block of 4 lines (advisory cap 3)'


def test_python_comment_block_at_the_cap_is_clean():
    assert check(block(3), Config()) == []


def test_trailing_comments_do_not_join_a_block():
    source = '# a\n# b\nx = 1  # c\ny = 2  # d\n# e\n'
    assert check(source, Config()) == []


def test_hash_inside_a_string_is_not_a_comment():
    source = 's = """\n# a\n# b\n# c\n# d\n"""\n'
    assert check(source, Config()) == []


def test_pep723_metadata_is_not_a_comment_block():
    source = '# /// script\n# requires-python = ">=3.12"\n# dependencies = []\n# ///\n# one\n'
    assert check(source, Config()) == []


def test_python_shebang_is_not_part_of_a_block():
    assert check('#!/usr/bin/env python\n' + block(3), Config()) == []


def test_every_over_cap_python_block_is_reported():
    source = block(4) + 'x = 1\n' + block(5) + 'y = 2\n' + block(3)
    found = check(source, Config())
    assert [(f.line, f.message) for f in found] == [
        (1, 'comment block of 4 lines (advisory cap 3)'),
        (6, 'comment block of 5 lines (advisory cap 3)'),
    ]


def test_comment_block_max_lines_knob():
    cfg = Config({'rules': {'comment-block': {'max_lines': 1}}})
    assert len(check('# a\n# b\n', cfg)) == 1


def test_comment_block_off():
    cfg = Config({'rules': {'comment-block': {'severity': OFF}}})
    assert check(block(10), cfg) == []


def test_python_comment_runs_on_broken_source_is_empty():
    assert python.comment_runs('# a\n# b\n# c\n# d\ndef f(:\n  """\n', 3) == []


# --- other languages ----------------------------------------------------------


def test_slash_comment_block():
    source = 'x();\n' + ''.join(f'// {i}\n' for i in range(5))
    [finding] = findings_for('src/a.ts', source, None, Config())
    assert (finding.line, finding.message) == (2, 'comment block of 5 lines (advisory cap 3)')


def test_jsdoc_block_is_skipped():
    source = '/**\n * one\n * two\n * three\n * four\n */\nfunction f() {}\n'
    assert findings_for('src/a.js', source, None, Config()) == []


def test_runs_split_by_code():
    assert comments.comment_runs('# a\n# b\nx\n# c\n# d\n', '#', 3) == []
    assert comments.comment_runs('# a\n# b\n# c\n# d\nx\n# e\n', '#', 3) == [(1, 4)]


def test_shebang_only_counts_on_line_one():
    assert comments.comment_runs('#!/bin/sh\n# a\n# b\n# c\n', '#', 3) == []
    assert comments.comment_runs('# a\n# b\n#!x\n# c\n', '#', 3) == [(1, 4)]


def test_heredoc_body_is_not_a_comment_block():
    source = 'cat <<EOF\n# a\n# b\n# c\n# d\nEOF\necho hi\n'
    assert findings_for('run.sh', source, None, Config()) == []


def test_comment_mentioning_a_heredoc_does_not_open_one():
    source = '# write it with cat <<EOF\n# a\n# b\n# c\n# d\n'
    assert comments.comment_runs(source, '#', 3) == [(1, 5)]


def test_ruby_and_shell_squiggly_heredoc_is_a_heredoc():
    source = 'cat <<~EOF\n  # a\n  # b\n  # c\n  # d\n  EOF\necho hi\n'
    assert comments.comment_runs(source, '#', 3) == []


def test_comment_run_lines_ignore_exotic_line_breaks():
    source = 'x = "a\u2028b"  # note\n# a\n# b\n# c\n# d\n'
    assert comments.comment_runs(source, '#', 3) == [(2, 4)]


def test_unknown_suffix_and_custom_prefix():
    source = ''.join(f'% {i}\n' for i in range(5))
    assert findings_for('notes.tex', source, None, Config()) == []
    cfg = Config({'comments': {'prefixes': {'.tex': '%'}}})
    assert len(findings_for('notes.tex', source, None, cfg)) == 1


def test_comments_disabled():
    cfg = Config({'comments': {'enabled': False}})
    assert findings_for('a.sh', block(10), None, cfg) == []


def test_dotted_directory_without_a_suffix():
    assert findings_for('.github/workflows/release', block(10), None, Config()) == []


def test_trailing_comment_mentioning_a_heredoc_does_not_open_one():
    source = 'x=1  # feed it via <<EOF\n' + '# c\n' * 5 + 'y=2\n'
    assert comments.comment_runs(source, '#', 3) == [(2, 5)]


def test_heredoc_with_a_trailing_comment_still_opens():
    source = 'cat <<EOF  # here\n# a\n# b\n# c\n# d\nEOF\n'
    assert comments.comment_runs(source, '#', 3) == []


def test_here_string_is_not_a_heredoc():
    source = 'grep x <<< foo\n' + '# c\n' * 5
    assert comments.comment_runs(source, '#', 3) == [(2, 5)]


def test_tab_separated_trailing_comment_does_not_open_a_heredoc():
    source = 'x=1\t# feed <<EOF\n' + '# c\n' * 5
    assert comments.comment_runs(source, '#', 3) == [(2, 5)]


def test_quoted_hash_before_a_heredoc_still_opens_it():
    source = "sed -e 's/ #.*//' <<'EOF'\n" + '# body\n' * 6 + 'EOF\n'
    assert comments.comment_runs(source, '#', 3) == []


def test_heredoc_operator_inside_a_quoted_span_opens_nothing():
    for line in ("X='<<FILL'", 'X="<<FILL"', "printf '... value: <<FILL: nope>>\\n' >f"):
        source = line + '\n' + '# c\n' * 4 + 'y=2\n'
        assert comments.comment_runs(source, '#', 3) == [(2, 4)], line


def test_shift_in_arithmetic_is_not_a_heredoc():
    for line in ('n=$((1<<N))', 'n=$(( (1<<N) + 1 ))', '(( n = 1<<N ))'):
        source = line + '\n' + '# c\n' * 4 + 'y=2\n'
        assert comments.comment_runs(source, '#', 3) == [(2, 4)], line


def test_heredoc_after_arithmetic_or_quotes_still_opens():
    source = "n=$((1<<N)) && cat <<'EOF'\n" + '# body\n' * 5 + 'EOF\n'
    assert comments.comment_runs(source, '#', 3) == []
    source = "echo '<<A' <<B\n" + '# body\n' * 5 + 'B\n'
    assert comments.comment_runs(source, '#', 3) == []


def test_heredoc_without_a_terminator_does_not_swallow_the_file():
    source = 'cat <<NOPE\n' + '# c\n' * 4 + 'y=2\n'
    assert comments.comment_runs(source, '#', 3) == [(2, 4)]
