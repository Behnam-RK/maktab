# momayezi: the wire protocol

What the plugin and the remote reviewer (nameless hosts it) share. Both ends
must run the same maktab release.

## Constants

Constants in [protocol.py](../src/momayezi/protocol.py):

| What | Value |
|---|---|
| Check run | `momayez`, conclusion `neutral`, ledger in `output.text` |
| Press label | `review`, removed then re-added on each request |
| Workflow | `momayez.yaml`, inputs `ref`, `ledger`; gh-dispatch adds `pr`, `head`, `post` |
| Artifact | `momayez-ledger`, holding `ledger.json` or `error.json` |
| Failure | `momayezi-error: {json}`: a pod log's last line, or `<!-- … -->` in a failed check run |
| k8s | label `momayez.maktab/head`, annotation `momayez.maktab/target` |
| Markers | `<!-- momayez-ledger:v2 <json> -->`, editor comment `<!-- momayezi-editor-ledger:v2 <json> -->` |
| Size cap | 65,535 bytes; drops nits, then minor evidence, minor findings, all evidence; `truncated`, `last_id` |
| Version | `v2` since 2.3.0; `v1` is not read (open loops restart). One pin for both ends. |

## CI scripts

For CI, pin a release: `uvx --from git+https://github.com/Behnam-RK/maktab@maktab--vX.Y.Z <script>`.
`momayezi-post`, `-prior` and `-wait` read `GH_TOKEN` (an App or Actions
token, to create check runs) and `GITHUB_REPOSITORY`:

- `momayezi-post <pr|ref>`: posts the ledger on stdin as the check run, plus
  one COMMENT review that inlines this round's in-diff findings.
- `momayezi-prior <pr|ref>`: prints the newest prior ledger.
- `momayezi-wait <pr|ref> <head_sha> [--handle <json>] [--timeout s]
  [--queue-timeout s]`: waits for the next check run, or for the review the
  handle names. Its JSON result has `status` and `phase` (`queued`, `running`,
  `done`), with `queued_for` and `ran_for` seconds on a `timeout`.
- `momayezi-review --repo o/n --pr N|--ref B --head <sha> [--ledger-file f]
  [--out dir] [--follow-rebase] [--no-project-memory]`: clones the head and
  runs one review-only round, for every backend. It needs only a read-only
  `GH_TOKEN`, refuses a fork, and prints the ledger marker as its last line.
  - A moved head is refused, unless `--follow-rebase` and its patch-id over
    `merge-base..head` matches the requested one: then the new head is
    reviewed, with `target.rebased_from` and a note.
  - A failure prints `momayezi-error: {status, reason, resets_at?}` last
    and exits 1. `status` is `limited` for a usage limit, `resets_at` when
    the message names a time.
  - `--out` also writes `ledger.json`, or `error.json`: upload the directory
    as the `momayez-ledger` artifact `if: always()`.
- `momayezi-post <pr|ref> --error error.json --head <sha>`: posts a failure as
  a `failure` check run, for gh-label to read back.
- `momayezi-prior` in a dispatched run reads its `ledger` input, PR or branch.
