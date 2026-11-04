# Gate discovery

First hit wins:

1. `Taskfile.yml` check task
2. `Makefile` check or test target
3. `justfile`
4. `package.json` check or test scripts
5. `noxfile.py` or `tox.ini`
6. `pyproject.toml` test config
7. `.pre-commit-config.yaml`
8. What CI runs

Nothing found: ask the user once, accepting "none".

## Baseline

Record the exit status, not a grep of the output. If red, also record the
failing set: test names, else the failure count. Later runs are red only
beyond it: a name not in the set, or a higher count.
