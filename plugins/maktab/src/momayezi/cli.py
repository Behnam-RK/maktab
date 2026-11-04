"""momayezi-post, momayezi-prior, momayezi-wait and the channel, behind one argument parser."""

from __future__ import annotations

import argparse
import json
import sys

from . import ledger as ledgers
from . import poll, post, prior
from .github import Gh, GhError, Target
from .protocol import WAIT_TIMEOUT


def _ids(text: str) -> set[int]:
    return {int(i) for i in text.split(',') if i.strip()}


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
    wait.add_argument('--timeout', type=float, default=WAIT_TIMEOUT, help='seconds (default %(default)s)')
    sub.add_parser('channel', help='run the MCP channel server on stdio')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == 'channel':
        from .channel import serve
        return serve()
    try:
        gh = Gh.here(args.repo)
        if args.command == 'post':
            print(post.publish(gh, args.target, ledgers.loads(sys.stdin.read())))
        elif args.command == 'prior':
            found = prior.find(gh, args.target)
            if found:
                print(ledgers.dumps(found))
        else:
            print(json.dumps(poll.wait(gh, args.target, args.head_sha, args.known, args.timeout)))
    except (GhError, ledgers.LedgerError, OSError) as exc:
        print(f'momayezi-{args.command}: {exc}', file=sys.stderr)
        return 1
    return 0


def post_main() -> int:
    return main(['post', *sys.argv[1:]])


def prior_main() -> int:
    return main(['prior', *sys.argv[1:]])


def wait_main() -> int:
    return main(['wait', *sys.argv[1:]])
