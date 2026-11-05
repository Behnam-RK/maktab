"""Every constant both ends of the momayez wire share. nameless hosts the other end; change these here only."""

CHECK_RUN = 'momayez'
LABEL = 'review'
WORKFLOW = 'momayez.yaml'
WORKFLOW_INPUTS = ('ref', 'ledger')

REVIEWER_MARKER = 'momayez-ledger:v2'
EDITOR_MARKER = 'momayezi-editor-ledger:v2'
# A new loop's round 1: the PR's review history is not its prior.
EDITOR_RESET = f'<!-- {EDITOR_MARKER} null -->'
FINDING_MARKER = 'momayez-finding:'
# A review that left no ledger says why: `<!-- momayezi-error: {json} -->` in a check run's text,
# the same line (unwrapped) last in a pod log, or ERROR_FILE beside ledger.json in the artifact.
ERROR_MARKER = 'momayezi-error:'
ERROR_FILE = 'error.json'
FAILURES = ('failed', 'limited')

# GitHub's limit on a check run's output.text and on a comment body. Measured in
# UTF-8 bytes, which is never fewer than GitHub's own count.
CAP = 65535
# workflow_dispatch caps all inputs together at the same size; leave room for `ref`.
DISPATCH_CAP = 60000

POLL_FIRST = 15.0
POLL_MAX = 30.0
POLL_BACKOFF = 1.5
WAIT_TIMEOUT = 1200.0
# The channel forgets a request after this, so a lost review stops costing API calls.
PENDING_TTL = 3600.0

# --- reviewer backends (docs/momayezi-remote.md, "Backends")

BACKENDS = ('gh-label', 'gh-dispatch', 'k8s-job')
PR_COMMENTS = ('auto', 'all', 'none')
CONFIG_FILE = '.momayez.toml'

# gh-dispatch: momayez.yaml takes these inputs, names its run RUN_NAME, and leaves the ledger
# (`ledger.json`) in the ARTIFACT artifact; `post: false` skips momayez-post.
DISPATCH_INPUTS = ('pr', 'ref', 'head', 'ledger', 'post')
RUN_NAME = 'momayez {target}@{head}'
ARTIFACT = 'momayez-ledger'

# k8s-job: the Job template's placeholders, the labels the plugin sets, and the ConfigMap the
# runner reads its prior ledger from (well under the 1 MiB ConfigMap limit).
PLACEHOLDERS = ('name', 'namespace', 'repo', 'target_flag', 'target', 'head', 'ledger_configmap')
K8S_HEAD_LABEL = 'momayez.maktab/head'
K8S_TARGET_ANNOTATION = 'momayez.maktab/target'
LEDGER_KEY = 'ledger.json'
CONFIGMAP_CAP = 900000
