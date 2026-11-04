from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from docsteward import tokens
from docsteward.tokens import ESTIMATE_GRACE, Counter, ExactCountUnavailable, resolve


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    # `_tiktoken` creates its cache dir before importing; keep it out of $HOME.
    monkeypatch.setenv('TIKTOKEN_CACHE_DIR', str(tmp_path / 'tiktoken'))
    for name in tokens.COUNTER_ENV:
        monkeypatch.delenv(name, raising=False)
    # Absent whether or not the optional extra happens to be installed.
    monkeypatch.setitem(sys.modules, 'tiktoken', None)


def test_estimate_is_chars_over_four():
    counter = Counter('estimate', ESTIMATE_GRACE)
    assert counter.count('') == 0
    assert counter.count('abcd') == 1
    assert counter.count('a' * 400) == 100
    assert counter.count('abcdef') == 2  # 1.5 rounds to even


def test_estimate_is_not_exact():
    assert not Counter('estimate', ESTIMATE_GRACE).exact


def test_counter_with_an_encoder_is_exact():
    counter = Counter('words', 1.0, str.split)
    assert counter.exact
    assert counter.count('one two three') == 3


def test_resolve_degrades_to_the_estimator_without_tiktoken():
    counter = resolve()
    assert counter.name == 'estimate'
    assert counter.grace == ESTIMATE_GRACE
    assert not counter.exact


def test_resolve_require_exact_raises_without_tiktoken():
    with pytest.raises(ExactCountUnavailable):
        resolve(require_exact=True)


@pytest.mark.parametrize('name', tokens.COUNTER_ENV)
def test_env_forces_the_estimator(monkeypatch, name):
    monkeypatch.setenv(name, 'estimate')
    monkeypatch.setattr(tokens, '_tiktoken', lambda: pytest.fail('tiktoken was tried'))
    assert resolve().name == 'estimate'


def test_require_exact_ignores_the_forced_estimate(monkeypatch):
    monkeypatch.setenv('DOCS_COUNTER', 'estimate')
    with pytest.raises(ExactCountUnavailable):
        resolve(require_exact=True)


def test_resolve_uses_tiktoken_when_it_loads(monkeypatch):
    exact = Counter('tiktoken/cl100k_base', 1.0, list)
    monkeypatch.setattr(tokens, '_tiktoken', lambda: exact)
    assert resolve(require_exact=True) is exact


def test_cache_dir_honours_an_absolute_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    assert tokens._cache_dir() == tmp_path / 'docsteward' / 'tiktoken'


def test_cache_dir_ignores_a_relative_xdg_cache_home(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CACHE_HOME', 'relative/cache')
    monkeypatch.setenv('HOME', str(tmp_path))
    assert tokens._cache_dir() == tmp_path / '.cache' / 'docsteward' / 'tiktoken'


def test_special_token_text_in_a_doc_is_counted_not_refused(monkeypatch):
    seen = {}

    class Encoding:
        def encode(self, text, **kwargs):
            seen.update(kwargs)
            return [1]

    fake = SimpleNamespace(get_encoding=lambda name: Encoding())
    monkeypatch.setitem(sys.modules, 'tiktoken', fake)
    assert tokens._tiktoken().count('<|endoftext|>') == 1
    assert seen == {'disallowed_special': ()}
