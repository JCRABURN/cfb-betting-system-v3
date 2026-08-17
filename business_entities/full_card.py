"""Fail-closed generation of one side for every locked contest game.

This engine creates complete draft cards only. It assigns Confidence 1-5 from
explicit model uncertainty and ranks a Top 5 without using raw model edge.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime

from contest_lines import EffectiveContestLine, list_effective_locked_lines

from business_entities.cards import (
    ContestCard,
    ContestPick,
    add_contest_pick,
    create_contest_card,
    get_contest_card,
    list_contest_picks,
)
from business_entities.common import (
    BusinessEntityError,
    atomic,
    integer,
    required_text,
    timestamp_on_or_before,
    utc_timestamp,
)
from business_entities.modeling import (
    ModelPrediction,
    get_model_prediction,
    get_model_run,
)
from business_entities.ranking import (
    TOP_FIVE_COUNT,
    ConfidenceRankingPolicy,
    assign_card_ranking_policy,
    confidence_for_uncertainty,
    get_card_ranking_policy,
    recorded_policy_matches,
    register_confidence_ranking_policy,
    validate_confidence_ranking_policy,
)
from business_entities.reproducibility import (
    FullCardPolicy,
    assert_card_run_manifest,
    card_run_manifest_matches,
    record_card_run_manifest,
    register_contest_selection_policy,
    validate_full_card_policy,
)


MARKET_CURRENT_PREFIX = "market_current_line:"
MARKET_OPENING_PREFIX = "market_opening_line:"
LOCKED_LINE_UNDERDOG = "locked_line_underdog"
LOCKED_LINE_PICKEM_HOME = "locked_line_pickem_tiebreak_home"
LOCKED_LINE_PICKEM_AWAY = "locked_line_pickem_tiebreak_away"
_MARKET_FALLBACK = re.compile(r"^(market_current_line|market_opening_line):(\d+)$")


class FullCardError(BusinessEntityError):
    """Base error for full-card generation and validation failures."""


class IncompleteCardError(FullCardError):
    """Raised when a card fails one or more side-completeness gates."""

    def __init__(self, report: "CardCompletenessReport") -> None:
        self.report = report
        super().__init__(
            "contest card is incomplete: "
            f"missing={report.missing_locked_line_ids}, "
            f"unexpected={report.unexpected_locked_line_ids}, "
            f"unresolved={report.unresolved_locked_line_ids}, "
            f"invalid_picks={report.invalid_pick_ids}, "
            f"invalid_confidence={report.invalid_confidence_pick_ids}, "
            f"invalid_top_five={report.invalid_top_five_pick_ids}"
        )


@dataclass(frozen=True)
class CardCompletenessReport:
    card_id: int
    contest_id: int
    expected_locked_line_count: int
    normalized_matchup_count: int
    pick_count: int
    model_pick_count: int
    fallback_pick_count: int
    duplicate_pick_count: int
    missing_locked_line_ids: tuple[int, ...]
    unexpected_locked_line_ids: tuple[int, ...]
    unresolved_locked_line_ids: tuple[int, ...]
    mismatched_matchup_line_ids: tuple[int, ...]
    invalid_kickoff_line_ids: tuple[int, ...]
    invalid_pick_ids: tuple[int, ...]
    missing_provenance_pick_ids: tuple[int, ...]
    invalid_fallback_pick_ids: tuple[int, ...]
    confidence_coverage_count: int
    top_five_count: int
    ranked_pick_count: int
    invalid_confidence_pick_ids: tuple[int, ...]
    invalid_top_five_pick_ids: tuple[int, ...]
    model_metadata_complete: bool
    locked_line_snapshot_matches: bool
    policy_replay_matches: bool
    confidence_ranking_policy_matches: bool
    reproducibility_manifest_matches: bool

    @property
    def side_complete(self) -> bool:
        return not any(
            (
                self.expected_locked_line_count == 0,
                self.duplicate_pick_count,
                self.missing_locked_line_ids,
                self.unexpected_locked_line_ids,
                self.unresolved_locked_line_ids,
                self.mismatched_matchup_line_ids,
                self.invalid_kickoff_line_ids,
                self.invalid_pick_ids,
                self.missing_provenance_pick_ids,
                self.invalid_fallback_pick_ids,
                not self.model_metadata_complete,
                not self.locked_line_snapshot_matches,
                not self.policy_replay_matches,
            )
        )

    @property
    def official_ready(self) -> bool:
        return self.contest_complete

    @property
    def contest_complete(self) -> bool:
        expected_top_five = min(TOP_FIVE_COUNT, self.expected_locked_line_count)
        return (
            self.side_complete
            and self.confidence_coverage_count == self.expected_locked_line_count
            and self.top_five_count == expected_top_five
            and self.ranked_pick_count == expected_top_five
            and not self.invalid_confidence_pick_ids
            and not self.invalid_top_five_pick_ids
            and self.confidence_ranking_policy_matches
            and self.reproducibility_manifest_matches
        )


@dataclass(frozen=True)
class FullCardResult:
    card: ContestCard
    picks: tuple[ContestPick, ...]
    report: CardCompletenessReport


@dataclass(frozen=True)
class _MarketLine:
    id: int
    home_spread: float
    book: str
    line_type: str
    source: str
    fetched_at: str


@dataclass(frozen=True)
class _Selection:
    line: EffectiveContestLine
    selected_side: str
    model_prediction_id: int | None
    fallback_code: str | None
    provenance: str
    uncertainty_points: float | None = None
    confidence: int | None = None
    rank: int | None = None
    is_top_five: bool = False


def _validated_policy(policy: FullCardPolicy) -> FullCardPolicy:
    try:
        return validate_full_card_policy(policy)
    except BusinessEntityError as exc:
        raise FullCardError(str(exc)) from exc


def _snapshot_payload(line: EffectiveContestLine) -> dict[str, object]:
    return {
        "locked_line_id": line.locked_line_id,
        "contest_id": line.contest_id,
        "game_id": line.game_id,
        "season": line.season,
        "week": line.week,
        "raw_home_team": line.raw_home_team,
        "raw_away_team": line.raw_away_team,
        "normalized_home_team": line.normalized_home_team,
        "normalized_away_team": line.normalized_away_team,
        "home_spread": line.home_spread,
        "total": line.total,
        "original_locked_at": line.original_locked_at,
        "effective_at": line.effective_at,
        "correction_id": line.correction_id,
        "correction_sequence": line.correction_sequence,
        "source": line.source,
        "source_line_id": line.source_line_id,
        "provenance": line.provenance,
        "payload_sha256": line.payload_sha256,
    }


def locked_line_snapshot_sha256(lines: tuple[EffectiveContestLine, ...]) -> str:
    """Hash the complete effective line set in stable locked-line order."""
    payload = [
        _snapshot_payload(line)
        for line in sorted(lines, key=lambda item: item.locked_line_id)
    ]
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _game_row(
    conn: sqlite3.Connection, line: EffectiveContestLine
) -> tuple[int, int, str, str, str | None] | None:
    if line.game_id is None:
        return None
    return conn.execute(
        "SELECT season, week, home_team, away_team, start_date "
        "FROM games WHERE game_id = ?",
        (line.game_id,),
    ).fetchone()


def _valid_matchup(
    line: EffectiveContestLine,
    game: tuple[int, int, str, str, str | None] | None,
) -> bool:
    return game is not None and game[:4] == (
        line.season,
        line.week,
        line.normalized_home_team,
        line.normalized_away_team,
    )


def _before_kickoff(
    conn: sqlite3.Connection,
    generated_at: str,
    game: tuple[int, int, str, str, str | None] | None,
) -> bool:
    if game is None or game[4] is None:
        return False
    row = conn.execute(
        "SELECT julianday(?) IS NOT NULL "
        "AND julianday(?) IS NOT NULL "
        "AND julianday(?) < julianday(?)",
        (generated_at, game[4], generated_at, game[4]),
    ).fetchone()
    return row is not None and row[0] == 1


def _prediction_for_line(
    conn: sqlite3.Connection,
    *,
    model_run_id: int,
    line: EffectiveContestLine,
    generated_at: str,
) -> ModelPrediction | None:
    if line.game_id is None:
        return None
    row = conn.execute(
        "SELECT id FROM model_predictions "
        "WHERE model_run_id = ? AND game_id = ? "
        "AND julianday(generated_at) <= julianday(?)",
        (model_run_id, line.game_id, generated_at),
    ).fetchone()
    return get_model_prediction(conn, row[0]) if row is not None else None


def _eligible_market_line(
    conn: sqlite3.Connection,
    *,
    game_id: int,
    line_type: str,
    book: str,
    generated_at: str,
) -> _MarketLine | None:
    order = "DESC" if line_type == "current" else "ASC"
    row = conn.execute(
        "SELECT id, home_spread, book, line_type, source, fetched_at "
        "FROM betting_lines WHERE game_id = ? AND line_type = ? AND book = ? "
        "AND home_spread IS NOT NULL AND julianday(fetched_at) IS NOT NULL "
        "AND julianday(fetched_at) <= julianday(?) "
        f"ORDER BY julianday(fetched_at) {order}, id {order} LIMIT 1",
        (game_id, line_type, book, generated_at),
    ).fetchone()
    return _MarketLine(*row) if row is not None else None


def _market_side(
    locked_home_spread: float,
    market_home_spread: float,
) -> str | None:
    home_edge = locked_home_spread - market_home_spread
    if home_edge > 0:
        return "home"
    if home_edge < 0:
        return "away"
    return None


def _fallback_selection(
    conn: sqlite3.Connection,
    *,
    line: EffectiveContestLine,
    policy: FullCardPolicy,
    generated_at: str,
    provenance: str,
) -> _Selection:
    if line.game_id is None:
        raise FullCardError(f"locked line {line.locked_line_id} has no canonical game")
    for line_type, prefix in (
        ("current", MARKET_CURRENT_PREFIX),
        ("opening", MARKET_OPENING_PREFIX),
    ):
        for book in policy.market_books:
            market = _eligible_market_line(
                conn,
                game_id=line.game_id,
                line_type=line_type,
                book=book,
                generated_at=generated_at,
            )
            if market is None:
                continue
            side = _market_side(line.home_spread, market.home_spread)
            if side is None:
                continue
            code = f"{prefix}{market.id}"
            detail = (
                f"{provenance};selection=fallback;fallback_code={code};"
                f"market_book={market.book};market_source={market.source};"
                f"market_fetched_at={market.fetched_at};locked_line_id={line.locked_line_id}"
            )
            return _Selection(
                line=line,
                selected_side=side,
                model_prediction_id=None,
                fallback_code=code,
                provenance=detail,
            )

    if line.home_spread < 0:
        side = "away"
        code = LOCKED_LINE_UNDERDOG
    elif line.home_spread > 0:
        side = "home"
        code = LOCKED_LINE_UNDERDOG
    else:
        side = policy.pickem_tiebreak_side
        code = (
            LOCKED_LINE_PICKEM_HOME
            if side == "home"
            else LOCKED_LINE_PICKEM_AWAY
        )
    detail = (
        f"{provenance};selection=fallback;fallback_code={code};"
        f"locked_line_id={line.locked_line_id};locked_line_source={line.source};"
        f"locked_line_payload_sha256={line.payload_sha256}"
    )
    return _Selection(
        line=line,
        selected_side=side,
        model_prediction_id=None,
        fallback_code=code,
        provenance=detail,
    )


def _select_side(
    conn: sqlite3.Connection,
    *,
    line: EffectiveContestLine,
    model_run_id: int,
    policy: FullCardPolicy,
    generated_at: str,
    provenance: str,
) -> _Selection:
    prediction = _prediction_for_line(
        conn,
        model_run_id=model_run_id,
        line=line,
        generated_at=generated_at,
    )
    if prediction is not None:
        home_edge = prediction.predicted_home_margin + line.home_spread
        if home_edge != 0:
            side = "home" if home_edge > 0 else "away"
            detail = (
                f"{provenance};selection=model_prediction;"
                f"model_prediction_id={prediction.id};locked_line_id={line.locked_line_id}"
            )
            return _Selection(
                line,
                side,
                prediction.id,
                None,
                detail,
                uncertainty_points=prediction.uncertainty_points,
            )
        if policy.model_tie_side in ("home", "away"):
            code = f"model_tie_{policy.model_tie_side}"
            detail = (
                f"{provenance};selection=fallback;fallback_code={code};"
                f"model_prediction_id={prediction.id};locked_line_id={line.locked_line_id}"
            )
            return _Selection(
                line,
                policy.model_tie_side,
                prediction.id,
                code,
                detail,
                uncertainty_points=prediction.uncertainty_points,
            )
    return _fallback_selection(
        conn,
        line=line,
        policy=policy,
        generated_at=generated_at,
        provenance=provenance,
    )


def _rank_selections(
    selections: tuple[_Selection, ...],
    policy: ConfidenceRankingPolicy,
) -> tuple[_Selection, ...]:
    """Assign confidence and Top 5 from reliability, never raw model edge."""
    policy = validate_confidence_ranking_policy(policy)
    with_confidence = tuple(
        replace(
            selection,
            confidence=confidence_for_uncertainty(
                policy,
                selection.uncertainty_points,
            ),
        )
        for selection in selections
    )
    ordered = sorted(
        with_confidence,
        key=lambda selection: (
            -selection.confidence,
            selection.uncertainty_points is None,
            selection.uncertainty_points
            if selection.uncertainty_points is not None
            else float("inf"),
            selection.line.locked_line_id,
        ),
    )
    top_count = min(TOP_FIVE_COUNT, len(ordered))
    ranks = {
        selection.line.locked_line_id: top_count - index
        for index, selection in enumerate(ordered[:top_count])
    }
    ranked: list[_Selection] = []
    for selection in with_confidence:
        rank = ranks.get(selection.line.locked_line_id)
        reliability = (
            f"model_uncertainty_points:{selection.uncertainty_points}"
            if selection.uncertainty_points is not None
            else "unscored_floor"
        )
        detail = (
            f"{selection.provenance};confidence_policy_version="
            f"{policy.confidence_policy_version};ranking_policy_version="
            f"{policy.ranking_policy_version};confidence={selection.confidence};"
            f"reliability={reliability};top_five={str(rank is not None).lower()};"
            f"rank={rank if rank is not None else 'none'}"
        )
        ranked.append(
            replace(
                selection,
                rank=rank,
                is_top_five=rank is not None,
                provenance=detail,
            )
        )
    return tuple(ranked)


def _market_fallback_valid(
    conn: sqlite3.Connection,
    *,
    pick: ContestPick,
    line: EffectiveContestLine,
    generated_at: str,
    match: re.Match[str],
) -> bool:
    expected_type = "current" if match.group(1) == "market_current_line" else "opening"
    market_id = int(match.group(2))
    row = conn.execute(
        "SELECT game_id, home_spread, book, line_type, fetched_at "
        "FROM betting_lines WHERE id = ?",
        (market_id,),
    ).fetchone()
    if (
        row is None
        or line.game_id is None
        or row[0] != line.game_id
        or row[2].casefold() == "consensus"
        or row[3] != expected_type
        or not timestamp_on_or_before(conn, row[4], generated_at)
    ):
        return False
    return _market_side(line.home_spread, row[1]) == pick.selected_side


def _fallback_valid(
    conn: sqlite3.Connection,
    *,
    pick: ContestPick,
    line: EffectiveContestLine,
    generated_at: str,
) -> bool:
    code = pick.fallback_code
    if code is None:
        if pick.model_prediction_id is None or line.game_id is None:
            return False
        prediction = get_model_prediction(conn, pick.model_prediction_id)
        home_edge = prediction.predicted_home_margin + line.home_spread
        expected = "home" if home_edge > 0 else "away" if home_edge < 0 else None
        return prediction.game_id == line.game_id and pick.selected_side == expected
    if pick.model_prediction_id is not None and not code.startswith("model_tie_"):
        return False
    market_match = _MARKET_FALLBACK.fullmatch(code)
    if market_match is not None:
        return _market_fallback_valid(
            conn,
            pick=pick,
            line=line,
            generated_at=generated_at,
            match=market_match,
        )
    if code == LOCKED_LINE_UNDERDOG:
        expected = (
            "away"
            if line.home_spread < 0
            else "home"
            if line.home_spread > 0
            else None
        )
        return expected == pick.selected_side
    if code == LOCKED_LINE_PICKEM_HOME:
        return line.home_spread == 0 and pick.selected_side == "home"
    if code == LOCKED_LINE_PICKEM_AWAY:
        return line.home_spread == 0 and pick.selected_side == "away"
    if code in ("model_tie_home", "model_tie_away"):
        if pick.model_prediction_id is None or line.game_id is None:
            return False
        prediction = get_model_prediction(conn, pick.model_prediction_id)
        expected_side = code.removeprefix("model_tie_")
        return (
            prediction.game_id == line.game_id
            and prediction.predicted_home_margin + line.home_spread == 0
            and pick.selected_side == expected_side
        )
    return False


def _selection_replay_matches(
    *,
    existing: tuple[ContestPick, ...],
    selections: tuple[_Selection, ...],
) -> bool:
    if len(existing) != len(selections):
        return False
    by_line = {pick.locked_line_id: pick for pick in existing}
    for selection in selections:
        pick = by_line.get(selection.line.locked_line_id)
        if pick is None or (
            pick.model_prediction_id,
            pick.selected_side,
            pick.fallback_code,
        ) != (
            selection.model_prediction_id,
            selection.selected_side,
            selection.fallback_code,
        ):
            return False
        if not pick.provenance.startswith(f"{selection.provenance};"):
            return False
    return True


def inspect_full_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    policy: FullCardPolicy,
    confidence_policy: ConfidenceRankingPolicy,
) -> CardCompletenessReport:
    """Inspect side, Confidence, ranking, and provenance without mutation."""
    policy = _validated_policy(policy)
    confidence_policy = validate_confidence_ranking_policy(confidence_policy)
    card = get_contest_card(conn, integer(card_id, "card_id", 1))
    generated_at = datetime.fromisoformat(card.generated_at)
    lines = list_effective_locked_lines(conn, card.contest_id, as_of=generated_at)
    by_line = {line.locked_line_id: line for line in lines}
    expected_ids = set(by_line)
    picks = list_contest_picks(conn, card.id)
    pick_ids = [pick.locked_line_id for pick in picks]
    actual_ids = set(pick_ids)

    unresolved: list[int] = []
    mismatched: list[int] = []
    invalid_kickoff: list[int] = []
    normalized_count = 0
    for line in lines:
        game = _game_row(conn, line)
        if line.game_id is None:
            unresolved.append(line.locked_line_id)
        elif not _valid_matchup(line, game):
            mismatched.append(line.locked_line_id)
        else:
            normalized_count += 1
        if not _before_kickoff(conn, card.generated_at, game):
            invalid_kickoff.append(line.locked_line_id)

    invalid_picks: list[int] = []
    missing_provenance: list[int] = []
    invalid_fallback: list[int] = []
    model_pick_count = 0
    fallback_pick_count = 0
    confidence_coverage_count = 0
    invalid_confidence: list[int] = []
    invalid_top_five: list[int] = []
    ranks: dict[int, list[int]] = {}
    for pick in picks:
        line = by_line.get(pick.locked_line_id)
        if pick.selected_side not in ("home", "away") or line is None:
            invalid_picks.append(pick.id)
            continue
        if not pick.provenance.strip():
            missing_provenance.append(pick.id)
        if pick.model_prediction_id is not None:
            prediction = get_model_prediction(conn, pick.model_prediction_id)
            if (
                line.game_id is None
                or prediction.game_id != line.game_id
                or prediction.model_run_id != card.model_run_id
                or not timestamp_on_or_before(
                    conn, prediction.generated_at, card.generated_at
                )
            ):
                invalid_picks.append(pick.id)
            model_pick_count += 1
        if pick.fallback_code is not None:
            fallback_pick_count += 1
        if pick.confidence is not None:
            confidence_coverage_count += 1
        if pick.confidence not in (1, 2, 3, 4, 5):
            invalid_confidence.append(pick.id)
        if pick.is_top_five != (pick.rank is not None):
            invalid_top_five.append(pick.id)
        if pick.rank is not None:
            ranks.setdefault(pick.rank, []).append(pick.id)
            if not 1 <= pick.rank <= TOP_FIVE_COUNT:
                invalid_top_five.append(pick.id)
        if not _fallback_valid(
            conn,
            pick=pick,
            line=line,
            generated_at=card.generated_at,
        ):
            invalid_fallback.append(pick.id)

    model_metadata_complete = False
    if card.model_run_id is not None:
        run = get_model_run(conn, card.model_run_id)
        model_metadata_complete = run.status == "completed" and timestamp_on_or_before(
            conn, run.generated_at, card.generated_at
        )

    policy_replay_matches = card.policy_version == policy.version
    confidence_ranking_policy_matches = False
    if model_metadata_complete and policy_replay_matches:
        expected_side_selections = tuple(
            _select_side(
                conn,
                line=line,
                model_run_id=card.model_run_id,
                policy=policy,
                generated_at=card.generated_at,
                provenance=card.provenance,
            )
            for line in lines
        )
        policy_replay_matches = _selection_replay_matches(
            existing=picks,
            selections=expected_side_selections,
        )
        try:
            recorded_policy = get_card_ranking_policy(conn, card.id)
            confidence_ranking_policy_matches = recorded_policy_matches(
                recorded_policy,
                confidence_policy,
            )
            if confidence_ranking_policy_matches:
                expected_ranked_selections = _rank_selections(
                    expected_side_selections,
                    confidence_policy,
                )
                _assert_replay_matches(
                    existing=picks,
                    selections=expected_ranked_selections,
                )
        except BusinessEntityError:
            confidence_ranking_policy_matches = False

    duplicate_rank_pick_ids = {
        pick_id
        for pick_ids in ranks.values()
        if len(pick_ids) > 1
        for pick_id in pick_ids
    }
    invalid_top_five.extend(duplicate_rank_pick_ids)
    expected_top_five = min(TOP_FIVE_COUNT, len(lines))
    if set(ranks) != set(range(1, expected_top_five + 1)):
        invalid_top_five.extend(pick.id for pick in picks)

    return CardCompletenessReport(
        card_id=card.id,
        contest_id=card.contest_id,
        expected_locked_line_count=len(lines),
        normalized_matchup_count=normalized_count,
        pick_count=len(picks),
        model_pick_count=model_pick_count,
        fallback_pick_count=fallback_pick_count,
        duplicate_pick_count=len(pick_ids) - len(actual_ids),
        missing_locked_line_ids=tuple(sorted(expected_ids - actual_ids)),
        unexpected_locked_line_ids=tuple(sorted(actual_ids - expected_ids)),
        unresolved_locked_line_ids=tuple(unresolved),
        mismatched_matchup_line_ids=tuple(mismatched),
        invalid_kickoff_line_ids=tuple(invalid_kickoff),
        invalid_pick_ids=tuple(sorted(set(invalid_picks))),
        missing_provenance_pick_ids=tuple(missing_provenance),
        invalid_fallback_pick_ids=tuple(invalid_fallback),
        confidence_coverage_count=confidence_coverage_count,
        top_five_count=sum(pick.is_top_five for pick in picks),
        ranked_pick_count=sum(pick.rank is not None for pick in picks),
        invalid_confidence_pick_ids=tuple(sorted(set(invalid_confidence))),
        invalid_top_five_pick_ids=tuple(sorted(set(invalid_top_five))),
        model_metadata_complete=model_metadata_complete,
        locked_line_snapshot_matches=(
            locked_line_snapshot_sha256(lines) == card.locked_line_snapshot_sha256
        ),
        policy_replay_matches=policy_replay_matches,
        confidence_ranking_policy_matches=confidence_ranking_policy_matches,
        reproducibility_manifest_matches=card_run_manifest_matches(
            conn,
            card.id,
            policy=policy,
            confidence_policy=confidence_policy,
        ),
    )


def validate_full_card(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    policy: FullCardPolicy,
    confidence_policy: ConfidenceRankingPolicy,
) -> CardCompletenessReport:
    """Return a report only for a complete, policy-reproducible contest card."""
    report = inspect_full_card(
        conn,
        card_id,
        policy=policy,
        confidence_policy=confidence_policy,
    )
    if not report.contest_complete:
        raise IncompleteCardError(report)
    return report


def _existing_card_generation_time(
    conn: sqlite3.Connection,
    *,
    card_key: str,
    contest_id: int,
    version: int,
    requested: datetime | None,
) -> datetime:
    row = conn.execute(
        "SELECT id FROM contest_cards "
        "WHERE card_key = ? OR (contest_id = ? AND version = ?) "
        "ORDER BY card_key = ? DESC LIMIT 1",
        (card_key, contest_id, version, card_key),
    ).fetchone()
    if row is not None:
        return datetime.fromisoformat(get_contest_card(conn, row[0]).generated_at)
    return datetime.fromisoformat(utc_timestamp(requested, "generated_at"))


def _assert_replay_matches(
    *,
    existing: tuple[ContestPick, ...],
    selections: tuple[_Selection, ...],
) -> None:
    if len(existing) != len(selections):
        raise FullCardError("existing card is incomplete and cannot be appended in place")
    by_line = {pick.locked_line_id: pick for pick in existing}
    for selection in selections:
        pick = by_line.get(selection.line.locked_line_id)
        if pick is None or (
            pick.model_prediction_id,
            pick.selected_side,
            pick.confidence,
            pick.rank,
            pick.is_top_five,
            pick.fallback_code,
            pick.provenance,
        ) != (
            selection.model_prediction_id,
            selection.selected_side,
            selection.confidence,
            selection.rank,
            selection.is_top_five,
            selection.fallback_code,
            selection.provenance,
        ):
            raise FullCardError("existing card differs from the deterministic replay")


def generate_full_card(
    conn: sqlite3.Connection,
    *,
    card_key: str,
    contest_id: int,
    model_run_id: int,
    version: int,
    policy: FullCardPolicy,
    confidence_policy: ConfidenceRankingPolicy,
    created_by: str,
    provenance: str,
    generated_at: datetime | None = None,
) -> FullCardResult:
    """Atomically create a complete ranked draft card or persist nothing."""
    card_key = required_text(card_key, "card_key")
    contest_id = integer(contest_id, "contest_id", 1)
    model_run_id = integer(model_run_id, "model_run_id", 1)
    version = integer(version, "version", 1)
    policy = _validated_policy(policy)
    confidence_policy = validate_confidence_ranking_policy(confidence_policy)
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")
    run = get_model_run(conn, model_run_id)
    if run.status != "completed":
        raise FullCardError("full cards require a completed model run")

    generation_time = _existing_card_generation_time(
        conn,
        card_key=card_key,
        contest_id=contest_id,
        version=version,
        requested=generated_at,
    )
    generated_at_value = generation_time.isoformat()
    if not timestamp_on_or_before(conn, run.generated_at, generated_at_value):
        raise FullCardError("model run must complete before card generation")
    lines = list_effective_locked_lines(conn, contest_id, as_of=generation_time)
    if not lines:
        raise FullCardError("contest has no locked lines")

    side_selections: list[_Selection] = []
    for line in lines:
        game = _game_row(conn, line)
        if not _valid_matchup(line, game):
            raise FullCardError(
                f"locked line {line.locked_line_id} has unresolved or mismatched game identity"
            )
        if not _before_kickoff(conn, generated_at_value, game):
            raise FullCardError(
                f"locked line {line.locked_line_id} lacks a future valid kickoff"
            )
        side_selections.append(
            _select_side(
                conn,
                line=line,
                model_run_id=model_run_id,
                policy=policy,
                generated_at=generated_at_value,
                provenance=provenance,
            )
        )
    selections = _rank_selections(tuple(side_selections), confidence_policy)

    existing_row = conn.execute(
        "SELECT id FROM contest_cards "
        "WHERE card_key = ? OR (contest_id = ? AND version = ?) "
        "ORDER BY card_key = ? DESC LIMIT 1",
        (card_key, contest_id, version, card_key),
    ).fetchone()
    if existing_row is not None:
        card = create_contest_card(
            conn,
            card_key=card_key,
            contest_id=contest_id,
            model_run_id=model_run_id,
            version=version,
            status="draft",
            policy_version=policy.version,
            locked_line_snapshot_sha256=locked_line_snapshot_sha256(lines),
            generated_at=generation_time,
            created_by=created_by,
            provenance=provenance,
        )
        picks = list_contest_picks(conn, card.id)
        try:
            recorded_policy = get_card_ranking_policy(conn, card.id)
        except BusinessEntityError as exc:
            raise FullCardError(
                "existing card has no immutable Confidence and ranking policy"
            ) from exc
        if not recorded_policy_matches(recorded_policy, confidence_policy):
            raise FullCardError(
                "existing card has a different Confidence or ranking policy"
            )
        _assert_replay_matches(existing=picks, selections=selections)
        try:
            assert_card_run_manifest(
                conn,
                card.id,
                policy=policy,
                confidence_policy=confidence_policy,
            )
        except BusinessEntityError as exc:
            raise FullCardError(
                "existing card has no matching immutable run manifest"
            ) from exc
        return FullCardResult(
            card,
            picks,
            validate_full_card(
                conn,
                card.id,
                policy=policy,
                confidence_policy=confidence_policy,
            ),
        )

    with atomic(conn):
        selection_policy = register_contest_selection_policy(
            conn,
            policy,
            effective_at=generation_time,
            created_by=created_by,
            provenance=provenance,
        )
        recorded_policy = register_confidence_ranking_policy(
            conn,
            confidence_policy,
        )
        card = create_contest_card(
            conn,
            card_key=card_key,
            contest_id=contest_id,
            model_run_id=model_run_id,
            version=version,
            status="draft",
            policy_version=policy.version,
            locked_line_snapshot_sha256=locked_line_snapshot_sha256(lines),
            generated_at=generation_time,
            created_by=created_by,
            provenance=provenance,
        )
        assign_card_ranking_policy(
            conn,
            card_id=card.id,
            ranking_policy_id=recorded_policy.id,
            provenance=provenance,
            assigned_at=generation_time,
        )
        for selection in selections:
            add_contest_pick(
                conn,
                pick_key=f"{card_key}:locked-line:{selection.line.locked_line_id}",
                card_id=card.id,
                locked_line_id=selection.line.locked_line_id,
                model_prediction_id=selection.model_prediction_id,
                selected_side=selection.selected_side,
                confidence=selection.confidence,
                rank=selection.rank,
                is_top_five=selection.is_top_five,
                fallback_code=selection.fallback_code,
                generated_at=generation_time,
                provenance=selection.provenance,
            )
        record_card_run_manifest(
            conn,
            card_id=card.id,
            selection_policy_id=selection_policy.id,
            ranking_policy_id=recorded_policy.id,
        )
        report = validate_full_card(
            conn,
            card.id,
            policy=policy,
            confidence_policy=confidence_policy,
        )
        return FullCardResult(card, list_contest_picks(conn, card.id), report)
