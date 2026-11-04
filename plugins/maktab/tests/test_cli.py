from __future__ import annotations

import json
import runpy
import sys
import warnings

import pytest
from helpers import commit, git, repo, write

from docsteward import cli
from docsteward.cli import main
from docsteward.tokens import Counter


DOCSTRING = 'def f():\n    """Doc."""\n'


@pytest.fixture(autouse=True)
def estimate(monkeypatch, tmp_path):
    monkeypatch.setenv('DOCS_COUNTER', 'estimate')
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR', str(tmp_path / 'tiktoken'))
    for name in ('DOCS_ROOT', 'DOC_BUDGET_ROOT'):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clean(tmp_path):
    return repo(tmp_path, {'README.md': '# Project\n\nShort.\n', 'app.py': 'x = 1\n'})


def run(root, *args):
    return main([*args, '--root', str(root)])


def report(capsys):
    return json.loads(capsys.readouterr().out)


def repo_add(root):
    git(root, 'add', '-A')


# --- check --------------------------------------------------------------------


def test_check_clean_repo(clean, capsys):
    assert run(clean, 'check') == 0
    out = capsys.readouterr().out
    assert '0 failures' in out
    assert 'ESTIMATED' in out


def test_check_fails_on_a_docstring_under_strict(clean, capsys):
    write(clean, {'app.py': DOCSTRING})
    assert run(clean, 'check', '--profile', 'strict') == 1
    err = capsys.readouterr().err
    assert 'FAIL  app.py:1' in err
    assert '1 failure(s)' in err


def test_check_fails_on_the_hard_cap(clean, capsys):
    write(clean, {
        '.docs.toml': '[defaults]\nsoft = 5\nhard = 10\n',
        'docs/big.md': '# Big\n\n' + 'word ' * 20 + '\n',
    })
    repo_add(clean)
    assert run(clean, 'check') == 1
    assert 'FAIL  docs/big.md\n' in capsys.readouterr().err


def test_check_warnings_alone_exit_0(clean, capsys):
    write(clean, {'docs/long.md': '# Long\n\n' + 'word ' * 30 + '\n'})
    repo_add(clean)
    assert run(clean, 'check') == 0
    out = capsys.readouterr().out
    assert 'prose-line-long' in out
    assert '--verbose' in out


def test_check_verbose_lists_warnings(clean, capsys):
    write(clean, {'docs/long.md': '# Long\n\n' + 'word ' * 30 + '\n'})
    repo_add(clean)
    assert run(clean, 'check', '--verbose') == 0
    assert 'WARN  docs/long.md:3' in capsys.readouterr().out


def test_check_untracked_files_are_not_measured(clean, capsys):
    write(clean, {'app.py': 'x = 1\n', 'new.py': DOCSTRING})
    assert run(clean, 'check', '--profile', 'strict') == 0


def test_check_scoped_to_files(clean, capsys):
    write(clean, {'other.py': DOCSTRING})
    repo_add(clean)
    assert run(clean, 'check', '--profile', 'strict', 'app.py') == 0
    assert run(clean, 'check', '--profile', 'strict', 'other.py') == 1


BIG = {'.docs.toml': '[defaults]\nsoft = 5\nhard = 10\n', 'docs/big.md': '# Big\n\n' + 'word ' * 20 + '\n'}


def test_scoped_check_against_head_demotes_a_committed_oversize(clean, capsys):
    commit(clean, BIG)
    assert run(clean, 'check') == 1
    assert run(clean, 'check', 'docs/big.md') == 0
    assert 'pre-existing' in capsys.readouterr().out


def test_scoped_check_base_fails_a_doc_that_grew_past_the_cap(clean, capsys):
    before = git(clean, 'rev-parse', 'HEAD').strip()
    commit(clean, BIG)
    assert run(clean, 'check', 'docs/big.md', '--base', before) == 1
    assert 'FAIL  docs/big.md' in capsys.readouterr().err


def test_scoped_check_base_still_demotes_what_the_base_already_had(clean, capsys):
    base = commit(clean, BIG)
    commit(clean, {'x.md': '# X\n'})
    assert run(clean, 'check', 'docs/big.md', '--base', base) == 0


def test_scoped_check_with_an_unresolvable_base_exits_2(clean, capsys):
    commit(clean, BIG)
    assert run(clean, 'check', 'docs/big.md', '--base', 'nope') == 2
    assert 'cannot resolve --base' in capsys.readouterr().err


def test_scoped_check_finds_a_duplicate_of_an_unscoped_doc(clean, capsys):
    block = ' '.join(f'unique{i}' for i in range(60)) + '\n'
    commit(clean, {'docs/a.md': '# A\n\n' + block, 'docs/b.md': '# B\n\n' + block})
    assert run(clean, 'check', 'docs/a.md', '--json') == 0
    found = [f for f in report(capsys)['findings'] if f['rule'] == 'cross-doc-duplicate']
    assert [f['rel'] for f in found] == ['docs/a.md']


def test_check_from_a_subdirectory_finds_the_repo_root(clean, monkeypatch, capsys):
    commit(clean, {**BIG, 'sub/keep.txt': 'x\n'})
    monkeypatch.chdir(clean / 'sub')
    assert main(['check']) == 1
    assert 'FAIL  docs/big.md' in capsys.readouterr().err


def test_scoped_file_args_are_relative_to_the_working_directory_when_the_root_is_found(
    clean, monkeypatch, capsys
):
    commit(clean, {'sub/DOC.md': '# D\n', '.docs.toml': '# defaults\n'})
    write(clean, {'sub/app.py': DOCSTRING})
    repo_add(clean)
    monkeypatch.chdir(clean / 'sub')
    assert main(['check', '--profile', 'strict', 'app.py']) == 1
    assert 'FAIL  sub/app.py:1' in capsys.readouterr().err


def test_a_file_argument_that_cannot_be_measured_is_said_out_loud(clean, tmp_path_factory, capsys):
    outside = tmp_path_factory.mktemp('elsewhere') / 'x.md'
    outside.write_text('# x\n', encoding='utf-8')
    write(clean, {'draft.md': '# d\n'})
    assert run(clean, 'check', 'gone.md', str(outside), 'draft.md') == 0
    err = capsys.readouterr().err
    assert 'gone.md: no such file' in err
    assert 'outside the root' in err
    assert 'draft.md: not tracked by git' in err


def test_check_require_exact_without_tiktoken_exits_2(clean, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, 'tiktoken', None)
    assert run(clean, 'check', '--require-exact') == 2
    assert 'exact token counts required' in capsys.readouterr().err


def test_check_outside_a_git_repo_exits_2(tmp_path, capsys):
    assert run(tmp_path, 'check') == 2
    assert 'not a git repository' in capsys.readouterr().err


# --- scan ---------------------------------------------------------------------


def test_scan_exits_0_with_findings(clean, capsys):
    write(clean, {'app.py': DOCSTRING})
    assert run(clean, 'scan', '--profile', 'strict', '--json') == 0
    [finding] = report(capsys)['findings']
    assert (finding['rule'], finding['severity']) == ('docstring', 'warn')


def test_scan_reports_rules_that_are_off_by_default(clean, capsys):
    write(clean, {'app.py': DOCSTRING})
    assert run(clean, 'check', '--json') == 0
    assert report(capsys)['findings'] == []
    assert run(clean, 'scan', '--json') == 0
    assert [f['rule'] for f in report(capsys)['findings']] == ['docstring']


def test_scan_respects_a_stated_off(clean, capsys):
    write(clean, {'app.py': DOCSTRING, '.docs.toml': '[rules.docstring]\nseverity = "off"\n'})
    assert run(clean, 'scan', '--json') == 0
    assert report(capsys)['findings'] == []


# --- config errors ------------------------------------------------------------


@pytest.mark.parametrize('command', ['check', 'scan'])
def test_config_error_exits_2(clean, capsys, command):
    write(clean, {'.docs.toml': '[exclude]\npaths = "vendor"\n'})
    assert run(clean, command) == 2
    assert capsys.readouterr().err.startswith('tahrir: [exclude]: paths must be')


def test_unknown_profile_flag_exits_2(clean, capsys):
    assert run(clean, 'check', '--profile', 'nope') == 2
    assert 'unknown profile' in capsys.readouterr().err


def test_explicit_config_path(clean, capsys):
    write(clean, {'app.py': DOCSTRING, 'alt.toml': 'profile = "strict"\n'})
    assert run(clean, 'check', '--config', str(clean / 'alt.toml')) == 1
    assert run(clean, 'check', '--config', str(clean / 'missing.toml')) == 2


# --- explain and help ---------------------------------------------------------


def test_explain_a_rule(capsys):
    assert main(['--explain', 'wall-of-text']) == 0
    out = capsys.readouterr().out
    assert out.startswith('wall-of-text  (default severity: warn)')
    assert 'tokens_per_heading = 450' in out
    assert '[rules.wall-of-text]' in out


def test_explain_a_rule_without_knobs(capsys):
    assert main(['--explain', 'docstring']) == 0
    assert 'knobs' not in capsys.readouterr().out


def test_explain_unknown_rule_exits_2(capsys):
    assert main(['--explain', 'nope']) == 2
    err = capsys.readouterr().err
    assert "unknown rule 'nope'" in err
    assert 'wall-of-text' in err


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert 'usage: tahrir' in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['--version'])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith('tahrir ')


# --- json ---------------------------------------------------------------------


def test_json_shape(clean, capsys):
    write(clean, {'CHANGELOG.md': '# Log\n'})
    repo_add(clean)
    assert run(clean, 'check', '--json') == 0
    data = report(capsys)
    assert data['counter'] == 'estimate'
    assert data['exact'] is False
    assert data['caps'] == {'soft': 1000, 'hard': 1400, 'readme_soft': 2000, 'readme_hard': 3000}
    assert data['exempt'] == ['CHANGELOG.md (pattern)']
    assert [d['rel'] for d in data['docs']] == ['README.md']
    assert data['docs'][0]['sections'] == 1


def test_json_finding_fields(clean, capsys):
    write(clean, {'app.py': DOCSTRING})
    assert run(clean, 'check', '--profile', 'strict', '--json') == 1
    [finding] = report(capsys)['findings']
    assert finding == {
        'rel': 'app.py', 'line': 1, 'rule': 'docstring', 'severity': 'fail',
        'message': 'f has a docstring — not runtime-surfaced, delete', 'hint': '',
    }


def test_exempt_marker_is_listed(clean, capsys):
    write(clean, {'docs/gen.md': '<!-- docs: exempt — generated -->\n' + 'word ' * 3000})
    repo_add(clean)
    assert run(clean, 'check', '--json') == 0
    assert report(capsys)['exempt'] == ['docs/gen.md (marker: generated)']


# --- entry points and root resolution -----------------------------------------


def _run_module(monkeypatch, name, *argv):
    monkeypatch.setattr(sys, 'argv', ['tahrir', *argv])
    with pytest.raises(SystemExit) as exit_info:
        with warnings.catch_warnings():
            # `docsteward.cli` is already imported, which runpy notes and which
            # is the point of running it again as __main__.
            warnings.simplefilter('ignore', RuntimeWarning)
            runpy.run_module(name, run_name='__main__')
    return exit_info.value.code


def test_python_dash_m_package_runs_the_cli(monkeypatch, capsys):
    assert _run_module(monkeypatch, 'docsteward', '--explain', 'docstring') == 0
    assert capsys.readouterr().out.startswith('docstring  (default severity: ')


def test_python_dash_m_package_passes_the_exit_code_through(monkeypatch, capsys):
    assert _run_module(monkeypatch, 'docsteward', '--explain', 'nope') == 2
    assert "unknown rule 'nope'" in capsys.readouterr().err


def test_python_dash_m_cli_module_runs_the_cli(monkeypatch, capsys):
    assert _run_module(monkeypatch, 'docsteward.cli', '--explain', 'nope') == 2
    assert "unknown rule 'nope'" in capsys.readouterr().err


def test_init_without_root_scaffolds_the_working_directory(clean, monkeypatch):
    monkeypatch.chdir(clean)
    assert main(['init']) == 0
    assert (clean / '.docs.toml').is_file()


@pytest.mark.parametrize('name', ['DOCS_ROOT', 'DOC_BUDGET_ROOT'])
def test_root_env_var_names_the_root_for_init(clean, tmp_path_factory, monkeypatch, name):
    elsewhere = tmp_path_factory.mktemp('elsewhere')
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(name, str(clean))
    assert main(['init']) == 0
    assert (clean / '.docs.toml').is_file()
    assert not (elsewhere / '.docs.toml').exists()


def test_root_env_var_names_the_root_for_check(clean, tmp_path_factory, monkeypatch, capsys):
    commit(clean, BIG)
    monkeypatch.chdir(tmp_path_factory.mktemp('elsewhere'))
    monkeypatch.setenv('DOCS_ROOT', str(clean))
    assert main(['check']) == 1
    assert 'FAIL  docs/big.md' in capsys.readouterr().err


def test_the_config_search_stops_at_the_repo_top(clean, monkeypatch, capsys):
    # An outer repo's strict config must not govern a nested repo of its own.
    commit(clean, {'.docs.toml': '[defaults]\nsoft = 1\nhard = 2\n'})
    inner = clean / 'inner'
    inner.mkdir()
    repo(inner, {'README.md': '# Inner\n\n' + 'word ' * 20 + '\n'})
    monkeypatch.chdir(inner)
    assert main(['check']) == 0
    assert 'FAIL' not in capsys.readouterr().err


def test_check_without_git_installed_says_so_and_exits_2(clean, monkeypatch, capsys):
    monkeypatch.chdir(clean)
    monkeypatch.setenv('PATH', '')
    assert main(['check']) == 2
    assert 'cannot run git' in capsys.readouterr().err


# --- counters, duplicates, unmeasured files -----------------------------------


def test_an_exact_counter_does_not_announce_an_estimate(clean, monkeypatch, capsys):
    monkeypatch.setattr(
        'docsteward.cli.resolve_counter',
        lambda require_exact=False: Counter('fake-bpe', 1.0, encode=lambda text: list(text)),
    )
    assert run(clean, 'check') == 0
    out = capsys.readouterr().out
    assert 'counter: fake-bpe' in out
    assert 'ESTIMATED' not in out


def test_a_file_both_globs_list_is_scanned_once_as_a_document(clean, capsys):
    commit(clean, {
        '.docs.toml': '[corpus]\ncode_globs = ["*.py", "*.md"]\n\n'
                      '[rules.todo-marker]\nseverity = "warn"\n',
        'NOTES.md': '# Notes\n\nTODO tidy\n\n```text\nTODO sample\n```\n',
    })
    assert run(clean, 'scan', '--json') == 0
    found = [f for f in report(capsys)['findings'] if f['rule'] == 'todo-marker']
    assert [(f['rel'], f['line']) for f in found] == [('NOTES.md', 3)]


def test_a_directory_argument_is_said_out_loud(clean, capsys):
    (clean / 'docs').mkdir()
    assert run(clean, 'check', 'docs') == 0
    assert 'docs: is a directory — name the files' in capsys.readouterr().err


def test_a_git_that_cannot_list_the_files_leaves_them_unjudged(clean, capsys):
    # A tracked name git reads as unknown pathspec magic: `ls-files` refuses it.
    commit(clean, {':(bogus)x.md': '# x\n'})
    assert run(clean, 'check', ':(bogus)x.md') == 0
    assert 'not tracked' not in capsys.readouterr().err


def test_the_config_search_runs_to_the_filesystem_root_when_git_names_no_ancestor(
    clean, tmp_path_factory, monkeypatch, capsys
):
    # GIT_WORK_TREE can put the reported top-level outside the working directory.
    elsewhere = tmp_path_factory.mktemp('worktree')
    git_in_cli = cli.corpus.git
    monkeypatch.setattr(
        cli.corpus, 'git',
        lambda root, *args: f'{elsewhere}\n' if args[0] == 'rev-parse' else git_in_cli(root, *args),
    )
    monkeypatch.chdir(clean)
    assert main(['check']) == 0
    assert capsys.readouterr().out.endswith('0 failures, 0 warnings, 0 exempt.\n')
