from __future__ import annotations

import json

import pytest
from helpers import commit, git, repo, rules, write

from docsteward import cli, scanner
from docsteward.config import WARN, Config
from docsteward.corpus import GitUnavailable


ON = rules(changed_without_docs='warn')


@pytest.fixture
def base(tmp_path):
    repo(tmp_path)
    return commit(tmp_path, {'app.py': 'x = 1\n', 'README.md': '# App\n', 'CHANGELOG.md': '# Log\n'})


def changed(tmp_path, base, config=ON):
    return scanner.changed_without_docs(tmp_path, base, config)


def test_code_without_docs(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n', 'lib.py': 'y = 1\n'})
    [finding] = changed(tmp_path, base)
    assert finding.rule == 'changed-without-docs'
    assert finding.rel == '.'
    assert finding.severity == WARN
    assert finding.message == f'2 file(s) changed since {base}, no doc changed'


def test_code_with_docs(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n', 'README.md': '# App, changed\n'})
    assert changed(tmp_path, base) == []


def test_docs_only(tmp_path, base):
    commit(tmp_path, {'README.md': '# App, changed\n'})
    assert changed(tmp_path, base) == []


def test_changelog_alone_is_not_a_doc_change(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n', 'CHANGELOG.md': '# Log\n\n- x\n'})
    assert len(changed(tmp_path, base)) == 1


def test_excluded_and_muted_code_needs_no_doc(tmp_path, base):
    commit(tmp_path, {'vendor/a.py': 'v = 1\n', 'gen/b.py': 'g = 1\n'})
    cfg = Config({
        'rules': {'changed-without-docs': {'severity': 'warn'}},
        'exclude': {'paths': ['vendor/**']},
        'overrides': [{'pattern': 'gen/**', 'rules': 'off'}],
    })
    assert changed(tmp_path, base, cfg) == []


def test_a_muted_doc_does_not_count_as_a_doc_change(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n', 'gen/notes.md': '# generated\n'})
    cfg = Config({
        'rules': {'changed-without-docs': {'severity': 'warn'}},
        'overrides': [{'pattern': 'gen/**', 'rules': 'off'}],
    })
    assert len(changed(tmp_path, base, cfg)) == 1


def test_off_by_default_and_without_a_base(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    assert changed(tmp_path, base, Config()) == []
    assert changed(tmp_path, None) == []


def test_scan_view_turns_it_on(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    assert len(changed(tmp_path, base, Config().for_scan())) == 1


def test_stated_off_stays_off_in_a_scan(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    assert changed(tmp_path, base, rules(changed_without_docs='off').for_scan()) == []


def test_unresolvable_base_is_an_error(tmp_path, base):
    with pytest.raises(GitUnavailable, match='cannot resolve --base'):
        changed(tmp_path, 'no-such-ref')


def test_root_inside_a_repo_sees_only_its_subtree(tmp_path):
    repo(tmp_path)
    first = commit(tmp_path, {'svc/app.py': 'x = 1\n', 'other/lib.py': 'y = 1\n'})
    commit(tmp_path, {'other/lib.py': 'y = 2\n'})
    assert changed(tmp_path / 'svc', first) == []
    assert len(changed(tmp_path, first)) == 1


def test_custom_code_globs(tmp_path, base):
    commit(tmp_path, {'main.go': 'package main\n'})
    assert changed(tmp_path, base) == []
    cfg = Config({'rules': {'changed-without-docs': {'severity': 'warn'}},
                  'corpus': {'code_globs': ['*.go']}})
    assert len(changed(tmp_path, base, cfg)) == 1


def test_empty_code_globs_name_no_code(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    cfg = Config({'rules': {'changed-without-docs': {'severity': 'warn'}},
                  'corpus': {'code_globs': []}})
    assert changed(tmp_path, base, cfg) == []


def test_empty_doc_globs_name_no_docs(tmp_path, base):
    commit(tmp_path, {'app.py': 'x = 2\n', 'README.md': '# App, changed\n'})
    cfg = Config({'rules': {'changed-without-docs': {'severity': 'warn'}},
                  'corpus': {'doc_globs': []}})
    assert len(changed(tmp_path, base, cfg)) == 1


def test_an_unknown_base_in_a_shallow_clone_is_skipped_with_a_note(tmp_path, base, capsys):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    clone = tmp_path.parent / f'{tmp_path.name}-shallow'
    git(tmp_path, 'clone', '-q', '--depth', '1', f'file://{tmp_path}', str(clone))
    assert changed(clone, 'no-such-ref') == []
    assert capsys.readouterr().err == (
        "tahrir: --base 'no-such-ref' is outside a shallow clone — "
        'changed-without-docs skipped\n'
    )


# --- through the CLI ----------------------------------------------------------


@pytest.fixture
def estimate(monkeypatch, tmp_path):
    monkeypatch.setenv('DOCS_COUNTER', 'estimate')
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR', str(tmp_path / 'tiktoken'))


def scan_json(root, *args):
    return cli.main(['scan', '--root', str(root), '--json', *args])


def test_scan_base_reports_changed_without_docs(tmp_path, base, estimate, capsys):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    assert scan_json(tmp_path, '--base', base) == 0
    report = json.loads(capsys.readouterr().out)
    assert [f['rule'] for f in report['findings']] == ['changed-without-docs']


def test_scan_without_base_does_not_report_it(tmp_path, base, estimate, capsys):
    commit(tmp_path, {'app.py': 'x = 2\n'})
    assert scan_json(tmp_path) == 0
    assert json.loads(capsys.readouterr().out)['findings'] == []


def test_scan_bad_base_exits_2(tmp_path, base, estimate, capsys):
    assert scan_json(tmp_path, '--base', 'nope') == 2
    assert 'cannot resolve --base' in capsys.readouterr().err


# --- suffix index -------------------------------------------------------------


def test_suffix_index(tmp_path):
    repo(tmp_path, {'a/b/c.py': ''})
    index = scanner.suffix_index(tmp_path)
    assert {'a/b/c.py', 'b/c.py', 'c.py', 'a', 'a/b', 'b'} <= index
    assert 'a/c.py' not in index


def test_resolve_by_suffix_through_the_cli(tmp_path, estimate, capsys):
    repo(tmp_path, {'pkg/src/mod.py': 'x = 1\n', 'README.md': '# R\n\nsee `src/mod.py`\n'})
    assert scan_json(tmp_path) == 0
    assert [f['rule'] for f in json.loads(capsys.readouterr().out)['findings']] == ['stale-file-ref']
    (tmp_path / '.docs.toml').write_text('[rules.stale-file-ref]\nresolve_by_suffix = true\n')
    git(tmp_path, 'add', '.docs.toml')
    assert scan_json(tmp_path) == 0
    assert json.loads(capsys.readouterr().out)['findings'] == []


# --- citations and references -------------------------------------------------


def cite(root, text, rel='README.md'):
    return scanner.section_citations(root, rel, text, rules(section_citation='warn'))


def test_a_protocol_relative_citation_is_not_a_file_reference(tmp_path):
    assert cite(tmp_path, 'See the "Install" section of `//host/x.md`.\n') == []


def test_a_cited_path_that_is_a_directory_has_no_sections(tmp_path):
    (tmp_path / 'notes.md').mkdir()
    [finding] = cite(tmp_path, 'See the "Install" section of `notes.md`.\n')
    assert finding.message == 'cites "Install" in notes.md — no such section'


def test_a_citation_of_a_missing_file_says_so(tmp_path):
    [finding] = cite(tmp_path, 'See the "Install" section of `gone.md`.\n')
    assert finding.message == 'cites "Install" in gone.md — no such file'


def refs(root, rel, text):
    return scanner.stale_file_refs(root, rel, text, rules(stale_file_ref='warn'))


def test_a_root_level_doc_resolves_against_the_repo_root_only(tmp_path):
    write(tmp_path, {'pyproject.toml': '', 'src/mod.py': ''})
    assert refs(tmp_path, 'README.md', 'see `src/mod.py`\n') == []
    [finding] = refs(tmp_path, 'README.md', 'see `src/gone.py`\n')
    assert finding.message == 'reference to src/gone.py — no such file'


def test_a_doc_in_a_project_resolves_from_that_projects_manifest(tmp_path):
    write(tmp_path, {'svc/pyproject.toml': '', 'svc/src/mod.py': '', 'svc/docs/g.md': ''})
    assert refs(tmp_path, 'svc/docs/g.md', 'see `src/mod.py`\n') == []


def test_a_doc_outside_any_project_ignores_another_projects_manifest(tmp_path):
    write(tmp_path, {'svc/pyproject.toml': '', 'svc/src/mod.py': '', 'docs/g.md': ''})
    assert len(refs(tmp_path, 'docs/g.md', 'see `src/mod.py`\n')) == 1
