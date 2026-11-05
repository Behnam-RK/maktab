"""momayezi-post: publish a review-only ledger as the `momayez` check run and one PR review."""

from __future__ import annotations

from typing import Any

from . import failure as failures
from . import ledger as ledgers
from .github import Gh, GhError, Target
from .protocol import CHECK_RUN, FINDING_MARKER, REVIEWER_MARKER

ORDER = {'critical': 0, 'major': 1, 'minor': 2, 'nit': 3}


def place(target: Target, repo: str, ledger: ledgers.Ledger) -> ledgers.Ledger:
    """Fill in what the CI run could not learn: the repo and the PR or ref."""
    where = dict(ledger['target'], repo=repo)
    where.pop('pr', None)
    where.pop('ref', None)
    where.update({'pr': target.pr} if target.pr else {'ref': target.ref})
    return ledgers.validate(dict(ledger, target=where))


def fresh(ledger: ledgers.Ledger) -> list[dict[str, Any]]:
    """Open findings raised or re-raised this round, most severe first."""
    found = [f for f in ledger['findings']
             if f.get('last_round', f['round']) == ledger['round'] and f['state'] == 'open']
    return sorted(found, key=lambda f: (ORDER[f['severity']], f['id']))


def where(finding: dict[str, Any]) -> str:
    at = finding['at']
    end = f'-{at["end_line"]}' if at.get('end_line', at['line']) != at['line'] else ''
    return f'{at["path"]}:{at["line"]}{end}'


def headline(finding: dict[str, Any]) -> str:
    return f'**{finding["id"]}** {finding["severity"]} · {finding["lens"]} · `{where(finding)}`'


def detail(finding: dict[str, Any]) -> str:
    parts = [f'{headline(finding)} (confidence {finding["confidence"]})', '', finding['claim']]
    if finding['evidence']:
        parts += ['', '\n'.join('> ' + line for line in finding['evidence'].splitlines())]
    if finding['fix']:
        parts += ['', f'**Fix:** {finding["fix"]}']
    return '\n'.join(parts)


def summary(ledger: ledgers.Ledger) -> str:
    counts = {s: 0 for s in ORDER}
    for f in ledger['findings']:
        if f['state'] == 'open':
            counts[f['severity']] += 1
    effort = f' · effort {ledger["effort"]}' if 'effort' in ledger else ''
    lines = [
        f'Round {ledger["round"]} · {ledger["verdict"]} · lenses {", ".join(ledger["lenses"])} '
        f'on {ledger["model"]}{effort} · tier {ledger["tier"]}',
        'Open: ' + ', '.join(f'{n} {s}' for s, n in counts.items()),
    ]
    lines += [f'- {headline(f)}: {f["claim"]}' for f in fresh(ledger)]
    if ledger['truncated']:
        lines.append('_Truncated to fit GitHub: nits, then minor evidence, then minor findings, '
                     'and last all evidence were dropped._')
    lines += [f'> {note}' for note in ledger.get('notes', [])]
    return '\n'.join(lines)[:60000]


def finish(gh: Gh, head: str, body: dict[str, Any]) -> None:
    """Complete the `momayez` check run on `head`: the one the workflow opened as in progress,
    finished in place rather than doubled, else a new one."""
    open_runs = [r for r in gh.runs(head) if r.get('status') != 'completed']
    if open_runs:
        gh.api(f'repos/{{repo}}/check-runs/{open_runs[0]["id"]}', 'PATCH', body)
    else:
        gh.api('repos/{repo}/check-runs', 'POST', dict(body, name=CHECK_RUN, head_sha=head))


def check_run(gh: Gh, ledger: ledgers.Ledger) -> None:
    output = {
        'title': f'momayez: {ledger["verdict"]}',
        'summary': summary(ledger),
        'text': ledgers.to_marker(ledger, REVIEWER_MARKER),
    }
    body = {'status': 'completed', 'conclusion': 'neutral', 'output': output}
    finish(gh, ledger['target']['head_sha'], body)
    # A rebased head's review also lands on the head that was requested, where waiters look.
    if ledger['target'].get('rebased_from'):
        try:
            finish(gh, ledger['target']['rebased_from'], body)
        except GhError:  # an old head GitHub no longer serves; the review itself has landed
            pass


def error_run(gh: Gh, head: str, why: failures.Failure) -> str:
    """A review that left no ledger, posted as a failed `momayez` check run that says why."""
    told = why['reason'] + (f' (resets {why["resets_at"]})' if 'resets_at' in why else '')
    finish(gh, head, {'status': 'completed', 'conclusion': 'failure', 'output': {
        'title': f'momayez: {why["status"]}', 'summary': told[:60000], 'text': f'<!-- {failures.line(why)} -->'}})
    return why['status']


def inline(finding: dict[str, Any]) -> dict[str, Any]:
    at = finding['at']
    comment = {'path': at['path'], 'line': at['line'], 'side': 'RIGHT',
               'body': f'{detail(finding)}\n\n<!-- {FINDING_MARKER}{finding["id"]} -->'}
    if at.get('end_line', at['line']) > at['line']:
        comment.update(start_line=at['line'], line=at['end_line'], start_side='RIGHT')
    return comment


def review(gh: Gh, pr: int, ledger: ledgers.Ledger) -> str:
    found = fresh(ledger)
    if not found:
        return 'none'
    head = ledger['target']['head_sha']
    in_diff = [f for f in found if f['in_diff']]
    outside = [f for f in found if not f['in_diff']]

    def post(comments: list[dict[str, Any]], body_findings: list[dict[str, Any]]) -> None:
        body = '\n\n'.join(['**momayez** review: ' + ledger['verdict']] + [detail(f) for f in body_findings])
        gh.api(f'repos/{{repo}}/pulls/{pr}/reviews', 'POST',
               {'commit_id': head, 'event': 'COMMENT', 'body': body[:60000], 'comments': comments})

    try:
        post([inline(f) for f in in_diff], outside)
        return 'inline'
    except GhError as exc:
        # One line outside the diff rejects the whole review: fall back to the body.
        if exc.status != 422 or not in_diff:
            raise
    post([], found)
    return 'body'


def publish(gh: Gh, target: Target, ledger: ledgers.Ledger, with_check_run: bool = True) -> str:
    """Post the ledger. Only a GitHub App may create check runs, so a caller posting with its
    own token (k8s-job under pr_comments=all) passes with_check_run=False."""
    ledger = ledgers.fit(place(target, gh.repo, ledger), REVIEWER_MARKER)
    if with_check_run:
        check_run(gh, ledger)
    return review(gh, target.pr, ledger) if target.pr else 'none'
