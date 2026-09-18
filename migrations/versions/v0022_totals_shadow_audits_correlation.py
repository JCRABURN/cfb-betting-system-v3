"""Add totals component, audit, and correlation-aware shadow custody."""

from __future__ import annotations

import sqlite3


VERSION = 22
NAME = "totals_shadow_audits_correlation"

_UTC = "julianday({0}) IS NOT NULL AND substr({0}, -6) = '+00:00'"
_SHA256 = "length({0}) = 64 AND lower({0}) NOT GLOB '*[^0-9a-f]*'"


STATEMENTS = (
    f"""
    CREATE TABLE total_score_component_predictions (
        total_model_prediction_id INTEGER PRIMARY KEY,
        component_model_version TEXT NOT NULL
            CHECK (length(trim(component_model_version)) > 0),
        projected_home_points REAL NOT NULL CHECK (
            typeof(projected_home_points) IN ('integer', 'real')
            AND projected_home_points >= 0
        ),
        projected_away_points REAL NOT NULL CHECK (
            typeof(projected_away_points) IN ('integer', 'real')
            AND projected_away_points >= 0
        ),
        projected_total REAL NOT NULL CHECK (
            typeof(projected_total) IN ('integer', 'real')
            AND projected_total >= 0
        ),
        generated_at TEXT NOT NULL CHECK ({_UTC.format('generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (abs(
            projected_home_points + projected_away_points - projected_total
        ) < 0.000000001),
        FOREIGN KEY (total_model_prediction_id) REFERENCES total_model_predictions(id)
    )
    """,
    f"""
    CREATE TABLE total_postgame_audit_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        grading_method TEXT NOT NULL
            CHECK (grading_method = 'locked_total_comparison_v1'),
        clv_method TEXT NOT NULL
            CHECK (clv_method = 'selected_total_locked_to_close_v1'),
        projection_error_method TEXT NOT NULL
            CHECK (projection_error_method = 'projection_minus_actual_v1'),
        context_evidence_method TEXT NOT NULL
            CHECK (context_evidence_method = 'explicit_evidence_only_v1'),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        effective_at TEXT NOT NULL CHECK ({_UTC.format('effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE total_postgame_audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_key TEXT NOT NULL UNIQUE
            CHECK (length(trim(audit_run_key)) > 0),
        total_shadow_card_id INTEGER NOT NULL,
        total_postgame_audit_policy_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_run_id INTEGER,
        expected_candidate_count INTEGER NOT NULL
            CHECK (expected_candidate_count >= 0),
        input_sha256 TEXT NOT NULL CHECK ({_SHA256.format('input_sha256')}),
        audited_at TEXT NOT NULL CHECK ({_UTC.format('audited_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (total_shadow_card_id, sequence),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id),
        FOREIGN KEY (total_postgame_audit_policy_id)
            REFERENCES total_postgame_audit_policies(id),
        FOREIGN KEY (supersedes_run_id) REFERENCES total_postgame_audit_runs(id)
    )
    """,
    f"""
    CREATE TABLE total_postgame_audit_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_key TEXT NOT NULL UNIQUE CHECK (length(trim(audit_key)) > 0),
        total_postgame_audit_run_id INTEGER NOT NULL,
        total_card_candidate_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        exact_locked_total REAL NOT NULL,
        closing_market_line_id INTEGER,
        closing_total REAL,
        closing_book TEXT,
        closing_status TEXT NOT NULL CHECK (
            closing_status IN ('captured', 'missing_closing_total')
        ),
        final_home_points INTEGER NOT NULL CHECK (final_home_points >= 0),
        final_away_points INTEGER NOT NULL CHECK (final_away_points >= 0),
        actual_total INTEGER NOT NULL CHECK (actual_total >= 0),
        selected_direction TEXT NOT NULL
            CHECK (selected_direction IN ('over', 'under')),
        result TEXT NOT NULL CHECK (result IN ('win', 'loss', 'push')),
        unit_profit_at_minus_110 REAL NOT NULL CHECK (
            unit_profit_at_minus_110 IN (0, -1)
            OR abs(unit_profit_at_minus_110 - 0.9090909090909091) < 0.000000001
        ),
        clv_points REAL,
        projected_total REAL NOT NULL CHECK (projected_total >= 0),
        projection_error REAL NOT NULL,
        raw_edge REAL NOT NULL,
        confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
        weather_impact_status TEXT NOT NULL
            CHECK (weather_impact_status IN ('not_evaluated', 'observed', 'not_observed')),
        qb_injury_impact_status TEXT NOT NULL
            CHECK (qb_injury_impact_status IN ('not_evaluated', 'observed', 'not_observed')),
        overtime_impact_status TEXT NOT NULL
            CHECK (overtime_impact_status IN ('not_evaluated', 'observed', 'not_observed')),
        garbage_time_impact_status TEXT NOT NULL
            CHECK (garbage_time_impact_status IN ('not_evaluated', 'observed', 'not_observed')),
        late_score_impact_status TEXT NOT NULL
            CHECK (late_score_impact_status IN ('not_evaluated', 'observed', 'not_observed')),
        context_evidence TEXT,
        logic_failure_code TEXT NOT NULL CHECK (
            logic_failure_code IN (
                'not_evaluated', 'no_failure', 'model_projection_failure',
                'pace_failure', 'matchup_failure', 'game_script_failure',
                'quarterback_failure', 'offensive_line_failure',
                'defensive_personnel_failure', 'weather_failure',
                'overtime_variance', 'garbage_time_variance', 'late_score_variance'
            )
        ),
        audited_at TEXT NOT NULL CHECK ({_UTC.format('audited_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (closing_status = 'captured'
             AND closing_market_line_id IS NOT NULL
             AND closing_total IS NOT NULL
             AND length(trim(closing_book)) > 0
             AND clv_points IS NOT NULL)
            OR
            (closing_status = 'missing_closing_total'
             AND closing_market_line_id IS NULL
             AND closing_total IS NULL
             AND closing_book IS NULL
             AND clv_points IS NULL)
        ),
        CHECK (
            (weather_impact_status = 'not_evaluated'
             AND qb_injury_impact_status = 'not_evaluated'
             AND overtime_impact_status = 'not_evaluated'
             AND garbage_time_impact_status = 'not_evaluated'
             AND late_score_impact_status = 'not_evaluated'
             AND logic_failure_code = 'not_evaluated'
             AND context_evidence IS NULL)
            OR context_evidence IS NOT NULL
        ),
        UNIQUE (total_postgame_audit_run_id, total_card_candidate_id),
        FOREIGN KEY (total_postgame_audit_run_id)
            REFERENCES total_postgame_audit_runs(id),
        FOREIGN KEY (total_card_candidate_id) REFERENCES total_card_candidates(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (closing_market_line_id) REFERENCES betting_lines(id)
    )
    """,
    f"""
    CREATE TABLE total_postgame_audit_completions (
        total_postgame_audit_run_id INTEGER PRIMARY KEY,
        audit_count INTEGER NOT NULL CHECK (audit_count >= 0),
        win_count INTEGER NOT NULL CHECK (win_count >= 0),
        loss_count INTEGER NOT NULL CHECK (loss_count >= 0),
        push_count INTEGER NOT NULL CHECK (push_count >= 0),
        ledger_sha256 TEXT NOT NULL CHECK ({_SHA256.format('ledger_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC.format('completed_at')}),
        CHECK (audit_count = win_count + loss_count + push_count),
        FOREIGN KEY (total_postgame_audit_run_id)
            REFERENCES total_postgame_audit_runs(id)
    )
    """,
    f"""
    CREATE TABLE cross_market_correlation_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        policy_version TEXT NOT NULL UNIQUE CHECK (length(trim(policy_version)) > 0),
        evidence_method TEXT NOT NULL
            CHECK (evidence_method = 'phi_fisher_95_lower_bound_v1'),
        penalty_method TEXT NOT NULL
            CHECK (penalty_method = 'positive_covariance_probability_penalty_v1'),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        effective_at TEXT NOT NULL CHECK ({_UTC.format('effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE cross_market_correlation_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cross_market_correlation_policy_id INTEGER NOT NULL,
        relation_code TEXT NOT NULL CHECK (relation_code IN (
            'favorite_over', 'favorite_under',
            'underdog_over', 'underdog_under', 'pickem_over', 'pickem_under'
        )),
        sample_n INTEGER NOT NULL CHECK (sample_n >= 0),
        phi_correlation REAL CHECK (
            phi_correlation IS NULL OR phi_correlation BETWEEN -1 AND 1
        ),
        fisher_lower_95 REAL CHECK (
            fisher_lower_95 IS NULL OR fisher_lower_95 BETWEEN -1 AND 1
        ),
        fisher_upper_95 REAL CHECK (
            fisher_upper_95 IS NULL OR fisher_upper_95 BETWEEN -1 AND 1
        ),
        positive_penalty_weight REAL NOT NULL CHECK (
            positive_penalty_weight BETWEEN 0 AND 1
        ),
        evidence_status TEXT NOT NULL CHECK (
            evidence_status IN ('estimated', 'insufficient_variation', 'no_data')
        ),
        dataset_sha256 TEXT NOT NULL CHECK ({_SHA256.format('dataset_sha256')}),
        generated_at TEXT NOT NULL CHECK ({_UTC.format('generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (evidence_status = 'estimated'
             AND sample_n > 3
             AND phi_correlation IS NOT NULL
             AND fisher_lower_95 IS NOT NULL
             AND fisher_upper_95 IS NOT NULL
             AND fisher_lower_95 <= phi_correlation
             AND phi_correlation <= fisher_upper_95
             AND abs(positive_penalty_weight - max(fisher_lower_95, 0))
                 < 0.000000001)
            OR
            (evidence_status != 'estimated'
             AND phi_correlation IS NULL
             AND fisher_lower_95 IS NULL
             AND fisher_upper_95 IS NULL
             AND positive_penalty_weight = 0)
        ),
        UNIQUE (cross_market_correlation_policy_id, relation_code),
        FOREIGN KEY (cross_market_correlation_policy_id)
            REFERENCES cross_market_correlation_policies(id)
    )
    """,
    f"""
    CREATE TABLE correlation_aware_unified_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        policy_version TEXT NOT NULL UNIQUE CHECK (length(trim(policy_version)) > 0),
        cross_market_correlation_policy_id INTEGER NOT NULL,
        top_five_count INTEGER NOT NULL CHECK (top_five_count = 5),
        base_score_metric TEXT NOT NULL
            CHECK (base_score_metric = 'calibrated_selection_probability'),
        ordering_method TEXT NOT NULL CHECK (
            ordering_method = 'greedy_probability_minus_same_game_covariance_v1'
        ),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        effective_at TEXT NOT NULL CHECK ({_UTC.format('effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (cross_market_correlation_policy_id)
            REFERENCES cross_market_correlation_policies(id)
    )
    """,
    f"""
    CREATE TABLE correlation_aware_unified_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        contest_card_id INTEGER NOT NULL,
        ats_shadow_calibration_run_id INTEGER NOT NULL,
        total_shadow_card_id INTEGER NOT NULL,
        correlation_aware_unified_policy_id INTEGER NOT NULL,
        candidate_input_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format('candidate_input_sha256')}),
        status TEXT NOT NULL CHECK (status = 'shadow'),
        generated_at TEXT NOT NULL CHECK ({_UTC.format('generated_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (
            contest_card_id, ats_shadow_calibration_run_id,
            total_shadow_card_id, correlation_aware_unified_policy_id
        ),
        FOREIGN KEY (contest_card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (ats_shadow_calibration_run_id)
            REFERENCES ats_shadow_calibration_runs(id),
        FOREIGN KEY (total_shadow_card_id) REFERENCES total_shadow_cards(id),
        FOREIGN KEY (correlation_aware_unified_policy_id)
            REFERENCES correlation_aware_unified_policies(id)
    )
    """,
    f"""
    CREATE TABLE correlation_aware_unified_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_key TEXT NOT NULL UNIQUE CHECK (length(trim(candidate_key)) > 0),
        correlation_aware_unified_run_id INTEGER NOT NULL,
        market_type TEXT NOT NULL CHECK (market_type IN ('ATS', 'TOTAL')),
        game_id INTEGER NOT NULL,
        contest_pick_id INTEGER,
        ats_shadow_calibrated_evaluation_id INTEGER,
        total_card_candidate_id INTEGER,
        same_game_predecessor_candidate_id INTEGER,
        correlation_cell_id INTEGER,
        correlation_relation_code TEXT CHECK (
            correlation_relation_code IS NULL OR correlation_relation_code IN (
                'favorite_over', 'favorite_under',
                'underdog_over', 'underdog_under', 'pickem_over', 'pickem_under'
            )
        ),
        calibrated_probability REAL NOT NULL
            CHECK (calibrated_probability BETWEEN 0.5 AND 1),
        reliability_policy_version TEXT NOT NULL
            CHECK (length(trim(reliability_policy_version)) > 0),
        correlation_penalty REAL NOT NULL CHECK (correlation_penalty BETWEEN 0 AND 1),
        adjusted_score REAL NOT NULL CHECK (
            adjusted_score BETWEEN 0 AND 1
            AND abs(adjusted_score - max(
                calibrated_probability - correlation_penalty, 0
            )) < 0.000000001
        ),
        correlation_status TEXT NOT NULL CHECK (
            correlation_status IN (
                'no_same_game_predecessor', 'penalized_positive_correlation',
                'same_game_not_empirically_positive', 'same_game_no_evidence'
            )
        ),
        pool_rank INTEGER NOT NULL CHECK (pool_rank > 0),
        top_five_rank INTEGER CHECK (top_five_rank BETWEEN 1 AND 5),
        is_top_five INTEGER NOT NULL CHECK (is_top_five IN (0, 1)),
        generated_at TEXT NOT NULL CHECK ({_UTC.format('generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (market_type = 'ATS'
             AND contest_pick_id IS NOT NULL
             AND ats_shadow_calibrated_evaluation_id IS NOT NULL
             AND total_card_candidate_id IS NULL)
            OR
            (market_type = 'TOTAL'
             AND contest_pick_id IS NULL
             AND ats_shadow_calibrated_evaluation_id IS NULL
             AND total_card_candidate_id IS NOT NULL)
        ),
        CHECK (
            (is_top_five = 1 AND top_five_rank = pool_rank AND pool_rank <= 5)
            OR (is_top_five = 0 AND top_five_rank IS NULL AND pool_rank > 5)
        ),
        CHECK (
            (same_game_predecessor_candidate_id IS NULL
             AND correlation_cell_id IS NULL
             AND correlation_relation_code IS NULL
             AND correlation_penalty = 0
             AND correlation_status = 'no_same_game_predecessor')
            OR
            (same_game_predecessor_candidate_id IS NOT NULL
             AND correlation_relation_code IS NOT NULL
             AND correlation_status != 'no_same_game_predecessor')
        ),
        UNIQUE (correlation_aware_unified_run_id, market_type, game_id),
        UNIQUE (correlation_aware_unified_run_id, pool_rank),
        UNIQUE (correlation_aware_unified_run_id, top_five_rank),
        FOREIGN KEY (correlation_aware_unified_run_id)
            REFERENCES correlation_aware_unified_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (ats_shadow_calibrated_evaluation_id)
            REFERENCES ats_shadow_calibrated_evaluations(id),
        FOREIGN KEY (total_card_candidate_id) REFERENCES total_card_candidates(id),
        FOREIGN KEY (same_game_predecessor_candidate_id)
            REFERENCES correlation_aware_unified_candidates(id),
        FOREIGN KEY (correlation_cell_id) REFERENCES cross_market_correlation_cells(id)
    )
    """,
    f"""
    CREATE TABLE correlation_aware_unified_pair_flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        correlation_aware_unified_run_id INTEGER NOT NULL,
        ats_candidate_id INTEGER NOT NULL,
        total_candidate_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        relation_code TEXT NOT NULL,
        correlation_cell_id INTEGER,
        penalty_applied REAL NOT NULL CHECK (penalty_applied BETWEEN 0 AND 1),
        status TEXT NOT NULL CHECK (
            status IN ('penalized_positive_correlation',
                       'not_empirically_positive', 'no_evidence')
        ),
        generated_at TEXT NOT NULL CHECK ({_UTC.format('generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (correlation_aware_unified_run_id, game_id),
        FOREIGN KEY (correlation_aware_unified_run_id)
            REFERENCES correlation_aware_unified_runs(id),
        FOREIGN KEY (ats_candidate_id)
            REFERENCES correlation_aware_unified_candidates(id),
        FOREIGN KEY (total_candidate_id)
            REFERENCES correlation_aware_unified_candidates(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (correlation_cell_id) REFERENCES cross_market_correlation_cells(id)
    )
    """,
    f"""
    CREATE TABLE correlation_aware_unified_completions (
        correlation_aware_unified_run_id INTEGER PRIMARY KEY,
        candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
        selected_count INTEGER NOT NULL CHECK (selected_count BETWEEN 0 AND 5),
        same_game_top_five_pair_count INTEGER NOT NULL CHECK (
            same_game_top_five_pair_count >= 0
        ),
        rank_five_score REAL,
        rank_six_score REAL,
        cutoff_gap REAL,
        ledger_sha256 TEXT NOT NULL CHECK ({_SHA256.format('ledger_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC.format('completed_at')}),
        CHECK (
            (candidate_count >= 6
             AND rank_five_score IS NOT NULL
             AND rank_six_score IS NOT NULL
             AND cutoff_gap IS NOT NULL
             AND abs(cutoff_gap - (rank_five_score - rank_six_score))
                 < 0.000000001)
            OR
            (candidate_count < 6
             AND rank_five_score IS NULL
             AND rank_six_score IS NULL
             AND cutoff_gap IS NULL)
        ),
        CHECK (selected_count = min(candidate_count, 5)),
        FOREIGN KEY (correlation_aware_unified_run_id)
            REFERENCES correlation_aware_unified_runs(id)
    )
    """,
    f"""
    CREATE TABLE mixed_top_five_audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_key TEXT NOT NULL UNIQUE CHECK (length(trim(audit_run_key)) > 0),
        correlation_aware_unified_run_id INTEGER NOT NULL UNIQUE,
        card_postgame_audit_run_id INTEGER NOT NULL,
        total_postgame_audit_run_id INTEGER NOT NULL,
        input_sha256 TEXT NOT NULL CHECK ({_SHA256.format('input_sha256')}),
        audited_at TEXT NOT NULL CHECK ({_UTC.format('audited_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (correlation_aware_unified_run_id)
            REFERENCES correlation_aware_unified_runs(id),
        FOREIGN KEY (card_postgame_audit_run_id)
            REFERENCES card_postgame_audit_runs(id),
        FOREIGN KEY (total_postgame_audit_run_id)
            REFERENCES total_postgame_audit_runs(id)
    )
    """,
    f"""
    CREATE TABLE mixed_top_five_audit_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mixed_top_five_audit_run_id INTEGER NOT NULL,
        unified_candidate_id INTEGER NOT NULL UNIQUE,
        market_type TEXT NOT NULL CHECK (market_type IN ('ATS', 'TOTAL')),
        game_id INTEGER NOT NULL,
        pick_audit_detail_id INTEGER,
        total_postgame_audit_detail_id INTEGER,
        result TEXT NOT NULL CHECK (result IN ('win', 'loss', 'push')),
        unit_profit_at_minus_110 REAL NOT NULL,
        clv_points REAL,
        expected_win_probability REAL NOT NULL
            CHECK (expected_win_probability BETWEEN 0.5 AND 1),
        audited_at TEXT NOT NULL CHECK ({_UTC.format('audited_at')}),
        CHECK (
            (market_type = 'ATS' AND pick_audit_detail_id IS NOT NULL
             AND total_postgame_audit_detail_id IS NULL)
            OR
            (market_type = 'TOTAL' AND pick_audit_detail_id IS NULL
             AND total_postgame_audit_detail_id IS NOT NULL)
        ),
        UNIQUE (mixed_top_five_audit_run_id, game_id, market_type),
        FOREIGN KEY (mixed_top_five_audit_run_id) REFERENCES mixed_top_five_audit_runs(id),
        FOREIGN KEY (unified_candidate_id)
            REFERENCES correlation_aware_unified_candidates(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (pick_audit_detail_id) REFERENCES pick_audit_details(audit_id),
        FOREIGN KEY (total_postgame_audit_detail_id)
            REFERENCES total_postgame_audit_details(id)
    )
    """,
    f"""
    CREATE TABLE mixed_top_five_audit_completions (
        mixed_top_five_audit_run_id INTEGER PRIMARY KEY,
        audit_count INTEGER NOT NULL CHECK (audit_count BETWEEN 0 AND 5),
        ats_count INTEGER NOT NULL CHECK (ats_count >= 0),
        total_count INTEGER NOT NULL CHECK (total_count >= 0),
        win_count INTEGER NOT NULL CHECK (win_count >= 0),
        loss_count INTEGER NOT NULL CHECK (loss_count >= 0),
        push_count INTEGER NOT NULL CHECK (push_count >= 0),
        unit_profit_at_minus_110 REAL NOT NULL,
        roi_at_minus_110 REAL,
        average_clv REAL,
        expected_win_rate REAL,
        actual_win_rate REAL,
        ledger_sha256 TEXT NOT NULL CHECK ({_SHA256.format('ledger_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC.format('completed_at')}),
        CHECK (audit_count = ats_count + total_count),
        CHECK (audit_count = win_count + loss_count + push_count),
        FOREIGN KEY (mixed_top_five_audit_run_id)
            REFERENCES mixed_top_five_audit_runs(id)
    )
    """,
    """
    CREATE INDEX idx_total_postgame_audit_details_run
    ON total_postgame_audit_details (total_postgame_audit_run_id, total_card_candidate_id)
    """,
    """
    CREATE INDEX idx_correlation_aware_candidates_run
    ON correlation_aware_unified_candidates (correlation_aware_unified_run_id, pool_rank)
    """,
    """
    CREATE TRIGGER total_score_component_predictions_validate
    BEFORE INSERT ON total_score_component_predictions
    WHEN NOT EXISTS (
        SELECT 1 FROM total_model_predictions AS prediction
        JOIN total_model_runs AS run ON run.id = prediction.total_model_run_id
        JOIN games AS game ON game.game_id = prediction.game_id
        WHERE prediction.id = NEW.total_model_prediction_id
          AND abs(prediction.projected_total - NEW.projected_total) < 0.000000001
          AND run.lifecycle_stage = 'shadow'
          AND run.status = 'completed'
          AND NEW.generated_at = prediction.generated_at
          AND julianday(NEW.generated_at) <= julianday(game.start_date)
    )
    BEGIN
        SELECT RAISE(ABORT, 'total score components do not match shadow prediction');
    END
    """,
    """
    CREATE TRIGGER total_postgame_audit_runs_validate
    BEFORE INSERT ON total_postgame_audit_runs
    WHEN NEW.sequence != COALESCE((
        SELECT MAX(sequence) + 1 FROM total_postgame_audit_runs
        WHERE total_shadow_card_id = NEW.total_shadow_card_id
    ), 1)
    OR NEW.supersedes_run_id IS NOT (
        SELECT id FROM total_postgame_audit_runs
        WHERE total_shadow_card_id = NEW.total_shadow_card_id
        ORDER BY sequence DESC LIMIT 1
    )
    OR NOT EXISTS (
        SELECT 1 FROM total_shadow_cards AS card
        JOIN total_shadow_card_completions AS completion
          ON completion.total_shadow_card_id = card.id
        JOIN total_postgame_audit_policies AS policy
          ON policy.id = NEW.total_postgame_audit_policy_id
        WHERE card.id = NEW.total_shadow_card_id
          AND NEW.expected_candidate_count = completion.candidate_count
          AND julianday(policy.effective_at) <= julianday(NEW.audited_at)
          AND julianday(card.generated_at) <= julianday(NEW.audited_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'total audit run lacks complete governed inputs');
    END
    """,
    """
    CREATE TRIGGER total_postgame_audit_details_validate
    BEFORE INSERT ON total_postgame_audit_details
    WHEN EXISTS (
        SELECT 1 FROM total_postgame_audit_completions
        WHERE total_postgame_audit_run_id = NEW.total_postgame_audit_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM total_postgame_audit_runs AS run
        JOIN total_shadow_cards AS card ON card.id = run.total_shadow_card_id
        JOIN total_card_candidates AS candidate
          ON candidate.total_shadow_card_id = card.id
        JOIN games AS game ON game.game_id = candidate.game_id
        WHERE run.id = NEW.total_postgame_audit_run_id
          AND candidate.id = NEW.total_card_candidate_id
          AND NEW.audit_key = run.audit_run_key || ':candidate:' || candidate.id
          AND NEW.game_id = candidate.game_id
          AND NEW.locked_line_id = candidate.locked_line_id
          AND NEW.exact_locked_total = candidate.exact_locked_total
          AND NEW.selected_direction = candidate.selected_direction
          AND NEW.projected_total = candidate.projected_total
          AND NEW.raw_edge = candidate.projected_total - candidate.exact_locked_total
          AND NEW.confidence = candidate.confidence
          AND game.completed = 1
          AND game.home_points = NEW.final_home_points
          AND game.away_points = NEW.final_away_points
          AND NEW.actual_total = game.home_points + game.away_points
          AND NEW.projection_error = candidate.projected_total - NEW.actual_total
          AND NEW.result = CASE
              WHEN NEW.actual_total = candidate.exact_locked_total THEN 'push'
              WHEN (candidate.selected_direction = 'over'
                    AND NEW.actual_total > candidate.exact_locked_total)
                OR (candidate.selected_direction = 'under'
                    AND NEW.actual_total < candidate.exact_locked_total) THEN 'win'
              ELSE 'loss' END
          AND abs(NEW.unit_profit_at_minus_110 - CASE NEW.result
              WHEN 'win' THEN 0.9090909090909091
              WHEN 'loss' THEN -1.0 ELSE 0.0 END) < 0.000000001
          AND NEW.audited_at = run.audited_at
          AND NEW.source = run.source
          AND NEW.provenance = run.provenance
          AND julianday(game.start_date) <= julianday(NEW.audited_at)
          AND (
              (NEW.closing_status = 'missing_closing_total')
              OR EXISTS (
                  SELECT 1 FROM betting_lines AS closing
                  WHERE closing.id = NEW.closing_market_line_id
                    AND closing.game_id = game.game_id
                    AND closing.line_type = 'closing'
                    AND closing.total = NEW.closing_total
                    AND closing.book = NEW.closing_book
                    AND julianday(closing.fetched_at) >= julianday(card.generated_at)
                    AND julianday(closing.fetched_at) <= julianday(game.start_date)
                    AND NEW.clv_points = CASE candidate.selected_direction
                        WHEN 'over' THEN closing.total - candidate.exact_locked_total
                        ELSE candidate.exact_locked_total - closing.total END
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total audit detail does not match governed card/results');
    END
    """,
    """
    CREATE TRIGGER total_postgame_audit_completions_validate
    BEFORE INSERT ON total_postgame_audit_completions
    WHEN EXISTS (
        SELECT 1 FROM total_postgame_audit_completions
        WHERE total_postgame_audit_run_id = NEW.total_postgame_audit_run_id
    )
    OR NOT EXISTS (
        SELECT 1 FROM total_postgame_audit_runs AS run
        WHERE run.id = NEW.total_postgame_audit_run_id
          AND NEW.audit_count = run.expected_candidate_count
          AND NEW.audit_count = (
              SELECT COUNT(*) FROM total_postgame_audit_details
              WHERE total_postgame_audit_run_id = run.id
          )
          AND NEW.win_count = (
              SELECT COUNT(*) FROM total_postgame_audit_details
              WHERE total_postgame_audit_run_id = run.id AND result = 'win'
          )
          AND NEW.loss_count = (
              SELECT COUNT(*) FROM total_postgame_audit_details
              WHERE total_postgame_audit_run_id = run.id AND result = 'loss'
          )
          AND NEW.push_count = (
              SELECT COUNT(*) FROM total_postgame_audit_details
              WHERE total_postgame_audit_run_id = run.id AND result = 'push'
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'total audit completion is incomplete');
    END
    """,
    """
    CREATE TRIGGER cross_market_correlation_cells_validate
    BEFORE INSERT ON cross_market_correlation_cells
    WHEN NEW.positive_penalty_weight != max(COALESCE(NEW.fisher_lower_95, 0), 0)
    BEGIN
        SELECT RAISE(ABORT, 'correlation penalty is not derived from evidence');
    END
    """,
    """
    CREATE TRIGGER correlation_aware_unified_runs_validate
    BEFORE INSERT ON correlation_aware_unified_runs
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS contest_card
        JOIN ats_shadow_calibration_runs AS ats_run
          ON ats_run.contest_card_id = contest_card.id
        JOIN ats_shadow_calibration_completions AS ats_completion
          ON ats_completion.ats_shadow_calibration_run_id = ats_run.id
        JOIN total_shadow_cards AS total_card
          ON total_card.contest_id = contest_card.contest_id
        JOIN total_shadow_card_completions AS total_completion
          ON total_completion.total_shadow_card_id = total_card.id
        JOIN correlation_aware_unified_policies AS policy
          ON policy.id = NEW.correlation_aware_unified_policy_id
        WHERE contest_card.id = NEW.contest_card_id
          AND ats_run.id = NEW.ats_shadow_calibration_run_id
          AND total_card.id = NEW.total_shadow_card_id
          AND julianday(policy.effective_at) <= julianday(NEW.generated_at)
          AND julianday(contest_card.generated_at) <= julianday(NEW.generated_at)
          AND julianday(total_card.generated_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'correlation-aware run lacks complete governed inputs');
    END
    """,
    """
    CREATE TRIGGER correlation_aware_unified_candidates_validate
    BEFORE INSERT ON correlation_aware_unified_candidates
    WHEN EXISTS (
        SELECT 1 FROM correlation_aware_unified_completions
        WHERE correlation_aware_unified_run_id = NEW.correlation_aware_unified_run_id
    )
    OR NOT EXISTS (
        SELECT 1 FROM correlation_aware_unified_runs AS run
        WHERE run.id = NEW.correlation_aware_unified_run_id
          AND (
            (NEW.market_type = 'ATS' AND EXISTS (
                SELECT 1 FROM ats_shadow_calibrated_evaluations AS evaluation
                WHERE evaluation.id = NEW.ats_shadow_calibrated_evaluation_id
                  AND evaluation.ats_shadow_calibration_run_id = run.ats_shadow_calibration_run_id
                  AND evaluation.contest_pick_id = NEW.contest_pick_id
                  AND evaluation.game_id = NEW.game_id
                  AND evaluation.calibrated_selected_side_probability = NEW.calibrated_probability
                  AND evaluation.reliability_policy_version = NEW.reliability_policy_version
            ))
            OR
            (NEW.market_type = 'TOTAL' AND EXISTS (
                SELECT 1 FROM total_card_candidates AS candidate
                WHERE candidate.id = NEW.total_card_candidate_id
                  AND candidate.total_shadow_card_id = run.total_shadow_card_id
                  AND candidate.game_id = NEW.game_id
                  AND candidate.selected_probability = NEW.calibrated_probability
                  AND candidate.reliability_policy_version = NEW.reliability_policy_version
            ))
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'correlation-aware candidate breaks source custody');
    END
    """,
    """
    CREATE TRIGGER correlation_aware_unified_candidates_validate_penalty
    BEFORE INSERT ON correlation_aware_unified_candidates
    WHEN (
        NEW.same_game_predecessor_candidate_id IS NULL
        AND EXISTS (
            SELECT 1 FROM correlation_aware_unified_candidates AS prior
            WHERE prior.correlation_aware_unified_run_id =
                  NEW.correlation_aware_unified_run_id
              AND prior.game_id = NEW.game_id
              AND prior.market_type != NEW.market_type
              AND prior.pool_rank < NEW.pool_rank
        )
    )
    OR (
        NEW.same_game_predecessor_candidate_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM correlation_aware_unified_candidates AS prior
            JOIN correlation_aware_unified_runs AS run
              ON run.id = NEW.correlation_aware_unified_run_id
            JOIN correlation_aware_unified_policies AS policy
              ON policy.id = run.correlation_aware_unified_policy_id
            JOIN cross_market_correlation_cells AS cell
              ON cell.id = NEW.correlation_cell_id
             AND cell.cross_market_correlation_policy_id =
                 policy.cross_market_correlation_policy_id
             AND cell.relation_code = NEW.correlation_relation_code
            WHERE prior.id = NEW.same_game_predecessor_candidate_id
              AND prior.correlation_aware_unified_run_id = run.id
              AND prior.game_id = NEW.game_id
              AND prior.market_type != NEW.market_type
              AND prior.pool_rank < NEW.pool_rank
              AND (
                (cell.evidence_status = 'estimated'
                 AND cell.positive_penalty_weight > 0
                 AND NEW.correlation_status = 'penalized_positive_correlation'
                 AND abs(NEW.correlation_penalty -
                     cell.positive_penalty_weight * sqrt(
                       NEW.calibrated_probability * (1 - NEW.calibrated_probability)
                       * prior.calibrated_probability * (1 - prior.calibrated_probability)
                     )) < 0.000000001)
                OR
                (cell.evidence_status = 'estimated'
                 AND cell.positive_penalty_weight = 0
                 AND NEW.correlation_status = 'same_game_not_empirically_positive'
                 AND NEW.correlation_penalty = 0)
                OR
                (cell.evidence_status != 'estimated'
                 AND NEW.correlation_status = 'same_game_no_evidence'
                 AND NEW.correlation_penalty = 0)
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'correlation-aware penalty is not evidence-derived');
    END
    """,
    """
    CREATE TRIGGER correlation_aware_unified_pair_flags_validate
    BEFORE INSERT ON correlation_aware_unified_pair_flags
    WHEN NOT EXISTS (
        SELECT 1
        FROM correlation_aware_unified_runs AS run
        JOIN correlation_aware_unified_policies AS policy
          ON policy.id = run.correlation_aware_unified_policy_id
        JOIN correlation_aware_unified_candidates AS ats
          ON ats.id = NEW.ats_candidate_id
        JOIN correlation_aware_unified_candidates AS total
          ON total.id = NEW.total_candidate_id
        WHERE run.id = NEW.correlation_aware_unified_run_id
          AND ats.correlation_aware_unified_run_id = run.id
          AND total.correlation_aware_unified_run_id = run.id
          AND ats.market_type = 'ATS' AND total.market_type = 'TOTAL'
          AND ats.game_id = NEW.game_id AND total.game_id = NEW.game_id
          AND ats.is_top_five = 1 AND total.is_top_five = 1
          AND CASE WHEN ats.pool_rank > total.pool_rank
                   THEN ats.correlation_relation_code
                   ELSE total.correlation_relation_code END = NEW.relation_code
          AND NEW.penalty_applied = CASE
              WHEN ats.pool_rank > total.pool_rank THEN ats.correlation_penalty
              ELSE total.correlation_penalty END
          AND (
            (NEW.correlation_cell_id IS NULL
             AND NEW.status = 'no_evidence' AND NEW.penalty_applied = 0)
            OR EXISTS (
                SELECT 1 FROM cross_market_correlation_cells AS cell
                WHERE cell.id = NEW.correlation_cell_id
                  AND cell.cross_market_correlation_policy_id =
                      policy.cross_market_correlation_policy_id
                  AND cell.relation_code = NEW.relation_code
                  AND (
                    (cell.positive_penalty_weight > 0
                     AND NEW.status = 'penalized_positive_correlation')
                    OR
                    (cell.positive_penalty_weight = 0
                     AND NEW.status = 'not_empirically_positive')
                  )
            )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'correlation pair flag does not match selected pair/evidence');
    END
    """,
    """
    CREATE TRIGGER correlation_aware_unified_completions_validate
    BEFORE INSERT ON correlation_aware_unified_completions
    WHEN NOT EXISTS (
        SELECT 1 FROM correlation_aware_unified_runs AS run
        WHERE run.id = NEW.correlation_aware_unified_run_id
          AND NEW.candidate_count = (
              SELECT COUNT(*) FROM correlation_aware_unified_candidates
              WHERE correlation_aware_unified_run_id = run.id
          )
          AND NEW.selected_count = (
              SELECT COUNT(*) FROM correlation_aware_unified_candidates
              WHERE correlation_aware_unified_run_id = run.id AND is_top_five = 1
          )
          AND NEW.same_game_top_five_pair_count = (
              SELECT COUNT(*) FROM correlation_aware_unified_pair_flags
              WHERE correlation_aware_unified_run_id = run.id
          )
          AND (NEW.candidate_count < 6 OR (
              NEW.rank_five_score = (SELECT adjusted_score
                  FROM correlation_aware_unified_candidates
                  WHERE correlation_aware_unified_run_id = run.id AND pool_rank = 5)
              AND NEW.rank_six_score = (SELECT adjusted_score
                  FROM correlation_aware_unified_candidates
                  WHERE correlation_aware_unified_run_id = run.id AND pool_rank = 6)
          ))
    )
    BEGIN
        SELECT RAISE(ABORT, 'correlation-aware completion does not match ledger');
    END
    """,
    """
    CREATE TRIGGER mixed_top_five_audit_runs_validate
    BEFORE INSERT ON mixed_top_five_audit_runs
    WHEN NOT EXISTS (
        SELECT 1
        FROM correlation_aware_unified_runs AS unified
        JOIN correlation_aware_unified_completions AS unified_completion
          ON unified_completion.correlation_aware_unified_run_id = unified.id
        JOIN card_postgame_audit_runs AS ats_audit
          ON ats_audit.id = NEW.card_postgame_audit_run_id
        JOIN card_postgame_audit_completions AS ats_completion
          ON ats_completion.audit_run_id = ats_audit.id
        JOIN total_postgame_audit_runs AS total_audit
          ON total_audit.id = NEW.total_postgame_audit_run_id
        JOIN total_postgame_audit_completions AS total_completion
          ON total_completion.total_postgame_audit_run_id = total_audit.id
        WHERE unified.id = NEW.correlation_aware_unified_run_id
          AND ats_audit.card_id = unified.contest_card_id
          AND total_audit.total_shadow_card_id = unified.total_shadow_card_id
          AND julianday(unified.generated_at) <= julianday(NEW.audited_at)
          AND julianday(ats_audit.audited_at) <= julianday(NEW.audited_at)
          AND julianday(total_audit.audited_at) <= julianday(NEW.audited_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed audit lacks complete governed sub-audits');
    END
    """,
    """
    CREATE TRIGGER mixed_top_five_audit_details_validate
    BEFORE INSERT ON mixed_top_five_audit_details
    WHEN EXISTS (
        SELECT 1 FROM mixed_top_five_audit_completions
        WHERE mixed_top_five_audit_run_id = NEW.mixed_top_five_audit_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM mixed_top_five_audit_runs AS run
        JOIN correlation_aware_unified_candidates AS candidate
          ON candidate.correlation_aware_unified_run_id =
             run.correlation_aware_unified_run_id
        WHERE run.id = NEW.mixed_top_five_audit_run_id
          AND candidate.id = NEW.unified_candidate_id
          AND candidate.is_top_five = 1
          AND candidate.market_type = NEW.market_type
          AND candidate.game_id = NEW.game_id
          AND candidate.calibrated_probability = NEW.expected_win_probability
          AND NEW.audited_at = run.audited_at
          AND (
            (NEW.market_type = 'ATS' AND EXISTS (
                SELECT 1 FROM pick_audit_details AS detail
                WHERE detail.audit_id = NEW.pick_audit_detail_id
                  AND detail.audit_run_id = run.card_postgame_audit_run_id
                  AND detail.contest_pick_id = candidate.contest_pick_id
                  AND detail.game_id = candidate.game_id
                  AND detail.ats_result = NEW.result
                  AND detail.clv_points = NEW.clv_points
                  AND abs(NEW.unit_profit_at_minus_110 - CASE detail.ats_result
                      WHEN 'win' THEN 0.9090909090909091
                      WHEN 'loss' THEN -1.0 ELSE 0.0 END) < 0.000000001
            ))
            OR
            (NEW.market_type = 'TOTAL' AND EXISTS (
                SELECT 1 FROM total_postgame_audit_details AS detail
                WHERE detail.id = NEW.total_postgame_audit_detail_id
                  AND detail.total_postgame_audit_run_id = run.total_postgame_audit_run_id
                  AND detail.total_card_candidate_id = candidate.total_card_candidate_id
                  AND detail.game_id = candidate.game_id
                  AND detail.result = NEW.result
                  AND detail.clv_points IS NEW.clv_points
                  AND detail.unit_profit_at_minus_110 = NEW.unit_profit_at_minus_110
            ))
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed audit detail breaks source custody');
    END
    """,
    """
    CREATE TRIGGER mixed_top_five_audit_completions_validate
    BEFORE INSERT ON mixed_top_five_audit_completions
    WHEN NOT EXISTS (
        SELECT 1 FROM mixed_top_five_audit_runs AS run
        WHERE run.id = NEW.mixed_top_five_audit_run_id
          AND NEW.audit_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id
          )
          AND NEW.ats_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id AND market_type = 'ATS'
          )
          AND NEW.total_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id AND market_type = 'TOTAL'
          )
          AND NEW.win_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id AND result = 'win'
          )
          AND NEW.loss_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id AND result = 'loss'
          )
          AND NEW.push_count = (
              SELECT COUNT(*) FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id AND result = 'push'
          )
          AND abs(NEW.unit_profit_at_minus_110 - COALESCE((
              SELECT SUM(unit_profit_at_minus_110)
              FROM mixed_top_five_audit_details
              WHERE mixed_top_five_audit_run_id = run.id
          ), 0)) < 0.000000001
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed audit completion does not match detail ledger');
    END
    """,
)


TABLES = (
    "total_score_component_predictions",
    "total_postgame_audit_policies",
    "total_postgame_audit_runs",
    "total_postgame_audit_details",
    "total_postgame_audit_completions",
    "cross_market_correlation_policies",
    "cross_market_correlation_cells",
    "correlation_aware_unified_policies",
    "correlation_aware_unified_runs",
    "correlation_aware_unified_candidates",
    "correlation_aware_unified_pair_flags",
    "correlation_aware_unified_completions",
    "mixed_top_five_audit_runs",
    "mixed_top_five_audit_details",
    "mixed_top_five_audit_completions",
)


IMMUTABLE_TRIGGERS = tuple(
    f"""
    CREATE TRIGGER {table}_immutable_update
    BEFORE UPDATE ON {table}
    BEGIN
        SELECT RAISE(ABORT, '{table} rows are immutable');
    END
    """
    for table in TABLES
) + tuple(
    f"""
    CREATE TRIGGER {table}_immutable_delete
    BEFORE DELETE ON {table}
    BEGIN
        SELECT RAISE(ABORT, '{table} rows are immutable');
    END
    """
    for table in TABLES
)


def upgrade(conn: sqlite3.Connection) -> None:
    for statement in (*STATEMENTS, *IMMUTABLE_TRIGGERS):
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    for table in TABLES:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"missing migration-22 table: {table}")
        for suffix in ("immutable_update", "immutable_delete"):
            trigger = f"{table}_{suffix}"
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                (trigger,),
            ).fetchone() is None:
                raise RuntimeError(f"missing migration-22 trigger: {trigger}")
