from __future__ import annotations

from gh_fake import HEAD, gh, run, runs_path, sample

from momayezi import poll
from momayezi.backend import GhLabel
from momayezi.github import GhError, Target

PR = Target(pr=4)
FLOWS = f'repos/o/r/actions/workflows/momayez.yaml/runs?head_sha={HEAD}&per_page=5'


def test_known_snapshots_existing_runs():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1), run(2, status='in_progress')]}})
    assert poll.known(client, HEAD) == {1, 2}


def test_check_skips_seen_and_unfinished_runs():
    opened = dict(run(2, status='in_progress'), started_at='2026-11-05T11:59:00Z')
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1, sample()), opened]}})
    assert poll.check(client, PR, HEAD, {1}, '2026-11-05T11:58:00Z') == {
        'pr': '4', 'head_sha': HEAD, 'status': 'pending', 'phase': 'running', 'queued_for': 60, 'ran_for': 60}
    queued = {'workflow_runs': [{'status': 'queued', 'created_at': '2026-11-05T11:59:00Z'}]}
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(2, status='queued')]}, ('GET', FLOWS): queued})
    assert poll.check(client, PR, HEAD, set(), 'not a time')['phase'] == 'queued'


def test_check_returns_the_new_ledger():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1, sample()), run(5, sample())]}})
    got = poll.check(client, PR, HEAD, {1})
    assert got == {'pr': '4', 'head_sha': HEAD, 'url': 'https://x/5', 'status': 'done',
                   'verdict': 'findings', 'ledger': sample()}


def test_a_run_without_a_ledger_is_a_failure():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(5, text='crashed')]}})
    got = poll.check(client, Target(ref='b'), HEAD, set())
    assert got['status'] == 'failed' and got['ref'] == 'b' and got['conclusion'] == 'neutral'


def test_intervals_back_off_to_the_cap():
    step = poll.intervals()
    assert [step() for _ in range(5)] == [15.0, 22.5, 30.0, 30.0, 30.0]


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_wait_retries_failed_polls_until_the_review_lands():
    pending = {'check_runs': [run(1, sample())]}
    landed = {'check_runs': [run(2, sample()), run(1, sample())]}
    client, _ = gh({('GET', runs_path()): [GhError('HTTP 502'), pending, landed]})
    clock = Clock()
    handle = {'backend': 'gh-label', 'pr': '4', 'head_sha': HEAD, 'known': [1]}
    got = poll.wait(GhLabel(client), handle, timeout=100, sleep=clock.sleep, clock=clock)
    assert got['status'] == 'done' and clock.slept == [15.0, 22.5]


def test_wait_times_out_without_oversleeping():
    client, _ = gh({('GET', runs_path()): {'check_runs': []}})
    clock = Clock()
    handle = {'backend': 'gh-label', 'pr': '4', 'head_sha': HEAD, 'known': []}
    got = poll.wait(GhLabel(client), handle, timeout=20, sleep=clock.sleep, clock=clock)
    assert got == {'pr': '4', 'head_sha': HEAD, 'status': 'timeout', 'phase': 'unknown', 'queued_for': 0,
                   'ran_for': 0} and clock.slept == [15.0, 5.0]


def test_wait_gives_up_on_a_review_no_runner_picks_up():
    client, _ = gh({('GET', runs_path()): {'check_runs': []},
                    ('GET', FLOWS): {'workflow_runs': [{'status': 'queued', 'created_at': '2026-11-05T11:50:00Z'}]}})
    clock = Clock()
    handle = {'backend': 'gh-label', 'pr': '4', 'head_sha': HEAD, 'known': [], 'requested_at': '2026-11-05T11:50:00Z'}
    got = poll.wait(GhLabel(client), handle, timeout=1200, queue_timeout=300, sleep=clock.sleep, clock=clock)
    assert got['status'] == 'timeout' and got['phase'] == 'queued' and got['queued_for'] == 600
    assert clock.slept == []


def test_without_a_check_run_the_workflow_run_tells_the_phase():
    since = '2026-11-05T11:55:00Z'
    flows = {'workflow_runs': [{'status': 'completed', 'created_at': '2026-11-05T11:00:00Z'},
                               {'status': 'in_progress', 'created_at': '2026-11-05T11:56:00Z',
                                'run_started_at': '2026-11-05T11:58:00Z'}]}
    client, runner = gh({('GET', runs_path()): {'check_runs': []}, ('GET', FLOWS): flows})
    got = poll.check(client, PR, HEAD, set(), since)
    assert (got['phase'], got['queued_for'], got['ran_for']) == ('running', 120, 120)
    runner.routes[('GET', FLOWS)] = {'workflow_runs': flows['workflow_runs'][:1]}
    assert poll.check(client, PR, HEAD, set(), since)['phase'] == 'unknown'
    runner.routes[('GET', FLOWS)] = flows
    assert poll.check(client, PR, HEAD, set(), '')['phase'] == 'running'


def test_a_workflow_run_that_ended_without_a_check_run_fails():
    since = '2026-11-05T11:55:00Z'
    ended = {'status': 'completed', 'conclusion': 'startup_failure', 'created_at': '2026-11-05T11:56:00Z',
             'html_url': 'u'}
    skipped = {'status': 'completed', 'conclusion': 'skipped', 'created_at': '2026-11-05T11:57:00Z'}
    client, runner = gh({('GET', runs_path()): {'check_runs': []}, ('GET', FLOWS): {'workflow_runs': [ended, skipped]}})
    got = poll.check(client, PR, HEAD, set(), since)
    assert got['status'] == 'failed' and got['reason'] == 'the review run ended startup_failure'
    runner.routes[('GET', FLOWS)] = {'workflow_runs': [dict(ended, conclusion='success')]}
    assert poll.check(client, PR, HEAD, set(), since)['phase'] == 'running'


def test_pending_names_its_reason():
    assert poll.pending({}, 'queued', reason='0/3 nodes are available')['reason'] == '0/3 nodes are available'
    assert poll.iso() == '2026-11-05T12:00:00Z'


def test_the_real_clock_is_utc(monkeypatch):
    monkeypatch.undo()  # the frozen clock every other test reads
    assert poll.now().utcoffset().total_seconds() == 0
