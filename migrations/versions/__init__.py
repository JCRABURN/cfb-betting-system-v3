"""Immutable, ordered migration modules.

Never edit a migration after it has been merged and applied. Add the next
numbered module and append it to ``MIGRATION_MODULES`` instead.
"""

from migrations.versions import (
    v0001_initial_schema,
    v0002_team_game_stats_features,
    v0003_lookup_indexes,
    v0004_supplemental_game_dates,
    v0005_immutable_contest_lines,
    v0006_separate_business_entities,
    v0007_confidence_ranking_policies,
    v0008_reproducible_card_runs,
)


MIGRATION_MODULES = (
    v0001_initial_schema,
    v0002_team_game_stats_features,
    v0003_lookup_indexes,
    v0004_supplemental_game_dates,
    v0005_immutable_contest_lines,
    v0006_separate_business_entities,
    v0007_confidence_ranking_policies,
    v0008_reproducible_card_runs,
)
