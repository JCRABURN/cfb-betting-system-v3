"""Add immutable weekly diagnostics and evidence-gated policy recommendations."""

from __future__ import annotations

import sqlite3


VERSION = 12
NAME = "weekly_diagnostics"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE weekly_diagnostic_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        segment_method TEXT NOT NULL
            CHECK (segment_method = 'eight_required_dimensions_v1'),
        ats_rate_method TEXT NOT NULL
            CHECK (ats_rate_method = 'wins_over_decisions_excluding_pushes'),
        lesson_method TEXT NOT NULL
            CHECK (lesson_method = 'sample_qualified_descriptive_extremes_v1'),
        recommendation_method TEXT NOT NULL CHECK (
            recommendation_method =
                'hold_unless_confidence_underperforms_v1'
        ),
        minimum_recommendation_sample INTEGER NOT NULL
            CHECK (minimum_recommendation_sample >= 5),
        minimum_ats_delta_percentage_points REAL NOT NULL CHECK (
            minimum_ats_delta_percentage_points > 0
            AND minimum_ats_delta_percentage_points <= 100
        ),
        confidence_threshold_step_points REAL NOT NULL CHECK (
            confidence_threshold_step_points > 0
        ),
        expected_segment_count INTEGER NOT NULL
            CHECK (expected_segment_count = 26),
        expected_lesson_count INTEGER NOT NULL
            CHECK (expected_lesson_count = 4),
        expected_recommendation_count INTEGER NOT NULL
            CHECK (expected_recommendation_count = 4),
        effective_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE weekly_diagnostic_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        diagnostic_run_key TEXT NOT NULL UNIQUE
            CHECK (length(trim(diagnostic_run_key)) > 0),
        audit_run_id INTEGER NOT NULL,
        diagnostic_policy_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_run_id INTEGER,
        expected_segment_count INTEGER NOT NULL
            CHECK (expected_segment_count = 26),
        expected_lesson_count INTEGER NOT NULL
            CHECK (expected_lesson_count = 4),
        expected_recommendation_count INTEGER NOT NULL
            CHECK (expected_recommendation_count = 4),
        generated_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='generated_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (audit_run_id, sequence),
        FOREIGN KEY (audit_run_id) REFERENCES card_postgame_audit_runs(id),
        FOREIGN KEY (diagnostic_policy_id)
            REFERENCES weekly_diagnostic_policies(id),
        FOREIGN KEY (supersedes_run_id) REFERENCES weekly_diagnostic_runs(id)
    )
    """,
    """
    CREATE TABLE weekly_diagnostic_segments (
        diagnostic_run_id INTEGER NOT NULL,
        dimension_code TEXT NOT NULL,
        category_code TEXT NOT NULL,
        sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
        win_count INTEGER NOT NULL CHECK (win_count >= 0),
        loss_count INTEGER NOT NULL CHECK (loss_count >= 0),
        push_count INTEGER NOT NULL CHECK (push_count >= 0),
        ats_win_rate REAL CHECK (
            ats_win_rate IS NULL
            OR (ats_win_rate >= 0 AND ats_win_rate <= 100)
        ),
        PRIMARY KEY (diagnostic_run_id, dimension_code, category_code),
        CHECK (sample_count = win_count + loss_count + push_count),
        CHECK (
            (dimension_code = 'favorite_status'
             AND category_code IN ('favorite', 'underdog', 'pickem'))
            OR (dimension_code = 'location_status'
                AND category_code IN ('home', 'away', 'neutral'))
            OR (dimension_code = 'spread_bucket'
                AND category_code IN (
                    'pickem', 'under_3', '3_to_6_5', '7_to_9_5',
                    '10_to_13_5', '14_plus'
                ))
            OR (dimension_code = 'road_favorite'
                AND category_code IN ('road_favorite', 'other'))
            OR (dimension_code = 'confidence'
                AND category_code IN ('1', '2', '3', '4', '5'))
            OR (dimension_code = 'card_tier'
                AND category_code IN ('top_five', 'remaining'))
            OR (dimension_code = 'model_output'
                AND category_code IN ('raw_model', 'final_adjusted'))
            OR (dimension_code = 'clv_sign'
                AND category_code IN ('positive', 'neutral', 'negative'))
        ),
        FOREIGN KEY (diagnostic_run_id) REFERENCES weekly_diagnostic_runs(id)
    )
    """,
    """
    CREATE TABLE weekly_diagnostic_lessons (
        diagnostic_run_id INTEGER NOT NULL,
        lesson_order INTEGER NOT NULL CHECK (lesson_order BETWEEN 1 AND 4),
        lesson_code TEXT NOT NULL CHECK (
            lesson_code IN (
                'strongest_segment', 'weakest_segment',
                'raw_vs_adjusted', 'clv_signal'
            )
        ),
        evidence_status TEXT NOT NULL
            CHECK (evidence_status IN ('sufficient', 'insufficient')),
        dimension_code TEXT NOT NULL,
        category_code TEXT NOT NULL,
        comparison_category_code TEXT,
        sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
        primary_ats_win_rate REAL,
        comparison_ats_win_rate REAL,
        delta_percentage_points REAL,
        narrative TEXT NOT NULL CHECK (length(trim(narrative)) > 0),
        PRIMARY KEY (diagnostic_run_id, lesson_order),
        UNIQUE (diagnostic_run_id, lesson_code),
        CHECK (
            (lesson_order = 1 AND lesson_code = 'strongest_segment')
            OR (lesson_order = 2 AND lesson_code = 'weakest_segment')
            OR (lesson_order = 3 AND lesson_code = 'raw_vs_adjusted')
            OR (lesson_order = 4 AND lesson_code = 'clv_signal')
        ),
        CHECK (
            (lesson_code IN ('strongest_segment', 'weakest_segment')
             AND comparison_category_code IS NULL
             AND comparison_ats_win_rate IS NULL
             AND delta_percentage_points IS NULL)
            OR (lesson_code = 'raw_vs_adjusted'
                AND dimension_code = 'model_output'
                AND category_code = 'final_adjusted'
                AND comparison_category_code = 'raw_model')
            OR (lesson_code = 'clv_signal'
                AND dimension_code = 'clv_sign'
                AND category_code = 'positive'
                AND comparison_category_code = 'negative')
        ),
        FOREIGN KEY (diagnostic_run_id, dimension_code, category_code)
            REFERENCES weekly_diagnostic_segments(
                diagnostic_run_id, dimension_code, category_code
            ),
        FOREIGN KEY (
            diagnostic_run_id, dimension_code, comparison_category_code
        ) REFERENCES weekly_diagnostic_segments(
            diagnostic_run_id, dimension_code, category_code
        )
    )
    """,
    """
    CREATE TABLE policy_change_recommendations (
        diagnostic_run_id INTEGER NOT NULL,
        recommendation_order INTEGER NOT NULL
            CHECK (recommendation_order BETWEEN 1 AND 4),
        confidence_level INTEGER NOT NULL
            CHECK (confidence_level BETWEEN 2 AND 5),
        parameter_name TEXT NOT NULL CHECK (
            parameter_name IN (
                'confidence_5_max_uncertainty',
                'confidence_4_max_uncertainty',
                'confidence_3_max_uncertainty',
                'confidence_2_max_uncertainty'
            )
        ),
        source_ranking_policy_id INTEGER NOT NULL,
        source_confidence_policy_version TEXT NOT NULL
            CHECK (length(trim(source_confidence_policy_version)) > 0),
        source_ranking_policy_version TEXT NOT NULL
            CHECK (length(trim(source_ranking_policy_version)) > 0),
        proposed_confidence_policy_version TEXT,
        current_value REAL NOT NULL CHECK (current_value >= 0),
        recommended_value REAL NOT NULL CHECK (recommended_value >= 0),
        sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
        segment_ats_win_rate REAL,
        overall_ats_win_rate REAL,
        observed_delta_percentage_points REAL,
        recommendation_status TEXT NOT NULL CHECK (
            recommendation_status IN (
                'hold_insufficient_evidence', 'hold_no_change',
                'hold_threshold_boundary',
                'candidate_pending_owner_approval'
            )
        ),
        owner_approval_required INTEGER NOT NULL
            CHECK (owner_approval_required IN (0, 1)),
        rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
        PRIMARY KEY (diagnostic_run_id, recommendation_order),
        UNIQUE (diagnostic_run_id, parameter_name),
        CHECK (
            (recommendation_order = 1 AND confidence_level = 5
             AND parameter_name = 'confidence_5_max_uncertainty')
            OR (recommendation_order = 2 AND confidence_level = 4
                AND parameter_name = 'confidence_4_max_uncertainty')
            OR (recommendation_order = 3 AND confidence_level = 3
                AND parameter_name = 'confidence_3_max_uncertainty')
            OR (recommendation_order = 4 AND confidence_level = 2
                AND parameter_name = 'confidence_2_max_uncertainty')
        ),
        CHECK (
            (recommendation_status = 'candidate_pending_owner_approval'
             AND owner_approval_required = 1
             AND proposed_confidence_policy_version IS NOT NULL
             AND length(trim(proposed_confidence_policy_version)) > 0
             AND recommended_value != current_value)
            OR (recommendation_status != 'candidate_pending_owner_approval'
                AND owner_approval_required = 0
                AND proposed_confidence_policy_version IS NULL
                AND recommended_value = current_value)
        ),
        FOREIGN KEY (diagnostic_run_id) REFERENCES weekly_diagnostic_runs(id),
        FOREIGN KEY (source_ranking_policy_id)
            REFERENCES contest_ranking_policies(id)
    )
    """,
    f"""
    CREATE TABLE weekly_diagnostic_completions (
        diagnostic_run_id INTEGER PRIMARY KEY,
        segment_count INTEGER NOT NULL CHECK (segment_count = 26),
        lesson_count INTEGER NOT NULL CHECK (lesson_count = 4),
        recommendation_count INTEGER NOT NULL
            CHECK (recommendation_count = 4),
        candidate_recommendation_count INTEGER NOT NULL
            CHECK (candidate_recommendation_count BETWEEN 0 AND 4),
        ledger_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='ledger_sha256')}),
        completed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='completed_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (diagnostic_run_id) REFERENCES weekly_diagnostic_runs(id)
    )
    """,
    """
    CREATE VIEW weekly_diagnostic_source_results AS
    SELECT audit_run_id, 'favorite_status' AS dimension_code,
           favorite_status AS category_code, ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'location_status', location_status, ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'spread_bucket', spread_bucket_code, ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'road_favorite',
           CASE WHEN favorite_status = 'favorite' AND location_status = 'away'
                THEN 'road_favorite' ELSE 'other' END,
           ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'confidence', CAST(confidence AS TEXT), ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'card_tier',
           CASE WHEN is_top_five = 1 THEN 'top_five' ELSE 'remaining' END,
           ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'clv_sign',
           CASE WHEN clv_points > 0 THEN 'positive'
                WHEN clv_points < 0 THEN 'negative' ELSE 'neutral' END,
           ats_result
    FROM pick_audit_details
    UNION ALL
    SELECT audit_run_id, 'model_output', 'raw_model', raw_ats_result
    FROM pick_audit_details
    WHERE raw_ats_result IS NOT NULL
    UNION ALL
    SELECT audit_run_id, 'model_output', 'final_adjusted', ats_result
    FROM pick_audit_details
    WHERE raw_ats_result IS NOT NULL
    """,
    """
    CREATE INDEX idx_weekly_diagnostic_runs_audit
    ON weekly_diagnostic_runs (audit_run_id, sequence)
    """,
    """
    CREATE INDEX idx_weekly_diagnostic_segments_dimension
    ON weekly_diagnostic_segments (
        diagnostic_run_id, dimension_code, category_code
    )
    """,
    """
    CREATE INDEX idx_policy_change_recommendations_status
    ON policy_change_recommendations (
        recommendation_status, diagnostic_run_id
    )
    """,
    """
    CREATE TRIGGER weekly_diagnostic_runs_validate
    BEFORE INSERT ON weekly_diagnostic_runs
    WHEN NEW.sequence != COALESCE((
        SELECT MAX(sequence) + 1 FROM weekly_diagnostic_runs
        WHERE audit_run_id = NEW.audit_run_id
    ), 1)
    OR NEW.supersedes_run_id IS NOT (
        SELECT id FROM weekly_diagnostic_runs
        WHERE audit_run_id = NEW.audit_run_id
        ORDER BY sequence DESC LIMIT 1
    )
    OR NOT EXISTS (
        SELECT 1
        FROM card_postgame_audit_runs AS audit_run
        JOIN card_postgame_audit_completions AS audit_completion
          ON audit_completion.audit_run_id = audit_run.id
        JOIN weekly_diagnostic_policies AS policy
          ON policy.id = NEW.diagnostic_policy_id
        WHERE audit_run.id = NEW.audit_run_id
          AND julianday(policy.effective_at) <= julianday(NEW.generated_at)
          AND julianday(audit_completion.completed_at)
              <= julianday(NEW.generated_at)
          AND NEW.expected_segment_count = policy.expected_segment_count
          AND NEW.expected_lesson_count = policy.expected_lesson_count
          AND NEW.expected_recommendation_count =
              policy.expected_recommendation_count
    )
    BEGIN
        SELECT RAISE(ABORT, 'weekly diagnostic run requires a completed audit');
    END
    """,
    """
    CREATE TRIGGER weekly_diagnostic_segments_validate
    BEFORE INSERT ON weekly_diagnostic_segments
    WHEN EXISTS (
        SELECT 1 FROM weekly_diagnostic_completions
        WHERE diagnostic_run_id = NEW.diagnostic_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM weekly_diagnostic_runs AS run
        WHERE run.id = NEW.diagnostic_run_id
          AND NEW.sample_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_source_results AS source
              WHERE source.audit_run_id = run.audit_run_id
                AND source.dimension_code = NEW.dimension_code
                AND source.category_code = NEW.category_code
          )
          AND NEW.win_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_source_results AS source
              WHERE source.audit_run_id = run.audit_run_id
                AND source.dimension_code = NEW.dimension_code
                AND source.category_code = NEW.category_code
                AND source.ats_result = 'win'
          )
          AND NEW.loss_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_source_results AS source
              WHERE source.audit_run_id = run.audit_run_id
                AND source.dimension_code = NEW.dimension_code
                AND source.category_code = NEW.category_code
                AND source.ats_result = 'loss'
          )
          AND NEW.push_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_source_results AS source
              WHERE source.audit_run_id = run.audit_run_id
                AND source.dimension_code = NEW.dimension_code
                AND source.category_code = NEW.category_code
                AND source.ats_result = 'push'
          )
          AND (
              (NEW.win_count + NEW.loss_count = 0
               AND NEW.ats_win_rate IS NULL)
              OR (
                  NEW.win_count + NEW.loss_count > 0
                  AND abs(
                      NEW.ats_win_rate
                      - ROUND(
                          100.0 * NEW.win_count
                          / (NEW.win_count + NEW.loss_count),
                          2
                      )
                  ) < 0.000000001
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'weekly diagnostic segment does not match audit');
    END
    """,
    """
    CREATE TRIGGER weekly_diagnostic_lessons_validate
    BEFORE INSERT ON weekly_diagnostic_lessons
    WHEN EXISTS (
        SELECT 1 FROM weekly_diagnostic_completions
        WHERE diagnostic_run_id = NEW.diagnostic_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM weekly_diagnostic_runs AS run
        JOIN weekly_diagnostic_policies AS policy
          ON policy.id = run.diagnostic_policy_id
        JOIN weekly_diagnostic_segments AS primary_segment
          ON primary_segment.diagnostic_run_id = run.id
         AND primary_segment.dimension_code = NEW.dimension_code
         AND primary_segment.category_code = NEW.category_code
        LEFT JOIN weekly_diagnostic_segments AS comparison_segment
          ON comparison_segment.diagnostic_run_id = run.id
         AND comparison_segment.dimension_code = NEW.dimension_code
         AND comparison_segment.category_code = NEW.comparison_category_code
        WHERE run.id = NEW.diagnostic_run_id
          AND NEW.sample_count = primary_segment.sample_count
          AND NEW.primary_ats_win_rate IS primary_segment.ats_win_rate
          AND NEW.comparison_ats_win_rate IS comparison_segment.ats_win_rate
          AND NEW.delta_percentage_points IS CASE
              WHEN comparison_segment.ats_win_rate IS NULL
                OR primary_segment.ats_win_rate IS NULL THEN NULL
              ELSE ROUND(
                  primary_segment.ats_win_rate
                  - comparison_segment.ats_win_rate,
                  2
              )
          END
          AND NEW.evidence_status = CASE
              WHEN primary_segment.sample_count
                       < policy.minimum_recommendation_sample
                OR primary_segment.ats_win_rate IS NULL
                OR (
                    NEW.comparison_category_code IS NOT NULL
                    AND (
                        comparison_segment.sample_count
                            < policy.minimum_recommendation_sample
                        OR comparison_segment.ats_win_rate IS NULL
                    )
                ) THEN 'insufficient'
              ELSE 'sufficient'
          END
    )
    BEGIN
        SELECT RAISE(ABORT, 'weekly diagnostic lesson lacks matching evidence');
    END
    """,
    """
    CREATE TRIGGER policy_change_recommendations_validate
    BEFORE INSERT ON policy_change_recommendations
    WHEN EXISTS (
        SELECT 1 FROM weekly_diagnostic_completions
        WHERE diagnostic_run_id = NEW.diagnostic_run_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM weekly_diagnostic_runs AS run
        JOIN card_postgame_audit_runs AS audit_run
          ON audit_run.id = run.audit_run_id
        JOIN contest_card_policy_assignments AS assignment
          ON assignment.card_id = audit_run.card_id
        JOIN contest_ranking_policies AS ranking_policy
          ON ranking_policy.id = assignment.ranking_policy_id
        JOIN weekly_diagnostic_policies AS diagnostic_policy
          ON diagnostic_policy.id = run.diagnostic_policy_id
        JOIN weekly_diagnostic_segments AS segment
          ON segment.diagnostic_run_id = run.id
         AND segment.dimension_code = 'confidence'
         AND segment.category_code = CAST(NEW.confidence_level AS TEXT)
        WHERE run.id = NEW.diagnostic_run_id
          AND NEW.source_ranking_policy_id = ranking_policy.id
          AND NEW.source_confidence_policy_version =
              ranking_policy.confidence_policy_version
          AND NEW.source_ranking_policy_version =
              ranking_policy.ranking_policy_version
          AND NEW.current_value = CASE NEW.confidence_level
              WHEN 5 THEN ranking_policy.confidence_5_max_uncertainty
              WHEN 4 THEN ranking_policy.confidence_4_max_uncertainty
              WHEN 3 THEN ranking_policy.confidence_3_max_uncertainty
              WHEN 2 THEN ranking_policy.confidence_2_max_uncertainty
          END
          AND NEW.sample_count = segment.sample_count
          AND NEW.segment_ats_win_rate IS segment.ats_win_rate
          AND NEW.overall_ats_win_rate IS (
              SELECT CASE
                  WHEN SUM(ats_result IN ('win', 'loss')) = 0 THEN NULL
                  ELSE ROUND(
                      100.0 * SUM(ats_result = 'win')
                      / SUM(ats_result IN ('win', 'loss')),
                      2
                  )
              END
              FROM pick_audit_details
              WHERE audit_run_id = audit_run.id
          )
          AND NEW.observed_delta_percentage_points IS CASE
              WHEN segment.ats_win_rate IS NULL
                OR NEW.overall_ats_win_rate IS NULL THEN NULL
              ELSE ROUND(
                  segment.ats_win_rate - NEW.overall_ats_win_rate,
                  2
              )
          END
          AND (
              (
                  NEW.recommendation_status = 'hold_insufficient_evidence'
                  AND (
                      segment.sample_count
                          < diagnostic_policy.minimum_recommendation_sample
                      OR segment.ats_win_rate IS NULL
                      OR NEW.overall_ats_win_rate IS NULL
                  )
              )
              OR (
                  NEW.recommendation_status = 'hold_no_change'
                  AND segment.sample_count
                      >= diagnostic_policy.minimum_recommendation_sample
                  AND segment.ats_win_rate IS NOT NULL
                  AND NEW.overall_ats_win_rate IS NOT NULL
                  AND NEW.observed_delta_percentage_points
                      > -diagnostic_policy.minimum_ats_delta_percentage_points
              )
              OR (
                  NEW.recommendation_status = 'hold_threshold_boundary'
                  AND segment.sample_count
                      >= diagnostic_policy.minimum_recommendation_sample
                  AND NEW.observed_delta_percentage_points
                      <= -diagnostic_policy.minimum_ats_delta_percentage_points
                  AND NEW.current_value
                      - diagnostic_policy.confidence_threshold_step_points
                      <= CASE NEW.confidence_level
                          WHEN 5 THEN -0.000000001
                          WHEN 4 THEN
                              ranking_policy.confidence_5_max_uncertainty
                          WHEN 3 THEN
                              ranking_policy.confidence_4_max_uncertainty
                          WHEN 2 THEN
                              ranking_policy.confidence_3_max_uncertainty
                      END
              )
              OR (
                  NEW.recommendation_status =
                      'candidate_pending_owner_approval'
                  AND segment.sample_count
                      >= diagnostic_policy.minimum_recommendation_sample
                  AND NEW.observed_delta_percentage_points
                      <= -diagnostic_policy.minimum_ats_delta_percentage_points
                  AND abs(
                      NEW.recommended_value
                      - (
                          NEW.current_value
                          - diagnostic_policy.confidence_threshold_step_points
                      )
                  ) < 0.000000001
                  AND NEW.recommended_value
                      > CASE NEW.confidence_level
                          WHEN 5 THEN -0.000000001
                          WHEN 4 THEN
                              ranking_policy.confidence_5_max_uncertainty
                          WHEN 3 THEN
                              ranking_policy.confidence_4_max_uncertainty
                          WHEN 2 THEN
                              ranking_policy.confidence_3_max_uncertainty
                      END
                  AND NEW.proposed_confidence_policy_version
                      != ranking_policy.confidence_policy_version
                  AND NOT EXISTS (
                      SELECT 1 FROM contest_ranking_policies
                      WHERE confidence_policy_version =
                          NEW.proposed_confidence_policy_version
                  )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'policy recommendation is not supported by audit evidence');
    END
    """,
    """
    CREATE TRIGGER weekly_diagnostic_completions_validate
    BEFORE INSERT ON weekly_diagnostic_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM weekly_diagnostic_runs AS run
        WHERE run.id = NEW.diagnostic_run_id
          AND NEW.completed_at = run.generated_at
          AND NEW.provenance = run.provenance
          AND NEW.segment_count = run.expected_segment_count
          AND NEW.lesson_count = run.expected_lesson_count
          AND NEW.recommendation_count = run.expected_recommendation_count
          AND NEW.segment_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_segments
              WHERE diagnostic_run_id = run.id
          )
          AND NEW.lesson_count = (
              SELECT COUNT(*) FROM weekly_diagnostic_lessons
              WHERE diagnostic_run_id = run.id
          )
          AND NEW.recommendation_count = (
              SELECT COUNT(*) FROM policy_change_recommendations
              WHERE diagnostic_run_id = run.id
          )
          AND NEW.candidate_recommendation_count = (
              SELECT COUNT(*) FROM policy_change_recommendations
              WHERE diagnostic_run_id = run.id
                AND recommendation_status =
                    'candidate_pending_owner_approval'
          )
          AND (
              SELECT COUNT(DISTINCT dimension_code || ':' || category_code)
              FROM weekly_diagnostic_segments
              WHERE diagnostic_run_id = run.id
          ) = 26
          AND (
              SELECT COUNT(DISTINCT lesson_code)
              FROM weekly_diagnostic_lessons
              WHERE diagnostic_run_id = run.id
          ) = 4
          AND (
              SELECT COUNT(DISTINCT parameter_name)
              FROM policy_change_recommendations
              WHERE diagnostic_run_id = run.id
          ) = 4
          AND (
              SELECT COUNT(DISTINCT proposed_confidence_policy_version)
              FROM policy_change_recommendations
              WHERE diagnostic_run_id = run.id
                AND proposed_confidence_policy_version IS NOT NULL
          ) <= 1
    )
    BEGIN
        SELECT RAISE(ABORT, 'weekly diagnostics require complete evidence coverage');
    END
    """,
)


IMMUTABLE_TABLES = (
    (
        "weekly_diagnostic_policies",
        "id = NEW.id OR policy_version = NEW.policy_version",
    ),
    (
        "weekly_diagnostic_runs",
        "id = NEW.id OR diagnostic_run_key = NEW.diagnostic_run_key "
        "OR (audit_run_id = NEW.audit_run_id AND sequence = NEW.sequence)",
    ),
    (
        "weekly_diagnostic_segments",
        "diagnostic_run_id = NEW.diagnostic_run_id "
        "AND dimension_code = NEW.dimension_code "
        "AND category_code = NEW.category_code",
    ),
    (
        "weekly_diagnostic_lessons",
        "diagnostic_run_id = NEW.diagnostic_run_id "
        "AND (lesson_order = NEW.lesson_order OR lesson_code = NEW.lesson_code)",
    ),
    (
        "policy_change_recommendations",
        "diagnostic_run_id = NEW.diagnostic_run_id "
        "AND (recommendation_order = NEW.recommendation_order "
        "OR parameter_name = NEW.parameter_name)",
    ),
    (
        "weekly_diagnostic_completions",
        "diagnostic_run_id = NEW.diagnostic_run_id",
    ),
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
    if len(words) >= 3 and words[0:2] == ["CREATE", "VIEW"]:
        return "view", words[2]
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
