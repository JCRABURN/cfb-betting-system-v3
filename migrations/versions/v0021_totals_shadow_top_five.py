"""Add isolated totals-shadow custody and unified Top-5 candidate storage."""

from __future__ import annotations

import sqlite3


VERSION = 21
NAME = "totals_shadow_top_five"


STATEMENTS = (
    """
    CREATE TABLE total_model_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
        model_version TEXT NOT NULL CHECK (length(trim(model_version)) > 0),
        feature_schema_version TEXT NOT NULL
            CHECK (length(trim(feature_schema_version)) > 0),
        configuration_version TEXT NOT NULL
            CHECK (length(trim(configuration_version)) > 0),
        code_commit_sha TEXT NOT NULL CHECK (
            length(code_commit_sha) = 40
            AND lower(code_commit_sha) NOT GLOB '*[^0-9a-f]*'
        ),
        data_snapshot_sha256 TEXT NOT NULL CHECK (
            length(data_snapshot_sha256) = 64
            AND lower(data_snapshot_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        lifecycle_stage TEXT NOT NULL CHECK (lifecycle_stage IN ('research', 'shadow')),
        status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
        failure_reason TEXT CHECK (
            (status = 'completed' AND failure_reason IS NULL)
            OR (status = 'failed' AND length(trim(failure_reason)) > 0)
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE total_model_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prediction_key TEXT NOT NULL UNIQUE CHECK (length(trim(prediction_key)) > 0),
        total_model_run_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        projected_total REAL NOT NULL CHECK (
            typeof(projected_total) IN ('integer', 'real') AND projected_total >= 0
        ),
        uncertainty_points REAL NOT NULL CHECK (
            typeof(uncertainty_points) IN ('integer', 'real') AND uncertainty_points > 0
        ),
        home_stats_as_of_season INTEGER NOT NULL CHECK (home_stats_as_of_season >= 1869),
        home_stats_as_of_week INTEGER NOT NULL CHECK (home_stats_as_of_week >= 0),
        away_stats_as_of_season INTEGER NOT NULL CHECK (away_stats_as_of_season >= 1869),
        away_stats_as_of_week INTEGER NOT NULL CHECK (away_stats_as_of_week >= 0),
        features_as_of_at TEXT NOT NULL CHECK (
            julianday(features_as_of_at) IS NOT NULL
            AND substr(features_as_of_at, -6) = '+00:00'
        ),
        feature_snapshot_sha256 TEXT NOT NULL CHECK (
            length(feature_snapshot_sha256) = 64
            AND lower(feature_snapshot_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (total_model_run_id, game_id),
        FOREIGN KEY (total_model_run_id) REFERENCES total_model_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE total_reliability_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        reliability_policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(reliability_policy_version)) > 0),
        probability_model_version TEXT NOT NULL
            CHECK (length(trim(probability_model_version)) > 0),
        calibration_method TEXT NOT NULL
            CHECK (calibration_method = 'symmetric_logit_scale_v1'),
        calibration_slope REAL NOT NULL CHECK (
            typeof(calibration_slope) IN ('integer', 'real') AND calibration_slope > 0
        ),
        confidence_2_min_probability REAL NOT NULL
            CHECK (confidence_2_min_probability > 0.5),
        confidence_3_min_probability REAL NOT NULL,
        confidence_4_min_probability REAL NOT NULL,
        confidence_5_min_probability REAL NOT NULL
            CHECK (confidence_5_min_probability <= 1.0),
        forecast_tie_direction TEXT NOT NULL
            CHECK (forecast_tie_direction IN ('over', 'under')),
        effective_at TEXT NOT NULL CHECK (
            julianday(effective_at) IS NOT NULL AND substr(effective_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            confidence_2_min_probability < confidence_3_min_probability
            AND confidence_3_min_probability < confidence_4_min_probability
            AND confidence_4_min_probability < confidence_5_min_probability
        )
    )
    """,
    """
    CREATE TABLE total_shadow_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_key TEXT NOT NULL UNIQUE CHECK (length(trim(card_key)) > 0),
        contest_id INTEGER NOT NULL,
        total_model_run_id INTEGER NOT NULL,
        total_reliability_policy_id INTEGER NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        locked_line_snapshot_sha256 TEXT NOT NULL CHECK (
            length(locked_line_snapshot_sha256) = 64
            AND lower(locked_line_snapshot_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        request_sha256 TEXT NOT NULL CHECK (
            length(request_sha256) = 64
            AND lower(request_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_id, version),
        FOREIGN KEY (contest_id) REFERENCES contests(id),
        FOREIGN KEY (total_model_run_id) REFERENCES total_model_runs(id),
        FOREIGN KEY (total_reliability_policy_id) REFERENCES total_reliability_policies(id)
    )
    """,
    """
    CREATE TABLE total_card_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_key TEXT NOT NULL UNIQUE CHECK (length(trim(candidate_key)) > 0),
        total_shadow_card_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        total_model_prediction_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        exact_locked_total REAL NOT NULL CHECK (
            typeof(exact_locked_total) IN ('integer', 'real') AND exact_locked_total >= 0
        ),
        line_effective_at TEXT NOT NULL CHECK (
            julianday(line_effective_at) IS NOT NULL
            AND substr(line_effective_at, -6) = '+00:00'
        ),
        correction_id INTEGER,
        projected_total REAL NOT NULL CHECK (
            typeof(projected_total) IN ('integer', 'real') AND projected_total >= 0
        ),
        uncertainty_points REAL NOT NULL CHECK (
            typeof(uncertainty_points) IN ('integer', 'real') AND uncertainty_points > 0
        ),
        selected_direction TEXT NOT NULL CHECK (selected_direction IN ('over', 'under')),
        raw_over_probability REAL NOT NULL
            CHECK (raw_over_probability >= 0 AND raw_over_probability <= 1),
        calibrated_over_probability REAL NOT NULL CHECK (
            calibrated_over_probability >= 0 AND calibrated_over_probability <= 1
        ),
        selected_probability REAL NOT NULL CHECK (
            selected_probability >= 0.5 AND selected_probability <= 1
        ),
        confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
        reliability_policy_version TEXT NOT NULL
            CHECK (length(trim(reliability_policy_version)) > 0),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (selected_direction = 'over'
                AND selected_probability = calibrated_over_probability)
            OR (selected_direction = 'under'
                AND selected_probability = 1 - calibrated_over_probability)
        ),
        UNIQUE (total_shadow_card_id, locked_line_id),
        UNIQUE (total_shadow_card_id, game_id),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (total_model_prediction_id) REFERENCES total_model_predictions(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (correction_id) REFERENCES contest_line_corrections(id)
    )
    """,
    """
    CREATE TABLE total_card_skips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skip_key TEXT NOT NULL UNIQUE CHECK (length(trim(skip_key)) > 0),
        total_shadow_card_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        game_id INTEGER,
        reason_code TEXT NOT NULL CHECK (
            reason_code IN (
                'missing_locked_total', 'missing_game_identity',
                'missing_total_prediction'
            )
        ),
        line_effective_at TEXT NOT NULL CHECK (
            julianday(line_effective_at) IS NOT NULL
            AND substr(line_effective_at, -6) = '+00:00'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (total_shadow_card_id, locked_line_id),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE total_shadow_card_completions (
        total_shadow_card_id INTEGER PRIMARY KEY,
        locked_line_count INTEGER NOT NULL CHECK (locked_line_count >= 0),
        candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
        skip_count INTEGER NOT NULL CHECK (skip_count >= 0),
        ledger_sha256 TEXT NOT NULL CHECK (
            length(ledger_sha256) = 64
            AND lower(ledger_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        completed_at TEXT NOT NULL CHECK (
            julianday(completed_at) IS NOT NULL AND substr(completed_at, -6) = '+00:00'
        ),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id)
    )
    """,
    """
    CREATE TABLE ats_shadow_calibration_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        reliability_policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(reliability_policy_version)) > 0),
        probability_method_version TEXT NOT NULL
            CHECK (length(trim(probability_method_version)) > 0),
        calibration_method TEXT NOT NULL
            CHECK (calibration_method = 'conservative_linear_margin_v1'),
        required_model_name TEXT NOT NULL CHECK (length(trim(required_model_name)) > 0),
        required_model_version TEXT NOT NULL
            CHECK (length(trim(required_model_version)) > 0),
        probability_per_margin_point REAL NOT NULL CHECK (
            probability_per_margin_point > 0
            AND probability_per_margin_point <= 0.01
        ),
        maximum_selected_probability REAL NOT NULL CHECK (
            maximum_selected_probability > 0.5
            AND maximum_selected_probability <= 0.6
        ),
        missing_prediction_probability REAL NOT NULL
            CHECK (missing_prediction_probability = 0.5),
        empirical_calibration_status TEXT NOT NULL
            CHECK (empirical_calibration_status = 'not_empirically_validated'),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        effective_at TEXT NOT NULL CHECK (
            julianday(effective_at) IS NOT NULL AND substr(effective_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE ats_shadow_calibration_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        contest_card_id INTEGER NOT NULL,
        ats_model_run_id INTEGER NOT NULL,
        ats_shadow_calibration_policy_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status = 'shadow'),
        input_sha256 TEXT NOT NULL CHECK (
            length(input_sha256) = 64
            AND lower(input_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_card_id, ats_shadow_calibration_policy_id),
        FOREIGN KEY (contest_card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (ats_model_run_id) REFERENCES model_runs(id),
        FOREIGN KEY (ats_shadow_calibration_policy_id)
            REFERENCES ats_shadow_calibration_policies(id)
    )
    """,
    """
    CREATE TABLE ats_shadow_calibrated_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_key TEXT NOT NULL UNIQUE CHECK (length(trim(evaluation_key)) > 0),
        ats_shadow_calibration_run_id INTEGER NOT NULL,
        contest_card_id INTEGER NOT NULL,
        contest_pick_id INTEGER NOT NULL,
        ats_model_run_id INTEGER NOT NULL,
        ats_model_prediction_id INTEGER,
        locked_line_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        selected_side TEXT NOT NULL CHECK (selected_side IN ('home', 'away')),
        ats_model_name TEXT NOT NULL CHECK (length(trim(ats_model_name)) > 0),
        ats_model_version TEXT NOT NULL CHECK (length(trim(ats_model_version)) > 0),
        reliability_policy_version TEXT NOT NULL
            CHECK (length(trim(reliability_policy_version)) > 0),
        probability_method_version TEXT NOT NULL
            CHECK (length(trim(probability_method_version)) > 0),
        selected_margin_advantage_points REAL NOT NULL
            CHECK (selected_margin_advantage_points >= 0),
        calibrated_selected_side_probability REAL NOT NULL CHECK (
            calibrated_selected_side_probability >= 0.5
            AND calibrated_selected_side_probability <= 0.6
        ),
        card_generated_at TEXT NOT NULL CHECK (
            julianday(card_generated_at) IS NOT NULL
            AND substr(card_generated_at, -6) = '+00:00'
        ),
        line_effective_at TEXT NOT NULL CHECK (
            julianday(line_effective_at) IS NOT NULL
            AND substr(line_effective_at, -6) = '+00:00'
        ),
        prediction_generated_at TEXT CHECK (
            prediction_generated_at IS NULL OR (
                julianday(prediction_generated_at) IS NOT NULL
                AND substr(prediction_generated_at, -6) = '+00:00'
            )
        ),
        input_sha256 TEXT NOT NULL CHECK (
            length(input_sha256) = 64
            AND lower(input_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (ats_shadow_calibration_run_id, contest_pick_id),
        UNIQUE (ats_shadow_calibration_run_id, locked_line_id),
        FOREIGN KEY (ats_shadow_calibration_run_id)
            REFERENCES ats_shadow_calibration_runs(id),
        FOREIGN KEY (contest_card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (ats_model_run_id) REFERENCES model_runs(id),
        FOREIGN KEY (ats_model_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE ats_shadow_calibration_completions (
        ats_shadow_calibration_run_id INTEGER PRIMARY KEY,
        evaluation_count INTEGER NOT NULL CHECK (evaluation_count >= 0),
        ledger_sha256 TEXT NOT NULL CHECK (
            length(ledger_sha256) = 64
            AND lower(ledger_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        completed_at TEXT NOT NULL CHECK (
            julianday(completed_at) IS NOT NULL AND substr(completed_at, -6) = '+00:00'
        ),
        FOREIGN KEY (ats_shadow_calibration_run_id)
            REFERENCES ats_shadow_calibration_runs(id)
    )
    """,
    """
    CREATE TABLE unified_top_five_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        policy_version TEXT NOT NULL UNIQUE CHECK (length(trim(policy_version)) > 0),
        top_five_count INTEGER NOT NULL CHECK (top_five_count = 5),
        allow_multiple_per_game INTEGER NOT NULL
            CHECK (allow_multiple_per_game IN (0, 1)),
        candidate_score_metric TEXT NOT NULL
            CHECK (candidate_score_metric = 'calibrated_selection_probability'),
        ordering_method TEXT NOT NULL CHECK (
            ordering_method = 'score_desc_market_type_asc_source_id_asc'
        ),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        effective_at TEXT NOT NULL CHECK (
            julianday(effective_at) IS NOT NULL AND substr(effective_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE unified_top_five_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        contest_card_id INTEGER NOT NULL,
        ats_shadow_calibration_run_id INTEGER NOT NULL,
        total_shadow_card_id INTEGER NOT NULL,
        unified_top_five_policy_id INTEGER NOT NULL,
        status TEXT NOT NULL CHECK (status = 'shadow'),
        candidate_input_sha256 TEXT NOT NULL CHECK (
            length(candidate_input_sha256) = 64
            AND lower(candidate_input_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (contest_card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (ats_shadow_calibration_run_id)
            REFERENCES ats_shadow_calibration_runs(id),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id),
        FOREIGN KEY (unified_top_five_policy_id) REFERENCES unified_top_five_policies(id)
    )
    """,
    """
    CREATE TABLE unified_top_five_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_key TEXT NOT NULL UNIQUE CHECK (length(trim(candidate_key)) > 0),
        unified_top_five_run_id INTEGER NOT NULL,
        market_type TEXT NOT NULL CHECK (market_type IN ('ATS', 'TOTAL')),
        game_id INTEGER NOT NULL,
        contest_pick_id INTEGER,
        ats_shadow_calibrated_evaluation_id INTEGER,
        total_card_candidate_id INTEGER,
        calibrated_probability REAL NOT NULL CHECK (
            calibrated_probability >= 0.5 AND calibrated_probability <= 1
        ),
        candidate_score REAL NOT NULL CHECK (
            candidate_score >= 0.5 AND candidate_score <= 1
            AND candidate_score = calibrated_probability
        ),
        reliability_policy_version TEXT NOT NULL
            CHECK (length(trim(reliability_policy_version)) > 0),
        pool_rank INTEGER NOT NULL CHECK (pool_rank > 0),
        top_five_rank INTEGER CHECK (top_five_rank BETWEEN 1 AND 5),
        is_top_five INTEGER NOT NULL CHECK (is_top_five IN (0, 1)),
        generated_at TEXT NOT NULL CHECK (
            julianday(generated_at) IS NOT NULL AND substr(generated_at, -6) = '+00:00'
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (market_type = 'ATS' AND contest_pick_id IS NOT NULL
                AND ats_shadow_calibrated_evaluation_id IS NOT NULL
                AND total_card_candidate_id IS NULL)
            OR (market_type = 'TOTAL' AND contest_pick_id IS NULL
                AND ats_shadow_calibrated_evaluation_id IS NULL
                AND total_card_candidate_id IS NOT NULL)
        ),
        CHECK (
            (is_top_five = 1 AND top_five_rank IS NOT NULL)
            OR (is_top_five = 0 AND top_five_rank IS NULL)
        ),
        UNIQUE (unified_top_five_run_id, pool_rank),
        UNIQUE (unified_top_five_run_id, market_type, contest_pick_id),
        UNIQUE (unified_top_five_run_id, market_type,
            ats_shadow_calibrated_evaluation_id),
        UNIQUE (unified_top_five_run_id, market_type, total_card_candidate_id),
        FOREIGN KEY (unified_top_five_run_id) REFERENCES unified_top_five_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (ats_shadow_calibrated_evaluation_id)
            REFERENCES ats_shadow_calibrated_evaluations(id),
        FOREIGN KEY (total_card_candidate_id) REFERENCES total_card_candidates(id)
    )
    """,
    """
    CREATE UNIQUE INDEX uq_unified_top_five_candidates_selected_rank
    ON unified_top_five_candidates (unified_top_five_run_id, top_five_rank)
    WHERE top_five_rank IS NOT NULL
    """,
    """
    CREATE TABLE unified_top_five_completions (
        unified_top_five_run_id INTEGER PRIMARY KEY,
        candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
        selected_count INTEGER NOT NULL CHECK (selected_count BETWEEN 0 AND 5),
        ledger_sha256 TEXT NOT NULL CHECK (
            length(ledger_sha256) = 64
            AND lower(ledger_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        completed_at TEXT NOT NULL CHECK (
            julianday(completed_at) IS NOT NULL AND substr(completed_at, -6) = '+00:00'
        ),
        FOREIGN KEY (unified_top_five_run_id) REFERENCES unified_top_five_runs(id)
    )
    """,
    """
    CREATE TRIGGER total_model_predictions_validate
    BEFORE INSERT ON total_model_predictions
    WHEN NOT EXISTS (
        SELECT 1
        FROM total_model_runs AS run
        JOIN games AS game ON game.game_id = NEW.game_id
        WHERE run.id = NEW.total_model_run_id
          AND run.status = 'completed'
          AND (
              NEW.home_stats_as_of_season < game.season
              OR (NEW.home_stats_as_of_season = game.season
                  AND NEW.home_stats_as_of_week < game.week)
          )
          AND (
              NEW.away_stats_as_of_season < game.season
              OR (NEW.away_stats_as_of_season = game.season
                  AND NEW.away_stats_as_of_week < game.week)
          )
          AND julianday(NEW.features_as_of_at) <= julianday(NEW.generated_at)
          AND julianday(run.generated_at) <= julianday(NEW.generated_at)
          AND julianday(game.start_date) > julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'total prediction violates run, feature, or kickoff PIT custody');
    END
    """,
    """
    CREATE TRIGGER total_shadow_cards_validate
    BEFORE INSERT ON total_shadow_cards
    WHEN NOT EXISTS (
        SELECT 1
        FROM total_model_runs AS run
        JOIN total_reliability_policies AS policy
          ON policy.id = NEW.total_reliability_policy_id
        WHERE run.id = NEW.total_model_run_id
          AND run.status = 'completed'
          AND run.lifecycle_stage = 'shadow'
          AND julianday(run.generated_at) <= julianday(NEW.generated_at)
          AND julianday(policy.effective_at) <= julianday(NEW.generated_at)
    ) OR EXISTS (
        SELECT 1
        FROM contest_locked_lines AS line
        JOIN games AS game ON game.game_id = line.game_id
        WHERE line.contest_id = NEW.contest_id
          AND julianday(line.locked_at) <= julianday(NEW.generated_at)
          AND (
              game.start_date IS NULL
              OR julianday(game.start_date) <= julianday(NEW.generated_at)
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total shadow card violates policy, model, or kickoff custody');
    END
    """,
    """
    CREATE TRIGGER total_card_candidates_validate
    BEFORE INSERT ON total_card_candidates
    WHEN NOT EXISTS (
        SELECT 1
        FROM total_shadow_cards AS card
        JOIN total_reliability_policies AS policy
          ON policy.id = card.total_reliability_policy_id
        JOIN contest_locked_lines AS line ON line.id = NEW.locked_line_id
        JOIN total_model_predictions AS prediction
          ON prediction.id = NEW.total_model_prediction_id
        JOIN games AS game ON game.game_id = NEW.game_id
        WHERE card.id = NEW.total_shadow_card_id
          AND line.contest_id = card.contest_id
          AND prediction.total_model_run_id = card.total_model_run_id
          AND prediction.game_id = NEW.game_id
          AND NEW.game_id IS CASE WHEN EXISTS (
              SELECT 1
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
          ) THEN (
              SELECT correction.game_id
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ) ELSE line.game_id END
          AND NEW.projected_total = prediction.projected_total
          AND NEW.uncertainty_points = prediction.uncertainty_points
          AND NEW.reliability_policy_version = policy.reliability_policy_version
          AND NEW.generated_at = card.generated_at
          AND julianday(prediction.generated_at) <= julianday(card.generated_at)
          AND julianday(game.start_date) > julianday(card.generated_at)
          AND NEW.exact_locked_total = CASE WHEN EXISTS (
              SELECT 1
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
          ) THEN (
                  SELECT correction.total
                  FROM contest_line_corrections AS correction
                  WHERE correction.locked_line_id = line.id
                    AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ORDER BY correction.sequence DESC LIMIT 1
              ) ELSE line.total END
          AND NEW.line_effective_at = COALESCE(
              (
                  SELECT correction.corrected_at
                  FROM contest_line_corrections AS correction
                  WHERE correction.locked_line_id = line.id
                    AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ORDER BY correction.sequence DESC LIMIT 1
              ),
              line.locked_at
          )
          AND NEW.correction_id IS (
              SELECT correction.id
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          )
          AND (
              (NEW.projected_total > NEW.exact_locked_total
                  AND NEW.selected_direction = 'over')
              OR (NEW.projected_total < NEW.exact_locked_total
                  AND NEW.selected_direction = 'under')
              OR (NEW.projected_total = NEW.exact_locked_total
                  AND NEW.selected_direction = policy.forecast_tie_direction)
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total candidate violates line, prediction, or PIT custody');
    END
    """,
    """
    CREATE TRIGGER total_card_skips_validate
    BEFORE INSERT ON total_card_skips
    WHEN NOT EXISTS (
        SELECT 1
        FROM total_shadow_cards AS card
        JOIN contest_locked_lines AS line ON line.id = NEW.locked_line_id
        WHERE card.id = NEW.total_shadow_card_id
          AND line.contest_id = card.contest_id
          AND NEW.generated_at = card.generated_at
          AND NEW.line_effective_at = COALESCE(
              (
                  SELECT correction.corrected_at
                  FROM contest_line_corrections AS correction
                  WHERE correction.locked_line_id = line.id
                    AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ORDER BY correction.sequence DESC LIMIT 1
              ),
              line.locked_at
          )
          AND NEW.game_id IS CASE WHEN EXISTS (
              SELECT 1
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
          ) THEN (
              SELECT correction.game_id
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ) ELSE line.game_id END
          AND (
              (NEW.reason_code = 'missing_locked_total' AND CASE WHEN EXISTS (
                  SELECT 1
                  FROM contest_line_corrections AS correction
                  WHERE correction.locked_line_id = line.id
                    AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ) THEN (
                      SELECT correction.total
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ORDER BY correction.sequence DESC LIMIT 1
                  ) ELSE line.total END IS NULL)
              OR (
                  NEW.reason_code = 'missing_game_identity'
                  AND NEW.game_id IS NULL
                  AND CASE WHEN EXISTS (
                      SELECT 1
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ) THEN (
                      SELECT correction.total
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ORDER BY correction.sequence DESC LIMIT 1
                  ) ELSE line.total END IS NOT NULL
              )
              OR (
                  NEW.reason_code = 'missing_total_prediction'
                  AND NEW.game_id IS NOT NULL
                  AND CASE WHEN EXISTS (
                      SELECT 1
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ) THEN (
                      SELECT correction.total
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ORDER BY correction.sequence DESC LIMIT 1
                  ) ELSE line.total END IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM total_model_predictions AS prediction
                      WHERE prediction.total_model_run_id = card.total_model_run_id
                        AND prediction.game_id = NEW.game_id
                        AND julianday(prediction.generated_at) <= julianday(card.generated_at)
                  )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total skip does not match the effective locked-line state');
    END
    """,
    """
    CREATE TRIGGER total_shadow_card_completions_validate
    BEFORE INSERT ON total_shadow_card_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM total_shadow_cards AS card
        WHERE card.id = NEW.total_shadow_card_id
          AND NEW.completed_at = card.generated_at
          AND NEW.locked_line_count = (
              SELECT COUNT(*) FROM contest_locked_lines AS line
              WHERE line.contest_id = card.contest_id
                AND julianday(line.locked_at) <= julianday(card.generated_at)
          )
          AND NEW.candidate_count = (
              SELECT COUNT(*) FROM total_card_candidates AS candidate
              WHERE candidate.total_shadow_card_id = card.id
          )
          AND NEW.skip_count = (
              SELECT COUNT(*) FROM total_card_skips AS skip
              WHERE skip.total_shadow_card_id = card.id
          )
          AND NEW.locked_line_count = NEW.candidate_count + NEW.skip_count
          AND NOT EXISTS (
              SELECT 1
              FROM contest_locked_lines AS line
              WHERE line.contest_id = card.contest_id
                AND julianday(line.locked_at) <= julianday(card.generated_at)
                AND NOT EXISTS (
                    SELECT 1 FROM total_card_candidates AS candidate
                    WHERE candidate.total_shadow_card_id = card.id
                      AND candidate.locked_line_id = line.id
                    UNION ALL
                    SELECT 1 FROM total_card_skips AS skip
                    WHERE skip.total_shadow_card_id = card.id
                      AND skip.locked_line_id = line.id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total shadow card is incomplete or its counts disagree');
    END
    """,
    """
    CREATE TRIGGER total_card_candidates_no_insert_after_completion
    BEFORE INSERT ON total_card_candidates
    WHEN EXISTS (
        SELECT 1 FROM total_shadow_card_completions AS completion
        WHERE completion.total_shadow_card_id = NEW.total_shadow_card_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'total shadow card ledger is sealed');
    END
    """,
    """
    CREATE TRIGGER total_card_skips_no_insert_after_completion
    BEFORE INSERT ON total_card_skips
    WHEN EXISTS (
        SELECT 1 FROM total_shadow_card_completions AS completion
        WHERE completion.total_shadow_card_id = NEW.total_shadow_card_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'total shadow card ledger is sealed');
    END
    """,
    """
    CREATE TRIGGER ats_shadow_calibration_runs_validate
    BEFORE INSERT ON ats_shadow_calibration_runs
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN model_runs AS model ON model.id = card.model_run_id
        JOIN ats_shadow_calibration_policies AS policy
          ON policy.id = NEW.ats_shadow_calibration_policy_id
        WHERE card.id = NEW.contest_card_id
          AND model.id = NEW.ats_model_run_id
          AND model.status = 'completed'
          AND model.model_name = policy.required_model_name
          AND model.model_version = policy.required_model_version
          AND julianday(model.generated_at) <= julianday(NEW.generated_at)
          AND julianday(card.generated_at) <= julianday(NEW.generated_at)
          AND julianday(policy.effective_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'ATS shadow calibration run lacks governed card/model custody');
    END
    """,
    """
    CREATE TRIGGER ats_shadow_calibrated_evaluations_validate
    BEFORE INSERT ON ats_shadow_calibrated_evaluations
    WHEN NOT EXISTS (
        SELECT 1
        FROM ats_shadow_calibration_runs AS run
        JOIN ats_shadow_calibration_policies AS policy
          ON policy.id = run.ats_shadow_calibration_policy_id
        JOIN contest_cards AS card ON card.id = run.contest_card_id
        JOIN contest_picks AS pick ON pick.id = NEW.contest_pick_id
        JOIN model_runs AS model ON model.id = run.ats_model_run_id
        JOIN contest_locked_lines AS line ON line.id = pick.locked_line_id
        LEFT JOIN model_predictions AS prediction
          ON prediction.id = pick.model_prediction_id
        JOIN games AS game ON game.game_id = NEW.game_id
        WHERE run.id = NEW.ats_shadow_calibration_run_id
          AND NEW.evaluation_key = run.run_key || ':pick:' || pick.id
          AND NEW.contest_card_id = run.contest_card_id
          AND pick.card_id = run.contest_card_id
          AND NEW.ats_model_run_id = run.ats_model_run_id
          AND NEW.ats_model_prediction_id IS pick.model_prediction_id
          AND NEW.locked_line_id = pick.locked_line_id
          AND NEW.selected_side = pick.selected_side
          AND NEW.ats_model_name = model.model_name
          AND NEW.ats_model_version = model.model_version
          AND NEW.reliability_policy_version = policy.reliability_policy_version
          AND NEW.probability_method_version = policy.probability_method_version
          AND NEW.card_generated_at = card.generated_at
          AND NEW.generated_at = run.generated_at
          AND NEW.prediction_generated_at IS prediction.generated_at
          AND NEW.game_id IS CASE WHEN EXISTS (
              SELECT 1 FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
          ) THEN (
              SELECT correction.game_id
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ) ELSE line.game_id END
          AND NEW.line_effective_at = CASE WHEN EXISTS (
              SELECT 1 FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
          ) THEN (
              SELECT correction.corrected_at
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = line.id
                AND julianday(correction.corrected_at) <= julianday(card.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ) ELSE line.locked_at END
          AND (
              prediction.id IS NULL OR (
                  prediction.model_run_id = run.ats_model_run_id
                  AND prediction.game_id = NEW.game_id
                  AND prediction.entry_locked_line_id = pick.locked_line_id
                  AND julianday(prediction.generated_at) <= julianday(card.generated_at)
              )
          )
          AND NEW.selected_margin_advantage_points = CASE
              WHEN prediction.id IS NULL THEN 0.0
              ELSE max(0.0, CASE WHEN pick.selected_side = 'home' THEN
                  prediction.predicted_home_margin + CASE WHEN EXISTS (
                      SELECT 1 FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ) THEN (
                      SELECT correction.home_spread
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ORDER BY correction.sequence DESC LIMIT 1
                  ) ELSE line.home_spread END
                  ELSE -(prediction.predicted_home_margin + CASE WHEN EXISTS (
                      SELECT 1 FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                  ) THEN (
                      SELECT correction.home_spread
                      FROM contest_line_corrections AS correction
                      WHERE correction.locked_line_id = line.id
                        AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ORDER BY correction.sequence DESC LIMIT 1
                  ) ELSE line.home_spread END) END)
          END
          AND NEW.calibrated_selected_side_probability = min(
              policy.maximum_selected_probability,
              policy.missing_prediction_probability
              + policy.probability_per_margin_point * CASE
                  WHEN prediction.id IS NULL THEN 0.0
                  ELSE max(0.0, CASE WHEN pick.selected_side = 'home' THEN
                      prediction.predicted_home_margin + CASE WHEN EXISTS (
                          SELECT 1 FROM contest_line_corrections AS correction
                          WHERE correction.locked_line_id = line.id
                            AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ) THEN (
                          SELECT correction.home_spread
                          FROM contest_line_corrections AS correction
                          WHERE correction.locked_line_id = line.id
                            AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                          ORDER BY correction.sequence DESC LIMIT 1
                      ) ELSE line.home_spread END
                      ELSE -(prediction.predicted_home_margin + CASE WHEN EXISTS (
                          SELECT 1 FROM contest_line_corrections AS correction
                          WHERE correction.locked_line_id = line.id
                            AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                      ) THEN (
                          SELECT correction.home_spread
                          FROM contest_line_corrections AS correction
                          WHERE correction.locked_line_id = line.id
                            AND julianday(correction.corrected_at) <= julianday(card.generated_at)
                          ORDER BY correction.sequence DESC LIMIT 1
                      ) ELSE line.home_spread END) END)
              END
          )
          AND julianday(NEW.generated_at) < julianday(game.start_date)
    )
    BEGIN
        SELECT RAISE(ABORT, 'ATS shadow evaluation does not match governed pick custody');
    END
    """,
    """
    CREATE TRIGGER ats_shadow_calibration_completions_validate
    BEFORE INSERT ON ats_shadow_calibration_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM ats_shadow_calibration_runs AS run
        WHERE run.id = NEW.ats_shadow_calibration_run_id
          AND NEW.completed_at = run.generated_at
          AND NEW.evaluation_count = (
              SELECT COUNT(*) FROM contest_picks AS pick
              WHERE pick.card_id = run.contest_card_id
          )
          AND NEW.evaluation_count = (
              SELECT COUNT(*) FROM ats_shadow_calibrated_evaluations AS evaluation
              WHERE evaluation.ats_shadow_calibration_run_id = run.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM contest_picks AS pick
              WHERE pick.card_id = run.contest_card_id
                AND NOT EXISTS (
                    SELECT 1
                    FROM ats_shadow_calibrated_evaluations AS evaluation
                    WHERE evaluation.ats_shadow_calibration_run_id = run.id
                      AND evaluation.contest_pick_id = pick.id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'ATS shadow calibration ledger is incomplete');
    END
    """,
    """
    CREATE TRIGGER ats_shadow_calibrated_evaluations_no_insert_after_completion
    BEFORE INSERT ON ats_shadow_calibrated_evaluations
    WHEN EXISTS (
        SELECT 1 FROM ats_shadow_calibration_completions AS completion
        WHERE completion.ats_shadow_calibration_run_id =
            NEW.ats_shadow_calibration_run_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'ATS shadow calibration ledger is sealed');
    END
    """,
    """
    CREATE TRIGGER unified_top_five_runs_validate
    BEFORE INSERT ON unified_top_five_runs
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS ats_card
        JOIN ats_shadow_calibration_runs AS ats_calibration
          ON ats_calibration.id = NEW.ats_shadow_calibration_run_id
        JOIN ats_shadow_calibration_completions AS ats_completion
          ON ats_completion.ats_shadow_calibration_run_id = ats_calibration.id
        JOIN total_shadow_cards AS total_card
          ON total_card.id = NEW.total_shadow_card_id
        JOIN total_shadow_card_completions AS total_completion
          ON total_completion.total_shadow_card_id = total_card.id
        JOIN unified_top_five_policies AS policy
          ON policy.id = NEW.unified_top_five_policy_id
        WHERE ats_card.id = NEW.contest_card_id
          AND ats_calibration.contest_card_id = ats_card.id
          AND julianday(ats_calibration.generated_at) <= julianday(NEW.generated_at)
          AND ats_card.contest_id = total_card.contest_id
          AND julianday(ats_card.generated_at) <= julianday(NEW.generated_at)
          AND julianday(total_card.generated_at) <= julianday(NEW.generated_at)
          AND julianday(policy.effective_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'unified Top-5 run requires aligned completed shadow inputs');
    END
    """,
    """
    CREATE TRIGGER unified_top_five_candidates_validate
    BEFORE INSERT ON unified_top_five_candidates
    WHEN NEW.generated_at != (
        SELECT generated_at FROM unified_top_five_runs WHERE id = NEW.unified_top_five_run_id
    ) OR (
        NEW.market_type = 'ATS' AND NOT EXISTS (
            SELECT 1
            FROM unified_top_five_runs AS run
            JOIN ats_shadow_calibration_runs AS calibration_run
              ON calibration_run.id = run.ats_shadow_calibration_run_id
            JOIN ats_shadow_calibrated_evaluations AS evaluation
              ON evaluation.id = NEW.ats_shadow_calibrated_evaluation_id
            WHERE run.id = NEW.unified_top_five_run_id
              AND calibration_run.contest_card_id = run.contest_card_id
              AND evaluation.ats_shadow_calibration_run_id = calibration_run.id
              AND evaluation.contest_card_id = run.contest_card_id
              AND evaluation.contest_pick_id = NEW.contest_pick_id
              AND evaluation.game_id = NEW.game_id
              AND evaluation.calibrated_selected_side_probability =
                  NEW.calibrated_probability
              AND evaluation.reliability_policy_version =
                  NEW.reliability_policy_version
        )
    ) OR (
        NEW.market_type = 'TOTAL' AND NOT EXISTS (
            SELECT 1
            FROM unified_top_five_runs AS run
            JOIN total_card_candidates AS candidate
              ON candidate.id = NEW.total_card_candidate_id
            WHERE run.id = NEW.unified_top_five_run_id
              AND candidate.total_shadow_card_id = run.total_shadow_card_id
              AND candidate.game_id = NEW.game_id
              AND candidate.selected_probability = NEW.calibrated_probability
              AND candidate.reliability_policy_version = NEW.reliability_policy_version
        )
    ) OR (
        NEW.is_top_five = 1
        AND EXISTS (
            SELECT 1
            FROM unified_top_five_candidates AS existing
            JOIN unified_top_five_runs AS run
              ON run.id = existing.unified_top_five_run_id
            JOIN unified_top_five_policies AS policy
              ON policy.id = run.unified_top_five_policy_id
            WHERE existing.unified_top_five_run_id = NEW.unified_top_five_run_id
              AND existing.is_top_five = 1
              AND existing.game_id = NEW.game_id
              AND policy.allow_multiple_per_game = 0
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'unified candidate has an ambiguous or mismatched market reference');
    END
    """,
    """
    CREATE TRIGGER unified_top_five_completions_validate
    BEFORE INSERT ON unified_top_five_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM unified_top_five_runs AS run
        JOIN unified_top_five_policies AS policy
          ON policy.id = run.unified_top_five_policy_id
        WHERE run.id = NEW.unified_top_five_run_id
          AND NEW.completed_at = run.generated_at
          AND NEW.candidate_count = (
              SELECT COUNT(*) FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
          )
          AND NEW.candidate_count = (
              SELECT COUNT(*) FROM ats_shadow_calibrated_evaluations AS evaluation
              WHERE evaluation.ats_shadow_calibration_run_id =
                  run.ats_shadow_calibration_run_id
          ) + (
              SELECT COUNT(*) FROM total_card_candidates AS candidate
              WHERE candidate.total_shadow_card_id = run.total_shadow_card_id
          )
          AND NEW.selected_count = (
              SELECT COUNT(*) FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
                AND candidate.is_top_five = 1
          )
          AND NEW.selected_count = CASE
              WHEN policy.allow_multiple_per_game = 1 THEN min(5, NEW.candidate_count)
              ELSE min(5, (
                  SELECT COUNT(DISTINCT candidate.game_id)
                  FROM unified_top_five_candidates AS candidate
                  WHERE candidate.unified_top_five_run_id = run.id
              ))
          END
          AND COALESCE((
              SELECT min(candidate.pool_rank)
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
          ), 1) = CASE WHEN NEW.candidate_count = 0 THEN 1 ELSE 1 END
          AND COALESCE((
              SELECT max(candidate.pool_rank)
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
          ), 0) = NEW.candidate_count
          AND COALESCE((
              SELECT sum(candidate.pool_rank)
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
          ), 0) = (NEW.candidate_count * (NEW.candidate_count + 1)) / 2
          AND COALESCE((
              SELECT sum(candidate.top_five_rank)
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
                AND candidate.is_top_five = 1
          ), 0) = (NEW.selected_count * (NEW.selected_count + 1)) / 2
          AND NOT EXISTS (
              SELECT 1
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
                AND candidate.pool_rank != 1 + (
                    SELECT COUNT(*)
                    FROM unified_top_five_candidates AS better
                    WHERE better.unified_top_five_run_id = run.id
                      AND (
                          better.candidate_score > candidate.candidate_score
                          OR (
                              better.candidate_score = candidate.candidate_score
                              AND better.market_type < candidate.market_type
                          )
                          OR (
                              better.candidate_score = candidate.candidate_score
                              AND better.market_type = candidate.market_type
                              AND COALESCE(
                                  better.ats_shadow_calibrated_evaluation_id,
                                  better.total_card_candidate_id
                              ) < COALESCE(
                                  candidate.ats_shadow_calibrated_evaluation_id,
                                  candidate.total_card_candidate_id
                              )
                          )
                      )
                )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM unified_top_five_candidates AS candidate
              WHERE candidate.unified_top_five_run_id = run.id
                AND (
                    (
                        policy.allow_multiple_per_game = 1
                        AND (
                            candidate.is_top_five != (candidate.pool_rank <= 5)
                            OR (
                                candidate.is_top_five = 1
                                AND candidate.top_five_rank != candidate.pool_rank
                            )
                        )
                    )
                    OR (
                        policy.allow_multiple_per_game = 0
                        AND (
                            candidate.is_top_five != CASE WHEN
                                NOT EXISTS (
                                    SELECT 1
                                    FROM unified_top_five_candidates AS same_game
                                    WHERE same_game.unified_top_five_run_id = run.id
                                      AND same_game.game_id = candidate.game_id
                                      AND same_game.pool_rank < candidate.pool_rank
                                )
                                AND (
                                    SELECT COUNT(*)
                                    FROM unified_top_five_candidates AS prior_best
                                    WHERE prior_best.unified_top_five_run_id = run.id
                                      AND prior_best.pool_rank < candidate.pool_rank
                                      AND NOT EXISTS (
                                          SELECT 1
                                          FROM unified_top_five_candidates AS earlier_same_game
                                          WHERE earlier_same_game.unified_top_five_run_id = run.id
                                            AND earlier_same_game.game_id = prior_best.game_id
                                            AND earlier_same_game.pool_rank < prior_best.pool_rank
                                      )
                                ) < 5
                                THEN 1 ELSE 0 END
                            OR (
                                candidate.is_top_five = 1
                                AND candidate.top_five_rank != 1 + (
                                    SELECT COUNT(*)
                                    FROM unified_top_five_candidates AS prior_best
                                    WHERE prior_best.unified_top_five_run_id = run.id
                                      AND prior_best.pool_rank < candidate.pool_rank
                                      AND NOT EXISTS (
                                          SELECT 1
                                          FROM unified_top_five_candidates AS earlier_same_game
                                          WHERE earlier_same_game.unified_top_five_run_id = run.id
                                            AND earlier_same_game.game_id = prior_best.game_id
                                            AND earlier_same_game.pool_rank < prior_best.pool_rank
                                      )
                                )
                            )
                        )
                    )
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'unified Top-5 candidate pool is incomplete or invalid');
    END
    """,
    """
    CREATE TRIGGER unified_top_five_candidates_no_insert_after_completion
    BEFORE INSERT ON unified_top_five_candidates
    WHEN EXISTS (
        SELECT 1 FROM unified_top_five_completions AS completion
        WHERE completion.unified_top_five_run_id = NEW.unified_top_five_run_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'unified Top-5 candidate ledger is sealed');
    END
    """,
)


for _table in (
    "total_model_runs",
    "total_model_predictions",
    "total_reliability_policies",
    "total_shadow_cards",
    "total_card_candidates",
    "total_card_skips",
    "total_shadow_card_completions",
    "ats_shadow_calibration_policies",
    "ats_shadow_calibration_runs",
    "ats_shadow_calibrated_evaluations",
    "ats_shadow_calibration_completions",
    "unified_top_five_policies",
    "unified_top_five_runs",
    "unified_top_five_candidates",
    "unified_top_five_completions",
):
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_update
        BEFORE UPDATE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable');
        END
        """,
        f"""
        CREATE TRIGGER {_table}_no_delete
        BEFORE DELETE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable and cannot be deleted');
        END
        """,
    )


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def _schema_object(statement: str) -> tuple[str, str] | None:
    words = statement.split()
    if len(words) >= 3 and words[0:2] == ["CREATE", "TABLE"]:
        return "table", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    if len(words) >= 4 and words[0:3] == ["CREATE", "UNIQUE", "INDEX"]:
        return "index", words[3]
    if len(words) >= 3 and words[0:2] == ["CREATE", "TRIGGER"]:
        return "trigger", words[2]
    return None


EXPECTED_OBJECT_SQL = {
    schema_object: _normalize_sql(statement)
    for statement in STATEMENTS
    if (schema_object := _schema_object(statement)) is not None
}


def upgrade(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    for (object_type, name), expected_sql in EXPECTED_OBJECT_SQL.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(f"required {object_type} is missing: {name}")
        if _normalize_sql(str(row[0])) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")

    for table in (
        "total_model_runs",
        "total_model_predictions",
        "total_reliability_policies",
        "total_shadow_cards",
        "total_card_candidates",
        "total_card_skips",
        "total_shadow_card_completions",
        "ats_shadow_calibration_policies",
        "ats_shadow_calibration_runs",
        "ats_shadow_calibrated_evaluations",
        "ats_shadow_calibration_completions",
        "unified_top_five_policies",
        "unified_top_five_runs",
        "unified_top_five_candidates",
        "unified_top_five_completions",
    ):
        if conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] < 0:
            raise RuntimeError(f"invalid row count for {table}")
