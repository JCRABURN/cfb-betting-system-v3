.PHONY: safety test verify-cfbd verify-migrations

YEAR ?= 2025
WEEK ?= 10

test:
	python -m pytest -q

safety:
	python scripts/verify_repo_safety.py

verify-migrations:
	python -m scripts.verify_migrations

# One real call per CFBD endpoint fetch_stats.py/backfill_historical_stats.py use;
# checks the field names those scripts assume against the live response.
# Requires CFBD_API_KEY in .env or the environment.
verify-cfbd:
	python verify_cfbd_fields.py --year $(YEAR) --week $(WEEK)
