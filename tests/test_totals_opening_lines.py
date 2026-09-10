import sqlite3

import pytest

from models.totals_opening_lines import (
    HistoricalTotalsLineError,
    TOTALS_BOOK_PRIORITY_POLICY_VERSION,
    UNVERIFIED_ARCHIVAL_OPENING,
    get_historical_opening_total,
)


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE betting_lines ("
        "id INTEGER PRIMARY KEY, game_id INTEGER, book TEXT, home_spread REAL, "
        "total REAL, line_type TEXT, source TEXT, fetched_at TEXT)"
    )
    return conn


def _line(conn, row_id, game_id, book, spread, total):
    conn.execute(
        "INSERT INTO betting_lines VALUES (?, ?, ?, ?, ?, 'opening', "
        "'cfbd_historical_lines', '2026-07-29T20:51:47.452630')",
        (row_id, game_id, book, spread, total),
    )


def test_totals_resolver_uses_total_availability_not_spread_availability():
    conn = _connection()
    _line(conn, 1, 10, "Bovada", None, 52.5)

    selected = get_historical_opening_total(conn, 10)

    assert selected is not None
    assert selected.total == 52.5
    assert selected.book == "Bovada"
    assert selected.archive_ingested_at == "2026-07-29T20:51:47.452630"
    assert selected.market_observed_at is None
    assert selected.original_quote_at is None
    assert selected.quote_time_custody_status == UNVERIFIED_ARCHIVAL_OPENING
    conn.close()


def test_totals_resolver_obeys_versioned_priority_not_alphabetical_order():
    conn = _connection()
    _line(conn, 1, 10, "Aardvark Sports", -3.0, 60.0)
    _line(conn, 2, 10, "ESPN Bet", -3.0, 59.0)
    _line(conn, 3, 10, "DraftKings", -3.0, 58.0)
    _line(conn, 4, 10, "Bovada", -3.0, 57.0)

    selected = get_historical_opening_total(conn, 10)

    assert selected is not None
    assert (selected.book, selected.total) == ("Bovada", 57.0)
    assert selected.book_priority_policy_version == TOTALS_BOOK_PRIORITY_POLICY_VERSION
    conn.close()


def test_totals_resolver_uses_next_priority_book_when_higher_book_has_no_total():
    conn = _connection()
    _line(conn, 1, 10, "Bovada", -3.0, None)
    _line(conn, 2, 10, "DraftKings", -3.0, 55.0)

    selected = get_historical_opening_total(conn, 10)

    assert selected is not None
    assert (selected.book, selected.total) == ("DraftKings", 55.0)
    conn.close()


def test_totals_resolver_rejects_unknown_only_book_instead_of_falling_back():
    conn = _connection()
    _line(conn, 1, 10, "Aardvark Sports", -3.0, 60.0)

    with pytest.raises(HistoricalTotalsLineError, match="outside"):
        get_historical_opening_total(conn, 10)
    conn.close()


def test_totals_resolver_rejects_duplicate_priority_book_rows():
    conn = _connection()
    _line(conn, 1, 10, "Bovada", -3.0, 52.0)
    _line(conn, 2, 10, "Bovada", -3.5, 52.5)

    with pytest.raises(HistoricalTotalsLineError, match="duplicate"):
        get_historical_opening_total(conn, 10)
    conn.close()


def test_totals_resolver_returns_none_when_no_opening_total_exists():
    conn = _connection()
    _line(conn, 1, 10, "Bovada", -3.0, None)

    assert get_historical_opening_total(conn, 10) is None
    conn.close()
