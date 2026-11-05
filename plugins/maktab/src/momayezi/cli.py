"""momayezi-post, -prior, -wait, -review and the channel, behind one argument parser."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import backend as backends
from . import failure as failures
from . import ledger as ledgers
from . import poll, post, prior, review
from .github import Gh, GhError, Target
from .protocol import ERROR_FILE, LEDGER_KEY, REVIEWER_MARKER, WAIT_TIMEOUT


def _ids(text: str) -> set[int]:
    return {int(i) for i in text.split(',') if i.strip()}


def _handle(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict) or 'head_sha' not in value:
        raise ValueError('a handle is a JSON object with a head_sha')
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='momayezi')
    sub = parser.add_subparsers(dest='command', required=True)
    target = argparse.ArgumentParser(add_help=False)
    target.add_argument('target', type=Target.parse, help='PR number, or a branch with no PR')
    target.add_argument('--repo', help='owner/name (default: $GITHUB_REPOSITORY, else the current repo)')

    post_ = sub.add_parser('post', parents=[target],
                           help='post the ledger on stdin as the momayez check run and a PR review')
    post_.add_argument('--error', type=Path, help="instead, post this error.json as a failed check run on --head")
    post_.add_argument('--head', help='the commit the failed review was for (with --error)')
    sub.add_parser('prior', parents=[target], help='print the newest prior ledger, or nothing')
    wait = sub.add_parser('wait', parents=[target], help='block until the review of HEAD_SHA lands')
    wait.add_argument('head_sha')
    wait.add_argument('--known', type=_ids, default=set(), help='check-run ids to ignore, comma-separated')
    wait.add_argument('--handle', type=_handle, help="the backend's handle from request_review's wait hint")
    wait.add_argument('--timeout', type=float, default=WAIT_TIMEOUT, help='seconds (default %(default)s)')
    wait.add_argument('--queue-timeout', type=float,
                      help='give up after this many seconds queued, before any runner took it (default: --timeout)')
    rev = sub.add_parser('review', help='review HEAD on a fresh clone and print the ledger marker')
    rev.add_argument('--repo', required=True, help='owner/name')
    which = rev.add_mutually_exclusive_group(required=True)
    which.add_argument('--pr', type=int)
    which.add_argument('--ref')
    rev.add_argument('--head', required=True, help='the commit to review; refused if the target moved')
    rev.add_argument('--ledger-file', type=Path, help='the prior ledger JSON (empty: round 1)')
    rev.add_argument('--workdir', type=Path, help='where to clone (default: a new temp dir)')
    rev.add_argument('--out', type=Path, help='also write ledger.json, or error.json on failure, here')
    rev.add_argument('--follow-rebase', action='store_true',
                     help='review a head that moved if it is the same change rebased (patch-id)')
    rev.add_argument('--no-project-memory', dest='memory', action='store_false',
                     help="don't pass the base branch's CLAUDE.md/AGENTS.md to the session")
    sub.add_parser('channel', help='run the MCP channel server on stdio')
    return parser


def _wait(args: argparse.Namespace) -> dict:
    handle = args.handle or {'backend': 'gh-label', **args.target.meta(), 'head_sha': args.head_sha,
                             'known': sorted(args.known)}
    return poll.wait(backends.revive(handle, lambda: Gh.here(args.repo)), handle, args.timeout,
                     args.queue_timeout)


def _review(args: argparse.Namespace) -> str:
    target = Target(pr=args.pr) if args.pr else Target(ref=args.ref)
    try:
        text = args.ledger_file.read_text(encoding='utf-8') if args.ledger_file else ''
        workdir = args.workdir or Path(tempfile.mkdtemp(prefix='momayez-'))
        found = review.review(Gh(args.repo), target, args.head, text, workdir,
                              follow_rebase=args.follow_rebase, memory=args.memory)
    except (GhError, ledgers.LedgerError, review.ReviewError, ValueError, OSError) as exc:
        why = exc.failure if isinstance(exc, review.ReviewError) else {'status': 'failed', 'reason': str(exc)}
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / ERROR_FILE).write_text(failures.dumps(why), encoding='utf-8')
        print(failures.line(why))  # the last line a pod log or a CI step shows
        raise
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / LEDGER_KEY).write_text(ledgers.dumps(found), encoding='utf-8')
    return ledgers.to_marker(found, REVIEWER_MARKER)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'channel':
        from .channel import serve
        return serve()
    try:
        if args.command == 'post' and args.error:
            why = failures.loads(args.error.read_text(encoding='utf-8'))
            if why is None or not args.head:
                raise ValueError('--error needs a valid error.json and --head')
            print(post.error_run(Gh.here(args.repo), args.head, why))
        elif args.command == 'post':
            print(post.publish(Gh.here(args.repo), args.target, ledgers.loads(sys.stdin.read())))
        elif args.command == 'prior':
            found = prior.find(Gh.here(args.repo), args.target)
            if found:
                print(ledgers.dumps(found))
        elif args.command == 'review':
            print(_review(args))
        else:
            print(json.dumps(_wait(args)))
    except (GhError, ledgers.LedgerError, review.ReviewError, ValueError, OSError) as exc:
        print(f'momayezi-{args.command}: {exc}', file=sys.stderr)
        return 1
    return 0


def post_main() -> int:
    return main(['post', *sys.argv[1:]])


def prior_main() -> int:
    return main(['prior', *sys.argv[1:]])


def wait_main() -> int:
    return main(['wait', *sys.argv[1:]])


def review_main() -> int:
    return main(['review', *sys.argv[1:]])
