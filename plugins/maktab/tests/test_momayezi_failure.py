from __future__ import annotations

from datetime import datetime, timezone

import pytest

from momayezi import failure

NOON = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('text, resets', [
    ("You've hit your session limit · resets 3pm (UTC)", '2026-11-05T15:00:00Z'),
    ('You have reached your usage limit. It resets at 9:30am (UTC)', '2026-11-06T09:30:00Z'),
    ('hit your weekly limit · resets 12am (Asia/Tehran)', '2026-11-05T20:30:00Z'),
    ('hit your limit · resets 14:00', '2026-11-05T14:00:00Z'),
    ('hit your limit · resets 3pm (Nowhere/Zone)', None),
    ('hit your limit · resets 25:00', None),
    ('hit your limit, try later', None),
])
def test_a_usage_limit_is_limited_with_its_reset(text, resets):
    got = failure.classify(text, NOON)
    assert got['status'] == 'limited' and got['reason'] == text
    assert got.get('resets_at') == resets


def test_anything_else_is_failed():
    assert failure.classify('  ', NOON) == {'status': 'failed', 'reason': 'the review failed'}
    assert failure.classify('crashed', NOON) == {'status': 'failed', 'reason': 'crashed'}


def test_round_trip_and_invalid():
    item = {'status': 'limited', 'reason': 'r', 'resets_at': 'x'}
    assert failure.loads(failure.dumps(item)) == item
    assert failure.from_text('log\n' + failure.line(item) + '\n') == item
    assert failure.from_text(f'<!-- {failure.line(item)} -->') == item
    assert failure.from_text('no line') is None and failure.loads('nope') is None
    assert failure.valid({'status': 'done', 'reason': 'r'}) is None
    assert failure.valid({'status': 'failed', 'reason': 'r', 'resets_at': 1}) == {'status': 'failed', 'reason': 'r'}
