from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from helpers import commit, config, counter, doc, git, prose, repo, rules, write

from docsteward import corpus
from docsteward.config import Config
from docsteward.corpus import GitUnavailable


# --- git and the filesystem encoding -----------------------------------------


def test_git_in_a_missing_root_is_unavailable_not_a_traceback(tmp_path):
    with pytest.raises(GitUnavailable, match='cannot run git in .*gone'):
        corpus.git(tmp_path / 'gone', 'status')


def test_a_git_that_hangs_is_unavailable(tmp_path, monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired('git', corpus.GIT_TIMEOUT)

    monkeypatch.setattr(corpus.subprocess, 'run', hang)
    with pytest.raises(GitUnavailable, match=r'git ls-files timed out after 30s'):
        corpus.git(tmp_path, 'ls-files')


@pytest.mark.parametrize('encoding', ['utf-8', 'UTF8', 'utf_8'])
def test_names_are_left_alone_on_a_utf8_filesystem(monkeypatch, encoding):
    monkeypatch.setattr(sys, 'getfilesystemencoding', lambda: encoding)
    assert corpus._fs('café') == 'café'


def test_names_survive_a_filesystem_that_is_not_utf8(monkeypatch):
    monkeypatch.setattr(sys, 'getfilesystemencoding', lambda: 'ascii')
    # The bytes git reported are what the filesystem codec will encode back.
    assert corpus._fs('café').encode('ascii', 'surrogateescape') == 'café'.encode('utf-8')
    on_disk = corpus._on_disk(Path('a/café.md'))
    assert str(on_disk).encode('ascii', 'surrogateescape') == 'a/café.md'.encode('utf-8')


# --- tracked and walk ---------------------------------------------------------


def test_no_globs_enumerates_nothing(tmp_path):
    repo(tmp_path, {'a.md': '# a\n', 'b.py': 'x = 1\n'})
    assert corpus.tracked(tmp_path, []) == []
    assert [p.name for p in corpus.tracked(tmp_path, ['*.md'])] == ['a.md']


def test_a_pathspec_git_rejects_is_not_blamed_on_the_repository(tmp_path):
    repo(tmp_path, {'a.md': '# a\n'})
    with pytest.raises(GitUnavailable, match='git rejected the configured patterns'):
        corpus.tracked(tmp_path, [':(bogus)a.md'])


def test_walk_applies_one_skip_policy(tmp_path):
    repo(tmp_path, {
        'keep.md': '# keep\n',
        'vendor/lib.md': '# vendored\n',
        'muted/a.md': '# muted\n',
        'a.prompt.md': '# prompt\n',
        'marked.md': '<!-- docs: exempt — generated -->\n# m\n',
        'bare.md': '<!-- docs: exempt -->\n# b\n',
    })
    cfg = Config({
        'exclude': {'paths': ['vendor/**']},
        'overrides': [{'pattern': 'muted/**', 'rules': 'off'}],
    })
    found = corpus.walk(tmp_path, ['*.md'], cfg)
    assert found.files == [('keep.md', '# keep\n')]
    assert found.exempt == [
        'a.prompt.md (pattern)',
        'bare.md (marker: no reason given)',
        'marked.md (marker: generated)',
    ]


def test_walk_reads_an_exempt_marker_only_in_a_doc(tmp_path):
    repo(tmp_path, {'marked.md': '<!-- docs: exempt — generated -->\n# m\n'})
    code = corpus.walk(tmp_path, ['*.md'], Config(), are_docs=False)
    assert [rel for rel, _ in code.files] == ['marked.md']
    assert code.exempt == []


def test_walk_yields_a_conflicted_path_once(tmp_path):
    repo(tmp_path, {'a.md': 'base\n'})
    git(tmp_path, 'checkout', '-q', '-b', 'side')
    commit(tmp_path, {'a.md': 'side\n'})
    git(tmp_path, 'checkout', '-q', 'main')
    commit(tmp_path, {'a.md': 'main\n'})
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', 'side'],
                   cwd=tmp_path, capture_output=True)
    # An unmerged path is listed once per index stage.
    assert git(tmp_path, 'ls-files', '-z', '--', '*.md').count('a.md') == 3
    found = corpus.walk(tmp_path, ['*.md'], Config())
    assert [rel for rel, _ in found.files] == ['a.md']


# --- baseline and base_rev ----------------------------------------------------


def test_baseline_follows_a_staged_rename(tmp_path):
    body = ''.join(f'line {i} of the original\n' for i in range(20))
    other = ''.join(f'row {i} of the other file\n' for i in range(20))
    repo(tmp_path, {'old-a.md': '﻿' + body, 'old-b.md': other})
    git(tmp_path, 'mv', 'old-a.md', 'new-a.md')
    git(tmp_path, 'mv', 'old-b.md', 'new-b.md')
    assert corpus.baseline(tmp_path, 'new-b.md') == other
    assert corpus.baseline(tmp_path, 'new-a.md') == body
    write(tmp_path, {'fresh.md': 'new\n'})
    git(tmp_path, 'add', 'fresh.md')
    assert corpus.baseline(tmp_path, 'fresh.md') is None


def test_baseline_of_a_rename_inside_a_subdirectory_root(tmp_path):
    body = ''.join(f'line {i} of the original\n' for i in range(20))
    repo(tmp_path, {'pkg/old.md': body})
    git(tmp_path, 'mv', 'pkg/old.md', 'pkg/new.md')
    assert corpus.baseline(tmp_path / 'pkg', 'new.md') == body


def test_baseline_without_git_is_absent(tmp_path):
    assert corpus.baseline(tmp_path, 'a.md') is None


def test_no_base_ref_means_no_base(tmp_path):
    assert corpus.base_rev(tmp_path, None) is None
    assert corpus.base_rev(tmp_path, '') is None


def test_base_rev_is_where_the_branch_left_the_ref(tmp_path):
    fork = commit(repo(tmp_path), {'a.md': 'a\n'})
    git(tmp_path, 'checkout', '-q', '-b', 'feature')
    commit(tmp_path, {'b.md': 'b\n'})
    git(tmp_path, 'checkout', '-q', 'main')
    commit(tmp_path, {'c.md': 'c\n'})
    git(tmp_path, 'checkout', '-q', 'feature')
    assert corpus.base_rev(tmp_path, 'main') == fork


def test_base_rev_falls_back_to_the_ref_when_histories_are_unrelated(tmp_path):
    commit(repo(tmp_path), {'a.md': 'a\n'})
    git(tmp_path, 'checkout', '-q', '--orphan', 'other')
    commit(tmp_path, {'b.md': 'b\n'})
    assert corpus.base_rev(tmp_path, 'main') == 'main'


def test_an_unresolvable_base_in_a_full_clone_is_an_error(tmp_path):
    repo(tmp_path, {'a.md': 'a\n'})
    with pytest.raises(GitUnavailable, match="cannot resolve --base 'nope' as a git ref"):
        corpus.base_rev(tmp_path, 'nope')


def test_an_unresolvable_base_in_a_shallow_clone_judges_files_as_new(tmp_path, capsys):
    origin = tmp_path / 'origin'
    origin.mkdir()
    repo(origin, {'a.md': 'a\n'})
    commit(origin, {'b.md': 'b\n'})
    git(tmp_path, 'clone', '-q', '--depth', '1', origin.as_uri(), 'clone')
    assert corpus.base_rev(tmp_path / 'clone', 'origin/gone') is None
    assert "--base 'origin/gone' is outside a shallow clone" in capsys.readouterr().err


# --- doc-code-ratio -----------------------------------------------------------

DOC_PATH = 'apps/shop/docs/guide.md'
CODE_PATH = 'apps/shop/src/app.py'
DOC_TEXT = '# Guide\n\n' + prose(200)
CODE_TEXT = 'x = 1\n' * 100


def ratio_config(floor=0, **sections):
    return Config({
        'rules': {'doc-code-ratio': {'severity': 'warn', 'ratio': 0.5, 'floor': floor}},
        'corpus': {'package_roots': ['apps']},
        **sections,
    })


def ratio(root, cfg, docs=(), already_read=None):
    return corpus.doc_code_findings(root, list(docs), counter(), cfg, already_read)


def test_a_package_whose_docs_outweigh_its_code_is_flagged(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT})
    docs_n, code_n = doc(DOC_TEXT, DOC_PATH).tokens, counter().count(CODE_TEXT)
    [finding] = ratio(tmp_path, ratio_config(), [doc(DOC_TEXT, DOC_PATH)])
    assert (finding.rel, finding.line, finding.rule) == ('apps/shop', 1, 'doc-code-ratio')
    assert finding.severity == 'warn'
    assert finding.message == (
        f'{docs_n} doc tokens vs {code_n} code tokens (ratio {docs_n / code_n:.2f}, over 0.5)'
    )
    assert 'needs the work' in finding.hint


def test_a_ratio_within_the_limit_is_quiet(tmp_path):
    repo(tmp_path, {DOC_PATH: '# Guide\n\nshort\n', CODE_PATH: CODE_TEXT})
    assert ratio(tmp_path, ratio_config()) == []


def test_the_rule_needs_to_be_on_and_package_roots_set(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT})
    off = Config({'corpus': {'package_roots': ['apps']}})
    assert ratio(tmp_path, off) == []
    no_roots = Config({'rules': {'doc-code-ratio': {'severity': 'warn', 'floor': 0}}})
    assert ratio(tmp_path, no_roots) == []


def test_a_doc_the_walk_stripped_still_counts_toward_its_package(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT})
    cfg = ratio_config(overrides=[{'pattern': 'apps/shop/docs/**', 'rules': 'off'}])
    assert [f.rel for f in ratio(tmp_path, cfg, docs=[])] == ['apps/shop']


def test_a_doc_already_analysed_is_not_read_again(tmp_path):
    repo(tmp_path, {DOC_PATH: '# Guide\n\nshort\n', CODE_PATH: CODE_TEXT})
    assert ratio(tmp_path, ratio_config()) == []
    assert len(ratio(tmp_path, ratio_config(), [doc(DOC_TEXT, DOC_PATH)])) == 1


def test_excluded_docs_and_code_are_not_measured(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT})
    assert ratio(tmp_path, ratio_config(exclude={'paths': ['apps/shop/docs/**']})) == []
    # Code that is excluded leaves a package with docs and nothing to divide by.
    assert ratio(tmp_path, ratio_config(exclude={'paths': ['apps/shop/src/**']})) == []


def test_a_package_with_docs_and_no_code_has_no_ratio(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, 'apps/shop/notes.txt': 'not code\n'})
    assert ratio(tmp_path, ratio_config(floor=0)) == []


def test_code_below_the_floor_is_too_small_to_judge(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT})
    code_n = counter().count(CODE_TEXT)
    assert ratio(tmp_path, ratio_config(floor=code_n + 1)) == []
    assert len(ratio(tmp_path, ratio_config(floor=code_n))) == 1


def test_only_files_inside_a_package_root_are_counted(tmp_path):
    repo(tmp_path, {
        'README.md': '# Top\n\n' + prose(500),
        'apps/README.md': '# Apps\n\n' + prose(500),
        'tools/lib/x.py': CODE_TEXT,
        'apps/zed/docs/a.md': DOC_TEXT, 'apps/zed/src/a.py': CODE_TEXT,
        'apps/ace/docs/a.md': DOC_TEXT, 'apps/ace/src/a.py': CODE_TEXT,
        'apps/calm/docs/a.md': '# Calm\n', 'apps/calm/src/a.py': CODE_TEXT,
    })
    found = ratio(tmp_path, ratio_config())
    assert [f.rel for f in found] == ['apps/ace', 'apps/zed']


def test_code_already_read_is_not_read_from_disk_again(tmp_path):
    repo(tmp_path, {DOC_PATH: DOC_TEXT, CODE_PATH: CODE_TEXT, 'apps/shop/src/b.py': CODE_TEXT})
    assert len(ratio(tmp_path, ratio_config())) == 1
    big = 'x = 1\n' * 5000
    # The caller's text wins for the file it read; the other still comes off disk.
    assert ratio(tmp_path, ratio_config(), already_read={CODE_PATH: big}) == []


# --- cross-doc-duplicate ------------------------------------------------------


def shared_docs(rel_a='a.md', rel_b='b.md', block=None):
    block = block or prose(60).replace('\n', ' ')
    return [doc(f'# A\n\n{block}\n', rel_a), doc(f'# B\n\n{block}\n', rel_b)]


def test_the_rule_off_finds_no_duplicates():
    assert corpus.duplicate_findings(shared_docs(), counter(), rules(cross_doc_duplicate='off')) == ([], {})


def test_an_override_can_switch_the_rule_on_for_one_subtree():
    cfg = Config({
        'rules': {'cross-doc-duplicate': {'severity': 'off'}},
        'overrides': [{'pattern': 'a/**', 'rules': {'cross-doc-duplicate': 'warn'}}],
    })
    found, worst = corpus.duplicate_findings(shared_docs('a/x.md', 'b/y.md'), counter(), cfg)
    assert [f.rel for f in found] == ['a/x.md']
    assert 'also in b/y.md' in found[0].message
    assert list(worst) == ['a/x.md']


def test_an_override_can_switch_the_rule_off_for_one_subtree():
    cfg = Config({'overrides': [{'pattern': 'b/**', 'rules': {'cross-doc-duplicate': 'off'}}]})
    found, worst = corpus.duplicate_findings(shared_docs('a/x.md', 'b/y.md'), counter(), cfg)
    assert [f.rel for f in found] == ['a/x.md']
    assert list(worst) == ['a/x.md']


def test_a_block_that_is_only_punctuation_is_not_a_duplicate():
    cfg = config(rules={'cross-doc-duplicate': {'min_tokens': 0}})
    assert corpus.duplicate_findings(shared_docs(block='...'), counter(), cfg) == ([], {})
    found, _ = corpus.duplicate_findings(shared_docs(block='the same words'), counter(), cfg)
    assert sorted(f.rel for f in found) == ['a.md', 'b.md']


def test_a_block_repeated_in_one_doc_is_not_a_duplicate_of_itself():
    block = prose(60).replace('\n', ' ')
    twice = doc(f'# A\n\n{block}\n\nbetween\n\n{block}\n', 'a.md')
    assert corpus.duplicate_findings([twice], counter(), Config()) == ([], {})


def test_each_occurrence_is_reported_and_the_worst_is_the_largest_block():
    block = prose(60).replace('\n', ' ')
    twice = doc(f'# A\n\n{block}\n\nbetween\n\n{block}\n', 'a.md')
    once = doc(f'# B\n\n{block}\n', 'b.md')
    found, worst = corpus.duplicate_findings([twice, once], counter(), Config())
    assert [(f.rel, f.line) for f in found] == [('a.md', 3), ('a.md', 7), ('b.md', 3)]
    size = counter().count(corpus._normalize(block))
    assert worst == {'a.md': (size, 'b.md'), 'b.md': (size, 'a.md')}


# --- changelog-unreleased-tagged ---------------------------------------------


def two_changelogs(tmp_path, **sections):
    repo(tmp_path, {
        'pkg-a/CHANGELOG.md': '## [1.0.0] - Unreleased\n',
        'pkg-b/CHANGELOG.md': '## [2.0.0] - Unreleased\n',
    })
    return Config({'rules': {'changelog-unreleased-tagged': {
        'tag_patterns': {'pkg-a/**': 'a-{version}', 'pkg-b/**': 'b-{version}'},
    }}, **sections})


def test_changelog_checks_the_template_of_the_first_pattern_that_matches(tmp_path):
    cfg = two_changelogs(tmp_path)
    git(tmp_path, 'tag', 'b-2.0.0')
    [finding] = corpus.changelog_findings(tmp_path, cfg)
    assert finding.rel == 'pkg-b/CHANGELOG.md'
    assert 'tag b-2.0.0 exists' in finding.message
    assert finding.hint.startswith('replace "Unreleased" with 20')


def test_a_changelog_rule_off_for_one_path_skips_only_that_changelog(tmp_path):
    cfg = two_changelogs(tmp_path, overrides=[
        {'pattern': 'pkg-b/**', 'rules': {'changelog-unreleased-tagged': 'off'}},
    ])
    git(tmp_path, 'tag', 'a-1.0.0')
    git(tmp_path, 'tag', 'b-2.0.0')
    assert [f.rel for f in corpus.changelog_findings(tmp_path, cfg)] == ['pkg-a/CHANGELOG.md']


def test_the_changelog_rule_off_finds_nothing(tmp_path):
    repo(tmp_path, {'CHANGELOG.md': '## [1.0.0] - Unreleased\n'})
    git(tmp_path, 'tag', 'v1.0.0')
    assert corpus.changelog_findings(tmp_path, rules(changelog_unreleased_tagged='off')) == []


def test_a_changelog_in_a_root_without_git_is_not_a_finding(tmp_path):
    write(tmp_path, {'CHANGELOG.md': '## [1.0.0] - Unreleased\n'})
    assert corpus.changelog_findings(tmp_path, Config()) == []
