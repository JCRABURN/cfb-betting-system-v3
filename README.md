# CFB Betting System V3

This repository is the isolated development copy of the College Football
Spread Betting System. Repository-wide agent and data-integrity rules are in
`AGENTS.md`.

## Reproducible development baseline

Python 3.11 is the supported automation runtime. Runtime packages and their
transitive dependencies are pinned in `requirements.txt`; test-only packages
are pinned in `requirements-dev.txt`. No new top-level package was introduced
by this lock—the existing `requests` and `pytest` dependencies are now resolved
deterministically.

Create an isolated virtual environment, then install and verify with:

```text
python -m pip install --requirement requirements-dev.txt
python scripts/verify_repo_safety.py
python -m pytest -q
```

Dependency updates must be intentional, must keep every requirement exactly
pinned, and must pass both verification commands.

## Workflow safety

Pull requests run the complete offline test suite with read-only repository
permissions. The copied production workflows have no schedule trigger in V3,
are serialized with concurrency controls, and contain an allow-list guard that
keeps their data-writing jobs inert outside `JCRABURN/cfb-betting-system`.

Do not weaken or remove those controls without explicit repository-owner
approval and a dedicated pull request.

## Database migrations

Schema changes use ordered, checksummed migration modules and a
`schema_migrations` ledger. Verify the entire migration chain against a
disposable copy of `data/cfb.db` with:

```text
python -m scripts.verify_migrations
```

The authoritative database is never opened for writing by that command. See
`migrations/README.md` for migration and recovery requirements.
