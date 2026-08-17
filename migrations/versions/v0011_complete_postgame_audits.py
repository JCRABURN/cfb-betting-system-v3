"""Add complete, versioned, immutable postgame audits for contest cards."""

from __future__ import annotations

import sqlite3


VERSION = 11
NAME = "complete_postgame_audits"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE postgame_audit_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        ats_method TEXT NOT NULL CHECK (ats_method = 'locked_home_spread'),
        clv_method TEXT NOT NULL
            CHECK (clv_method = 'selected_side_locked_to_close'),
        hook_method TEXT NOT NULL
            CHECK (hook_method = 'half_point_decision'),
        key_number_method TEXT NOT NULL
            CHECK (key_number_method = 'absolute_margin_and_line_crossing'),
        spread_bucket_method TEXT NOT NULL
            CHECK (spread_bucket_method = 'absolute_locked_spread_v1'),
        manual_adjustment_method TEXT NOT NULL
            CHECK (manual_adjustment_method = 'frozen_card_adjustment_snapshot'),
        backdoor_method TEXT NOT NULL
            CHECK (backdoor_method = 'scoring_sequence_evidence_only'),
        effective_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE postgame_audit_key_numbers (
        audit_policy_id INTEGER NOT NULL,
        priority INTEGER NOT NULL CHECK (priority > 0),
        key_number REAL NOT NULL CHECK (key_number > 0),
        PRIMARY KEY (audit_policy_id, key_number),
        UNIQUE (audit_policy_id, priority),
        FOREIGN KEY (audit_policy_id) REFERENCES postgame_audit_policies(id)
    )
    """,
    """
    CREATE TABLE postgame_audit_spread_buckets (
        audit_policy_id INTEGER NOT NULL,
        priority INTEGER NOT NULL CHECK (priority > 0),
        bucket_code TEXT NOT NULL CHECK (length(trim(bucket_code)) > 0),
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        PRIMARY KEY (audit_policy_id, bucket_code),
        UNIQUE (audit_policy_id, priority),
        FOREIGN KEY (audit_policy_id) REFERENCES postgame_audit_policies(id)
    )
    """,
    """
    CREATE TABLE postgame_audit_failure_taxonomy (
        audit_policy_id INTEGER NOT NULL,
        priority INTEGER NOT NULL CHECK (priority > 0),
        failure_code TEXT NOT NULL CHECK (length(trim(failure_code)) > 0),
        description TEXT NOT NULL CHECK (length(trim(description)) > 0),
        PRIMARY KEY (audit_policy_id, failure_code),
        UNIQUE (audit_policy_id, priority),
        FOREIGN KEY (audit_policy_id) REFERENCES postgame_audit_policies(id)
    )
    """,
    f"""
    CREATE TABLE card_postgame_audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_key TEXT NOT NULL UNIQUE
            CHECK (length(trim(audit_run_key)) > 0),
        card_id INTEGER NOT NULL,
        audit_policy_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_run_id INTEGER,
        expected_pick_count INTEGER NOT NULL CHECK (expected_pick_count > 0),
        audited_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='audited_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (card_id, sequence),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (audit_policy_id) REFERENCES postgame_audit_policies(id),
        FOREIGN KEY (supersedes_run_id) REFERENCES card_postgame_audit_runs(id)
    )
    """,
    f"""
    CREATE TABLE pick_audit_details (
        audit_id INTEGER PRIMARY KEY,
        audit_run_id INTEGER NOT NULL,
        audit_policy_id INTEGER NOT NULL,
        contest_pick_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        locked_line_correction_id INTEGER,
        locked_home_spread REAL NOT NULL,
        closing_market_line_id INTEGER NOT NULL,
        closing_home_spread REAL NOT NULL,
        closing_book TEXT NOT NULL CHECK (length(trim(closing_book)) > 0),
        final_home_points INTEGER NOT NULL CHECK (final_home_points >= 0),
        final_away_points INTEGER NOT NULL CHECK (final_away_points >= 0),
        actual_home_margin INTEGER NOT NULL,
        selected_side TEXT NOT NULL CHECK (selected_side IN ('home', 'away')),
        covered_margin REAL NOT NULL,
        ats_result TEXT NOT NULL CHECK (ats_result IN ('win', 'loss', 'push')),
        clv_points REAL NOT NULL,
        hook_outcome TEXT NOT NULL
            CHECK (hook_outcome IN ('won_by_hook', 'lost_by_hook', 'not_hook')),
        landed_key_number REAL,
        key_number_outcome TEXT NOT NULL CHECK (
            key_number_outcome IN (
                'not_key_number', 'key_number_win', 'key_number_loss',
                'key_number_push'
            )
        ),
        favorite_status TEXT NOT NULL
            CHECK (favorite_status IN ('favorite', 'underdog', 'pickem')),
        location_status TEXT NOT NULL
            CHECK (location_status IN ('home', 'away', 'neutral')),
        spread_bucket_code TEXT NOT NULL,
        confidence INTEGER NOT NULL CHECK (confidence BETWEEN 1 AND 5),
        rank INTEGER CHECK (rank IS NULL OR rank BETWEEN 1 AND 5),
        is_top_five INTEGER NOT NULL CHECK (is_top_five IN (0, 1)),
        raw_model_margin REAL,
        adjusted_model_margin REAL,
        raw_selected_side TEXT
            CHECK (raw_selected_side IS NULL OR raw_selected_side IN ('home', 'away', 'tie')),
        raw_ats_result TEXT
            CHECK (raw_ats_result IS NULL OR raw_ats_result IN ('win', 'loss', 'push')),
        manual_adjustment_count INTEGER NOT NULL CHECK (manual_adjustment_count >= 0),
        manual_margin_adjustment_total REAL NOT NULL,
        manual_confidence_adjustment_total INTEGER NOT NULL,
        manual_adjustment_effect TEXT NOT NULL CHECK (
            manual_adjustment_effect IN (
                'no_adjustment', 'net_zero', 'confidence_only', 'side_unchanged',
                'raw_tie_resolved', 'side_flip_helped', 'side_flip_harmed',
                'side_flip_neutral'
            )
        ),
        backdoor_outcome TEXT NOT NULL CHECK (
            backdoor_outcome IN (
                'not_evaluated', 'confirmed_backdoor_cover',
                'confirmed_not_backdoor'
            )
        ),
        scoring_sequence_evidence TEXT,
        audited_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='audited_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (backdoor_outcome = 'not_evaluated'
             AND scoring_sequence_evidence IS NULL)
            OR
            (backdoor_outcome != 'not_evaluated'
             AND length(trim(scoring_sequence_evidence)) > 0)
        ),
        CHECK (
            (landed_key_number IS NULL AND key_number_outcome = 'not_key_number')
            OR
            (landed_key_number IS NOT NULL
             AND key_number_outcome != 'not_key_number')
        ),
        UNIQUE (audit_run_id, contest_pick_id),
        FOREIGN KEY (audit_id) REFERENCES pick_audits(id),
        FOREIGN KEY (audit_run_id) REFERENCES card_postgame_audit_runs(id),
        FOREIGN KEY (audit_policy_id) REFERENCES postgame_audit_policies(id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (locked_line_correction_id) REFERENCES contest_line_corrections(id),
        FOREIGN KEY (closing_market_line_id) REFERENCES betting_lines(id),
        FOREIGN KEY (audit_policy_id, spread_bucket_code)
            REFERENCES postgame_audit_spread_buckets(audit_policy_id, bucket_code),
        FOREIGN KEY (audit_policy_id, landed_key_number)
            REFERENCES postgame_audit_key_numbers(audit_policy_id, key_number)
    )
    """,
    """
    CREATE TABLE pick_audit_key_number_crossings (
        audit_id INTEGER NOT NULL,
        audit_policy_id INTEGER NOT NULL,
        key_number REAL NOT NULL,
        direction TEXT NOT NULL CHECK (direction IN ('favorable', 'adverse')),
        PRIMARY KEY (audit_id, key_number),
        FOREIGN KEY (audit_id) REFERENCES pick_audit_details(audit_id),
        FOREIGN KEY (audit_policy_id, key_number)
            REFERENCES postgame_audit_key_numbers(audit_policy_id, key_number)
    )
    """,
    """
    CREATE TABLE pick_audit_failures (
        audit_id INTEGER NOT NULL,
        audit_policy_id INTEGER NOT NULL,
        priority INTEGER NOT NULL CHECK (priority > 0),
        failure_code TEXT NOT NULL,
        evidence TEXT NOT NULL CHECK (length(trim(evidence)) > 0),
        PRIMARY KEY (audit_id, failure_code),
        UNIQUE (audit_id, priority),
        FOREIGN KEY (audit_id) REFERENCES pick_audit_details(audit_id),
        FOREIGN KEY (audit_policy_id, failure_code)
            REFERENCES postgame_audit_failure_taxonomy(
                audit_policy_id, failure_code
            )
    )
    """,
    f"""
    CREATE TABLE card_postgame_audit_completions (
        audit_run_id INTEGER PRIMARY KEY,
        audit_count INTEGER NOT NULL CHECK (audit_count > 0),
        win_count INTEGER NOT NULL CHECK (win_count >= 0),
        loss_count INTEGER NOT NULL CHECK (loss_count >= 0),
        push_count INTEGER NOT NULL CHECK (push_count >= 0),
        ledger_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='ledger_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='completed_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (audit_count = win_count + loss_count + push_count),
        FOREIGN KEY (audit_run_id) REFERENCES card_postgame_audit_runs(id)
    )
    """,
    """
    CREATE INDEX idx_card_postgame_audit_runs_card
    ON card_postgame_audit_runs (card_id, sequence)
    """,
    """
    CREATE INDEX idx_pick_audit_details_run
    ON pick_audit_details (audit_run_id, contest_pick_id)
    """,
    """
    CREATE INDEX idx_pick_audit_failures_code
    ON pick_audit_failures (failure_code, audit_id)
    """,
    """
    CREATE TRIGGER card_postgame_audit_runs_validate
    BEFORE INSERT ON card_postgame_audit_runs
    WHEN NEW.sequence != COALESCE((
        SELECT MAX(sequence) + 1 FROM card_postgame_audit_runs
        WHERE card_id = NEW.card_id
    ), 1)
    OR NEW.supersedes_run_id IS NOT (
        SELECT id FROM card_postgame_audit_runs
        WHERE card_id = NEW.card_id ORDER BY sequence DESC LIMIT 1
    )
    OR NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN postgame_audit_policies AS policy
          ON policy.id = NEW.audit_policy_id
        WHERE card.id = NEW.card_id
          AND julianday(policy.effective_at) <= julianday(NEW.audited_at)
          AND julianday(card.generated_at) <= julianday(NEW.audited_at)
          AND NEW.expected_pick_count = (
              SELECT COUNT(*) FROM contest_picks WHERE card_id = card.id
          )
          AND NEW.expected_pick_count = (
              SELECT COUNT(*)
              FROM contest_locked_lines AS expected_line
              WHERE expected_line.contest_id = card.contest_id
                AND julianday(expected_line.locked_at)
                    <= julianday(card.generated_at)
          )
          AND NOT EXISTS (
              SELECT 1
              FROM contest_locked_lines AS expected_line
              WHERE expected_line.contest_id = card.contest_id
                AND julianday(expected_line.locked_at)
                    <= julianday(card.generated_at)
                AND NOT EXISTS (
                    SELECT 1 FROM contest_picks AS expected_pick
                    WHERE expected_pick.card_id = card.id
                      AND expected_pick.locked_line_id = expected_line.id
                )
          )
          AND (
              SELECT COUNT(*) FROM contest_picks
              WHERE card_id = card.id AND is_top_five = 1
          ) = min(5, NEW.expected_pick_count)
          AND NOT EXISTS (
              SELECT 1 FROM contest_picks
              WHERE card_id = card.id
                AND (
                    selected_side NOT IN ('home', 'away')
                    OR confidence IS NULL
                    OR confidence NOT BETWEEN 1 AND 5
                    OR (is_top_five = 1
                        AND (rank IS NULL OR rank NOT BETWEEN
                            1 AND min(5, NEW.expected_pick_count)))
                    OR (is_top_five = 0 AND rank IS NOT NULL)
                )
          )
          AND (
              SELECT COUNT(DISTINCT rank) FROM contest_picks
              WHERE card_id = card.id AND is_top_five = 1
          ) = min(5, NEW.expected_pick_count)
          AND NEW.expected_pick_count > 0
          AND (SELECT COUNT(*) FROM postgame_audit_key_numbers
               WHERE audit_policy_id = policy.id) = 4
          AND (SELECT COUNT(*) FROM postgame_audit_spread_buckets
               WHERE audit_policy_id = policy.id) = 6
          AND (SELECT COUNT(*) FROM postgame_audit_failure_taxonomy
               WHERE audit_policy_id = policy.id) = 7
    )
    BEGIN
        SELECT RAISE(ABORT, 'postgame audit run or policy is incomplete');
    END
    """,
    """
    CREATE TRIGGER pick_audit_details_validate
    BEFORE INSERT ON pick_audit_details
    WHEN EXISTS (
        SELECT 1 FROM card_postgame_audit_completions
        WHERE audit_run_id = NEW.audit_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM pick_audits AS audit
        JOIN card_postgame_audit_runs AS run ON run.id = NEW.audit_run_id
        JOIN contest_picks AS pick ON pick.id = NEW.contest_pick_id
        JOIN contest_cards AS card ON card.id = pick.card_id
        JOIN contest_locked_lines AS locked ON locked.id = pick.locked_line_id
        JOIN games AS game ON game.game_id = NEW.game_id
        JOIN betting_lines AS closing ON closing.id = NEW.closing_market_line_id
        WHERE audit.id = NEW.audit_id
          AND audit.contest_pick_id = pick.id
          AND audit.audit_key = run.audit_run_key || ':pick:' || pick.id
          AND audit.audit_status = 'final'
          AND audit.result = NEW.ats_result
          AND audit.final_home_points = NEW.final_home_points
          AND audit.final_away_points = NEW.final_away_points
          AND (audit.closing_market_line_id IS NULL
               OR audit.closing_market_line_id = closing.id)
          AND (audit.clv_points IS NULL
               OR abs(audit.clv_points - NEW.clv_points) < 0.000000001)
          AND audit.policy_version = (
              SELECT policy_version FROM postgame_audit_policies
              WHERE id = NEW.audit_policy_id
          )
          AND audit.audited_at = NEW.audited_at
          AND audit.source = NEW.source
          AND audit.provenance = NEW.provenance
          AND run.card_id = card.id
          AND run.audit_policy_id = NEW.audit_policy_id
          AND run.audited_at = NEW.audited_at
          AND run.source = NEW.source
          AND run.provenance = NEW.provenance
          AND pick.locked_line_id = NEW.locked_line_id
          AND locked.id = NEW.locked_line_id
          AND NEW.locked_line_correction_id IS (
              SELECT correction.id FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = locked.id
                AND julianday(correction.corrected_at)
                    <= julianday(pick.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          )
          AND NEW.locked_home_spread = COALESCE((
              SELECT correction.home_spread
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = locked.id
                AND julianday(correction.corrected_at)
                    <= julianday(pick.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ), locked.home_spread)
          AND NEW.game_id = COALESCE((
              SELECT correction.game_id
              FROM contest_line_corrections AS correction
              WHERE correction.locked_line_id = locked.id
                AND julianday(correction.corrected_at)
                    <= julianday(pick.generated_at)
              ORDER BY correction.sequence DESC LIMIT 1
          ), locked.game_id)
          AND game.completed = 1
          AND game.home_points = NEW.final_home_points
          AND game.away_points = NEW.final_away_points
          AND NEW.actual_home_margin = game.home_points - game.away_points
          AND closing.game_id = game.game_id
          AND closing.line_type = 'closing'
          AND closing.home_spread = NEW.closing_home_spread
          AND closing.book = NEW.closing_book
          AND julianday(closing.fetched_at) >= julianday(pick.generated_at)
          AND julianday(closing.fetched_at) <= julianday(game.start_date)
          AND julianday(game.start_date) <= julianday(NEW.audited_at)
          AND pick.selected_side = NEW.selected_side
          AND pick.confidence = NEW.confidence
          AND pick.rank IS NEW.rank
          AND pick.is_top_five = NEW.is_top_five
          AND (
              (
                  pick.model_prediction_id IS NULL
                  AND NEW.raw_model_margin IS NULL
                  AND NEW.adjusted_model_margin IS NULL
                  AND NEW.raw_selected_side IS NULL
                  AND NEW.raw_ats_result IS NULL
                  AND NEW.manual_adjustment_count = 0
                  AND NEW.manual_margin_adjustment_total = 0
                  AND NEW.manual_confidence_adjustment_total = 0
                  AND NEW.manual_adjustment_effect = 'no_adjustment'
              )
              OR EXISTS (
                  SELECT 1
                  FROM contest_pick_adjustment_snapshots AS snapshot
                  WHERE snapshot.contest_pick_id = pick.id
                    AND snapshot.model_prediction_id = pick.model_prediction_id
                    AND NEW.raw_model_margin = snapshot.raw_model_margin
                    AND NEW.adjusted_model_margin = snapshot.adjusted_model_margin
                    AND NEW.manual_adjustment_count = snapshot.adjustment_count
                    AND NEW.manual_margin_adjustment_total =
                        snapshot.margin_adjustment_total
                    AND NEW.manual_confidence_adjustment_total =
                        snapshot.confidence_adjustment_total
                    AND NEW.raw_selected_side = CASE
                        WHEN snapshot.raw_model_margin + NEW.locked_home_spread > 0
                            THEN 'home'
                        WHEN snapshot.raw_model_margin + NEW.locked_home_spread < 0
                            THEN 'away'
                        ELSE 'tie'
                    END
                    AND NEW.raw_ats_result IS CASE
                        WHEN snapshot.raw_model_margin + NEW.locked_home_spread = 0
                            THEN NULL
                        WHEN CASE
                            WHEN snapshot.raw_model_margin
                                 + NEW.locked_home_spread > 0
                                THEN NEW.actual_home_margin
                                     + NEW.locked_home_spread
                            ELSE -(NEW.actual_home_margin
                                   + NEW.locked_home_spread)
                        END > 0 THEN 'win'
                        WHEN CASE
                            WHEN snapshot.raw_model_margin
                                 + NEW.locked_home_spread > 0
                                THEN NEW.actual_home_margin
                                     + NEW.locked_home_spread
                            ELSE -(NEW.actual_home_margin
                                   + NEW.locked_home_spread)
                        END < 0 THEN 'loss'
                        ELSE 'push'
                    END
                    AND NEW.manual_adjustment_effect = CASE
                        WHEN snapshot.adjustment_count = 0
                            THEN 'no_adjustment'
                        WHEN snapshot.margin_adjustment_total = 0
                             AND snapshot.confidence_adjustment_total = 0
                            THEN 'net_zero'
                        WHEN snapshot.margin_adjustment_total = 0
                            THEN 'confidence_only'
                        WHEN NEW.raw_selected_side = NEW.selected_side
                            THEN 'side_unchanged'
                        WHEN NEW.raw_selected_side = 'tie'
                            THEN 'raw_tie_resolved'
                        WHEN NEW.ats_result = 'win'
                             AND NEW.raw_ats_result IN ('loss', 'push')
                            THEN 'side_flip_helped'
                        WHEN NEW.ats_result = 'push'
                             AND NEW.raw_ats_result = 'loss'
                            THEN 'side_flip_helped'
                        WHEN NEW.ats_result = 'loss'
                             AND NEW.raw_ats_result IN ('win', 'push')
                            THEN 'side_flip_harmed'
                        WHEN NEW.ats_result = 'push'
                             AND NEW.raw_ats_result = 'win'
                            THEN 'side_flip_harmed'
                        ELSE 'side_flip_neutral'
                    END
              )
          )
          AND abs(NEW.covered_margin - CASE NEW.selected_side
              WHEN 'home' THEN NEW.actual_home_margin + NEW.locked_home_spread
              ELSE -(NEW.actual_home_margin + NEW.locked_home_spread)
          END) < 0.000000001
          AND NEW.ats_result = CASE
              WHEN NEW.covered_margin > 0 THEN 'win'
              WHEN NEW.covered_margin < 0 THEN 'loss'
              ELSE 'push'
          END
          AND abs(NEW.clv_points - ROUND(CASE NEW.selected_side
              WHEN 'home' THEN NEW.locked_home_spread - NEW.closing_home_spread
              ELSE NEW.closing_home_spread - NEW.locked_home_spread
          END, 2)) < 0.000000001
          AND NEW.hook_outcome = CASE
              WHEN abs(NEW.locked_home_spread * 2) % 2 = 1
                   AND abs(NEW.covered_margin) = 0.5
                   AND NEW.ats_result = 'win' THEN 'won_by_hook'
              WHEN abs(NEW.locked_home_spread * 2) % 2 = 1
                   AND abs(NEW.covered_margin) = 0.5
                   AND NEW.ats_result = 'loss' THEN 'lost_by_hook'
              ELSE 'not_hook'
          END
          AND NEW.favorite_status = CASE
              WHEN NEW.locked_home_spread = 0 THEN 'pickem'
              WHEN (NEW.locked_home_spread < 0 AND NEW.selected_side = 'home')
                OR (NEW.locked_home_spread > 0 AND NEW.selected_side = 'away')
                THEN 'favorite'
              ELSE 'underdog'
          END
          AND NEW.location_status = CASE
              WHEN game.neutral_site = 1 THEN 'neutral'
              ELSE NEW.selected_side
          END
          AND NEW.spread_bucket_code = CASE
              WHEN abs(NEW.locked_home_spread) = 0 THEN 'pickem'
              WHEN abs(NEW.locked_home_spread) < 3 THEN 'under_3'
              WHEN abs(NEW.locked_home_spread) < 7 THEN '3_to_6_5'
              WHEN abs(NEW.locked_home_spread) < 10 THEN '7_to_9_5'
              WHEN abs(NEW.locked_home_spread) < 14 THEN '10_to_13_5'
              ELSE '14_plus'
          END
          AND NEW.landed_key_number IS CASE
              WHEN EXISTS (
                  SELECT 1 FROM postgame_audit_key_numbers AS key_number
                  WHERE key_number.audit_policy_id = NEW.audit_policy_id
                    AND key_number.key_number = abs(NEW.actual_home_margin)
              ) THEN abs(NEW.actual_home_margin)
              ELSE NULL
          END
          AND NEW.key_number_outcome = CASE
              WHEN NEW.landed_key_number IS NULL THEN 'not_key_number'
              ELSE 'key_number_' || NEW.ats_result
          END
          AND NOT (
              NEW.backdoor_outcome = 'confirmed_backdoor_cover'
              AND NEW.ats_result != 'win'
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick audit detail does not match immutable sources');
    END
    """,
    """
    CREATE TRIGGER pick_audit_key_number_crossings_validate
    BEFORE INSERT ON pick_audit_key_number_crossings
    WHEN EXISTS (
        SELECT 1 FROM pick_audit_details AS detail
        JOIN card_postgame_audit_completions AS completion
          ON completion.audit_run_id = detail.audit_run_id
        WHERE detail.audit_id = NEW.audit_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM pick_audit_details AS detail
        JOIN postgame_audit_key_numbers AS key_number
          ON key_number.audit_policy_id = detail.audit_policy_id
         AND key_number.key_number = NEW.key_number
        WHERE detail.audit_id = NEW.audit_id
          AND NEW.audit_policy_id = detail.audit_policy_id
          AND min(abs(detail.locked_home_spread), abs(detail.closing_home_spread))
                <= NEW.key_number
          AND NEW.key_number <=
              max(abs(detail.locked_home_spread), abs(detail.closing_home_spread))
          AND abs(detail.locked_home_spread) != abs(detail.closing_home_spread)
          AND NEW.direction = CASE
              WHEN detail.clv_points > 0 THEN 'favorable'
              ELSE 'adverse'
          END
          AND detail.clv_points != 0
    )
    BEGIN
        SELECT RAISE(ABORT, 'key-number crossing does not match audit lines');
    END
    """,
    """
    CREATE TRIGGER pick_audit_failures_validate
    BEFORE INSERT ON pick_audit_failures
    WHEN EXISTS (
        SELECT 1 FROM pick_audit_details AS detail
        JOIN card_postgame_audit_completions AS completion
          ON completion.audit_run_id = detail.audit_run_id
        WHERE detail.audit_id = NEW.audit_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM pick_audit_details AS detail
        JOIN postgame_audit_failure_taxonomy AS taxonomy
          ON taxonomy.audit_policy_id = detail.audit_policy_id
         AND taxonomy.failure_code = NEW.failure_code
        WHERE detail.audit_id = NEW.audit_id
          AND NEW.audit_policy_id = detail.audit_policy_id
          AND (
              (NEW.failure_code = 'no_failure' AND detail.ats_result = 'win')
              OR (NEW.failure_code = 'push' AND detail.ats_result = 'push')
              OR (
                  NEW.failure_code = 'model_backed_loss'
                  AND detail.ats_result = 'loss'
                  AND EXISTS (
                      SELECT 1 FROM contest_picks
                      WHERE id = detail.contest_pick_id
                        AND model_prediction_id IS NOT NULL
                  )
              )
              OR (
                  NEW.failure_code = 'fallback_loss'
                  AND detail.ats_result = 'loss'
                  AND EXISTS (
                      SELECT 1 FROM contest_picks
                      WHERE id = detail.contest_pick_id
                        AND model_prediction_id IS NULL
                  )
              )
              OR (
                  NEW.failure_code = 'hook_loss'
                  AND detail.hook_outcome = 'lost_by_hook'
              )
              OR (
                  NEW.failure_code = 'key_number_loss'
                  AND detail.key_number_outcome = 'key_number_loss'
              )
              OR (
                  NEW.failure_code = 'manual_adjustment_harmed'
                  AND detail.manual_adjustment_effect = 'side_flip_harmed'
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'failure code is not defined by the audit policy');
    END
    """,
    f"""
    CREATE TRIGGER card_postgame_audit_completions_validate
    BEFORE INSERT ON card_postgame_audit_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM card_postgame_audit_runs AS run
        WHERE run.id = NEW.audit_run_id
          AND NEW.completed_at = run.audited_at
          AND NEW.provenance = run.provenance
          AND NEW.audit_count = run.expected_pick_count
          AND NEW.audit_count = (
              SELECT COUNT(*) FROM pick_audit_details
              WHERE audit_run_id = run.id
          )
          AND NEW.win_count = (
              SELECT COUNT(*) FROM pick_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'win'
          )
          AND NEW.loss_count = (
              SELECT COUNT(*) FROM pick_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'loss'
          )
          AND NEW.push_count = (
              SELECT COUNT(*) FROM pick_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'push'
          )
          AND NOT EXISTS (
              SELECT 1 FROM contest_picks AS pick
              WHERE pick.card_id = run.card_id
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_details AS detail
                    WHERE detail.audit_run_id = run.id
                      AND detail.contest_pick_id = pick.id
                )
          )
          AND NOT EXISTS (
              SELECT 1
              FROM pick_audit_details AS detail
              JOIN postgame_audit_key_numbers AS key_number
                ON key_number.audit_policy_id = detail.audit_policy_id
              WHERE detail.audit_run_id = run.id
                AND min(abs(detail.locked_home_spread),
                        abs(detail.closing_home_spread)) <= key_number.key_number
                AND key_number.key_number <=
                    max(abs(detail.locked_home_spread),
                        abs(detail.closing_home_spread))
                AND abs(detail.locked_home_spread)
                    != abs(detail.closing_home_spread)
                AND detail.clv_points != 0
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_key_number_crossings AS crossing
                    WHERE crossing.audit_id = detail.audit_id
                      AND crossing.key_number = key_number.key_number
                )
          )
          AND NOT EXISTS (
              SELECT 1 FROM pick_audit_details AS detail
              WHERE detail.audit_run_id = run.id
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_failures AS failure
                    WHERE failure.audit_id = detail.audit_id
                      AND failure.failure_code = CASE
                          WHEN detail.ats_result = 'win' THEN 'no_failure'
                          WHEN detail.ats_result = 'push' THEN 'push'
                          WHEN EXISTS (
                              SELECT 1 FROM contest_picks
                              WHERE id = detail.contest_pick_id
                                AND model_prediction_id IS NULL
                          ) THEN 'fallback_loss'
                          ELSE 'model_backed_loss'
                      END
                )
          )
          AND NOT EXISTS (
              SELECT 1 FROM pick_audit_details AS detail
              WHERE detail.audit_run_id = run.id
                AND detail.hook_outcome = 'lost_by_hook'
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_failures AS failure
                    WHERE failure.audit_id = detail.audit_id
                      AND failure.failure_code = 'hook_loss'
                )
          )
          AND NOT EXISTS (
              SELECT 1 FROM pick_audit_details AS detail
              WHERE detail.audit_run_id = run.id
                AND detail.key_number_outcome = 'key_number_loss'
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_failures AS failure
                    WHERE failure.audit_id = detail.audit_id
                      AND failure.failure_code = 'key_number_loss'
                )
          )
          AND NOT EXISTS (
              SELECT 1 FROM pick_audit_details AS detail
              WHERE detail.audit_run_id = run.id
                AND detail.manual_adjustment_effect = 'side_flip_harmed'
                AND NOT EXISTS (
                    SELECT 1 FROM pick_audit_failures AS failure
                    WHERE failure.audit_id = detail.audit_id
                      AND failure.failure_code = 'manual_adjustment_harmed'
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'postgame audit completion requires full valid coverage');
    END
    """,
)


POLICY_DEFINITION_TABLES = (
    "postgame_audit_key_numbers",
    "postgame_audit_spread_buckets",
    "postgame_audit_failure_taxonomy",
)

for _table in POLICY_DEFINITION_TABLES:
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_freeze_on_use
        BEFORE INSERT ON {_table}
        WHEN EXISTS (
            SELECT 1 FROM card_postgame_audit_runs
            WHERE audit_policy_id = NEW.audit_policy_id
        )
        BEGIN
            SELECT RAISE(ABORT, '{_table} policy definitions are frozen once used');
        END
        """,
    )


IMMUTABLE_TABLES = (
    ("postgame_audit_policies", "id = NEW.id OR policy_version = NEW.policy_version"),
    (
        "postgame_audit_key_numbers",
        "(audit_policy_id = NEW.audit_policy_id "
        "AND (key_number = NEW.key_number OR priority = NEW.priority))",
    ),
    (
        "postgame_audit_spread_buckets",
        "(audit_policy_id = NEW.audit_policy_id "
        "AND (bucket_code = NEW.bucket_code OR priority = NEW.priority))",
    ),
    (
        "postgame_audit_failure_taxonomy",
        "(audit_policy_id = NEW.audit_policy_id "
        "AND (failure_code = NEW.failure_code OR priority = NEW.priority))",
    ),
    (
        "card_postgame_audit_runs",
        "id = NEW.id OR audit_run_key = NEW.audit_run_key "
        "OR (card_id = NEW.card_id AND sequence = NEW.sequence)",
    ),
    (
        "pick_audit_details",
        "audit_id = NEW.audit_id OR (audit_run_id = NEW.audit_run_id "
        "AND contest_pick_id = NEW.contest_pick_id)",
    ),
    (
        "pick_audit_key_number_crossings",
        "audit_id = NEW.audit_id AND key_number = NEW.key_number",
    ),
    (
        "pick_audit_failures",
        "audit_id = NEW.audit_id AND (failure_code = NEW.failure_code "
        "OR priority = NEW.priority)",
    ),
    ("card_postgame_audit_completions", "audit_run_id = NEW.audit_run_id"),
)

for _table, _duplicate_condition in IMMUTABLE_TABLES:
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_duplicate_insert
        BEFORE INSERT ON {_table}
        WHEN EXISTS (
            SELECT 1 FROM {_table} WHERE {_duplicate_condition}
        )
        BEGIN
            SELECT RAISE(ABORT, '{_table} records cannot be replaced');
        END
        """,
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
    if len(words) >= 3 and words[0:2] == ["CREATE", "TRIGGER"]:
        return "trigger", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
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
        if _normalize_sql(row[0]) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")
