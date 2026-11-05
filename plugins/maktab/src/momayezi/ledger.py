"""The momayezi ledger: schema validation, canonical JSON, wire markers and the size cap."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from .protocol import CAP

SCHEMA_NAME = 'ledger.schema.json'
# Installed from the wheel, the schema sits beside this module; in the plugin
# tree it lives with the skill that documents it.
SCHEMA_PATHS = (
    Path(__file__).resolve().parent / SCHEMA_NAME,
    Path(__file__).resolve().parents[2] / 'skills' / 'momayezi' / 'references' / SCHEMA_NAME,
)

Ledger = dict[str, Any]


class LedgerError(ValueError):
    pass


@cache
def schema() -> dict[str, Any]:
    for path in SCHEMA_PATHS:
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8'))
    raise LedgerError(f'{SCHEMA_NAME} not found beside the package or the skill')


# --- validation: the JSON Schema keywords ledger.schema.json uses, and no others.

ANNOTATIONS = {'$schema', 'title', 'description', 'definitions'}
TYPES = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'boolean': lambda v: isinstance(v, bool),
}


def _check(value: Any, node: dict[str, Any], root: dict[str, Any], at: str, errors: list[str]) -> None:
    unknown = set(node) - ANNOTATIONS - {
        '$ref', 'type', 'enum', 'required', 'properties', 'additionalProperties',
        'items', 'minimum', 'maximum', 'minLength', 'pattern',
    }
    if unknown:
        raise LedgerError(f'schema uses unsupported keywords at {at}: {sorted(unknown)}')
    if '$ref' in node:
        target = root
        for part in node['$ref'].removeprefix('#/').split('/'):
            target = target[part]
        _check(value, target, root, at, errors)
        return
    if 'enum' in node and value not in node['enum']:
        errors.append(f'{at}: {value!r} is not one of {node["enum"]}')
        return
    if 'type' in node and not TYPES[node['type']](value):
        errors.append(f'{at}: expected {node["type"]}')
        return
    if isinstance(value, dict):
        for key in node.get('required', ()):
            if key not in value:
                errors.append(f'{at}: missing {key}')
        props = node.get('properties', {})
        for key, item in value.items():
            if key in props:
                _check(item, props[key], root, f'{at}.{key}', errors)
            elif node.get('additionalProperties') is False:
                errors.append(f'{at}: unexpected {key}')
    if isinstance(value, list) and 'items' in node:
        for i, item in enumerate(value):
            _check(item, node['items'], root, f'{at}[{i}]', errors)
    if isinstance(value, int) and not isinstance(value, bool):
        if 'minimum' in node and value < node['minimum']:
            errors.append(f'{at}: {value} is below {node["minimum"]}')
        if 'maximum' in node and value > node['maximum']:
            errors.append(f'{at}: {value} is above {node["maximum"]}')
    if isinstance(value, str):
        if len(value) < node.get('minLength', 0):
            errors.append(f'{at}: shorter than {node["minLength"]}')
        if 'pattern' in node and not re.search(node['pattern'], value):
            errors.append(f'{at}: {value!r} does not match {node["pattern"]}')


def errors(value: Any) -> list[str]:
    found: list[str] = []
    _check(value, schema(), schema(), '$', found)
    return found


def validate(value: Any) -> Ledger:
    found = errors(value)
    if found:
        raise LedgerError('invalid ledger: ' + '; '.join(found[:5]))
    return value


# --- a lenient editor ledger: target, round and each finding's id, state, at, claim, reason.

HEADER = ('lenses', 'model', 'tier', 'verdict', 'cited_files', 'truncated')


def complete_editor(raw: Any, last: Callable[[], Ledger | None]) -> Ledger:
    """`raw` as a full ledger: as it is when it validates, else filled from `last()`, the last
    remote ledger, finding by id. A finding it lacks is refused, never invented."""
    if not errors(raw):
        return raw
    if not isinstance(raw, dict) or not isinstance(raw.get('findings'), list):
        validate(raw)  # raises: not even a lean ledger
    found = last()
    if found is None:
        raise LedgerError('a lean editor ledger needs the last reviewer ledger, and none has arrived for '
                          'this target: send the full ledger, or wait for the review to land')
    prior = {f['id']: f for f in found['findings']}
    findings = []
    for item in raw['findings']:
        ident = item.get('id') if isinstance(item, dict) else None
        if ident not in prior:
            raise LedgerError(f'{ident} is not in the last remote ledger: send its full finding')
        findings.append({**prior[ident], **item})
    out = {'version': found['version'], **{k: copy.deepcopy(found[k]) for k in HEADER}, **raw}
    if 'last_id' in found and 'last_id' not in raw:  # a truncated ledger's dropped ids stay issued
        out['last_id'] = found['last_id']
    return validate(dict(out, findings=findings))


# --- canonical JSON: loads(dumps(x)) == x, and dumps(loads(s)) == s for canonical s.

def dumps(ledger: Ledger) -> str:
    return json.dumps(validate(ledger), sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def loads(text: str) -> Ledger:
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise LedgerError(f'not JSON: {exc}') from None
    return validate(value)


# --- markers: <!-- <kind> <json> --> inside a check run or a comment body.

def to_marker(ledger: Ledger, kind: str) -> str:
    # `<` and `>` only occur inside JSON strings, so escaping them is lossless and
    # keeps an evidence string holding `-->` from closing the comment.
    body = dumps(ledger).replace('<', '\\u003c').replace('>', '\\u003e')
    return f'<!-- {kind} {body} -->'


def from_marker(text: str | None, kind: str) -> Ledger | None:
    """The last marker of `kind` in `text`, validated; None when absent."""
    found = re.findall(rf'<!-- {re.escape(kind)} (.*?) -->', text or '', re.DOTALL)
    return loads(found[-1]) if found else None


def size(text: str) -> int:
    return len(text.encode('utf-8'))


# --- the cap: shed the least important detail first, and say so.

def _shed(ledger: Ledger, step: int) -> None:
    findings = ledger['findings']
    if step == 0:
        findings[:] = [f for f in findings if f['severity'] != 'nit']
    elif step == 1:
        for f in findings:
            if f['severity'] == 'minor':
                f['evidence'] = ''
    elif step == 2:
        findings[:] = [f for f in findings if f['severity'] != 'minor']
    else:
        for f in findings:
            f['evidence'] = ''


def highest(ledger: Ledger) -> int:
    """The highest finding number this ledger has issued, dropped findings included."""
    ids = [int(f['id'][1:]) for f in ledger['findings']]
    return max([ledger.get('last_id', 0), *ids])


def fit(ledger: Ledger, kind: str, cap: int = CAP) -> Ledger:
    """A copy of `ledger` whose marker fits `cap` bytes, `truncated` set if anything went.
    `last_id` keeps the highest id, so a dropped finding's id is never issued again."""
    out = copy.deepcopy(validate(ledger))
    last = highest(out)
    for step in range(4):
        if size(to_marker(out, kind)) <= cap:
            return out
        _shed(out, step)
        out['truncated'] = True
        if last:
            out['last_id'] = last
    if size(to_marker(out, kind)) > cap:
        raise LedgerError(f'ledger does not fit {cap} bytes even without evidence')
    return out
