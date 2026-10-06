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
    v0009_daily_refresh_revisions,
    v0010_manual_contextual_adjustments,
    v0011_complete_postgame_audits,
    v0012_weekly_diagnostics,
    v0013_provider_ingestion_custody,
    v0014_official_weekly_controller,
    v0015_live_sportsbook_recommendations,
    v0016_sportsbook_postgame_audits,
    v0017_production_context_evidence,
    v0018_card_context_snapshot_identity,
    v0019_football_identity_foundation,
    v0020_mixed_pickem_custody,
    v0021_totals_shadow_top_five,
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
    v0009_daily_refresh_revisions,
    v0010_manual_contextual_adjustments,
    v0011_complete_postgame_audits,
    v0012_weekly_diagnostics,
    v0013_provider_ingestion_custody,
    v0014_official_weekly_controller,
    v0015_live_sportsbook_recommendations,
    v0016_sportsbook_postgame_audits,
    v0017_production_context_evidence,
    v0018_card_context_snapshot_identity,
    v0019_football_identity_foundation,
    v0020_mixed_pickem_custody,
    v0021_totals_shadow_top_five,
)
