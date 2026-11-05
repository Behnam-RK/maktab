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
    assert git[4] == ['git', '-C', str(tmp_path), 'merge-base', TIP, HEAD]
    assert git[-1] == ['git', '-C', str(tmp_path), 'show', f'{TIP}:AGENTS.md']
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


OLD, NEW = 'c' * 40, 'd' * 40


class Repo(Proc):
    """Proc plus `git show <rev>:<path>` from `files`, a patch-id per diffed head, and fetches
    that fail for `gone` shas."""

    def __init__(self, claude, files=None, patches=None, gone=()):
        super().__init__(claude)
        self.files, self.patches, self.gone = files or {}, patches or {}, set(gone)

    def __call__(self, argv, cwd=None, env=None, check=True, stdin=None):
        out = super().__call__(argv, cwd, env, check)
        if argv[:1] == ['git'] and 'show' in argv:
            return self.files.get(argv[-1].split(':', 1)[1], '')
        if argv[:1] == ['git'] and 'fetch' in argv and set(argv) & self.gone:
            raise ReviewError('git failed: not our ref')
        if argv[:1] == ['git'] and 'diff' in argv:
            return 'diff of ' + argv[-1]
        if argv[:1] == ['git'] and 'patch-id' in argv:
            return self.patches.get(stdin.removeprefix('diff of '), '')
        return out


def rebased(**over):
    return {('GET', PULL): pull(head={'sha': NEW, 'repo': {'full_name': REPO}}, **over)}


def test_a_rebased_head_with_the_same_change_is_reviewed_and_stamped(tmp_path):
    client, _ = gh(rebased())
    proc = Repo({'structured_output': dict(sample(), notes=['no intent brief'])},
                patches={OLD: 'p1 0000\n', NEW: 'p1 0000\n'})
    got = review.review(client, Target(pr=4), OLD, '', tmp_path, proc, {}, follow_rebase=True)
    assert got['target']['head_sha'] == NEW and got['target']['rebased_from'] == OLD
    assert got['notes'] == ['no intent brief', f'head rebased from {OLD}; same change']
    assert f'--head {NEW}' in proc.calls[-1]['argv'][2]


@pytest.mark.parametrize('proc', [
    Repo({}, patches={OLD: 'p1\n', NEW: 'p2\n'}),
    Repo({}, patches={}),
    Repo({}, patches={OLD: 'p1\n', NEW: 'p1\n'}, gone=[OLD]),
])
def test_a_moved_head_with_another_change_is_refused(tmp_path, proc):
    client, _ = gh(rebased())
    with pytest.raises(ReviewError, match=f'#4 moved from {OLD} to {NEW}, a different change'):
        review.review(client, Target(pr=4), OLD, '', tmp_path, proc, {}, follow_rebase=True)


def test_a_moved_branch_without_follow_rebase_names_both_heads(tmp_path):
    client, _ = gh({('GET', f'repos/{REPO}/commits/feat'): {'sha': NEW}})
    with pytest.raises(ReviewError, match=f'feat moved from {OLD} to {NEW}: request it again'):
        review.review(client, Target(ref='feat'), OLD, '', tmp_path, Proc({}), {})


def test_project_memory_comes_from_the_base_with_its_imports(tmp_path):
    files = {
        'CLAUDE.md': '@AGENTS.md and @docs/rules.md, not `@code.md`, mail a@b.co, @~/x.md, @/etc/y.md,\n'
                     '```\n@fenced.md\n```\n@../up.md @maktab:momayezi\n',
        'AGENTS.md': 'house rules @CLAUDE.md @d1.md',
        'docs/rules.md': 'rules @../AGENTS.md',
        'd1.md': '@d2.md', 'd2.md': '@d3.md', 'd3.md': '@d4.md', 'd4.md': '@d5.md', 'd5.md': 'too deep',
        'code.md': 'X', 'fenced.md': 'X',
    }
    proc = Repo({'structured_output': sample()}, files=files)
    client, _ = gh({('GET', PULL): pull()})
    got = review.review(client, Target(pr=4), HEAD, '', tmp_path, proc, {})
    argv = proc.calls[-1]['argv']
    rules = argv[argv.index('--append-system-prompt') + 1]
    shown = [p for p in ('CLAUDE.md', 'AGENTS.md', 'docs/rules.md', 'd1.md', 'd2.md', 'd3.md', 'd4.md')
             if f'<!-- {p} -->' in rules]
    # Four hops from CLAUDE.md end at d3.md: its own import is not read.
    assert len(shown) == 6 and '<!-- d4.md -->' not in rules and 'X' not in rules.replace('<!--', '')
    assert got['notes'][1:] == ['project memory: skipped @~/x.md, outside the checkout',
                            'project memory: skipped @/etc/y.md, outside the checkout',
                            'project memory: skipped @../up.md, outside the checkout']
    assert argv[argv.index('--settings') + 1] == '{"outputStyle": "Concise"}'
    assert '--strict-mcp-config' in argv and argv[argv.index('--mcp-config') + 1] == '{"mcpServers": {}}'


def test_project_memory_falls_back_to_agents_md_is_capped_and_can_be_off(tmp_path, monkeypatch):
    monkeypatch.setattr(review, 'MEMORY_CAP', 80)
    proc = Repo({'structured_output': sample()}, files={'CLAUDE.md': ' \n', 'AGENTS.md': 'é' * 100})
    client, _ = gh({('GET', PULL): pull()})
    got = review.review(client, Target(pr=4), HEAD, '', tmp_path, proc, {})
    assert got['notes'][-1] == 'project memory: cut to 80 bytes'
    proc = Repo({'structured_output': sample()}, files={'AGENTS.md': 'rules'})
    review.review(client, Target(pr=4), HEAD, '', tmp_path, proc, {}, memory=False)
    assert '--append-system-prompt' not in proc.calls[-1]['argv']
    assert not [c for c in proc.calls if 'show' in c['argv']]


def test_a_usage_limit_is_its_own_failure(tmp_path):
    client, _ = gh({('GET', PULL): pull()})
    claude = {'is_error': True, 'result': "You've hit your session limit · resets 3pm (UTC)"}
    with pytest.raises(ReviewError) as caught:
        review.review(client, Target(pr=4), HEAD, '', tmp_path, Proc(claude), {})
    assert caught.value.failure['status'] == 'limited'
    assert caught.value.failure['resets_at'] == '2026-11-05T15:00:00Z'
    with pytest.raises(ReviewError) as caught:
        review.review(client, Target(pr=4), HEAD, '', tmp_path, Proc('Error: not logged in'), {})
    assert caught.value.failure == {'status': 'failed', 'reason': 'the review printed no JSON: Error: not logged in'}


def test_run_proc_passes_stdin(monkeypatch):
    seen = {}

    def done(argv, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(argv, 0, 'id', '')
    monkeypatch.setattr(subprocess, 'run', done)
    assert review.run_proc(['git', 'patch-id'], stdin='diff') == 'id' and seen['input'] == 'diff'
