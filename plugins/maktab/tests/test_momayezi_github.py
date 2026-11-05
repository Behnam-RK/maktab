from __future__ import annotations

import os
import stat

import pytest
from gh_fake import HEAD, REPO, gh, run, runs_path, sample

from momayezi import github
from momayezi.github import Gh, GhError, Target


def test_targets_parse_digits_as_prs():
    assert Target.parse('12') == Target(pr=12)
    assert Target.parse(' feat/x ') == Target(ref='feat/x')
    assert Target(pr=12).label == '#12' and Target(ref='main').label == 'main'
    assert Target(pr=3).meta() == {'pr': '3'} and Target(ref='m').meta() == {'ref': 'm'}
    with pytest.raises(ValueError):
        Target.parse('  ')


def test_gh_error_reads_the_http_status():
    assert GhError('gh: Not Found (HTTP 404)').status == 404
    assert GhError('boom').status is None
    assert str(GhError('  ')) == 'gh failed'


def test_here_takes_the_repo_from_args_env_or_gh(monkeypatch):
    monkeypatch.delenv('GITHUB_REPOSITORY', raising=False)
    assert Gh.here('a/b').repo == 'a/b'
    monkeypatch.setenv('GITHUB_REPOSITORY', 'c/d')
    assert Gh.here().repo == 'c/d'
    monkeypatch.delenv('GITHUB_REPOSITORY')
    assert Gh.here(run=lambda args, stdin: 'e/f\n').repo == 'e/f'


def test_api_builds_argv_sends_bodies_and_flattens_pages():
    client, runner = gh({('GET', f'repos/{REPO}/x'): '', ('GET', f'repos/{REPO}/p'): [[[1], [2, 3]]]})
    assert client.api('repos/{repo}/x') is None
    assert client.api('repos/{repo}/p', pages=True) == [1, 2, 3]
    client.api('repos/{repo}/x', 'POST', {'a': 1})
    assert runner.calls[1][2] == ['api', '-X', 'GET', f'repos/{REPO}/p', '--paginate', '--slurp']
    assert runner.sent('POST', f'repos/{REPO}/x') == [{'a': 1}]


def test_head_for_a_pr_and_a_ref():
    client, _ = gh({('GET', f'repos/{REPO}/pulls/7'): {'head': {'sha': 'abc'}},
                    ('GET', f'repos/{REPO}/commits/main'): {'sha': 'def'}})
    assert client.head(Target(pr=7)) == 'abc' and client.head(Target(ref='main')) == 'def'


def test_runs_are_newest_first():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1), run(3), run(2)]}})
    assert [r['id'] for r in client.runs(HEAD)] == [3, 2, 1]


def test_upsert_edits_the_marked_comment_or_posts_one():
    marked = {'id': 9, 'body': 'x <!-- k {} -->'}
    client, runner = gh({('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[[{'id': 1, 'body': 'hi'}, marked]]]})
    client.upsert_comment(4, 'k', 'new')
    assert runner.sent('PATCH', f'repos/{REPO}/issues/comments/9') == [{'body': 'new'}]
    client, runner = gh({('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    client.upsert_comment(4, 'k', 'new')
    assert runner.sent('POST', f'repos/{REPO}/issues/4/comments') == [{'body': 'new'}]


def test_press_removes_then_adds_and_tolerates_an_absent_label():
    label = f'repos/{REPO}/issues/4/labels/review'
    for removal in ({}, GhError('Label does not exist (HTTP 404)')):
        client, runner = gh({('DELETE', label): removal})
        client.press(4, 'review')
        assert [c[:2] for c in runner.calls] == [('DELETE', label), ('POST', f'repos/{REPO}/issues/4/labels')]
    client, _ = gh({('DELETE', label): GhError('HTTP 403')})
    with pytest.raises(GhError):
        client.press(4, 'review')


def test_dispatch_passes_each_input_as_a_field():
    client, runner = gh()
    client.dispatch('momayezi.yaml', {'ref': 'b', 'ledger': '{}'})
    assert runner.calls[0][2] == ['workflow', 'run', 'momayezi.yaml', '--repo', REPO, '-f', 'ref=b', '-f', 'ledger={}']


def test_reply_on_the_newest_thread_or_the_pr():
    path = f'repos/{REPO}/pulls/4/comments?per_page=100'
    tagged = [{'id': 5, 'body': 'a <!-- momayezi-finding:F2 -->'}, {'id': 8, 'body': 'b <!-- momayezi-finding:F2 -->'},
              {'id': 9, 'body': 'c <!-- momayezi-finding:F21 -->'}]
    client, runner = gh({('GET', path): [[tagged]]})
    assert client.reply(4, 'F2', 'because') == 'thread'
    assert runner.sent('POST', f'repos/{REPO}/pulls/4/comments/8/replies') == [{'body': 'because'}]
    assert client.reply(4, 'F7', 'because') == 'summary'
    assert runner.sent('POST', f'repos/{REPO}/issues/4/comments') == [{'body': '**Re F7** (momayezi): because'}]


def test_run_ledger_reads_valid_markers_only():
    assert github.run_ledger(run(1, sample())) == sample()
    assert github.run_ledger(run(1, text='<!-- momayezi-ledger:v2 {"x":1} -->')) is None
    assert github.run_ledger({'id': 1, 'output': None}) is None


@pytest.fixture
def fake_gh_on_path(tmp_path, monkeypatch):
    script = tmp_path / 'gh'
    script.write_text('#!/bin/sh\nif [ "$1" = fail ]; then echo "nope (HTTP 422)" >&2; exit 1; fi\n'
                      'echo "$@"; cat\n', encoding='utf-8')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(tmp_path))


def test_run_gh_runs_the_real_binary(fake_gh_on_path):
    assert github.run_gh(['api', 'x'], 'in') == 'api x\nin'
    with pytest.raises(GhError) as caught:
        github.run_gh(['fail'])
    assert caught.value.status == 422


def test_run_gh_without_gh(monkeypatch, tmp_path):
    monkeypatch.setenv('PATH', str(tmp_path))
    with pytest.raises(GhError, match='not installed'):
        github.run_gh(['api'])
