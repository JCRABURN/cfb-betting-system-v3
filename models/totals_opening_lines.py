"""Governed historical opening-total selection for totals research only.

The legacy ATS accessor is deliberately not changed here.  Historical totals
research requires a non-null total and selects a real book through one frozen,
versioned priority.  The historical CFBD archive does not carry an original
quote timestamp, so ``fetched_at`` is preserved only as the archive ingestion
time and the quote-time status remains explicitly unverified.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


TOTALS_BOOK_PRIORITY_POLICY_VERSION = "historical-totals-book-priority-v1"
TOTALS_BOOK_PRIORITY = ("Bovada", "DraftKings", "ESPN Bet")
UNVERIFIED_ARCHIVAL_OPENING = "UNVERIFIED_ARCHIVAL_OPENING"


class HistoricalTotalsLineError(ValueError):
    """Raised when historical total-line custody is ambiguous or unsupported."""


@dataclass(frozen=True)
class HistoricalOpeningTotal:
    betting_line_id: int
    game_id: int
    total: float
    book: str
    source: str
    archive_ingested_at: str
    market_observed_at: str | None
    original_quote_at: str | None
    quote_time_custody_status: str
    book_priority_policy_version: str


def get_historical_opening_total(
    conn: sqlite3.Connection, game_id: int
) -> HistoricalOpeningTotal | None:
    """Resolve one opening total without consulting spread availability.

    Unknown books are never selected as an implicit alphabetical fallback.  A
    game with only out-of-policy books is rejected so the priority must be
    explicitly versioned before that data can enter a research ledger.
    """
    rows = conn.execute(
        "SELECT id, game_id, total, book, source, fetched_at "
        "FROM betting_lines WHERE game_id = ? AND line_type = 'opening' "
        "AND total IS NOT NULL ORDER BY id",
        (game_id,),
    ).fetchall()
    if not rows:
        return None

    by_book: dict[str, list[tuple[object, ...]]] = {}
    for row in rows:
        by_book.setdefault(str(row[3]), []).append(row)
    for book in TOTALS_BOOK_PRIORITY:
        candidates = by_book.get(book, [])
        if len(candidates) > 1:
            raise HistoricalTotalsLineError(
                f"game {game_id} has duplicate opening totals for priority book {book}"
            )
        if candidates:
            row = candidates[0]
            return HistoricalOpeningTotal(
                betting_line_id=int(row[0]),
                game_id=int(row[1]),
                total=float(row[2]),
                book=str(row[3]),
                source=str(row[4]),
                archive_ingested_at=str(row[5]),
                market_observed_at=None,
                original_quote_at=None,
                quote_time_custody_status=UNVERIFIED_ARCHIVAL_OPENING,
                book_priority_policy_version=TOTALS_BOOK_PRIORITY_POLICY_VERSION,
            )

    available = ", ".join(sorted(by_book))
    raise HistoricalTotalsLineError(
        f"game {game_id} has opening totals only from books outside "
        f"{TOTALS_BOOK_PRIORITY_POLICY_VERSION}: {available}"
    )
