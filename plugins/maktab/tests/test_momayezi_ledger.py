from __future__ import annotations

import json

import pytest
from gh_fake import sample

from momayezi import ledger as ledgers
from momayezi.protocol import EDITOR_MARKER, REVIEWER_MARKER


def test_a_sample_round_validates_and_round_trips():
    data = sample()
    text = ledgers.dumps(data)
    assert ledgers.loads(text) == data
    assert ledgers.dumps(ledgers.loads(text)) == text


def test_the_validator_reads_the_shipped_schema():
    assert ledgers.schema()['definitions']['finding']['properties']['severity']['enum'] == [
        'critical', 'major', 'minor', 'nit']


@pytest.mark.parametrize('mutate, message', [
    (lambda d: d.update(version='v2'), "$.version: 'v2' is not one of"),
    (lambda d: d.pop('round'), '$: missing round'),
    (lambda d: d.update(extra=1), '$: unexpected extra'),
    (lambda d: d.update(round='2'), '$.round: expected integer'),
    (lambda d: d.update(truncated=1), '$.truncated: expected boolean'),
    (lambda d: d.update(round=True), '$.round: expected integer'),
    (lambda d: d.update(round=0), '$.round: 0 is below 1'),
    (lambda d: d['findings'][0].update(confidence=101), 'confidence: 101 is above 100'),
    (lambda d: d['findings'][0].update(id='M1'), "id: 'M1' does not match"),
    (lambda d: d['findings'][0]['at'].update(path=''), 'path: shorter than 1'),
    (lambda d: d['findings'][0].update(lens='style'), "lens: 'style' is not one of"),
    (lambda d: d.update(lenses='correctness'), '$.lenses: expected array'),
    (lambda d: d['target'].update(head_sha='HEAD'), "head_sha: 'HEAD' does not match"),
])
def test_invalid_ledgers_name_the_field(mutate, message):
    data = sample()
    mutate(data)
    with pytest.raises(ledgers.LedgerError, match='invalid ledger') as caught:
        ledgers.validate(data)
    assert message in str(caught.value)


def test_loads_rejects_non_json():
    with pytest.raises(ledgers.LedgerError, match='not JSON'):
        ledgers.loads('{nope')


def test_an_unsupported_schema_keyword_fails_loudly(monkeypatch):
    monkeypatch.setattr(ledgers, 'schema', lambda: {'type': 'object', 'oneOf': []})
    with pytest.raises(ledgers.LedgerError, match='unsupported keywords'):
        ledgers.errors({})


def test_schema_falls_back_to_the_skill_copy_and_fails_when_both_are_gone(monkeypatch, tmp_path):
    ledgers.schema.cache_clear()
    skill_copy = ledgers.SCHEMA_PATHS[1]
    monkeypatch.setattr(ledgers, 'SCHEMA_PATHS', (tmp_path / 'missing.json', skill_copy))
    assert ledgers.schema()['title'] == 'momayezi ledger v1'
    ledgers.schema.cache_clear()
    monkeypatch.setattr(ledgers, 'SCHEMA_PATHS', (tmp_path / 'missing.json',))
    with pytest.raises(ledgers.LedgerError, match='not found'):
        ledgers.schema()
    ledgers.schema.cache_clear()


def test_markers_survive_comment_closers_in_evidence():
    data = sample()
    marker = ledgers.to_marker(data, REVIEWER_MARKER)
    assert '<' not in marker[4:-3] and '>' not in marker[4:-3]
    text = f'summary\n{ledgers.to_marker(dict(data, round=1), REVIEWER_MARKER)}\n{marker}\ntrailer'
    assert ledgers.from_marker(text, REVIEWER_MARKER) == data  # the last marker wins
    assert ledgers.from_marker(text, EDITOR_MARKER) is None
    assert ledgers.from_marker(None, REVIEWER_MARKER) is None


def test_an_invalid_marker_raises():
    with pytest.raises(ledgers.LedgerError):
        ledgers.from_marker(f'<!-- {REVIEWER_MARKER} {{"version":"v1"}} -->', REVIEWER_MARKER)


def big(severity: str, n: int, evidence: int = 400) -> list[dict]:
    base = sample()['findings'][1]
    return [dict(base, id=f'F{100 + i}', severity=severity, evidence='e' * evidence) for i in range(n)]


def size(data):
    return ledgers.size(ledgers.to_marker(data, REVIEWER_MARKER))


def test_fit_leaves_a_small_ledger_alone():
    data = sample()
    assert ledgers.fit(data, REVIEWER_MARKER) == data


def test_fit_drops_nits_first():
    data = dict(sample(), findings=big('major', 2) + big('nit', 40))
    out = ledgers.fit(data, REVIEWER_MARKER, cap=size(dict(data, findings=big('major', 2))) + 10)
    assert out['truncated'] and {f['severity'] for f in out['findings']} == {'major'}
    assert data['truncated'] is False  # the input is not touched


def test_fit_then_drops_minor_evidence_then_minor_findings():
    data = dict(sample(), findings=big('major', 2) + big('minor', 40))
    stripped = dict(data, findings=big('major', 2) + big('minor', 40, evidence=0))
    out = ledgers.fit(data, REVIEWER_MARKER, cap=size(stripped) + 10)
    assert len(out['findings']) == 42
    assert all(f['evidence'] == '' for f in out['findings'] if f['severity'] == 'minor')
    out = ledgers.fit(data, REVIEWER_MARKER, cap=size(dict(data, findings=big('major', 2))) + 10)
    assert [f['severity'] for f in out['findings']] == ['major', 'major']


def test_fit_last_drops_all_evidence_then_gives_up():
    data = dict(sample(), findings=big('critical', 40))
    bare = dict(data, findings=big('critical', 40, evidence=0))
    out = ledgers.fit(data, REVIEWER_MARKER, cap=size(bare) + 10)
    assert len(out['findings']) == 40 and all(f['evidence'] == '' for f in out['findings'])
    with pytest.raises(ledgers.LedgerError, match='does not fit'):
        ledgers.fit(data, REVIEWER_MARKER, cap=100)


def test_canonical_json_is_compact_and_sorted():
    assert ledgers.dumps(sample()).startswith('{"cited_files":["stats.py"],')
    assert json.loads(ledgers.dumps(sample()))['notes']


def test_objects_without_additional_properties_false_accept_extra_keys(monkeypatch):
    monkeypatch.setattr(ledgers, 'schema', lambda: {'type': 'object', 'properties': {'a': {'type': 'string'}}})
    assert ledgers.errors({'a': 'x', 'b': 1}) == []
