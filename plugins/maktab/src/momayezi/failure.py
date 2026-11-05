"""Why a remote review left no ledger: `{status: failed|limited, reason, resets_at?}`.

momayezi-review writes it (error.json, or a last log line); momayezi-post --error posts it as a
failed check run; each backend reads it back into its `failed` or `limited` result.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .protocol import ERROR_MARKER, FAILURES

Failure = dict[str, Any]

LIMIT = re.compile(r"\b(?:hit|reached) your [\w -]*limit", re.I)
RESETS = re.compile(r'resets (?:at )?(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(([^)]+)\))?', re.I)


def classify(reason: str, now: datetime) -> Failure:
    """A failure from its text: `limited` when it names a usage limit, with `resets_at` (ISO, UTC)
    as the next time the message names, in its zone, after `now`."""
    reason = reason.strip()[-2000:] or 'the review failed'
    if not LIMIT.search(reason):
        return {'status': 'failed', 'reason': reason}
    out: Failure = {'status': 'limited', 'reason': reason}
    match = RESETS.search(reason)
    if match:
        hour, minute, half, zone = int(match[1]), int(match[2] or 0), (match[3] or '').lower(), match[4]
        hour = hour % 12 + (12 if half == 'pm' else 0) if half else hour
        zone = (zone or 'UTC').strip()
        try:
            tz = timezone.utc if zone.upper() == 'UTC' else ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            return out
        if hour < 24 and minute < 60:
            local = now.astimezone(tz)
            at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if at <= local:
                at += timedelta(days=1)
            out['resets_at'] = at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return out


def valid(value: Any) -> Failure | None:
    """`value` as a failure, or None when it isn't one."""
    if not isinstance(value, dict) or value.get('status') not in FAILURES or not isinstance(value.get('reason'), str):
        return None
    out = {'status': value['status'], 'reason': value['reason']}
    if isinstance(value.get('resets_at'), str):
        out['resets_at'] = value['resets_at']
    return out


def dumps(failure: Failure) -> str:
    return json.dumps(failure, sort_keys=True, separators=(',', ':'))


def line(failure: Failure) -> str:
    return f'{ERROR_MARKER} {dumps(failure)}'


def loads(text: str | None) -> Failure | None:
    try:
        return valid(json.loads(text or ''))
    except ValueError:
        return None


def from_text(text: str | None) -> Failure | None:
    """The last `momayezi-error:` line or marker in a log or check-run text."""
    found = re.findall(rf'{re.escape(ERROR_MARKER)} (\{{.*?\}})(?: -->|\s*$)', text or '', re.M)
    return loads(found[-1]) if found else None
