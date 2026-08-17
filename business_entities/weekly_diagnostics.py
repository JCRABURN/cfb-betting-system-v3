"""Immutable weekly diagnostics and evidence-gated policy recommendations."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.complete_audits import (
    get_card_postgame_audit_run,
    validate_postgame_audit_run,
)
from business_entities.ranking import get_card_ranking_policy


SEGMENT_METHOD = "eight_required_dimensions_v1"
ATS_RATE_METHOD = "wins_over_decisions_excluding_pushes"
LESSON_METHOD = "sample_qualified_descriptive_extremes_v1"
RECOMMENDATION_METHOD = "hold_unless_confidence_underperforms_v1"
EXPECTED_LESSON_COUNT = 4
EXPECTED_RECOMMENDATION_COUNT = 4

SEGMENT_CATEGORIES = (
    ("favorite_status", "favorite"),
    ("favorite_status", "underdog"),
    ("favorite_status", "pickem"),
    ("location_status", "home"),
    ("location_status", "away"),
    ("location_status", "neutral"),
    ("spread_bucket", "pickem"),
    ("spread_bucket", "under_3"),
    ("spread_bucket", "3_to_6_5"),
    ("spread_bucket", "7_to_9_5"),
    ("spread_bucket", "10_to_13_5"),
    ("spread_bucket", "14_plus"),
    ("road_favorite", "road_favorite"),
    ("road_favorite", "other"),
    ("confidence", "1"),
    ("confidence", "2"),
    ("confidence", "3"),
    ("confidence", "4"),
    ("confidence", "5"),
    ("card_tier", "top_five"),
    ("card_tier", "remaining"),
    ("model_output", "raw_model"),
    ("model_output", "final_adjusted"),
    ("clv_sign", "positive"),
    ("clv_sign", "neutral"),
    ("clv_sign", "negative"),
)
EXPECTED_SEGMENT_COUNT = len(SEGMENT_CATEGORIES)

LESSON_CODES = (
    "strongest_segment",
    "weakest_segment",
    "raw_vs_adjusted",
    "clv_signal",
)
RECOMMENDATION_PARAMETERS = (
    (5, "confidence_5_max_uncertainty"),
    (4, "confidence_4_max_uncertainty"),
    (3, "confidence_3_max_uncertainty"),
    (2, "confidence_2_max_uncertainty"),
)


@dataclass(frozen=True)
class WeeklyDiagnosticsPolicy:
    policy_version: str
    minimum_recommendation_sample: int
    minimum_ats_delta_percentage_points: float
    confidence_threshold_step_points: float
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedWeeklyDiagnosticsPolicy:
    id: int
    policy_version: str
    segment_method: str
    ats_rate_method: str
    lesson_method: str
    recommendation_method: str
    minimum_recommendation_sample: int
    minimum_ats_delta_percentage_points: float
    confidence_threshold_step_points: float
    expected_segment_count: int
    expected_lesson_count: int
    expected_recommendation_count: int
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class WeeklyDiagnosticRun:
    id: int
    diagnostic_run_key: str
    audit_run_id: int
    diagnostic_policy_id: int
    sequence: int
    supersedes_run_id: int | None
    expected_segment_count: int
    expected_lesson_count: int
    expected_recommendation_count: int
    generated_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class WeeklyDiagnosticSegment:
    diagnostic_run_id: int
    dimension_code: str
    category_code: str
    sample_count: int
    win_count: int
    loss_count: int
    push_count: int
    ats_win_rate: float | None


@dataclass(frozen=True)
class WeeklyDiagnosticLesson:
    diagnostic_run_id: int
    lesson_order: int
    lesson_code: str
    evidence_status: str
    dimension_code: str
    category_code: str
    comparison_category_code: str | None
    sample_count: int
    primary_ats_win_rate: float | None
    comparison_ats_win_rate: float | None
    delta_percentage_points: float | None
    narrative: str


@dataclass(frozen=True)
class PolicyChangeRecommendation:
    diagnostic_run_id: int
    recommendation_order: int
    confidence_level: int
    parameter_name: str
    source_ranking_policy_id: int
    source_confidence_policy_version: str
    source_ranking_policy_version: str
    proposed_confidence_policy_version: str | None
    current_value: float
    recommended_value: float
    sample_count: int
    segment_ats_win_rate: float | None
    overall_ats_win_rate: float | None
    observed_delta_percentage_points: float | None
    recommendation_status: str
    owner_approval_required: bool
    rationale: str


@dataclass(frozen=True)
class WeeklyDiagnosticCompletion:
    diagnostic_run_id: int
    segment_count: int
    lesson_count: int
    recommendation_count: int
    candidate_recommendation_count: int
    ledger_sha256: str
    completed_at: str
    provenance: str


@dataclass(frozen=True)
class WeeklyDiagnosticsReport:
    diagnostic_run_id: int
    expected_segment_count: int
    segment_count: int
    missing_segments: tuple[tuple[str, str], ...]
    lesson_count: int
    missing_lesson_codes: tuple[str, ...]
    recommendation_count: int
    missing_recommendation_parameters: tuple[str, ...]
    candidate_recommendation_count: int
    ledger_sha256: str
    recorded_ledger_sha256: str | None

    @property
    def complete(self) -> bool:
        return (
            self.segment_count == self.expected_segment_count
            and not self.missing_segments
            and self.lesson_count == EXPECTED_LESSON_COUNT
            and not self.missing_lesson_codes
            and self.recommendation_count == EXPECTED_RECOMMENDATION_COUNT
            and not self.missing_recommendation_parameters
            and self.recorded_ledger_sha256 == self.ledger_sha256
        )


@dataclass(frozen=True)
class WeeklyDiagnosticsResult:
    run: WeeklyDiagnosticRun
    segments: tuple[WeeklyDiagnosticSegment, ...]
    lessons: tuple[WeeklyDiagnosticLesson, ...]
    recommendations: tuple[PolicyChangeRecommendation, ...]
    completion: WeeklyDiagnosticCompletion
    report: WeeklyDiagnosticsReport


_POLICY_COLUMNS = (
    "id, policy_version, segment_method, ats_rate_method, lesson_method, "
    "recommendation_method, minimum_recommendation_sample, "
    "minimum_ats_delta_percentage_points, confidence_threshold_step_points, "
    "expected_segment_count, expected_lesson_count, "
    "expected_recommendation_count, effective_at, created_by, provenance"
)
_RUN_COLUMNS = (
    "id, diagnostic_run_key, audit_run_id, diagnostic_policy_id, sequence, "
    "supersedes_run_id, expected_segment_count, expected_lesson_count, "
    "expected_recommendation_count, generated_at, source, provenance"
)
_SEGMENT_COLUMNS = (
    "diagnostic_run_id, dimension_code, category_code, sample_count, "
    "win_count, loss_count, push_count, ats_win_rate"
)
_LESSON_COLUMNS = (
    "diagnostic_run_id, lesson_order, lesson_code, evidence_status, "
    "dimension_code, category_code, comparison_category_code, sample_count, "
    "primary_ats_win_rate, comparison_ats_win_rate, delta_percentage_points, "
    "narrative"
)
_RECOMMENDATION_COLUMNS = (
    "diagnostic_run_id, recommendation_order, confidence_level, "
    "parameter_name, source_ranking_policy_id, "
    "source_confidence_policy_version, source_ranking_policy_version, "
    "proposed_confidence_policy_version, current_value, recommended_value, "
    "sample_count, segment_ats_win_rate, overall_ats_win_rate, "
    "observed_delta_percentage_points, recommendation_status, "
    "owner_approval_required, rationale"
)
_COMPLETION_COLUMNS = (
    "diagnostic_run_id, segment_count, lesson_count, recommendation_count, "
    "candidate_recommendation_count, ledger_sha256, completed_at, provenance"
)


def _validated_policy(policy: WeeklyDiagnosticsPolicy) -> WeeklyDiagnosticsPolicy:
    if not isinstance(policy, WeeklyDiagnosticsPolicy):
        raise BusinessEntityError(
            "diagnostic_policy must be a WeeklyDiagnosticsPolicy"
        )
    minimum_sample = integer(
        policy.minimum_recommendation_sample,
        "minimum_recommendation_sample",
        5,
    )
    minimum_delta = number(
        policy.minimum_ats_delta_percentage_points,
        "minimum_ats_delta_percentage_points",
    )
    if minimum_delta <= 0 or minimum_delta > 100:
        raise BusinessEntityError(
            "minimum_ats_delta_percentage_points must be within (0, 100]"
        )
    threshold_step = number(
        policy.confidence_threshold_step_points,
        "confidence_threshold_step_points",
    )
    if threshold_step <= 0:
        raise BusinessEntityError(
            "confidence_threshold_step_points must be greater than zero"
        )
    return WeeklyDiagnosticsPolicy(
        policy_version=required_text(policy.policy_version, "policy_version"),
        minimum_recommendation_sample=minimum_sample,
        minimum_ats_delta_percentage_points=minimum_delta,
        confidence_threshold_step_points=threshold_step,
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "effective_at")
        ),
        created_by=required_text(policy.created_by, "created_by"),
        provenance=required_text(policy.provenance, "provenance"),
    )


def get_weekly_diagnostics_policy(
    conn: sqlite3.Connection, diagnostic_policy_id: int
) -> RecordedWeeklyDiagnosticsPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM weekly_diagnostic_policies WHERE id = ?",
        (integer(diagnostic_policy_id, "diagnostic_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"weekly diagnostic policy does not exist: {diagnostic_policy_id}"
        )
    return RecordedWeeklyDiagnosticsPolicy(*row)


def register_weekly_diagnostics_policy(
    conn: sqlite3.Connection, policy: WeeklyDiagnosticsPolicy
) -> RecordedWeeklyDiagnosticsPolicy:
    policy = _validated_policy(policy)
    requested = (
        policy.policy_version,
        SEGMENT_METHOD,
        ATS_RATE_METHOD,
        LESSON_METHOD,
        RECOMMENDATION_METHOD,
        policy.minimum_recommendation_sample,
        policy.minimum_ats_delta_percentage_points,
        policy.confidence_threshold_step_points,
        EXPECTED_SEGMENT_COUNT,
        EXPECTED_LESSON_COUNT,
        EXPECTED_RECOMMENDATION_COUNT,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM weekly_diagnostic_policies "
                "WHERE policy_version = ?",
                (policy.policy_version,),
            ).fetchone()
            if row is not None:
                existing = RecordedWeeklyDiagnosticsPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "weekly diagnostic policy version has different "
                        "immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO weekly_diagnostic_policies "
                "(policy_version, segment_method, ats_rate_method, "
                "lesson_method, recommendation_method, "
                "minimum_recommendation_sample, "
                "minimum_ats_delta_percentage_points, "
                "confidence_threshold_step_points, expected_segment_count, "
                "expected_lesson_count, expected_recommendation_count, "
                "effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_weekly_diagnostics_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("weekly diagnostic policy", exc) from exc


def get_weekly_diagnostic_run(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> WeeklyDiagnosticRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM weekly_diagnostic_runs WHERE id = ?",
        (integer(diagnostic_run_id, "diagnostic_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"weekly diagnostic run does not exist: {diagnostic_run_id}"
        )
    return WeeklyDiagnosticRun(*row)


def list_weekly_diagnostic_segments(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> tuple[WeeklyDiagnosticSegment, ...]:
    rows = conn.execute(
        f"SELECT {_SEGMENT_COLUMNS} FROM weekly_diagnostic_segments "
        "WHERE diagnostic_run_id = ? ORDER BY dimension_code, category_code",
        (integer(diagnostic_run_id, "diagnostic_run_id", 1),),
    ).fetchall()
    return tuple(WeeklyDiagnosticSegment(*row) for row in rows)


def list_weekly_diagnostic_lessons(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> tuple[WeeklyDiagnosticLesson, ...]:
    rows = conn.execute(
        f"SELECT {_LESSON_COLUMNS} FROM weekly_diagnostic_lessons "
        "WHERE diagnostic_run_id = ? ORDER BY lesson_order",
        (integer(diagnostic_run_id, "diagnostic_run_id", 1),),
    ).fetchall()
    return tuple(WeeklyDiagnosticLesson(*row) for row in rows)


def list_policy_change_recommendations(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> tuple[PolicyChangeRecommendation, ...]:
    rows = conn.execute(
        f"SELECT {_RECOMMENDATION_COLUMNS} "
        "FROM policy_change_recommendations "
        "WHERE diagnostic_run_id = ? ORDER BY recommendation_order",
        (integer(diagnostic_run_id, "diagnostic_run_id", 1),),
    ).fetchall()
    recommendations = []
    for row in rows:
        values = list(row)
        values[15] = bool(values[15])
        recommendations.append(PolicyChangeRecommendation(*values))
    return tuple(recommendations)


def get_weekly_diagnostic_completion(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> WeeklyDiagnosticCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM weekly_diagnostic_completions "
        "WHERE diagnostic_run_id = ?",
        (integer(diagnostic_run_id, "diagnostic_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"weekly diagnostic run is incomplete: {diagnostic_run_id}"
        )
    return WeeklyDiagnosticCompletion(*row)


def _ats_rate(wins: int, losses: int) -> float | None:
    decisions = wins + losses
    if decisions == 0:
        return None
    return round(100.0 * wins / decisions, 2)


def _build_segments(
    conn: sqlite3.Connection,
    *,
    diagnostic_run_id: int,
    audit_run_id: int,
) -> tuple[WeeklyDiagnosticSegment, ...]:
    segments = []
    for dimension_code, category_code in SEGMENT_CATEGORIES:
        row = conn.execute(
            "SELECT COUNT(*), "
            "SUM(ats_result = 'win'), SUM(ats_result = 'loss'), "
            "SUM(ats_result = 'push') "
            "FROM weekly_diagnostic_source_results "
            "WHERE audit_run_id = ? AND dimension_code = ? "
            "AND category_code = ?",
            (audit_run_id, dimension_code, category_code),
        ).fetchone()
        sample_count = int(row[0])
        wins = int(row[1] or 0)
        losses = int(row[2] or 0)
        pushes = int(row[3] or 0)
        segments.append(
            WeeklyDiagnosticSegment(
                diagnostic_run_id,
                dimension_code,
                category_code,
                sample_count,
                wins,
                losses,
                pushes,
                _ats_rate(wins, losses),
            )
        )
    return tuple(segments)


def _evidence_status(
    primary: WeeklyDiagnosticSegment,
    minimum_sample: int,
    comparison: WeeklyDiagnosticSegment | None = None,
) -> str:
    if (
        primary.sample_count < minimum_sample
        or primary.ats_win_rate is None
        or (
            comparison is not None
            and (
                comparison.sample_count < minimum_sample
                or comparison.ats_win_rate is None
            )
        )
    ):
        return "insufficient"
    return "sufficient"


def _rate_delta(
    primary: WeeklyDiagnosticSegment,
    comparison: WeeklyDiagnosticSegment,
) -> float | None:
    if primary.ats_win_rate is None or comparison.ats_win_rate is None:
        return None
    return round(primary.ats_win_rate - comparison.ats_win_rate, 2)


def _descriptive_extreme(
    segments: tuple[WeeklyDiagnosticSegment, ...],
    *,
    strongest: bool,
    minimum_sample: int,
) -> WeeklyDiagnosticSegment:
    candidates = tuple(
        segment
        for segment in segments
        if segment.dimension_code != "model_output"
        and segment.ats_win_rate is not None
    )
    qualified = tuple(
        segment
        for segment in candidates
        if segment.sample_count >= minimum_sample
    )
    pool = qualified or candidates
    if not pool:
        return next(
            segment
            for segment in segments
            if (segment.dimension_code, segment.category_code)
            == ("card_tier", "top_five")
        )
    key = lambda segment: (
        segment.ats_win_rate,
        segment.sample_count,
        -SEGMENT_CATEGORIES.index(
            (segment.dimension_code, segment.category_code)
        ),
    )
    return max(pool, key=key) if strongest else min(pool, key=key)


def _build_lessons(
    *,
    diagnostic_run_id: int,
    segments: tuple[WeeklyDiagnosticSegment, ...],
    minimum_sample: int,
) -> tuple[WeeklyDiagnosticLesson, ...]:
    by_key = {
        (segment.dimension_code, segment.category_code): segment
        for segment in segments
    }
    strongest = _descriptive_extreme(
        segments,
        strongest=True,
        minimum_sample=minimum_sample,
    )
    weakest = _descriptive_extreme(
        segments,
        strongest=False,
        minimum_sample=minimum_sample,
    )
    raw = by_key[("model_output", "raw_model")]
    adjusted = by_key[("model_output", "final_adjusted")]
    clv_positive = by_key[("clv_sign", "positive")]
    clv_negative = by_key[("clv_sign", "negative")]
    return (
        WeeklyDiagnosticLesson(
            diagnostic_run_id,
            1,
            "strongest_segment",
            _evidence_status(strongest, minimum_sample),
            strongest.dimension_code,
            strongest.category_code,
            None,
            strongest.sample_count,
            strongest.ats_win_rate,
            None,
            None,
            "Descriptive only: the strongest sample-qualified segment was "
            f"{strongest.dimension_code}/{strongest.category_code} at "
            f"{strongest.ats_win_rate}% ATS over {strongest.sample_count} picks.",
        ),
        WeeklyDiagnosticLesson(
            diagnostic_run_id,
            2,
            "weakest_segment",
            _evidence_status(weakest, minimum_sample),
            weakest.dimension_code,
            weakest.category_code,
            None,
            weakest.sample_count,
            weakest.ats_win_rate,
            None,
            None,
            "Descriptive only: the weakest sample-qualified segment was "
            f"{weakest.dimension_code}/{weakest.category_code} at "
            f"{weakest.ats_win_rate}% ATS over {weakest.sample_count} picks.",
        ),
        WeeklyDiagnosticLesson(
            diagnostic_run_id,
            3,
            "raw_vs_adjusted",
            _evidence_status(adjusted, minimum_sample, raw),
            "model_output",
            "final_adjusted",
            "raw_model",
            adjusted.sample_count,
            adjusted.ats_win_rate,
            raw.ats_win_rate,
            _rate_delta(adjusted, raw),
            "Final adjusted selections differed from the frozen raw-model "
            f"sides by {_rate_delta(adjusted, raw)} percentage points ATS; "
            "this is descriptive and does not establish causation.",
        ),
        WeeklyDiagnosticLesson(
            diagnostic_run_id,
            4,
            "clv_signal",
            _evidence_status(clv_positive, minimum_sample, clv_negative),
            "clv_sign",
            "positive",
            "negative",
            clv_positive.sample_count,
            clv_positive.ats_win_rate,
            clv_negative.ats_win_rate,
            _rate_delta(clv_positive, clv_negative),
            "CLV-positive picks differed from CLV-negative picks by "
            f"{_rate_delta(clv_positive, clv_negative)} percentage points "
            "ATS; the weekly sample alone does not justify a rule change.",
        ),
    )


def _overall_ats_rate(
    conn: sqlite3.Connection, audit_run_id: int
) -> float | None:
    row = conn.execute(
        "SELECT SUM(ats_result = 'win'), SUM(ats_result = 'loss') "
        "FROM pick_audit_details WHERE audit_run_id = ?",
        (audit_run_id,),
    ).fetchone()
    return _ats_rate(int(row[0] or 0), int(row[1] or 0))


def _build_recommendations(
    conn: sqlite3.Connection,
    *,
    run: WeeklyDiagnosticRun,
    segments: tuple[WeeklyDiagnosticSegment, ...],
    policy: RecordedWeeklyDiagnosticsPolicy,
) -> tuple[PolicyChangeRecommendation, ...]:
    audit_run = get_card_postgame_audit_run(conn, run.audit_run_id)
    ranking_policy = get_card_ranking_policy(conn, audit_run.card_id)
    segment_by_key = {
        (segment.dimension_code, segment.category_code): segment
        for segment in segments
    }
    overall_rate = _overall_ats_rate(conn, run.audit_run_id)
    thresholds = {
        5: ranking_policy.confidence_5_max_uncertainty,
        4: ranking_policy.confidence_4_max_uncertainty,
        3: ranking_policy.confidence_3_max_uncertainty,
        2: ranking_policy.confidence_2_max_uncertainty,
    }
    lower_bounds = {
        5: -0.000000001,
        4: thresholds[5],
        3: thresholds[4],
        2: thresholds[3],
    }
    proposed_version = (
        f"{ranking_policy.confidence_policy_version}.candidate."
        f"{run.diagnostic_run_key}"
    )
    recommendations = []
    for order, (confidence_level, parameter_name) in enumerate(
        RECOMMENDATION_PARAMETERS,
        1,
    ):
        segment = segment_by_key[("confidence", str(confidence_level))]
        delta = (
            None
            if segment.ats_win_rate is None or overall_rate is None
            else round(segment.ats_win_rate - overall_rate, 2)
        )
        current_value = float(thresholds[confidence_level])
        candidate_value = round(
            current_value - policy.confidence_threshold_step_points,
            8,
        )
        proposed = None
        recommended_value = current_value
        owner_approval_required = False
        if (
            segment.sample_count < policy.minimum_recommendation_sample
            or segment.ats_win_rate is None
            or overall_rate is None
        ):
            status = "hold_insufficient_evidence"
            rationale = (
                "Hold: the completed weekly audit does not meet the "
                f"minimum sample of {policy.minimum_recommendation_sample}."
            )
        elif delta > -policy.minimum_ats_delta_percentage_points:
            status = "hold_no_change"
            rationale = (
                "Hold: this Confidence tier did not underperform the full "
                "card by the policy's minimum numeric delta."
            )
        elif candidate_value <= lower_bounds[confidence_level]:
            status = "hold_threshold_boundary"
            rationale = (
                "Hold: the configured tightening step would violate ordered "
                "Confidence thresholds."
            )
        else:
            status = "candidate_pending_owner_approval"
            proposed = proposed_version
            recommended_value = candidate_value
            owner_approval_required = True
            rationale = (
                f"Candidate only: tighten {parameter_name} by "
                f"{policy.confidence_threshold_step_points} uncertainty "
                "points. A new version, broader out-of-sample evidence, and "
                "explicit owner approval are required before use."
            )
        recommendations.append(
            PolicyChangeRecommendation(
                run.id,
                order,
                confidence_level,
                parameter_name,
                ranking_policy.id,
                ranking_policy.confidence_policy_version,
                ranking_policy.ranking_policy_version,
                proposed,
                current_value,
                recommended_value,
                segment.sample_count,
                segment.ats_win_rate,
                overall_rate,
                delta,
                status,
                owner_approval_required,
                rationale,
            )
        )
    return tuple(recommendations)


def _ledger_sha256(
    segments: tuple[WeeklyDiagnosticSegment, ...],
    lessons: tuple[WeeklyDiagnosticLesson, ...],
    recommendations: tuple[PolicyChangeRecommendation, ...],
) -> str:
    canonical = json.dumps(
        {
            "segments": [asdict(item) for item in segments],
            "lessons": [asdict(item) for item in lessons],
            "recommendations": [asdict(item) for item in recommendations],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_weekly_diagnostics(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> WeeklyDiagnosticsReport:
    run = get_weekly_diagnostic_run(conn, diagnostic_run_id)
    segments = list_weekly_diagnostic_segments(conn, run.id)
    lessons = list_weekly_diagnostic_lessons(conn, run.id)
    recommendations = list_policy_change_recommendations(conn, run.id)
    actual_segments = {
        (segment.dimension_code, segment.category_code) for segment in segments
    }
    actual_lessons = {lesson.lesson_code for lesson in lessons}
    actual_parameters = {
        recommendation.parameter_name for recommendation in recommendations
    }
    try:
        completion = get_weekly_diagnostic_completion(conn, run.id)
        recorded_hash = completion.ledger_sha256
    except BusinessEntityError:
        recorded_hash = None
    return WeeklyDiagnosticsReport(
        run.id,
        run.expected_segment_count,
        len(segments),
        tuple(sorted(set(SEGMENT_CATEGORIES) - actual_segments)),
        len(lessons),
        tuple(sorted(set(LESSON_CODES) - actual_lessons)),
        len(recommendations),
        tuple(
            sorted(
                {parameter for _, parameter in RECOMMENDATION_PARAMETERS}
                - actual_parameters
            )
        ),
        sum(
            recommendation.recommendation_status
            == "candidate_pending_owner_approval"
            for recommendation in recommendations
        ),
        _ledger_sha256(segments, lessons, recommendations),
        recorded_hash,
    )


def validate_weekly_diagnostics(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> WeeklyDiagnosticsReport:
    report = inspect_weekly_diagnostics(conn, diagnostic_run_id)
    if not report.complete:
        raise BusinessEntityError(
            "weekly diagnostics are incomplete or their immutable ledger "
            "does not match: "
            f"segments={report.segment_count}/{report.expected_segment_count}; "
            f"missing_segments={report.missing_segments}; "
            f"lessons={report.lesson_count}/{EXPECTED_LESSON_COUNT}; "
            f"missing_lessons={report.missing_lesson_codes}; "
            "recommendations="
            f"{report.recommendation_count}/{EXPECTED_RECOMMENDATION_COUNT}; "
            "missing_recommendations="
            f"{report.missing_recommendation_parameters}; "
            f"ledger_matches={report.recorded_ledger_sha256 == report.ledger_sha256}"
        )
    return report


def _load_result(
    conn: sqlite3.Connection, diagnostic_run_id: int
) -> WeeklyDiagnosticsResult:
    run = get_weekly_diagnostic_run(conn, diagnostic_run_id)
    segments = list_weekly_diagnostic_segments(conn, run.id)
    lessons = list_weekly_diagnostic_lessons(conn, run.id)
    recommendations = list_policy_change_recommendations(conn, run.id)
    completion = get_weekly_diagnostic_completion(conn, run.id)
    report = validate_weekly_diagnostics(conn, run.id)
    return WeeklyDiagnosticsResult(
        run,
        segments,
        lessons,
        recommendations,
        completion,
        report,
    )


def generate_weekly_diagnostics(
    conn: sqlite3.Connection,
    *,
    diagnostic_run_key: str,
    audit_run_id: int,
    diagnostic_policy: WeeklyDiagnosticsPolicy,
    source: str,
    provenance: str,
    generated_at: datetime | None = None,
) -> WeeklyDiagnosticsResult:
    """Generate all required cuts and recommendations without changing rules."""
    diagnostic_run_key = required_text(
        diagnostic_run_key,
        "diagnostic_run_key",
    )
    audit_run_id = integer(audit_run_id, "audit_run_id", 1)
    diagnostic_policy = _validated_policy(diagnostic_policy)
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    validate_postgame_audit_run(conn, audit_run_id)

    existing_row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM weekly_diagnostic_runs "
        "WHERE diagnostic_run_key = ?",
        (diagnostic_run_key,),
    ).fetchone()
    if existing_row is not None:
        existing = WeeklyDiagnosticRun(*existing_row)
        requested_time = (
            existing.generated_at
            if generated_at is None
            else utc_timestamp(generated_at, "generated_at")
        )
        recorded_policy = get_weekly_diagnostics_policy(
            conn,
            existing.diagnostic_policy_id,
        )
        if (
            existing.audit_run_id != audit_run_id
            or existing.generated_at != requested_time
            or existing.source != source
            or existing.provenance != provenance
            or recorded_policy.policy_version
            != diagnostic_policy.policy_version
        ):
            raise BusinessEntityConflictError(
                "weekly diagnostic run key has different immutable values"
            )
        replay_policy = register_weekly_diagnostics_policy(
            conn,
            diagnostic_policy,
        )
        if replay_policy.id != recorded_policy.id:
            raise BusinessEntityConflictError(
                "weekly diagnostic replay has a different immutable policy"
            )
        return _load_result(conn, existing.id)

    generated_at_value = utc_timestamp(generated_at, "generated_at")
    try:
        with atomic(conn):
            policy = register_weekly_diagnostics_policy(
                conn,
                diagnostic_policy,
            )
            if not timestamp_on_or_before(
                conn,
                policy.effective_at,
                generated_at_value,
            ):
                raise BusinessEntityError(
                    "weekly diagnostic policy is not yet effective"
                )
            latest = conn.execute(
                "SELECT id, sequence FROM weekly_diagnostic_runs "
                "WHERE audit_run_id = ? ORDER BY sequence DESC LIMIT 1",
                (audit_run_id,),
            ).fetchone()
            supersedes_run_id = latest[0] if latest is not None else None
            sequence = latest[1] + 1 if latest is not None else 1
            cursor = conn.execute(
                "INSERT INTO weekly_diagnostic_runs "
                "(diagnostic_run_key, audit_run_id, diagnostic_policy_id, "
                "sequence, supersedes_run_id, expected_segment_count, "
                "expected_lesson_count, expected_recommendation_count, "
                "generated_at, source, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    diagnostic_run_key,
                    audit_run_id,
                    policy.id,
                    sequence,
                    supersedes_run_id,
                    EXPECTED_SEGMENT_COUNT,
                    EXPECTED_LESSON_COUNT,
                    EXPECTED_RECOMMENDATION_COUNT,
                    generated_at_value,
                    source,
                    provenance,
                ),
            )
            run = get_weekly_diagnostic_run(conn, cursor.lastrowid)
            segments = _build_segments(
                conn,
                diagnostic_run_id=run.id,
                audit_run_id=run.audit_run_id,
            )
            for segment in segments:
                conn.execute(
                    "INSERT INTO weekly_diagnostic_segments "
                    f"({_SEGMENT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        segment.diagnostic_run_id,
                        segment.dimension_code,
                        segment.category_code,
                        segment.sample_count,
                        segment.win_count,
                        segment.loss_count,
                        segment.push_count,
                        segment.ats_win_rate,
                    ),
                )
            lessons = _build_lessons(
                diagnostic_run_id=run.id,
                segments=segments,
                minimum_sample=policy.minimum_recommendation_sample,
            )
            for lesson in lessons:
                conn.execute(
                    "INSERT INTO weekly_diagnostic_lessons "
                    f"({_LESSON_COLUMNS}) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        lesson.diagnostic_run_id,
                        lesson.lesson_order,
                        lesson.lesson_code,
                        lesson.evidence_status,
                        lesson.dimension_code,
                        lesson.category_code,
                        lesson.comparison_category_code,
                        lesson.sample_count,
                        lesson.primary_ats_win_rate,
                        lesson.comparison_ats_win_rate,
                        lesson.delta_percentage_points,
                        lesson.narrative,
                    ),
                )
            recommendations = _build_recommendations(
                conn,
                run=run,
                segments=segments,
                policy=policy,
            )
            for recommendation in recommendations:
                conn.execute(
                    "INSERT INTO policy_change_recommendations "
                    f"({_RECOMMENDATION_COLUMNS}) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        recommendation.diagnostic_run_id,
                        recommendation.recommendation_order,
                        recommendation.confidence_level,
                        recommendation.parameter_name,
                        recommendation.source_ranking_policy_id,
                        recommendation.source_confidence_policy_version,
                        recommendation.source_ranking_policy_version,
                        recommendation.proposed_confidence_policy_version,
                        recommendation.current_value,
                        recommendation.recommended_value,
                        recommendation.sample_count,
                        recommendation.segment_ats_win_rate,
                        recommendation.overall_ats_win_rate,
                        recommendation.observed_delta_percentage_points,
                        recommendation.recommendation_status,
                        int(recommendation.owner_approval_required),
                        recommendation.rationale,
                    ),
                )
            persisted_segments = list_weekly_diagnostic_segments(conn, run.id)
            persisted_lessons = list_weekly_diagnostic_lessons(conn, run.id)
            persisted_recommendations = list_policy_change_recommendations(
                conn,
                run.id,
            )
            ledger_hash = _ledger_sha256(
                persisted_segments,
                persisted_lessons,
                persisted_recommendations,
            )
            candidate_count = sum(
                recommendation.recommendation_status
                == "candidate_pending_owner_approval"
                for recommendation in recommendations
            )
            conn.execute(
                "INSERT INTO weekly_diagnostic_completions "
                "(diagnostic_run_id, segment_count, lesson_count, "
                "recommendation_count, candidate_recommendation_count, "
                "ledger_sha256, completed_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    len(segments),
                    len(lessons),
                    len(recommendations),
                    candidate_count,
                    ledger_hash,
                    run.generated_at,
                    run.provenance,
                ),
            )
            return _load_result(conn, run.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("weekly diagnostics", exc) from exc
