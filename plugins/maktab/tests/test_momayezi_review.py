from __future__ import annotations

import base64
import json
import subprocess

import pytest
from gh_fake import HEAD, REPO, gh, sample

from momayezi import ledger as ledgers
from momayezi import review
from momayezi.github import Target
from momayezi.review import ReviewError

BASE, TIP = 'a' * 40, 'b' * 40
PULL = f'repos/{REPO}/pulls/4'


class Proc:
    def __init__(self, claude):
        self.claude = claude
        self.calls = []

    def __call__(self, argv, cwd=None, env=None, check=True):
        self.calls.append({'argv': argv, 'cwd': cwd, 'env': env, 'check': check})
        if argv[0] == 'claude':
            return self.claude if isinstance(self.claude, str) else json.dumps(self.claude)
        return BASE + '\n' if 'merge-base' in argv else ''


def pull(**over):
    data = {'head': {'sha': HEAD, 'repo': {'full_name': REPO}}, 'base': {'sha': TIP},
            'title': 'Fix it', 'body': None}
    data.update(over)
    return data


def test_a_pr_review_clones_the_head_and_returns_the_placed_ledger(tmp_path):
    client, _ = gh({('GET', PULL): pull()})
    proc = Proc({'structured_output': sample(), 'num_turns': 9})
    env = {'GH_TOKEN': 'sekret', 'HOME': '/h'}
    got = review.review(client, Target(pr=4), HEAD, ledgers.dumps(sample()), tmp_path, proc, env)
    assert got['target'] == dict(sample()['target'], repo=REPO, pr=4, base_sha=BASE, head_sha=HEAD)
    git = [c['argv'] for c in proc.calls if c['argv'][0] == 'git']
    assert git[0] == ['git', 'init', '-q', str(tmp_path)]
    assert git[1] == ['git', '-C', str(tmp_path), 'remote', 'add', 'origin', f'https://github.com/{REPO}.git']
    assert git[2][-3:] == ['origin', HEAD, TIP] and 'sekret' not in ' '.join(git[2])
    header = proc.calls[2]['env']['GIT_CONFIG_VALUE_0']
    assert base64.b64decode(header.split()[-1]).decode() == 'x-access-token:sekret'
    assert git[-1] == ['git', '-C', str(tmp_path), 'merge-base', TIP, HEAD]
    claude = proc.calls[-1]
    assert claude['cwd'] == tmp_path and claude['check'] is False and claude['env'] == {'HOME': '/h'}
    prompt = claude['argv'][2]
    assert prompt == (f'/maktab:momayezi --review-only --base {BASE} --head {HEAD} --json '
                      '--ledger .momayez/prior.json --intent .momayez/intent.md')
    assert json.loads(claude['argv'][-1]) == ledgers.schema()
    assert ledgers.loads((tmp_path / '.momayez/prior.json').read_text()) == sample()
    assert (tmp_path / '.momayez/intent.md').read_text() == '# Fix it\n\n\n'


def test_a_branch_review_diffs_against_the_default_branch(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'tok')
    client, _ = gh({('GET', f'repos/{REPO}/commits/feat'): {'sha': HEAD},
                    ('GET', f'repos/{REPO}'): {'default_branch': 'develop'},
                    ('GET', f'repos/{REPO}/commits/develop'): {'sha': TIP}})
    proc = Proc({'structured_output': dict(sample(), target={})})
    got = review.review(client, Target(ref='feat'), HEAD, ' ', tmp_path, proc)
    assert got['target'] == {'repo': REPO, 'ref': 'feat', 'base_sha': BASE, 'head_sha': HEAD}
    assert proc.calls[-1]['argv'][2].endswith('--json') and 'GITHUB_TOKEN' not in proc.calls[-1]['env']
    assert proc.calls[2]['env']['GIT_CONFIG_KEY_0'] == 'http.https://github.com/.extraheader'


def test_git_env_without_a_token_only_disables_prompts():
    assert review.git_env({'A': '1'}) == {'A': '1', 'GIT_TERMINAL_PROMPT': '0'}


@pytest.mark.parametrize('target, routes, message', [
    (Target(pr=4), {('GET', PULL): pull(head={'sha': HEAD, 'repo': {'full_name': 'fork/r'}})}, 'from a fork'),
    (Target(pr=4), {('GET', PULL): pull(head={'sha': HEAD, 'repo': None})}, 'from a fork'),
    (Target(pr=4), {('GET', PULL): pull(head={'sha': TIP, 'repo': {'full_name': REPO}})}, 'moved from'),
    (Target(ref='feat'), {('GET', f'repos/{REPO}/commits/feat'): {'sha': TIP}}, 'feat moved from'),
])
def test_refuses_forks_and_moved_heads(tmp_path, target, routes, message):
    client, _ = gh(routes)
    with pytest.raises(ReviewError, match=message):
        review.review(client, target, HEAD, '', tmp_path, Proc({}), {})


@pytest.mark.parametrize('claude, message', [
    ('Error: not logged in', 'printed no JSON: Error: not logged in'),
    ({'subtype': 'error_max_turns'}, 'returned no ledger: error_max_turns'),
    ({'result': 'gave up', 'structured_output': None}, 'returned no ledger: gave up'),
    ({}, 'returned no ledger: $'),
    ([1], 'returned no ledger: $'),
])
def test_a_review_without_a_ledger_is_an_error(tmp_path, claude, message):
    client, _ = gh({('GET', PULL): pull()})
    with pytest.raises(ReviewError, match=message):
        review.review(client, Target(pr=4), HEAD, '', tmp_path, Proc(claude), {})


def test_run_proc(monkeypatch, tmp_path):
    def missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, 'run', missing)
    with pytest.raises(ReviewError, match='git is not installed'):
        review.run_proc(['git'])
    seen = {}

    def failing(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 2, 'out', '')
    monkeypatch.setattr(subprocess, 'run', failing)
    with pytest.raises(ReviewError, match='git failed: out'):
        review.run_proc(['git'], cwd=tmp_path, env={'A': '1'})
    assert seen['cwd'] == tmp_path and seen['env'] == {'A': '1'}
    assert review.run_proc(['claude'], check=False) == 'out' and seen['env'] is None
