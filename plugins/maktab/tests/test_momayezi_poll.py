from __future__ import annotations

from gh_fake import HEAD, gh, run, runs_path, sample

from momayezi import poll
from momayezi.github import GhError, Target

PR = Target(pr=4)


def test_known_snapshots_existing_runs():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1), run(2, status='in_progress')]}})
    assert poll.known(client, HEAD) == {1, 2}


def test_check_skips_seen_and_unfinished_runs():
    client, _ = gh({('GET', runs_path()): {'check_runs': [run(1, sample()), run(2, status='in_progress')]}})
    assert poll.check(client, PR, HEAD, {1}) is None


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
    got = poll.wait(client, PR, HEAD, {1}, timeout=100, sleep=clock.sleep, clock=clock)
    assert got['status'] == 'done' and clock.slept == [15.0, 22.5]


def test_wait_times_out_without_oversleeping():
    client, _ = gh({('GET', runs_path()): {'check_runs': []}})
    clock = Clock()
    got = poll.wait(client, PR, HEAD, set(), timeout=20, sleep=clock.sleep, clock=clock)
    assert got == {'pr': '4', 'head_sha': HEAD, 'status': 'timeout'} and clock.slept == [15.0, 5.0]
