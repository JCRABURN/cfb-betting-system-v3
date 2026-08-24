"""Read-only evidence report for one controlled live-week shadow rehearsal."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from business_entities.common import BusinessEntityError, integer, required_text
from business_entities.complete_audits import validate_postgame_audit_run
from business_entities.live_sportsbook import (
    DRAFTKINGS_BOOKMAKER,
    build_draftkings_betting_board,
    sportsbook_evaluation_matches_sources,
)
from business_entities.reproducibility import reproduce_card
from business_entities.sportsbook_audits import (
    get_sportsbook_postgame_audit_completion,
    validate_sportsbook_postgame_audit,
)
from business_entities.weekly_controller import inspect_official_card
from business_entities.weekly_diagnostics import (
    list_weekly_diagnostic_lessons,
    validate_weekly_diagnostics,
)


SHADOW_REHEARSAL_REPORT_VERSION = "controlled-live-week-shadow-v2"


@dataclass(frozen=True)
class ShadowCardEvidence:
    publication_id: int
    card_version: int
    locked_line_snapshot_sha256: str
    pick_count: int
    confidence_coverage_count: int
    top_five_count: int
    fallback_pick_count: int
    source_freshness_count: int
    explicit_missing_source_count: int
    valid: bool
    reproduced_exactly: bool


@dataclass(frozen=True)
class ControlledShadowRehearsalReport:
    report_version: str
    season: int
    week: int
    contest_key: str
    contest_id: int
    expected_lined_game_count: int
    locked_line_count: int
    locked_line_snapshot_sha256: str
    official_publication_count: int
    revision_count: int
    card_versions: tuple[ShadowCardEvidence, ...]
    provider_ingestion_run_count: int
    provider_noncomplete_run_count: int
    provider_rejection_count: int
    provider_failures_explicit_count: int
    missing_evidence: tuple[str, ...]
    sportsbook_evaluation_count: int
    sportsbook_game_coverage_count: int
    sportsbook_bet_count: int
    sportsbook_no_bet_count: int
    sportsbook_supersession_count: int
    reproducible_sportsbook_evaluation_count: int
    draftkings_provider_capture_attempted: bool
    draftkings_offers_received_count: int
    draftkings_eligible_games_with_offers_count: int
    draftkings_eligible_offers_evaluated_count: int
    draftkings_bet_count: int
    draftkings_no_bet_count: int
    draftkings_unavailable_count: int
    draftkings_stale_count: int
    draftkings_supersession_count: int
    draftkings_recommendation_reproduction_passed: bool
    draftkings_closing_line_coverage: str
    draftkings_clv_coverage: str
    draftkings_grading_coverage: str
    contest_audit_run_id: int
    contest_audit_count: int
    sportsbook_audit_run_id: int
    sportsbook_audit_count: int
    sportsbook_clv_graded_count: int
    sportsbook_missing_clv_count: int
    sportsbook_realized_profit_units: float
    sportsbook_roi_percent: float | None
    diagnostic_run_id: int
    diagnostics_complete: bool
    lesson_count: int
    lessons: tuple[str, ...]
    contextual_adjustment_count: int
    contextual_adjustments_with_evidence_count: int
    wagers_placed: int
    report_sha256: str

    @property
    def successful(self) -> bool:
        versions = tuple(item.card_version for item in self.card_versions)
        return (
            self.locked_line_count == self.expected_lined_game_count
            and self.official_publication_count == 5
            and self.revision_count == 4
            and versions == (1, 2, 3, 4, 5)
            and all(
                item.valid
                and item.reproduced_exactly
                and item.locked_line_snapshot_sha256
                == self.locked_line_snapshot_sha256
                and item.pick_count == self.expected_lined_game_count
                and item.confidence_coverage_count == self.expected_lined_game_count
                and item.top_five_count == min(5, self.expected_lined_game_count)
                and item.source_freshness_count == 5
                for item in self.card_versions
            )
            and self.provider_ingestion_run_count > 0
            and self.provider_noncomplete_run_count
            == self.provider_failures_explicit_count
            and self.sportsbook_evaluation_count
            == self.reproducible_sportsbook_evaluation_count
            and self.sportsbook_evaluation_count == self.sportsbook_audit_count
            and self.sportsbook_missing_clv_count == 0
            and self.sportsbook_clv_graded_count == self.sportsbook_audit_count
            and self.draftkings_provider_capture_attempted
            and self.draftkings_eligible_games_with_offers_count
            + self.draftkings_unavailable_count
            >= self.expected_lined_game_count
            and self.draftkings_offers_received_count
            == self.draftkings_eligible_offers_evaluated_count
            and self.draftkings_recommendation_reproduction_passed
            and self.draftkings_closing_line_coverage
            == f"{self.draftkings_eligible_games_with_offers_count}/"
            f"{self.draftkings_eligible_games_with_offers_count}"
            and self.draftkings_clv_coverage
            == f"{self.draftkings_eligible_offers_evaluated_count}/"
            f"{self.draftkings_eligible_offers_evaluated_count}"
            and self.draftkings_grading_coverage
            == f"{self.draftkings_eligible_offers_evaluated_count}/"
            f"{self.draftkings_eligible_offers_evaluated_count}"
            and self.contest_audit_count == self.expected_lined_game_count
            and self.diagnostics_complete
            and self.lesson_count == 4
            and self.contextual_adjustment_count
            == self.contextual_adjustments_with_evidence_count
            and self.wagers_placed == 0
        )


def _canonical_sha256(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_controlled_shadow_rehearsal(
    conn: sqlite3.Connection,
    *,
    contest_key: str,
    season: int,
    week: int,
    expected_lined_game_count: int,
    sportsbook_policy_id: int,
) -> ControlledShadowRehearsalReport:
    """Validate and summarize the entire durable shadow-week evidence chain."""
    contest_key = required_text(contest_key, "contest_key")
    season = integer(season, "season", 1869)
    week = integer(week, "week", 0)
    expected_lined_game_count = integer(
        expected_lined_game_count, "expected_lined_game_count", 1
    )
    sportsbook_policy_id = integer(sportsbook_policy_id, "sportsbook_policy_id", 1)
    contest = conn.execute(
        "SELECT id FROM contests WHERE contest_key = ? AND season = ? AND week = ?",
        (contest_key, season, week),
    ).fetchone()
    if contest is None:
        raise BusinessEntityError("shadow rehearsal contest does not exist")
    contest_id = int(contest[0])
    batch = conn.execute(
        "SELECT locked_line_count, locked_line_snapshot_sha256 "
        "FROM contest_line_lock_batches WHERE contest_id = ?",
        (contest_id,),
    ).fetchone()
    if batch is None:
        raise BusinessEntityError("shadow rehearsal has no immutable line-lock batch")
    locked_count, locked_snapshot = int(batch[0]), str(batch[1])
    publication_ids = tuple(
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM official_card_publications WHERE contest_id = ? "
            "ORDER BY card_version",
            (contest_id,),
        )
    )
    cards: list[ShadowCardEvidence] = []
    ingestion_run_ids: set[int] = set()
    missing_evidence: list[str] = []
    for publication_id in publication_ids:
        inspection = inspect_official_card(conn, publication_id=publication_id)
        model_run_key = conn.execute(
            "SELECT run.run_key FROM model_runs AS run "
            "JOIN contest_cards AS card ON card.model_run_id = run.id "
            "WHERE card.id = ?",
            (inspection.card.id,),
        ).fetchone()
        reproduced = False
        if model_run_key is not None:
            try:
                replay = reproduce_card(
                    conn,
                    card_key=inspection.card.card_key,
                    model_run_key=str(model_run_key[0]),
                )
                reproduced = (
                    replay.card == inspection.card and replay.picks == inspection.picks
                )
            except (BusinessEntityError, sqlite3.DatabaseError, ValueError):
                reproduced = False
        explicit_missing = 0
        for freshness in inspection.freshness:
            if freshness.ingestion_run_id is not None:
                ingestion_run_ids.add(int(freshness.ingestion_run_id))
            if freshness.state != "current":
                explicit_missing += 1
                missing_evidence.append(
                    f"card-v{inspection.publication.card_version}:"
                    f"{freshness.data_type}:{freshness.state}:"
                    f"{freshness.fallback_code or 'missing_fallback_code'}"
                )
        cards.append(
            ShadowCardEvidence(
                publication_id=publication_id,
                card_version=inspection.publication.card_version,
                locked_line_snapshot_sha256=(
                    inspection.publication.locked_line_snapshot_sha256
                ),
                pick_count=len(inspection.picks),
                confidence_coverage_count=sum(
                    pick.confidence is not None and 1 <= pick.confidence <= 5
                    for pick in inspection.picks
                ),
                top_five_count=sum(pick.is_top_five for pick in inspection.picks),
                fallback_pick_count=sum(
                    pick.fallback_code is not None for pick in inspection.picks
                ),
                source_freshness_count=len(inspection.freshness),
                explicit_missing_source_count=explicit_missing,
                valid=inspection.valid,
                reproduced_exactly=reproduced,
            )
        )

    ingestion_run_ids.update(
        int(row[0])
        for row in conn.execute(
            "SELECT DISTINCT snapshot.ingestion_run_id "
            "FROM provider_market_snapshots AS snapshot "
            "WHERE snapshot.season = ? AND snapshot.week = ?",
            (season, week),
        )
    )
    ingestion_run_ids.update(
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM provider_ingestion_runs "
            "WHERE json_extract(request_parameters, '$.season') = ? "
            "AND json_extract(request_parameters, '$.week') = ?",
            (season, week),
        )
    )

    provider_rows = ()
    if ingestion_run_ids:
        placeholders = ",".join("?" for _ in ingestion_run_ids)
        provider_rows = tuple(
            conn.execute(
                "SELECT id, status, failure_reason, rows_rejected "
                f"FROM provider_ingestion_runs WHERE id IN ({placeholders})",
                tuple(sorted(ingestion_run_ids)),
            )
        )
    noncomplete = tuple(row for row in provider_rows if row[1] != "completed")
    explicit_failures = sum(
        bool(row[1]) and (row[1] in ("empty", "partial", "rejected") or bool(row[2]))
        for row in noncomplete
    )
    rejection_count = sum(int(row[3]) for row in provider_rows)
    missing_evidence.extend(
        f"provider-run:{int(row[0])}:{row[1]}:rejections:{int(row[3])}"
        for row in noncomplete
    )

    evaluation_rows = tuple(
        conn.execute(
            "SELECT evaluation.id, evaluation.decision, "
            "evaluation.supersedes_evaluation_id, offer.bookmaker "
            "FROM sportsbook_recommendation_evaluations AS evaluation "
            "JOIN sportsbook_market_offers AS offer "
            "ON offer.id = evaluation.market_offer_id "
            "JOIN games AS game ON game.game_id = offer.game_id "
            "WHERE game.season = ? AND game.week = ? AND evaluation.policy_id = ? "
            "ORDER BY evaluation.id",
            (season, week, sportsbook_policy_id),
        )
    )
    reproducible_evaluations = sum(
        sportsbook_evaluation_matches_sources(conn, int(row[0]))
        for row in evaluation_rows
    )
    draftkings_offer_rows = tuple(
        conn.execute(
            "SELECT offer.id, offer.game_id, evaluation.id "
            "FROM sportsbook_market_offers AS offer "
            "JOIN contest_locked_lines AS locked ON locked.game_id = offer.game_id "
            "LEFT JOIN sportsbook_recommendation_evaluations AS evaluation "
            "ON evaluation.market_offer_id = offer.id AND evaluation.policy_id = ? "
            "WHERE locked.contest_id = ? AND lower(trim(offer.bookmaker)) = ? "
            "AND offer.line_type IN ('opening', 'current') ORDER BY offer.id",
            (sportsbook_policy_id, contest_id, DRAFTKINGS_BOOKMAKER),
        )
    )
    draftkings_evaluation_rows = tuple(
        row
        for row in evaluation_rows
        if str(row[3]).strip().casefold() == DRAFTKINGS_BOOKMAKER
    )
    draftkings_reproducible = sum(
        sportsbook_evaluation_matches_sources(conn, int(row[0]))
        for row in draftkings_evaluation_rows
    )
    draftkings_board = build_draftkings_betting_board(
        conn,
        contest_id=contest_id,
        policy_id=sportsbook_policy_id,
        season=season,
        week=week,
        provider_ingestion_run_ids=tuple(sorted(ingestion_run_ids)),
    )
    draftkings_capture_attempted = any(
        row.provider_capture_attempted for row in draftkings_board
    )
    draftkings_unavailable_count = sum(
        row.availability_state != "AVAILABLE" for row in draftkings_board
    )
    draftkings_game_count = len({int(row[1]) for row in draftkings_offer_rows})
    missing_evidence.extend(
        f"draftkings-game:{row.game_id}:{row.reason_code}:"
        f"{row.observation_timestamp}"
        for row in draftkings_board
        if row.availability_state != "AVAILABLE"
    )

    final_card = conn.execute(
        "SELECT card_id FROM official_card_publications WHERE contest_id = ? "
        "ORDER BY card_version DESC LIMIT 1",
        (contest_id,),
    ).fetchone()
    if final_card is None:
        raise BusinessEntityError("shadow rehearsal has no final card")
    contest_audit = conn.execute(
        "SELECT run.id FROM card_postgame_audit_runs AS run "
        "JOIN card_postgame_audit_completions AS completion "
        "ON completion.audit_run_id = run.id WHERE run.card_id = ? "
        "ORDER BY run.sequence DESC LIMIT 1",
        (int(final_card[0]),),
    ).fetchone()
    if contest_audit is None:
        raise BusinessEntityError("shadow rehearsal contest audit is incomplete")
    contest_audit_id = int(contest_audit[0])
    contest_report = validate_postgame_audit_run(conn, contest_audit_id)

    sportsbook_audit = conn.execute(
        "SELECT run.id FROM sportsbook_postgame_audit_runs AS run "
        "JOIN sportsbook_postgame_audit_completions AS completion "
        "ON completion.audit_run_id = run.id "
        "WHERE run.season = ? AND run.week = ? AND run.policy_id = ? "
        "ORDER BY run.sequence DESC LIMIT 1",
        (season, week, sportsbook_policy_id),
    ).fetchone()
    if sportsbook_audit is None:
        raise BusinessEntityError("shadow rehearsal sportsbook audit is incomplete")
    sportsbook_audit_id = int(sportsbook_audit[0])
    sportsbook_report = validate_sportsbook_postgame_audit(conn, sportsbook_audit_id)
    sportsbook_completion = get_sportsbook_postgame_audit_completion(
        conn, sportsbook_audit_id
    )
    if sportsbook_report.missing_clv_count:
        missing_evidence.extend(
            f"sportsbook-evaluation:{evaluation_id}:missing-closing-line"
            for evaluation_id in conn.execute(
                "SELECT evaluation_id FROM sportsbook_postgame_audit_details "
                "WHERE audit_run_id = ? AND clv_evidence_status = 'missing' "
                "ORDER BY evaluation_id",
                (sportsbook_audit_id,),
            )
            for evaluation_id in (int(evaluation_id[0]),)
        )
    draftkings_audit_rows = tuple(
        conn.execute(
            "SELECT detail.evaluation_id, detail.clv_evidence_status "
            "FROM sportsbook_postgame_audit_details AS detail "
            "WHERE detail.audit_run_id = ? AND lower(trim(detail.bookmaker)) = ? "
            "ORDER BY detail.evaluation_id",
            (sportsbook_audit_id, DRAFTKINGS_BOOKMAKER),
        )
    )
    draftkings_clv_count = sum(row[1] == "available" for row in draftkings_audit_rows)
    draftkings_closing_game_count = int(
        conn.execute(
            "SELECT COUNT(DISTINCT designation.game_id) "
            "FROM sportsbook_closing_designations AS designation "
            "JOIN contest_locked_lines AS locked ON locked.game_id = designation.game_id "
            "WHERE locked.contest_id = ? AND lower(trim(designation.bookmaker)) = ?",
            (contest_id, DRAFTKINGS_BOOKMAKER),
        ).fetchone()[0]
    )

    diagnostic = conn.execute(
        "SELECT run.id FROM weekly_diagnostic_runs AS run "
        "JOIN weekly_diagnostic_completions AS completion "
        "ON completion.diagnostic_run_id = run.id "
        "WHERE run.audit_run_id = ? ORDER BY run.sequence DESC LIMIT 1",
        (contest_audit_id,),
    ).fetchone()
    if diagnostic is None:
        raise BusinessEntityError("shadow rehearsal diagnostics are incomplete")
    diagnostic_id = int(diagnostic[0])
    diagnostic_report = validate_weekly_diagnostics(conn, diagnostic_id)
    lessons = list_weekly_diagnostic_lessons(conn, diagnostic_id)

    adjustments = conn.execute(
        "SELECT COUNT(*), sum(CASE WHEN length(trim(adjustment.evidence)) > 0 "
        "AND length(trim(adjustment.source)) > 0 "
        "AND length(trim(adjustment.provenance)) > 0 "
        "THEN 1 ELSE 0 END) FROM manual_adjustments AS adjustment "
        "JOIN model_predictions AS prediction "
        "ON prediction.id = adjustment.model_prediction_id "
        "JOIN games AS game ON game.game_id = prediction.game_id "
        "WHERE game.season = ? AND game.week = ?",
        (season, week),
    ).fetchone()
    adjustment_count = int(adjustments[0]) if adjustments else 0
    evidenced_adjustments = int(adjustments[1] or 0) if adjustments else 0

    payload: dict[str, object] = {
        "report_version": SHADOW_REHEARSAL_REPORT_VERSION,
        "season": season,
        "week": week,
        "contest_key": contest_key,
        "contest_id": contest_id,
        "expected_lined_game_count": expected_lined_game_count,
        "locked_line_count": locked_count,
        "locked_line_snapshot_sha256": locked_snapshot,
        "official_publication_count": len(cards),
        "revision_count": max(0, len(cards) - 1),
        "card_versions": tuple(cards),
        "provider_ingestion_run_count": len(provider_rows),
        "provider_noncomplete_run_count": len(noncomplete),
        "provider_rejection_count": rejection_count,
        "provider_failures_explicit_count": explicit_failures,
        "missing_evidence": tuple(sorted(set(missing_evidence))),
        "sportsbook_evaluation_count": len(evaluation_rows),
        "sportsbook_game_coverage_count": conn.execute(
            "SELECT COUNT(DISTINCT offer.game_id) "
            "FROM sportsbook_recommendation_evaluations AS evaluation "
            "JOIN sportsbook_market_offers AS offer "
            "ON offer.id = evaluation.market_offer_id "
            "JOIN games AS game ON game.game_id = offer.game_id "
            "WHERE game.season = ? AND game.week = ? AND evaluation.policy_id = ?",
            (season, week, sportsbook_policy_id),
        ).fetchone()[0],
        "sportsbook_bet_count": sum(row[1] == "bet" for row in evaluation_rows),
        "sportsbook_no_bet_count": sum(row[1] == "no_bet" for row in evaluation_rows),
        "sportsbook_supersession_count": sum(row[2] is not None for row in evaluation_rows),
        "reproducible_sportsbook_evaluation_count": reproducible_evaluations,
        "draftkings_provider_capture_attempted": draftkings_capture_attempted,
        "draftkings_offers_received_count": len(
            {int(row[0]) for row in draftkings_offer_rows}
        ),
        "draftkings_eligible_games_with_offers_count": draftkings_game_count,
        "draftkings_eligible_offers_evaluated_count": len(
            {int(row[0]) for row in draftkings_offer_rows if row[2] is not None}
        ),
        "draftkings_bet_count": sum(
            row[1] == "bet" for row in draftkings_evaluation_rows
        ),
        "draftkings_no_bet_count": sum(
            row[1] == "no_bet" for row in draftkings_evaluation_rows
        ),
        "draftkings_unavailable_count": draftkings_unavailable_count,
        "draftkings_stale_count": sum(
            row.freshness == "STALE" for row in draftkings_board
        ),
        "draftkings_supersession_count": sum(
            row[2] is not None for row in draftkings_evaluation_rows
        ),
        "draftkings_recommendation_reproduction_passed": (
            draftkings_reproducible == len(draftkings_evaluation_rows)
            and len({int(row[0]) for row in draftkings_offer_rows})
            == len({int(row[0]) for row in draftkings_offer_rows if row[2] is not None})
        ),
        "draftkings_closing_line_coverage": (
            f"{draftkings_closing_game_count}/{draftkings_game_count}"
        ),
        "draftkings_clv_coverage": (
            f"{draftkings_clv_count}/"
            f"{len({int(row[0]) for row in draftkings_offer_rows if row[2] is not None})}"
        ),
        "draftkings_grading_coverage": (
            f"{len(draftkings_audit_rows)}/"
            f"{len({int(row[0]) for row in draftkings_offer_rows if row[2] is not None})}"
        ),
        "contest_audit_run_id": contest_audit_id,
        "contest_audit_count": contest_report.audit_count,
        "sportsbook_audit_run_id": sportsbook_audit_id,
        "sportsbook_audit_count": sportsbook_report.audit_count,
        "sportsbook_clv_graded_count": sportsbook_report.clv_graded_count,
        "sportsbook_missing_clv_count": sportsbook_report.missing_clv_count,
        "sportsbook_realized_profit_units": (
            sportsbook_completion.realized_profit_units
        ),
        "sportsbook_roi_percent": sportsbook_completion.roi_percent,
        "diagnostic_run_id": diagnostic_id,
        "diagnostics_complete": diagnostic_report.complete,
        "lesson_count": len(lessons),
        "lessons": tuple(lesson.narrative for lesson in lessons),
        "contextual_adjustment_count": adjustment_count,
        "contextual_adjustments_with_evidence_count": evidenced_adjustments,
        "wagers_placed": 0,
    }
    encoded = {
        key: [asdict(item) for item in value]
        if key == "card_versions"
        else value
        for key, value in payload.items()
    }
    return ControlledShadowRehearsalReport(
        **payload,
        report_sha256=_canonical_sha256(encoded),
    )
