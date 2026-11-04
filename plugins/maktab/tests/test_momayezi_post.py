from __future__ import annotations

import pytest
from gh_fake import HEAD, REPO, gh, run, runs_path, sample

from momayezi import ledger as ledgers
from momayezi import post
from momayezi.github import GhError, Target
from momayezi.protocol import REVIEWER_MARKER

CHECKS = f'repos/{REPO}/check-runs'
REVIEWS = f'repos/{REPO}/pulls/4/reviews'


def test_place_fills_repo_and_replaces_the_target():
    data = sample()
    data['target']['ref'] = 'old'
    placed = post.place(Target(pr=4), REPO, data)
    assert placed['target'] == dict(sample()['target'], repo=REPO, pr=4)
    assert post.place(Target(ref='b'), REPO, sample())['target']['ref'] == 'b'


def test_fresh_is_this_rounds_open_findings_most_severe_first():
    data = sample()
    data['findings'].append(dict(data['findings'][1], id='F4', severity='major'))
    data['findings'].append(dict(data['findings'][1], id='F5', state='fixed'))
    assert [f['id'] for f in post.fresh(data)] == ['F2', 'F4', 'F3']


def test_detail_and_where():
    f2, f3 = sample()['findings'][1:]
    assert post.where(f2) == 'stats.py:5-7' and post.where(f3) == 'README.md:1'
    text = post.detail(f2)
    assert '**F2** critical · security · `stats.py:5-7` (confidence 90)' in text
    assert '> return os.system' in text and '**Fix:** subprocess' in text
    assert '> ' not in post.detail(f3) and 'Fix' not in post.detail(f3)


def test_summary_counts_open_findings_and_flags_truncation():
    text = post.summary(dict(sample(), truncated=True))
    assert 'Round 2 · findings · lenses security, correctness on opus · tier small' in text
    assert 'Open: 1 critical, 0 major, 0 minor, 1 nit' in text
    assert '- **F2** critical' in text and 'Truncated' in text and '> No intent brief' in text
    assert 'Truncated' not in post.summary(dict(sample(), notes=[]))


def test_check_run_is_created_with_the_marker():
    client, runner = gh({('GET', runs_path()): {'check_runs': [run(1, sample())]}})
    post.check_run(client, sample())
    (body,) = runner.sent('POST', CHECKS)
    assert body['name'] == 'momayez' and body['head_sha'] == HEAD and body['conclusion'] == 'neutral'
    assert ledgers.from_marker(body['output']['text'], REVIEWER_MARKER) == sample()
    assert body['output']['title'] == 'momayez: findings'


def test_an_in_progress_run_is_completed_in_place():
    client, runner = gh({('GET', runs_path()): {'check_runs': [run(8, status='in_progress')]}})
    post.check_run(client, sample())
    assert runner.sent('PATCH', f'{CHECKS}/8')[0]['status'] == 'completed'
    assert not runner.sent('POST', CHECKS)


def test_inline_comments_carry_the_finding_marker_and_ranges():
    f1, f2, _ = sample()['findings']
    one = post.inline(f1)
    assert one['line'] == 2 and 'start_line' not in one and one['body'].endswith('<!-- momayez-finding:F1 -->')
    span = post.inline(f2)
    assert (span['start_line'], span['line'], span['start_side']) == (5, 7, 'RIGHT')


def test_review_inlines_in_diff_findings_and_summarises_the_rest():
    client, runner = gh()
    assert post.review(client, 4, sample()) == 'inline'
    (body,) = runner.sent('POST', REVIEWS)
    assert body['event'] == 'COMMENT' and body['commit_id'] == HEAD
    assert [c['path'] for c in body['comments']] == ['stats.py']
    assert '**F3**' in body['body'] and '**F2**' not in body['body']


def test_a_422_falls_back_to_the_body():
    client, runner = gh({('POST', REVIEWS): [GhError('line not in diff (HTTP 422)'), {}]})
    assert post.review(client, 4, sample()) == 'body'
    retry = runner.sent('POST', REVIEWS)[1]
    assert retry['comments'] == [] and '**F2**' in retry['body'] and '**F3**' in retry['body']


def test_other_errors_and_422s_with_nothing_inline_propagate():
    client, _ = gh({('POST', REVIEWS): GhError('HTTP 500')})
    with pytest.raises(GhError):
        post.review(client, 4, sample())
    data = sample()
    for f in data['findings']:
        f['in_diff'] = False
    client, _ = gh({('POST', REVIEWS): GhError('HTTP 422')})
    with pytest.raises(GhError):
        post.review(client, 4, data)


def test_no_new_findings_posts_no_review():
    data = dict(sample(), round=3)
    client, runner = gh()
    assert post.review(client, 4, data) == 'none' and not runner.calls


def test_publish_for_a_pr_and_for_a_ref():
    client, runner = gh({('GET', runs_path()): {'check_runs': []}})
    assert post.publish(client, Target(pr=4), sample()) == 'inline'
    marker = runner.sent('POST', CHECKS)[0]['output']['text']
    assert ledgers.from_marker(marker, REVIEWER_MARKER)['target']['pr'] == 4
    client, runner = gh({('GET', runs_path()): {'check_runs': []}})
    assert post.publish(client, Target(ref='b'), sample()) == 'none'
    assert not runner.sent('POST', REVIEWS)
