"""Append-only live sportsbook offers, policies, and BET/NO BET evaluations."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import NormalDist

from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    number,
    required_text,
    utc_timestamp,
)
from business_entities.modeling import get_model_prediction, get_model_run
from business_entities.wagering import record_sportsbook_recommendation


ACTIVE_MODEL_NAME = "epa_only"
ACTIVE_MODEL_VERSION = "epa-only-linear-v1"
PROBABILITY_MODEL_VERSION = "normal-margin-v1"
DRAFTKINGS_BOOKMAKER = "draftkings"
DRAFTKINGS_BOARD_TITLE = "DRAFTKINGS BETTING BOARD"


@dataclass(frozen=True)
class SportsbookMarketOffer:
    id: int
    provider_market_snapshot_id: int
    betting_line_id: int
    provider: str
    bookmaker: str
    game_id: int
    line_type: str
    home_spread: float
    home_price: int
    away_spread: float
    away_price: int
    observed_at: str
    event_start_at: str
    parser_version: str
    raw_record_sha256: str
    recorded_at: str
    provenance: str


@dataclass(frozen=True)
class SportsbookRecommendationPolicy:
    id: int
    policy_version: str
    production_model_name: str
    production_model_version: str
    probability_model_version: str
    residual_stddev_points: float
    minimum_spread_edge_points: float
    minimum_cover_probability: float
    minimum_expected_value: float
    maximum_odds_age_seconds: int
    material_update_seconds: int
    material_spread_change_points: float
    material_price_change: int
    maximum_stake_units: float
    stake_units_per_expected_value: float
    stake_increment_units: float
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class SportsbookRecommendationEvaluation:
    id: int
    evaluation_key: str
    recommendation_id: int
    policy_id: int
    policy_version: str
    market_offer_id: int
    model_prediction_id: int
    supersedes_evaluation_id: int | None
    lifecycle_state: str
    decision: str
    selected_side: str
    selected_team: str
    bookmaker: str
    offered_spread: float
    offered_price: int
    captured_at: str
    event_start_at: str
    model_fair_spread: float
    spread_edge_points: float
    estimated_cover_probability: float
    break_even_probability: float
    expected_value: float
    stake_units: float
    reason_code: str
    evaluated_at: str
    provenance: str

    def board_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["decision"] = self.decision.upper().replace("_", " ")
        return payload


@dataclass(frozen=True)
class SportsbookClosingDesignation:
    id: int
    designation_key: str
    market_offer_id: int
    closing_betting_line_id: int
    game_id: int
    bookmaker: str
    designated_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class DraftKingsBettingBoardRow:
    game_id: int
    game: str
    selected_team: str | None
    selected_side: str | None
    decision: str
    bookmaker: str
    offered_spread: float | None
    offered_price: int | None
    offer_captured_at: str | None
    observation_timestamp: str
    model_fair_spread: float | None
    spread_edge_points: float | None
    estimated_cover_probability: float | None
    break_even_probability: float | None
    expected_value: float | None
    stake_units: float
    policy_version: str
    reason_code: str
    freshness: str
    availability_state: str
    provider_capture_attempted: bool
    provider_ingestion_run_id: int | None
    provider_market_snapshot_id: int | None
    market_offer_id: int | None
    evaluation_id: int | None
    provenance: str

    def board_payload(self) -> dict[str, object]:
        return asdict(self)

    def owner_summary(self) -> str:
        if self.availability_state != "AVAILABLE":
            return (
                f"UNAVAILABLE | {self.game} | {self.reason_code} | "
                f"observed {self.observation_timestamp}"
            )
        assert self.selected_team is not None
        assert self.offered_spread is not None
        assert self.offered_price is not None
        assert self.model_fair_spread is not None
        assert self.estimated_cover_probability is not None
        assert self.expected_value is not None
        summary = (
            f"{self.decision} | {self.selected_team} {self.offered_spread:+g} | "
            f"{self.offered_price:+d} | Fair {self.model_fair_spread:+.1f} | "
            f"Cover {self.estimated_cover_probability:.1%} | "
            f"EV {self.expected_value:+.1%} | {self.stake_units:.2f}u"
        )
        return summary if self.decision == "BET" else f"{summary} | {self.reason_code}"


_OFFER_COLUMNS = (
    "id, provider_market_snapshot_id, betting_line_id, provider, bookmaker, "
    "game_id, line_type, home_spread, home_price, away_spread, away_price, "
    "observed_at, event_start_at, parser_version, raw_record_sha256, "
    "recorded_at, provenance"
)
_POLICY_COLUMNS = (
    "id, policy_version, production_model_name, production_model_version, "
    "probability_model_version, residual_stddev_points, "
    "minimum_spread_edge_points, minimum_cover_probability, "
    "minimum_expected_value, maximum_odds_age_seconds, "
    "material_update_seconds, material_spread_change_points, "
    "material_price_change, maximum_stake_units, "
    "stake_units_per_expected_value, stake_increment_units, effective_at, "
    "created_by, provenance"
)
_EVALUATION_COLUMNS = (
    "id, evaluation_key, recommendation_id, policy_id, policy_version, market_offer_id, "
    "model_prediction_id, supersedes_evaluation_id, lifecycle_state, decision, "
    "selected_side, selected_team, bookmaker, offered_spread, offered_price, "
    "captured_at, event_start_at, model_fair_spread, spread_edge_points, "
    "estimated_cover_probability, break_even_probability, expected_value, "
    "stake_units, reason_code, evaluated_at, provenance"
)
_CLOSING_COLUMNS = (
    "id, designation_key, market_offer_id, closing_betting_line_id, game_id, "
    "bookmaker, designated_at, source, provenance"
)


def _qualified(columns: str, alias: str) -> str:
    return ", ".join(f"{alias}.{column.strip()}" for column in columns.split(","))


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BusinessEntityError("recorded timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise BusinessEntityError("recorded timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _american_price(value: int, field: str) -> int:
    value = integer(value, field)
    if -100 < value < 100:
        raise BusinessEntityError(f"{field} must be valid American odds")
    return value


def get_sportsbook_market_offer(
    conn: sqlite3.Connection, offer_id: int
) -> SportsbookMarketOffer:
    row = conn.execute(
        f"SELECT {_OFFER_COLUMNS} FROM sportsbook_market_offers WHERE id = ?",
        (integer(offer_id, "offer_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"sportsbook market offer does not exist: {offer_id}")
    return SportsbookMarketOffer(*row)


def record_sportsbook_market_offer(
    conn: sqlite3.Connection,
    *,
    provider_market_snapshot_id: int,
    betting_line_id: int,
    line_type: str,
    away_spread: float | int,
    away_price: int,
    provenance: str,
) -> SportsbookMarketOffer:
    """Attach the two-sided, wagering-eligible offer to immutable provider custody."""
    provider_market_snapshot_id = integer(
        provider_market_snapshot_id, "provider_market_snapshot_id", 1
    )
    betting_line_id = integer(betting_line_id, "betting_line_id", 1)
    if line_type not in ("opening", "current", "closing"):
        raise BusinessEntityError("line_type must be opening, current, or closing")
    away_spread_value = number(away_spread, "away_spread")
    away_price_value = _american_price(away_price, "away_price")
    provenance = required_text(provenance, "provenance")
    with atomic(conn):
        snapshot = conn.execute(
            "SELECT provider, bookmaker, game_id, home_spread, home_price, observed_at, "
            "event_start_at, parser_version, raw_record_sha256, ingested_at "
            "FROM provider_market_snapshots WHERE id = ?",
            (provider_market_snapshot_id,),
        ).fetchone()
        if snapshot is None:
            raise BusinessEntityError("provider market snapshot does not exist")
        if snapshot[4] is None:
            raise BusinessEntityError("two-sided offers require a home American price")
        home_price = _american_price(int(snapshot[4]), "home_price")
        home_spread = float(snapshot[3])
        if not math.isclose(home_spread + away_spread_value, 0.0, abs_tol=1e-6):
            raise BusinessEntityError("home and away spreads must be exact opposites")
        line = conn.execute(
            "SELECT game_id, book, home_spread, home_moneyline, line_type, source, fetched_at "
            "FROM betting_lines WHERE id = ?",
            (betting_line_id,),
        ).fetchone()
        if line is None or tuple(line) != (
            snapshot[2],
            snapshot[1],
            snapshot[3],
            snapshot[4],
            line_type,
            snapshot[0],
            snapshot[5],
        ):
            raise BusinessEntityError(
                "sportsbook offer must match its exact provider and market-line custody"
            )
        requested = (
            provider_market_snapshot_id,
            betting_line_id,
            snapshot[0],
            snapshot[1],
            snapshot[2],
            line_type,
            home_spread,
            home_price,
            away_spread_value,
            away_price_value,
            snapshot[5],
            snapshot[6],
            snapshot[7],
            snapshot[8],
            snapshot[9],
            provenance,
        )
        row = conn.execute(
            f"SELECT {_OFFER_COLUMNS} FROM sportsbook_market_offers "
            "WHERE provider_market_snapshot_id = ? OR betting_line_id = ?",
            (provider_market_snapshot_id, betting_line_id),
        ).fetchone()
        if row is not None:
            existing = SportsbookMarketOffer(*row)
            if tuple(asdict(existing).values())[1:] != requested:
                raise BusinessEntityConflictError(
                    "sportsbook offer already has different immutable values"
                )
            return existing
        cursor = conn.execute(
            "INSERT INTO sportsbook_market_offers "
            "(provider_market_snapshot_id, betting_line_id, provider, bookmaker, "
            "game_id, line_type, home_spread, home_price, away_spread, away_price, "
            "observed_at, event_start_at, parser_version, raw_record_sha256, "
            "recorded_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            requested,
        )
        return get_sportsbook_market_offer(conn, cursor.lastrowid)


def get_sportsbook_closing_designation(
    conn: sqlite3.Connection, designation_id: int
) -> SportsbookClosingDesignation:
    row = conn.execute(
        f"SELECT {_CLOSING_COLUMNS} FROM sportsbook_closing_designations WHERE id = ?",
        (integer(designation_id, "designation_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"sportsbook closing designation does not exist: {designation_id}"
        )
    return SportsbookClosingDesignation(*row)


def designate_sportsbook_closing_offer(
    conn: sqlite3.Connection,
    *,
    market_offer_id: int,
    designated_at: datetime,
    source: str,
    provenance: str,
) -> SportsbookClosingDesignation:
    """Designate the exact latest current offer as the same-book pre-kickoff close."""
    offer = get_sportsbook_market_offer(conn, market_offer_id)
    if offer.line_type != "current":
        raise BusinessEntityError("only a current offer can be designated as closing")
    designated_at_value = utc_timestamp(designated_at, "designated_at")
    designated = _utc(designated_at_value)
    if _utc(offer.observed_at) > designated or designated >= _utc(offer.event_start_at):
        raise BusinessEntityError("closing designation must be after capture and before kickoff")
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    latest = conn.execute(
        "SELECT id FROM sportsbook_market_offers WHERE game_id = ? "
        "AND bookmaker = ? AND line_type = 'current' "
        "AND julianday(observed_at) <= julianday(?) "
        "ORDER BY julianday(observed_at) DESC, id DESC LIMIT 1",
        (offer.game_id, offer.bookmaker, designated_at_value),
    ).fetchone()
    if latest is None or int(latest[0]) != offer.id:
        raise BusinessEntityError("closing designation requires the latest current offer")
    key = f"sportsbook-closing:offer:{offer.id}"
    with atomic(conn):
        existing = conn.execute(
            f"SELECT {_CLOSING_COLUMNS} FROM sportsbook_closing_designations "
            "WHERE designation_key = ? OR market_offer_id = ?",
            (key, offer.id),
        ).fetchone()
        if existing is not None:
            designation = SportsbookClosingDesignation(*existing)
            if (
                designation.designation_key != key
                or designation.market_offer_id != offer.id
                or designation.game_id != offer.game_id
                or designation.bookmaker != offer.bookmaker
                or designation.designated_at != designated_at_value
                or designation.source != source
                or designation.provenance != provenance
            ):
                raise BusinessEntityConflictError(
                    "sportsbook closing designation has different immutable values"
                )
            return designation
        closing_line_id = int(
            conn.execute(
                "INSERT INTO betting_lines "
                "(game_id, season, week, home_team, away_team, book, home_spread, "
                "home_moneyline, line_type, source, fetched_at) "
                "SELECT game.game_id, game.season, game.week, game.home_team, "
                "game.away_team, ?, ?, ?, 'closing', ?, ? FROM games AS game "
                "WHERE game.game_id = ?",
                (
                    offer.bookmaker,
                    offer.home_spread,
                    offer.home_price,
                    offer.provider,
                    offer.observed_at,
                    offer.game_id,
                ),
            ).lastrowid
        )
        cursor = conn.execute(
            "INSERT INTO sportsbook_closing_designations "
            "(designation_key, market_offer_id, closing_betting_line_id, game_id, "
            "bookmaker, designated_at, source, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                offer.id,
                closing_line_id,
                offer.game_id,
                offer.bookmaker,
                designated_at_value,
                source,
                provenance,
            ),
        )
        return get_sportsbook_closing_designation(conn, cursor.lastrowid)


def designate_week_closing_offers(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    designated_at: datetime,
    source: str,
    provenance: str,
) -> tuple[SportsbookClosingDesignation, ...]:
    """Designate one latest current observation for every available game/book."""
    season = integer(season, "season", 1869)
    week = integer(week, "week", 0)
    designated_at_value = utc_timestamp(designated_at, "designated_at")
    rows = conn.execute(
        "SELECT offer.id FROM sportsbook_market_offers AS offer "
        "JOIN games AS game ON game.game_id = offer.game_id "
        "WHERE game.season = ? AND game.week = ? AND offer.line_type = 'current' "
        "AND julianday(offer.observed_at) <= julianday(?) "
        "AND julianday(?) < julianday(offer.event_start_at) "
        "AND NOT EXISTS (SELECT 1 FROM sportsbook_market_offers AS newer "
        "WHERE newer.game_id = offer.game_id AND newer.bookmaker = offer.bookmaker "
        "AND newer.line_type = 'current' "
        "AND julianday(newer.observed_at) <= julianday(?) AND ("
        "julianday(newer.observed_at) > julianday(offer.observed_at) "
        "OR newer.observed_at = offer.observed_at AND newer.id > offer.id)) "
        "ORDER BY offer.game_id, offer.bookmaker",
        (
            season,
            week,
            designated_at_value,
            designated_at_value,
            designated_at_value,
        ),
    ).fetchall()
    return tuple(
        designate_sportsbook_closing_offer(
            conn,
            market_offer_id=int(row[0]),
            designated_at=datetime.fromisoformat(designated_at_value),
            source=source,
            provenance=provenance,
        )
        for row in rows
    )


def get_sportsbook_recommendation_policy(
    conn: sqlite3.Connection, policy_id: int
) -> SportsbookRecommendationPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM sportsbook_recommendation_policies WHERE id = ?",
        (integer(policy_id, "policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"sportsbook policy does not exist: {policy_id}")
    return SportsbookRecommendationPolicy(*row)


def register_sportsbook_recommendation_policy(
    conn: sqlite3.Connection,
    *,
    policy_version: str,
    residual_stddev_points: float | int,
    minimum_spread_edge_points: float | int,
    minimum_cover_probability: float | int,
    minimum_expected_value: float | int,
    maximum_odds_age_seconds: int,
    material_update_seconds: int,
    material_spread_change_points: float | int,
    material_price_change: int,
    maximum_stake_units: float | int,
    stake_units_per_expected_value: float | int,
    stake_increment_units: float | int,
    effective_at: datetime,
    created_by: str,
    provenance: str,
) -> SportsbookRecommendationPolicy:
    policy_version = required_text(policy_version, "policy_version")
    residual = number(residual_stddev_points, "residual_stddev_points")
    edge = number(minimum_spread_edge_points, "minimum_spread_edge_points")
    cover = number(minimum_cover_probability, "minimum_cover_probability")
    expected_value = number(minimum_expected_value, "minimum_expected_value")
    maximum_age = integer(maximum_odds_age_seconds, "maximum_odds_age_seconds", 1)
    update_seconds = integer(material_update_seconds, "material_update_seconds", 1)
    spread_change = number(
        material_spread_change_points, "material_spread_change_points"
    )
    price_change = integer(material_price_change, "material_price_change", 1)
    maximum_stake = number(maximum_stake_units, "maximum_stake_units")
    stake_factor = number(
        stake_units_per_expected_value, "stake_units_per_expected_value"
    )
    stake_increment = number(stake_increment_units, "stake_increment_units")
    effective_at_value = utc_timestamp(effective_at, "effective_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")
    if residual <= 0 or edge < 0 or not 0.5 <= cover <= 1 or expected_value < 0:
        raise BusinessEntityError("sportsbook probability and decision thresholds are invalid")
    if maximum_age > 900 or spread_change <= 0 or maximum_stake <= 0:
        raise BusinessEntityError("sportsbook freshness, movement, or stake bounds are invalid")
    if stake_factor <= 0 or not 0 < stake_increment <= maximum_stake:
        raise BusinessEntityError("sportsbook stake policy is invalid")
    requested = (
        policy_version,
        ACTIVE_MODEL_NAME,
        ACTIVE_MODEL_VERSION,
        PROBABILITY_MODEL_VERSION,
        residual,
        edge,
        cover,
        expected_value,
        maximum_age,
        update_seconds,
        spread_change,
        price_change,
        maximum_stake,
        stake_factor,
        stake_increment,
        effective_at_value,
        created_by,
        provenance,
    )
    with atomic(conn):
        row = conn.execute(
            f"SELECT {_POLICY_COLUMNS} FROM sportsbook_recommendation_policies "
            "WHERE policy_version = ?",
            (policy_version,),
        ).fetchone()
        if row is not None:
            existing = SportsbookRecommendationPolicy(*row)
            if tuple(asdict(existing).values())[1:] != requested:
                raise BusinessEntityConflictError(
                    "sportsbook policy version already has different immutable values"
                )
            return existing
        cursor = conn.execute(
            "INSERT INTO sportsbook_recommendation_policies "
            "(policy_version, production_model_name, production_model_version, "
            "probability_model_version, residual_stddev_points, "
            "minimum_spread_edge_points, minimum_cover_probability, "
            "minimum_expected_value, maximum_odds_age_seconds, "
            "material_update_seconds, material_spread_change_points, "
            "material_price_change, maximum_stake_units, "
            "stake_units_per_expected_value, stake_increment_units, effective_at, "
            "created_by, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            requested,
        )
        return get_sportsbook_recommendation_policy(conn, cursor.lastrowid)


def get_sportsbook_recommendation_evaluation(
    conn: sqlite3.Connection, evaluation_id: int
) -> SportsbookRecommendationEvaluation:
    row = conn.execute(
        f"SELECT {_EVALUATION_COLUMNS} FROM sportsbook_recommendation_evaluations "
        "WHERE id = ?",
        (integer(evaluation_id, "evaluation_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"sportsbook evaluation does not exist: {evaluation_id}")
    return SportsbookRecommendationEvaluation(*row)


def sportsbook_evaluation_matches_sources(
    conn: sqlite3.Connection, evaluation_id: int
) -> bool:
    """Recalculate one stored decision from immutable inputs without writing."""
    try:
        evaluation = get_sportsbook_recommendation_evaluation(conn, evaluation_id)
        offer = get_sportsbook_market_offer(conn, evaluation.market_offer_id)
        prediction = get_model_prediction(conn, evaluation.model_prediction_id)
        run = get_model_run(conn, prediction.model_run_id)
        policy = get_sportsbook_recommendation_policy(conn, evaluation.policy_id)
        evaluated = _utc(evaluation.evaluated_at)
        captured = _utc(offer.observed_at)
        kickoff = _utc(offer.event_start_at)
        if (
            offer.line_type not in ("opening", "current")
            or prediction.game_id != offer.game_id
            or (run.model_name, run.model_version)
            != (policy.production_model_name, policy.production_model_version)
            or _utc(prediction.generated_at) > evaluated
            or captured > evaluated
            or evaluated >= kickoff
            or _utc(policy.effective_at) > evaluated
        ):
            return False
        teams = conn.execute(
            "SELECT home_team, away_team FROM games WHERE game_id = ?",
            (offer.game_id,),
        ).fetchone()
        if teams is None:
            return False
        home_edge = prediction.predicted_home_margin + offer.home_spread
        home_cover = NormalDist().cdf(home_edge / policy.residual_stddev_points)
        selected = max(
            (
                _candidate(
                    side=side,
                    home_edge=home_edge,
                    home_cover_probability=home_cover,
                    home_spread=offer.home_spread,
                    home_price=offer.home_price,
                    away_spread=offer.away_spread,
                    away_price=offer.away_price,
                    predicted_home_margin=prediction.predicted_home_margin,
                )
                for side in ("home", "away")
            ),
            key=lambda item: (item[6], item[4], item[0] == "home"),
        )
        side, spread, price, fair_spread, edge, cover_probability, expected_value = selected
        break_even = _break_even_probability(price)
        lifecycle = "active"
        if (evaluated - captured).total_seconds() > policy.maximum_odds_age_seconds:
            lifecycle, decision, reason = "expired", "no_bet", "stale_odds"
        elif edge < policy.minimum_spread_edge_points:
            decision, reason = "no_bet", "insufficient_spread_edge"
        elif cover_probability < policy.minimum_cover_probability:
            decision, reason = "no_bet", "insufficient_cover_probability"
        elif expected_value < policy.minimum_expected_value:
            decision, reason = "no_bet", "insufficient_expected_value"
        else:
            decision, reason = "bet", "positive_expected_value"
        stake = _stake(expected_value, policy) if decision == "bet" else 0.0
        if decision == "bet" and stake <= 0:
            decision, reason = "no_bet", "below_minimum_stake_increment"
        expected_key = (
            f"sportsbook:{policy.policy_version}:offer:{offer.id}:"
            f"prediction:{prediction.id}:"
            f"{'expired' if lifecycle == 'expired' else 'active'}"
        )
        exact = (
            evaluation.evaluation_key == expected_key
            and evaluation.policy_version == policy.policy_version
            and evaluation.lifecycle_state == lifecycle
            and evaluation.decision == decision
            and evaluation.selected_side == side
            and evaluation.selected_team == (teams[0] if side == "home" else teams[1])
            and evaluation.bookmaker == offer.bookmaker
            and evaluation.offered_price == price
            and evaluation.captured_at == offer.observed_at
            and evaluation.event_start_at == offer.event_start_at
            and evaluation.reason_code == reason
        )
        numeric = (
            (evaluation.offered_spread, spread),
            (evaluation.model_fair_spread, fair_spread),
            (evaluation.spread_edge_points, edge),
            (evaluation.estimated_cover_probability, cover_probability),
            (evaluation.break_even_probability, break_even),
            (evaluation.expected_value, expected_value),
            (evaluation.stake_units, stake),
        )
        return exact and all(
            math.isclose(recorded, expected, rel_tol=1e-12, abs_tol=1e-12)
            for recorded, expected in numeric
        )
    except (BusinessEntityError, sqlite3.DatabaseError, ValueError):
        return False


def _break_even_probability(price: int) -> float:
    return abs(price) / (abs(price) + 100) if price < 0 else 100 / (price + 100)


def _profit_per_unit(price: int) -> float:
    return 100 / abs(price) if price < 0 else price / 100


def _candidate(
    *,
    side: str,
    home_edge: float,
    home_cover_probability: float,
    home_spread: float,
    home_price: int,
    away_spread: float,
    away_price: int,
    predicted_home_margin: float,
) -> tuple[str, float, int, float, float, float, float]:
    if side == "home":
        spread = home_spread
        price = home_price
        probability = home_cover_probability
        edge = home_edge
        fair_spread = -predicted_home_margin
    else:
        spread = away_spread
        price = away_price
        probability = 1 - home_cover_probability
        edge = -home_edge
        fair_spread = predicted_home_margin
    break_even = _break_even_probability(price)
    expected_value = probability * _profit_per_unit(price) - (1 - probability)
    return side, spread, price, fair_spread, edge, probability, expected_value


def _stake(expected_value: float, policy: SportsbookRecommendationPolicy) -> float:
    raw = min(
        policy.maximum_stake_units,
        expected_value * policy.stake_units_per_expected_value,
    )
    increments = math.floor((raw + 1e-12) / policy.stake_increment_units)
    return round(increments * policy.stake_increment_units, 6)


def _evaluation_provenance(
    base: str,
    offer: SportsbookMarketOffer,
    model_prediction_id: int,
    policy: SportsbookRecommendationPolicy,
) -> str:
    return (
        f"{required_text(base, 'provenance')};provider={offer.provider};"
        f"provider_market_snapshot_id={offer.provider_market_snapshot_id};"
        f"market_offer_id={offer.id};raw_record_sha256={offer.raw_record_sha256};"
        f"model_prediction_id={model_prediction_id};policy_version={policy.policy_version}"
    )


def evaluate_sportsbook_offer(
    conn: sqlite3.Connection,
    *,
    market_offer_id: int,
    model_prediction_id: int,
    policy_id: int,
    evaluated_at: datetime,
    provenance: str,
    supersedes_evaluation_id: int | None = None,
) -> SportsbookRecommendationEvaluation:
    """Evaluate one exact current/opening offer; this function cannot place a wager."""
    offer = get_sportsbook_market_offer(conn, market_offer_id)
    if offer.line_type not in ("opening", "current"):
        raise BusinessEntityError(
            "pregame sportsbook recommendations cannot use a closing line"
        )
    prediction = get_model_prediction(conn, model_prediction_id)
    run = get_model_run(conn, prediction.model_run_id)
    policy = get_sportsbook_recommendation_policy(conn, policy_id)
    evaluated_at_value = utc_timestamp(evaluated_at, "evaluated_at")
    evaluated = _utc(evaluated_at_value)
    if prediction.game_id != offer.game_id:
        raise BusinessEntityError("recommendation and model prediction must refer to one game")
    if (run.model_name, run.model_version) != (
        policy.production_model_name,
        policy.production_model_version,
    ):
        raise BusinessEntityError("recommendation policy requires the active EPA-only model")
    if _utc(prediction.generated_at) > evaluated:
        raise BusinessEntityError("future model predictions cannot create recommendations")
    captured = _utc(offer.observed_at)
    kickoff = _utc(offer.event_start_at)
    if captured > evaluated:
        raise BusinessEntityError("future-dated odds cannot create recommendations")
    if evaluated >= kickoff:
        raise BusinessEntityError("pregame recommendations must be evaluated before kickoff")
    if _utc(policy.effective_at) > evaluated:
        raise BusinessEntityError("sportsbook policy is not effective at evaluation time")
    teams = conn.execute(
        "SELECT home_team, away_team FROM games WHERE game_id = ?", (offer.game_id,)
    ).fetchone()
    if teams is None:
        raise BusinessEntityError("sportsbook offer game does not exist")

    home_edge = prediction.predicted_home_margin + offer.home_spread
    home_cover = NormalDist().cdf(home_edge / policy.residual_stddev_points)
    candidates = (
        _candidate(
            side="home",
            home_edge=home_edge,
            home_cover_probability=home_cover,
            home_spread=offer.home_spread,
            home_price=offer.home_price,
            away_spread=offer.away_spread,
            away_price=offer.away_price,
            predicted_home_margin=prediction.predicted_home_margin,
        ),
        _candidate(
            side="away",
            home_edge=home_edge,
            home_cover_probability=home_cover,
            home_spread=offer.home_spread,
            home_price=offer.home_price,
            away_spread=offer.away_spread,
            away_price=offer.away_price,
            predicted_home_margin=prediction.predicted_home_margin,
        ),
    )
    selected = max(candidates, key=lambda item: (item[6], item[4], item[0] == "home"))
    side, spread, price, fair_spread, edge, cover_probability, expected_value = selected
    break_even = _break_even_probability(price)
    age_seconds = (evaluated - captured).total_seconds()
    lifecycle_state = "active"
    if age_seconds > policy.maximum_odds_age_seconds:
        lifecycle_state = "expired"
        decision = "no_bet"
        reason_code = "stale_odds"
    elif edge < policy.minimum_spread_edge_points:
        decision = "no_bet"
        reason_code = "insufficient_spread_edge"
    elif cover_probability < policy.minimum_cover_probability:
        decision = "no_bet"
        reason_code = "insufficient_cover_probability"
    elif expected_value < policy.minimum_expected_value:
        decision = "no_bet"
        reason_code = "insufficient_expected_value"
    else:
        decision = "bet"
        reason_code = "positive_expected_value"
    stake_units = _stake(expected_value, policy) if decision == "bet" else 0.0
    if decision == "bet" and stake_units <= 0:
        decision = "no_bet"
        reason_code = "below_minimum_stake_increment"
    provenance_value = _evaluation_provenance(
        provenance, offer, prediction.id, policy
    )
    state_token = "expired" if lifecycle_state == "expired" else "active"
    evaluation_key = (
        f"sportsbook:{policy.policy_version}:offer:{offer.id}:"
        f"prediction:{prediction.id}:{state_token}"
    )
    existing_row = conn.execute(
        f"SELECT {_EVALUATION_COLUMNS} FROM sportsbook_recommendation_evaluations "
        "WHERE evaluation_key = ?",
        (evaluation_key,),
    ).fetchone()
    if existing_row is not None:
        return SportsbookRecommendationEvaluation(*existing_row)
    recommended_team = teams[0] if side == "home" else teams[1]

    with atomic(conn):
        recommendation = record_sportsbook_recommendation(
            conn,
            recommendation_key=f"{evaluation_key}:recommendation",
            model_prediction_id=prediction.id,
            decision=decision,
            policy_version=policy.policy_version,
            reason_code=reason_code,
            provenance=provenance_value,
            market_line_id=offer.betting_line_id if decision == "bet" else None,
            recommended_side=side if decision == "bet" else None,
            offered_price=price if decision == "bet" else None,
            expected_value=expected_value if decision == "bet" else None,
            stake_units=stake_units,
            generated_at=evaluated,
        )
        cursor = conn.execute(
            "INSERT INTO sportsbook_recommendation_evaluations "
            "(evaluation_key, recommendation_id, policy_id, policy_version, market_offer_id, "
            "model_prediction_id, supersedes_evaluation_id, lifecycle_state, decision, "
            "selected_side, selected_team, bookmaker, offered_spread, offered_price, "
            "captured_at, event_start_at, model_fair_spread, spread_edge_points, "
            "estimated_cover_probability, break_even_probability, expected_value, "
            "stake_units, reason_code, evaluated_at, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evaluation_key,
                recommendation.id,
                policy.id,
                policy.policy_version,
                offer.id,
                prediction.id,
                supersedes_evaluation_id,
                lifecycle_state,
                decision,
                side,
                recommended_team,
                offer.bookmaker,
                spread,
                price,
                offer.observed_at,
                offer.event_start_at,
                fair_spread,
                edge,
                cover_probability,
                break_even,
                expected_value,
                stake_units,
                reason_code,
                evaluated_at_value,
                provenance_value,
            ),
        )
        return get_sportsbook_recommendation_evaluation(conn, cursor.lastrowid)


def _is_material_update(
    prior: SportsbookMarketOffer,
    current: SportsbookMarketOffer,
    policy: SportsbookRecommendationPolicy,
) -> bool:
    if _utc(current.observed_at) <= _utc(prior.observed_at):
        return False
    elapsed = (_utc(current.observed_at) - _utc(prior.observed_at)).total_seconds()
    return (
        elapsed >= policy.material_update_seconds
        or abs(current.home_spread - prior.home_spread)
        >= policy.material_spread_change_points
        or abs(current.home_price - prior.home_price) >= policy.material_price_change
        or abs(current.away_price - prior.away_price) >= policy.material_price_change
    )


def evaluate_live_sportsbook_board(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    policy_id: int,
    evaluated_at: datetime,
    provenance: str,
) -> tuple[SportsbookRecommendationEvaluation, ...]:
    """Evaluate the latest eligible observation for each game/book without wagering."""
    season = integer(season, "season", 1869)
    week = integer(week, "week")
    policy = get_sportsbook_recommendation_policy(conn, policy_id)
    evaluated_at_value = utc_timestamp(evaluated_at, "evaluated_at")
    offer_rows = conn.execute(
        f"SELECT {_qualified(_OFFER_COLUMNS, 'offer')} "
        "FROM sportsbook_market_offers AS offer "
        "JOIN games AS game ON game.game_id = offer.game_id "
        "WHERE game.season = ? AND game.week = ? "
        "AND offer.line_type IN ('opening', 'current') "
        "AND julianday(offer.observed_at) <= julianday(?) "
        "AND julianday(?) < julianday(offer.event_start_at) "
        "ORDER BY offer.game_id, offer.bookmaker, julianday(offer.observed_at) DESC, offer.id DESC",
        (season, week, evaluated_at_value, evaluated_at_value),
    ).fetchall()
    latest_offers: dict[tuple[int, str], SportsbookMarketOffer] = {}
    for row in offer_rows:
        offer = SportsbookMarketOffer(*row)
        latest_offers.setdefault((offer.game_id, offer.bookmaker), offer)

    results: list[SportsbookRecommendationEvaluation] = []
    for (game_id, bookmaker), offer in sorted(latest_offers.items()):
        prediction_row = conn.execute(
            "SELECT prediction.id FROM model_predictions AS prediction "
            "JOIN model_runs AS run ON run.id = prediction.model_run_id "
            "WHERE prediction.game_id = ? AND run.model_name = ? AND run.model_version = ? "
            "AND run.status = 'completed' "
            "AND julianday(prediction.generated_at) <= julianday(?) "
            "ORDER BY julianday(prediction.generated_at) DESC, prediction.id DESC LIMIT 1",
            (
                game_id,
                policy.production_model_name,
                policy.production_model_version,
                evaluated_at_value,
            ),
        ).fetchone()
        if prediction_row is None:
            continue
        prior_row = conn.execute(
            f"SELECT {_qualified(_EVALUATION_COLUMNS, 'evaluation')} "
            "FROM sportsbook_recommendation_evaluations AS evaluation "
            "JOIN sportsbook_market_offers AS prior_offer "
            "ON prior_offer.id = evaluation.market_offer_id "
            "WHERE evaluation.policy_id = ? AND prior_offer.game_id = ? "
            "AND prior_offer.bookmaker = ? "
            "AND NOT EXISTS (SELECT 1 FROM sportsbook_recommendation_evaluations AS newer "
            "WHERE newer.supersedes_evaluation_id = evaluation.id) "
            "ORDER BY evaluation.id DESC LIMIT 1",
            (policy.id, game_id, bookmaker),
        ).fetchone()
        prior = (
            SportsbookRecommendationEvaluation(*prior_row)
            if prior_row is not None
            else None
        )
        prior_offer = (
            get_sportsbook_market_offer(conn, prior.market_offer_id)
            if prior is not None
            else None
        )
        current_is_stale = (
            _utc(evaluated_at_value) - _utc(offer.observed_at)
        ).total_seconds() > policy.maximum_odds_age_seconds
        if prior is not None and prior_offer is not None:
            if offer.id == prior_offer.id:
                if prior.lifecycle_state == "expired" or not current_is_stale:
                    results.append(prior)
                    continue
            elif (
                bookmaker.strip().casefold() != DRAFTKINGS_BOOKMAKER
                and not _is_material_update(prior_offer, offer, policy)
            ):
                results.append(prior)
                continue
        evaluation = evaluate_sportsbook_offer(
            conn,
            market_offer_id=offer.id,
            model_prediction_id=int(prediction_row[0]),
            policy_id=policy.id,
            evaluated_at=_utc(evaluated_at_value),
            provenance=provenance,
            supersedes_evaluation_id=prior.id if prior is not None else None,
        )
        results.append(evaluation)
    return tuple(results)


def list_current_live_sportsbook_board(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    policy_id: int,
) -> tuple[SportsbookRecommendationEvaluation, ...]:
    rows = conn.execute(
        f"SELECT {_qualified(_EVALUATION_COLUMNS, 'evaluation')} "
        "FROM sportsbook_recommendation_evaluations AS evaluation "
        "JOIN sportsbook_market_offers AS offer ON offer.id = evaluation.market_offer_id "
        "JOIN games AS game ON game.game_id = offer.game_id "
        "WHERE game.season = ? AND game.week = ? AND evaluation.policy_id = ? "
        "AND NOT EXISTS (SELECT 1 FROM sportsbook_recommendation_evaluations AS newer "
        "WHERE newer.supersedes_evaluation_id = evaluation.id) "
        "ORDER BY game.start_date, offer.game_id, offer.bookmaker",
        (season, week, policy_id),
    ).fetchall()
    return tuple(SportsbookRecommendationEvaluation(*row) for row in rows)


def _draftkings_capture_run(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    provider_ingestion_run_ids: tuple[int, ...],
) -> tuple[int, str, str, str, bool] | None:
    if provider_ingestion_run_ids:
        placeholders = ",".join("?" for _ in provider_ingestion_run_ids)
        rows = conn.execute(
            "SELECT id, request_parameters, requested_at, status, raw_payload_reference "
            f"FROM provider_ingestion_runs WHERE id IN ({placeholders}) "
            "AND data_type = 'odds' ORDER BY julianday(requested_at) DESC, id DESC",
            provider_ingestion_run_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, request_parameters, requested_at, status, raw_payload_reference "
            "FROM provider_ingestion_runs WHERE data_type = 'odds' "
            "AND json_extract(request_parameters, '$.season') = ? "
            "AND json_extract(request_parameters, '$.week') = ? "
            "ORDER BY julianday(requested_at) DESC, id DESC",
            (season, week),
        ).fetchall()
    for run_id, parameters, requested_at, status, raw_reference in rows:
        try:
            request = json.loads(str(parameters))
        except (TypeError, ValueError):
            request = {}
        requested_books = request.get("bookmakers", "")
        if isinstance(requested_books, list):
            books = {str(book).strip().casefold() for book in requested_books}
        else:
            books = {
                book.strip().casefold()
                for book in str(requested_books).split(",")
                if book.strip()
            }
        has_snapshot = conn.execute(
            "SELECT 1 FROM provider_market_snapshots "
            "WHERE ingestion_run_id = ? AND lower(trim(bookmaker)) = ? LIMIT 1",
            (int(run_id), DRAFTKINGS_BOOKMAKER),
        ).fetchone()
        attempted = DRAFTKINGS_BOOKMAKER in books or has_snapshot is not None
        return (
            int(run_id),
            str(requested_at),
            str(status),
            str(raw_reference),
            attempted,
        )
    return None


def build_draftkings_betting_board(
    conn: sqlite3.Connection,
    *,
    contest_id: int,
    policy_id: int,
    season: int,
    week: int,
    provider_ingestion_run_ids: tuple[int, ...] = (),
) -> tuple[DraftKingsBettingBoardRow, ...]:
    """Return one explicit DraftKings row for every immutable contest-line game."""
    contest_id = integer(contest_id, "contest_id", 1)
    policy = get_sportsbook_recommendation_policy(conn, policy_id)
    season = integer(season, "season", 1869)
    week = integer(week, "week")
    run = _draftkings_capture_run(
        conn,
        season=season,
        week=week,
        provider_ingestion_run_ids=provider_ingestion_run_ids,
    )
    games = conn.execute(
        "SELECT locked.game_id, game.away_team, game.home_team "
        "FROM contest_locked_lines AS locked "
        "JOIN games AS game ON game.game_id = locked.game_id "
        "WHERE locked.contest_id = ? ORDER BY game.start_date, locked.game_id",
        (contest_id,),
    ).fetchall()
    result: list[DraftKingsBettingBoardRow] = []
    for game_id_value, away_team, home_team in games:
        game_id = int(game_id_value)
        game_label = f"{away_team} at {home_team}"
        run_id = None if run is None else run[0]
        observed_at = "NOT_ATTEMPTED" if run is None else run[1]
        capture_attempted = False if run is None else run[4]
        offer_row = None
        if run_id is not None and capture_attempted:
            offer_row = conn.execute(
                f"SELECT {_qualified(_OFFER_COLUMNS, 'offer')} "
                "FROM provider_market_snapshots AS snapshot "
                "JOIN sportsbook_market_offers AS offer "
                "ON offer.provider_market_snapshot_id = snapshot.id "
                "WHERE snapshot.ingestion_run_id = ? AND snapshot.game_id = ? "
                "AND lower(trim(snapshot.bookmaker)) = ? "
                "AND lower(trim(offer.bookmaker)) = ? "
                "AND offer.line_type IN ('opening', 'current') "
                "ORDER BY julianday(offer.observed_at) DESC, offer.id DESC LIMIT 1",
                (run_id, game_id, DRAFTKINGS_BOOKMAKER, DRAFTKINGS_BOOKMAKER),
            ).fetchone()
        if offer_row is None:
            if run is None or not capture_attempted:
                state = "CAPTURE_NOT_ATTEMPTED"
                reason = "DRAFTKINGS_CAPTURE_NOT_ATTEMPTED"
            elif run[2] not in ("completed", "partial", "empty"):
                state = "PROVIDER_UNAVAILABLE"
                reason = f"DRAFTKINGS_CAPTURE_{run[2].upper()}"
            else:
                state = "PROVIDER_UNAVAILABLE"
                reason = "DRAFTKINGS_SPREAD_NOT_RETURNED"
            provenance = (
                "draftkings-capture:not-attempted"
                if run is None
                else f"provider-ingestion-run:{run[0]};raw-payload:{run[3]}"
            )
            result.append(
                DraftKingsBettingBoardRow(
                    game_id=game_id,
                    game=game_label,
                    selected_team=None,
                    selected_side=None,
                    decision="DRAFTKINGS_UNAVAILABLE",
                    bookmaker="DraftKings",
                    offered_spread=None,
                    offered_price=None,
                    offer_captured_at=None,
                    observation_timestamp=observed_at,
                    model_fair_spread=None,
                    spread_edge_points=None,
                    estimated_cover_probability=None,
                    break_even_probability=None,
                    expected_value=None,
                    stake_units=0.0,
                    policy_version=policy.policy_version,
                    reason_code=reason,
                    freshness="UNAVAILABLE",
                    availability_state=state,
                    provider_capture_attempted=capture_attempted,
                    provider_ingestion_run_id=run_id,
                    provider_market_snapshot_id=None,
                    market_offer_id=None,
                    evaluation_id=None,
                    provenance=provenance,
                )
            )
            continue
        offer = SportsbookMarketOffer(*offer_row)
        evaluation_row = conn.execute(
            f"SELECT {_EVALUATION_COLUMNS} "
            "FROM sportsbook_recommendation_evaluations "
            "WHERE policy_id = ? AND market_offer_id = ? ORDER BY id DESC LIMIT 1",
            (policy.id, offer.id),
        ).fetchone()
        if evaluation_row is None:
            result.append(
                DraftKingsBettingBoardRow(
                    game_id=game_id,
                    game=game_label,
                    selected_team=None,
                    selected_side=None,
                    decision="DRAFTKINGS_UNAVAILABLE",
                    bookmaker="DraftKings",
                    offered_spread=None,
                    offered_price=None,
                    offer_captured_at=offer.observed_at,
                    observation_timestamp=offer.observed_at,
                    model_fair_spread=None,
                    spread_edge_points=None,
                    estimated_cover_probability=None,
                    break_even_probability=None,
                    expected_value=None,
                    stake_units=0.0,
                    policy_version=policy.policy_version,
                    reason_code="DRAFTKINGS_EVALUATION_MISSING",
                    freshness="UNAVAILABLE",
                    availability_state="EVALUATION_MISSING",
                    provider_capture_attempted=True,
                    provider_ingestion_run_id=run_id,
                    provider_market_snapshot_id=offer.provider_market_snapshot_id,
                    market_offer_id=offer.id,
                    evaluation_id=None,
                    provenance=(
                        f"provider-ingestion-run:{run_id};market-offer:{offer.id};"
                        f"provider-market-snapshot:{offer.provider_market_snapshot_id}"
                    ),
                )
            )
            continue
        evaluation = SportsbookRecommendationEvaluation(*evaluation_row)
        result.append(
            DraftKingsBettingBoardRow(
                game_id=game_id,
                game=game_label,
                selected_team=evaluation.selected_team,
                selected_side=evaluation.selected_side,
                decision=evaluation.decision.upper(),
                bookmaker="DraftKings",
                offered_spread=evaluation.offered_spread,
                offered_price=evaluation.offered_price,
                offer_captured_at=evaluation.captured_at,
                observation_timestamp=evaluation.captured_at,
                model_fair_spread=evaluation.model_fair_spread,
                spread_edge_points=evaluation.spread_edge_points,
                estimated_cover_probability=evaluation.estimated_cover_probability,
                break_even_probability=evaluation.break_even_probability,
                expected_value=evaluation.expected_value,
                stake_units=evaluation.stake_units,
                policy_version=evaluation.policy_version,
                reason_code=evaluation.reason_code,
                freshness=(
                    "STALE" if evaluation.lifecycle_state == "expired" else "CURRENT"
                ),
                availability_state="AVAILABLE",
                provider_capture_attempted=True,
                provider_ingestion_run_id=run_id,
                provider_market_snapshot_id=offer.provider_market_snapshot_id,
                market_offer_id=offer.id,
                evaluation_id=evaluation.id,
                provenance=evaluation.provenance,
            )
        )
    return tuple(result)
