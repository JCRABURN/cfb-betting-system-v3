"""Pure, replayable Week 5 postgame grading calculations."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from math import sqrt
from typing import Iterable


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def result_from_margin(margin: Decimal) -> str:
    return "WIN" if margin > 0 else "LOSS" if margin < 0 else "PUSH"


def grade_ats(side: str, locked_home_spread: object, actual_home_margin: int) -> tuple[str, Decimal]:
    """Grade against the immutable home spread; away is its exact inverse."""
    if side not in {"home", "away"}:
        raise ValueError("ATS side must be home or away")
    home_cover_margin = _d(actual_home_margin) + _d(locked_home_spread)
    selected_margin = home_cover_margin if side == "home" else -home_cover_margin
    return result_from_margin(selected_margin), selected_margin


def grade_total(pick: str, locked_total: object, actual_total: int) -> tuple[str, Decimal]:
    if pick not in {"over", "under"}:
        raise ValueError("total pick must be over or under")
    over_margin = _d(actual_total) - _d(locked_total)
    selected_margin = over_margin if pick == "over" else -over_margin
    return result_from_margin(selected_margin), selected_margin


def clv_ats(side: str, locked_home_spread: object, closing_home_spread: object) -> Decimal:
    """Positive means the selected locked spread beats the closing spread."""
    if side not in {"home", "away"}:
        raise ValueError("ATS side must be home or away")
    difference = _d(locked_home_spread) - _d(closing_home_spread)
    return difference if side == "home" else -difference


def clv_total(pick: str, locked_total: object, closing_total: object) -> Decimal:
    if pick not in {"over", "under"}:
        raise ValueError("total pick must be over or under")
    difference = _d(closing_total) - _d(locked_total)
    return difference if pick == "over" else -difference


def hook_key_classification(selected_spread: object, actual_margin: int, grading_margin: object) -> dict[str, str]:
    """Flag only a boundary that the actual final margin makes determinative."""
    spread = _d(selected_spread)
    margin = _d(grading_margin)
    has_half = abs(spread) % 1 == Decimal("0.5")
    hook = (
        "HOOK_WIN" if margin == Decimal("0.5") else
        "HOOK_LOSS" if margin == Decimal("-0.5") else
        "NOT_APPLICABLE"
    ) if has_half else "NOT_APPLICABLE"
    key_number = abs(actual_margin) if abs(actual_margin) in {3, 7} else None
    key = (
        "KEY_NUMBER_WIN" if margin > 0 else
        "KEY_NUMBER_LOSS" if margin < 0 else
        "NOT_APPLICABLE"
    ) if key_number is not None and abs(margin) <= 1 else "NOT_APPLICABLE"
    return {
        "hook_classification": hook,
        "key_number_classification": key,
        "key_number": str(key_number or ""),
        "one_point_boundary": str(abs(margin) == 1),
    }


def record(results: Iterable[str]) -> dict[str, object]:
    counts = Counter(results)
    wins, losses, pushes = (counts[value] for value in ("WIN", "LOSS", "PUSH"))
    n = wins + losses + pushes
    units = wins * (100 / 110) - losses
    return {
        "n": n,
        "win": wins,
        "loss": losses,
        "push": pushes,
        "win_rate_ex_push": wins / (wins + losses) if wins + losses else None,
        "units_minus110": round(units, 6),
        "roi_minus110": round(units / n, 6) if n else None,
    }


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    mx, my = sum(x) / len(x), sum(y) / len(y)
    dx, dy = [v - mx for v in x], [v - my for v in y]
    denominator = sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return round(sum(a * b for a, b in zip(dx, dy)) / denominator, 6) if denominator else None


def spread_bucket(value: object) -> str:
    n = abs(_d(value))
    if n <= Decimal("2.5"):
        return "0-2.5"
    if n <= Decimal("6.5"):
        return "3-6.5"
    if n <= Decimal("13.5"):
        return "7-13.5"
    if n <= Decimal("20.5"):
        return "14-20.5"
    return "21+"


def edge_bucket(value: object) -> str:
    n = abs(_d(value))
    if n < 3:
        return "<3"
    if n < 5:
        return "3-4.9"
    if n < 7:
        return "5-6.9"
    if n < 10:
        return "7-9.9"
    return "10+"


def classify_late_score(
    plays: list[dict[str, object]], side: str, locked_home_spread: object,
    final_away_score: int, final_home_score: int,
) -> dict[str, str]:
    """Classify late selected-team scores using complete play-by-play and locked ATS margin."""
    empty = {"decisive_score": "", "game_clock": "", "period": "",
             "score_before_late_play": "", "score_after_late_play": ""}
    if not plays or (int(plays[-1]["awayScore"]), int(plays[-1]["homeScore"])) != (final_away_score, final_home_score):
        return {"classification": "NOT_EVALUATED_NO_PBP", **empty}
    final_result, _ = grade_ats(side, locked_home_spread, final_home_score - final_away_score)
    selected_spread = _d(locked_home_spread) if side == "home" else -_d(locked_home_spread)
    selected_lost_game = (final_home_score < final_away_score) if side == "home" else (final_away_score < final_home_score)
    previous_away = previous_home = 0
    late_plays: list[tuple[dict[str, object], str, str, Decimal, Decimal, int, int]] = []
    for play in plays:
        away = int(play["awayScore"])
        home = int(play["homeScore"])
        period = int(play["period"]["number"])
        clock = float(play["clock"]["value"])
        if period > 4 or (period == 4 and clock <= 300):
            before, before_margin = grade_ats(side, locked_home_spread, previous_home - previous_away)
            after, after_margin = grade_ats(side, locked_home_spread, home - away)
            late_plays.append((play, before, after, before_margin, after_margin, previous_away, previous_home))
        previous_away, previous_home = away, home
    if not late_plays:
        return {"classification": "NOT_APPLICABLE", **empty}
    for play, before, after, before_margin, after_margin, prior_away, prior_home in reversed(late_plays):
        away, home = int(play["awayScore"]), int(play["homeScore"])
        selected_scored = (home > prior_home) if side == "home" else (away > prior_away)
        selected_trailing = (prior_home < prior_away) if side == "home" else (prior_away < prior_home)
        if not selected_scored:
            continue
        if before != "WIN" and after == final_result == "WIN":
            classification = "BACKDOOR_COVER" if selected_trailing and selected_lost_game else "LATE_FRONTDOOR_COVER"
        elif selected_spread > 0 and selected_trailing and after_margin > before_margin and final_result == "LOSS":
            classification = "BACKDOOR_FAILURE"
        else:
            continue
        return {
            "classification": classification,
            "decisive_score": str(play.get("text", "")),
            "game_clock": str(play["clock"].get("displayValue", "")),
            "period": str(play["period"]["number"]),
            "score_before_late_play": f"{prior_away}-{prior_home}",
            "score_after_late_play": f"{away}-{home}",
        }
    return {"classification": "LATE_SCORE_NONDETERMINATIVE", **empty}
