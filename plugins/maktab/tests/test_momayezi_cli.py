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

from momayezi import channel, cli, github
from momayezi import ledger as ledgers

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


def test_gh_failures_exit_1(monkeypatch, capsys):
    def broken(cls, repo=None, run=None):
        raise github.GhError('not logged in')
    monkeypatch.setattr(github.Gh, 'here', classmethod(broken))
    assert cli.main(['prior', 'main']) == 1
    assert 'momayezi-prior: not logged in' in capsys.readouterr().err


def test_channel_command_serves_stdio(monkeypatch):
    monkeypatch.setattr(channel, 'serve', lambda: 7)
    assert cli.main(['channel']) == 7


@pytest.mark.parametrize('entry, command', [('post_main', 'post'), ('prior_main', 'prior'), ('wait_main', 'wait')])
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
