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
| Artifact | `momayez-ledger`, holding `ledger.json` |
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
- `momayezi-wait <pr|ref> <head_sha> [--handle <json>]`: waits for the next
  check run, or for the review the handle names.
- `momayezi-review --repo o/n --pr N|--ref B --head <sha> [--ledger-file f]`:
  clones the head and runs one review-only round. It takes the repo from
  `--repo` and needs only a read-only `GH_TOKEN`. It refuses a fork or a moved
  head, and prints the ledger marker as its last line.
- `momayezi-prior` in a dispatched run reads its `ledger` input, PR or branch.
