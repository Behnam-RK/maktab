from __future__ import annotations

import json

import pytest
from gh_fake import REPO, gh, run, runs_path, sample

from momayezi import ledger as ledgers
from momayezi import prior
from momayezi.github import Target
from momayezi.protocol import EDITOR_MARKER

COMMITS = f'repos/{REPO}/pulls/4/commits?per_page=100'
COMMENTS = f'repos/{REPO}/issues/4/comments?per_page=100'
OLD, NEW = 'a' * 40, 'b' * 40


def editor_comment(ledger, updated_at, ident=1):
    return {'id': ident, 'updated_at': updated_at, 'body': 'x\n' + ledgers.to_marker(ledger, EDITOR_MARKER)}


def routes(runs_new, runs_old, comments):
    return {('GET', COMMITS): [[[{'sha': OLD}, {'sha': NEW}]]],
            ('GET', runs_path(NEW)): {'check_runs': runs_new},
            ('GET', runs_path(OLD)): {'check_runs': runs_old},
            ('GET', COMMENTS): [[comments]]}


def test_walks_commits_newest_first_to_the_last_review():
    older = dict(sample(), round=1)
    client, runner = gh(routes([run(3, status='in_progress'), run(2, text='broken')],
                               [run(1, older)], []))
    assert prior.from_pr(client, 4) == older
    client, runner = gh(routes([run(2, sample())], [run(1, older)], []))
    assert prior.from_pr(client, 4) == sample()
    assert not any(runs_path(OLD) == c[1] for c in runner.calls)


def test_a_newer_editor_ledger_wins_and_an_older_one_does_not():
    mine = dict(sample(), round=3)
    reviewed = run(2, sample(), completed_at='2026-11-04T10:00:00Z')
    client, _ = gh(routes([reviewed], [], [editor_comment(mine, '2026-11-04T11:00:00Z')]))
    assert prior.from_pr(client, 4) == mine
    client, _ = gh(routes([reviewed], [], [editor_comment(mine, '2026-11-04T09:00:00Z')]))
    assert prior.from_pr(client, 4) == sample()


def test_bad_editor_comments_are_skipped_with_a_warning(capsys):
    bad = {'id': 7, 'updated_at': 'z', 'body': f'<!-- {EDITOR_MARKER} {{"v":1}} -->'}
    plain = {'id': 8, 'updated_at': 'z', 'body': 'lgtm'}
    client, _ = gh(routes([], [], [bad, plain]))
    assert prior.from_pr(client, 4) is None
    assert 'skipping comment 7' in capsys.readouterr().err


def test_from_dispatch_reads_the_ledger_input(tmp_path):
    assert prior.from_dispatch({}) is None
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'inputs': {'ref': 'b', 'ledger': ledgers.dumps(sample())}}), encoding='utf-8')
    assert prior.from_dispatch({'GITHUB_EVENT_PATH': str(event)}) == sample()
    event.write_text(json.dumps({'inputs': {'ref': 'b', 'ledger': ' '}}), encoding='utf-8')
    assert prior.from_dispatch({'GITHUB_EVENT_PATH': str(event)}) is None
    event.write_text(json.dumps({}), encoding='utf-8')
    assert prior.from_dispatch({'GITHUB_EVENT_PATH': str(event)}) is None
    event.write_text(json.dumps({'inputs': {'ledger': '{"x":1}'}}), encoding='utf-8')
    with pytest.raises(ledgers.LedgerError):
        prior.from_dispatch({'GITHUB_EVENT_PATH': str(event)})


def test_find_dispatches_on_the_target(monkeypatch):
    monkeypatch.delenv('GITHUB_EVENT_PATH', raising=False)
    client, _ = gh(routes([run(2, sample())], [], []))
    assert prior.find(client, Target(pr=4)) == sample()
    assert prior.find(client, Target(ref='b')) is None
