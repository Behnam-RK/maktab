from __future__ import annotations

from datetime import datetime, timezone

import pytest

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = '2026-11-05T12:00:00Z'


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    """momayezi's wall clock (queue and run timings) reads a fixed instant in every test."""
    from momayezi import poll
    monkeypatch.setattr(poll, 'now', lambda: NOW)
