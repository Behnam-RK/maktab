"""Every constant both ends of the momayez wire share. nameless hosts the other end; change these here only."""

CHECK_RUN = 'momayez'
LABEL = 'review'
WORKFLOW = 'momayez.yaml'
WORKFLOW_INPUTS = ('ref', 'ledger')

REVIEWER_MARKER = 'momayez-ledger:v1'
EDITOR_MARKER = 'momayezi-editor-ledger:v1'
FINDING_MARKER = 'momayez-finding:'

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
