"""momayezi-post, -prior, -wait, -review and the channel, behind one argument parser."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import backend as backends
from . import ledger as ledgers
from . import poll, post, prior, review
from .github import Gh, GhError, Target
from .protocol import REVIEWER_MARKER, WAIT_TIMEOUT


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

    sub.add_parser('post', parents=[target],
                   help='post the ledger on stdin as the momayez check run and a PR review')
    sub.add_parser('prior', parents=[target], help='print the newest prior ledger, or nothing')
    wait = sub.add_parser('wait', parents=[target], help='block until the review of HEAD_SHA lands')
    wait.add_argument('head_sha')
    wait.add_argument('--known', type=_ids, default=set(), help='check-run ids to ignore, comma-separated')
    wait.add_argument('--handle', type=_handle, help="the backend's handle from request_review's wait hint")
    wait.add_argument('--timeout', type=float, default=WAIT_TIMEOUT, help='seconds (default %(default)s)')
    rev = sub.add_parser('review', help='review HEAD on a fresh clone and print the ledger marker')
    rev.add_argument('--repo', required=True, help='owner/name')
    which = rev.add_mutually_exclusive_group(required=True)
    which.add_argument('--pr', type=int)
    which.add_argument('--ref')
    rev.add_argument('--head', required=True, help='the commit to review; refused if the target moved')
    rev.add_argument('--ledger-file', type=Path, help='the prior ledger JSON (empty: round 1)')
    rev.add_argument('--workdir', type=Path, help='where to clone (default: a new temp dir)')
    sub.add_parser('channel', help='run the MCP channel server on stdio')
    return parser


def _wait(args: argparse.Namespace) -> dict:
    handle = args.handle or {'backend': 'gh-label', **args.target.meta(), 'head_sha': args.head_sha,
                             'known': sorted(args.known)}
    return poll.wait(backends.revive(handle, lambda: Gh.here(args.repo)), handle, args.timeout)


def _review(args: argparse.Namespace) -> str:
    target = Target(pr=args.pr) if args.pr else Target(ref=args.ref)
    text = args.ledger_file.read_text(encoding='utf-8') if args.ledger_file else ''
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix='momayez-'))
    found = review.review(Gh(args.repo), target, args.head, text, workdir)
    return ledgers.to_marker(found, REVIEWER_MARKER)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'channel':
        from .channel import serve
        return serve()
    try:
        if args.command == 'post':
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
