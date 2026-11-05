from __future__ import annotations

import io
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from gh_fake import HEAD, REPO, FakeRunner, run, runs_path, sample

from momayezi import channel, cli, github, review
from momayezi import ledger as ledgers
from momayezi.github import Target
from momayezi.protocol import REVIEWER_MARKER

PLUGIN = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(github.Gh, 'here', classmethod(lambda cls, repo=None, run=None: cls(REPO, runner)))
    return runner


def test_post_reads_the_ledger_from_stdin(fake, monkeypatch, capsys):
    fake.routes[('GET', runs_path())] = {'check_runs': []}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(ledgers.dumps(sample())))
    assert cli.main(['post', '4']) == 0
    assert capsys.readouterr().out == 'inline\n'


def test_post_rejects_an_invalid_ledger(fake, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('{}'))
    assert cli.main(['post', '4']) == 1
    assert capsys.readouterr().err.startswith('momayezi-post: invalid ledger')


def test_prior_prints_the_ledger_or_nothing(fake, capsys):
    fake.routes[('GET', f'repos/{REPO}/pulls/4/commits?per_page=100')] = [[[{'sha': HEAD}]]]
    fake.routes[('GET', f'repos/{REPO}/issues/4/comments?per_page=100')] = [[]]
    fake.routes[('GET', runs_path())] = {'check_runs': [run(1, sample())]}
    assert cli.main(['prior', '4']) == 0
    assert ledgers.loads(capsys.readouterr().out) == sample()
    fake.routes[('GET', runs_path())] = {'check_runs': []}
    assert cli.main(['prior', '4']) == 0
    assert capsys.readouterr().out == ''


def test_wait_prints_one_json_line(fake, capsys):
    fake.routes[('GET', runs_path())] = {'check_runs': [run(9, sample()), run(3, sample())]}
    assert cli.main(['wait', '4', HEAD, '--known', '9,', '--timeout', '1']) == 0
    got = json.loads(capsys.readouterr().out)
    assert got['status'] == 'done' and got['url'] == 'https://x/3'


def test_wait_follows_a_handle(fake, capsys):
    fake.routes[('GET', f'repos/{REPO}/actions/runs/7')] = {'id': 7, 'status': 'completed', 'conclusion': 'failure'}
    handle = json.dumps({'backend': 'gh-dispatch', 'pr': '4', 'head_sha': HEAD, 'run_id': 7})
    assert cli.main(['wait', '4', HEAD, '--handle', handle, '--timeout', '1']) == 0
    assert json.loads(capsys.readouterr().out)['reason'] == 'the review run ended failure'


@pytest.mark.parametrize('handle', ['[1]', '{"pr": "4"}', 'nope'])
def test_wait_rejects_a_bad_handle(handle, capsys):
    with pytest.raises(SystemExit):
        cli.main(['wait', '4', HEAD, '--handle', handle])
    assert 'invalid _handle value' in capsys.readouterr().err


def test_review_prints_the_ledger_marker(monkeypatch, tmp_path, capsys):
    seen = []

    def fake_review(gh, target, head, prior, workdir, follow_rebase, memory):
        seen.append((gh.repo, target, head, prior, workdir))
        return sample()
    monkeypatch.setattr(review, 'review', fake_review)
    (tmp_path / 'prior.json').write_text('{"x": 1}', encoding='utf-8')
    assert cli.main(['review', '--repo', REPO, '--pr', '4', '--head', HEAD,
                     '--ledger-file', str(tmp_path / 'prior.json'), '--workdir', str(tmp_path)]) == 0
    assert ledgers.from_marker(capsys.readouterr().out, REVIEWER_MARKER) == sample()
    assert seen == [(REPO, Target(pr=4), HEAD, '{"x": 1}', tmp_path)]
    assert cli.main(['review', '--repo', REPO, '--ref', 'feat', '--head', HEAD]) == 0
    assert seen[-1][1] == Target(ref='feat') and seen[-1][3] == '' and seen[-1][4].name.startswith('momayez-')


def test_review_failures_exit_1(monkeypatch, capsys):
    def broken(*a, **k):
        raise review.ReviewError('#4 comes from a fork: no review')
    monkeypatch.setattr(review, 'review', broken)
    assert cli.main(['review', '--repo', REPO, '--pr', '4', '--head', HEAD]) == 1
    assert capsys.readouterr().err == 'momayezi-review: #4 comes from a fork: no review\n'


def test_gh_failures_exit_1(monkeypatch, capsys):
    def broken(cls, repo=None, run=None):
        raise github.GhError('not logged in')
    monkeypatch.setattr(github.Gh, 'here', classmethod(broken))
    assert cli.main(['prior', 'main']) == 1
    assert 'momayezi-prior: not logged in' in capsys.readouterr().err


def test_channel_command_serves_stdio(monkeypatch):
    monkeypatch.setattr(channel, 'serve', lambda: 7)
    assert cli.main(['channel']) == 7


@pytest.mark.parametrize('entry, command', [('post_main', 'post'), ('prior_main', 'prior'), ('wait_main', 'wait'),
                                            ('review_main', 'review')])
def test_console_scripts_prefix_their_command(monkeypatch, entry, command):
    seen = []
    monkeypatch.setattr(cli, 'main', lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr(sys, 'argv', ['x', '4'])
    assert getattr(cli, entry)() == 0 and seen == [[command, '4']]


def test_python_dash_m(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['momayezi', 'channel'])
    monkeypatch.setattr(channel, 'serve', lambda: 0)
    with pytest.raises(SystemExit) as done:
        runpy.run_module('momayezi', run_name='__main__')
    assert done.value.code == 0


def test_the_bin_shim_runs_the_plugin_source(tmp_path):
    env = dict(os.environ, PATH=os.environ['PATH'], GITHUB_REPOSITORY=REPO)
    done = subprocess.run([str(PLUGIN / 'bin' / 'momayezi-wait'), '--help'],
                          capture_output=True, text=True, env=env, timeout=30)
    assert done.returncode == 0 and 'head_sha' in done.stdout


def test_review_out_writes_the_ledger_or_the_failure(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_review(gh, target, head, prior, workdir, follow_rebase, memory):
        seen.update(follow=follow_rebase, memory=memory)
        return sample()
    monkeypatch.setattr(review, 'review', fake_review)
    out = tmp_path / 'out'
    assert cli.main(['review', '--repo', REPO, '--pr', '4', '--head', HEAD, '--workdir', str(tmp_path),
                     '--out', str(out), '--follow-rebase', '--no-project-memory']) == 0
    assert ledgers.loads((out / 'ledger.json').read_text()) == sample()
    assert seen == {'follow': True, 'memory': False}
    capsys.readouterr()

    def limited(*a, **k):
        raise review.ReviewError('the review returned no ledger: limit',
                                 {'status': 'limited', 'reason': 'hit', 'resets_at': '2026-11-05T15:00:00Z'})
    monkeypatch.setattr(review, 'review', limited)
    assert cli.main(['review', '--repo', REPO, '--pr', '4', '--head', HEAD, '--out', str(out)]) == 1
    error = json.loads((out / 'error.json').read_text())
    assert error == {'status': 'limited', 'reason': 'hit', 'resets_at': '2026-11-05T15:00:00Z'}
    assert capsys.readouterr().out.strip() == 'momayezi-error: ' + json.dumps(error, sort_keys=True, separators=(',', ':'))

    def gone(*a, **k):
        raise github.GhError('HTTP 404')
    monkeypatch.setattr(review, 'review', gone)
    assert cli.main(['review', '--repo', REPO, '--pr', '4', '--head', HEAD]) == 1
    assert '"reason":"HTTP 404","status":"failed"' in capsys.readouterr().out


def test_a_label_wait_times_out_on_a_review_no_runner_took(fake, capsys):
    fake.routes[('GET', runs_path())] = {'check_runs': []}
    fake.routes[('GET', f'repos/{REPO}/actions/workflows/momayez.yaml/runs?head_sha={HEAD}&per_page=5')] = {
        'workflow_runs': [{'status': 'queued', 'created_at': '2026-11-05T11:59:50Z'}]}
    # The label press made the run before the waiter started: --since dates the request.
    assert cli.main(['wait', '4', HEAD, '--since', '2026-11-05T11:59:55Z', '--queue-timeout', '0',
                     '--timeout', '5']) == 0
    got = json.loads(capsys.readouterr().out)
    assert got['status'] == 'timeout' and got['phase'] == 'queued'


def test_post_error_posts_a_failed_check_run(fake, tmp_path, capsys):
    fake.routes[('GET', runs_path())] = {'check_runs': []}
    path = tmp_path / 'error.json'
    path.write_text('{"status": "failed", "reason": "crashed"}', encoding='utf-8')
    assert cli.main(['post', '4', '--error', str(path), '--head', HEAD]) == 0
    assert capsys.readouterr().out.strip() == 'failed'
    path.write_text('{}', encoding='utf-8')
    assert cli.main(['post', '4', '--error', str(path), '--head', HEAD]) == 1
    assert '--error needs a valid error.json and --head' in capsys.readouterr().err
