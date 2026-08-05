from datetime import datetime, timezone
import sqlite3

import pytest

from contest_lines import (
    ContestConflictError,
    ContestLineError,
    LineAlreadyLockedError,
    LineCorrectionError,
    correct_locked_line,
    create_contest,
    get_effective_locked_line,
    get_original_locked_line,
    list_line_corrections,
    lock_contest_line,
)


CAPTURED_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
CORRECTED_AT = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)
PAYLOAD_A = "a" * 64
PAYLOAD_B = "b" * 64
PAYLOAD_C = "c" * 64


def _insert_game(conn, game_id=101, home="Georgia", away="Clemson"):
    conn.execute(
        "INSERT INTO games (game_id, season, week, home_team, away_team) "
        "VALUES (?, 2026, 1, ?, ?)",
        (game_id, home, away),
    )
    conn.commit()


def _contest(conn):
    return create_contest(
        conn,
        contest_key="splashsports-weekly",
        name="SplashSports College Football Week 1",
        season=2026,
        week=1,
        source="splashsports",
        source_contest_id="contest-2026-01",
        provenance="fixture://splashsports/2026/week-1/card.csv",
        created_at=CAPTURED_AT,
    )


def _lock(conn, *, contest_id, game_id=101, home_spread=-3.5):
    return lock_contest_line(
        conn,
        contest_id=contest_id,
        game_id=game_id,
        raw_home_team="Georgia Bulldogs",
        raw_away_team="Clemson Tigers",
        normalized_home_team="Georgia",
        normalized_away_team="Clemson",
        home_spread=home_spread,
        source="splashsports",
        source_line_id="line-101",
        provenance="fixture://splashsports/2026/week-1/card.csv#game-101",
        payload_sha256=PAYLOAD_A,
        locked_at=CAPTURED_AT,
    )


def test_lock_preserves_identity_provenance_and_market_separation(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    contest = _contest(conn)
    result = _lock(conn, contest_id=contest.id)

    assert result.created is True
    assert result.line.season == 2026
    assert result.line.week == 1
    assert result.line.raw_home_team == "Georgia Bulldogs"
    assert result.line.raw_away_team == "Clemson Tigers"
    assert result.line.normalized_home_team == "Georgia"
    assert result.line.normalized_away_team == "Clemson"
    assert result.line.locked_at == "2026-08-25T15:30:00+00:00"
    assert result.line.source == "splashsports"
    assert result.line.payload_sha256 == PAYLOAD_A
    assert conn.execute("SELECT COUNT(*) FROM betting_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 1
    conn.close()


def test_identical_lock_replay_is_idempotent_but_changed_relock_is_rejected(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    contest = _contest(conn)
    first = _lock(conn, contest_id=contest.id)
    replay = _lock(conn, contest_id=contest.id)

    assert replay.created is False
    assert replay.line == first.line
    with pytest.raises(LineAlreadyLockedError, match="record a correction"):
        _lock(conn, contest_id=contest.id, home_spread=-4.0)
    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 1
    conn.close()


def test_raw_sql_cannot_update_delete_or_replace_a_locked_line(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    line = _lock(conn, contest_id=_contest(conn).id).line

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE contest_locked_lines SET home_spread = -7 WHERE id = ?",
            (line.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute("DELETE FROM contest_locked_lines WHERE id = ?", (line.id,))
    with pytest.raises(sqlite3.IntegrityError, match="already locked"):
        conn.execute(
            "INSERT OR REPLACE INTO contest_locked_lines "
            "SELECT id, contest_id, game_id, season, week, raw_home_team, raw_away_team, "
            "normalized_home_team, normalized_away_team, -7, total, locked_at, source, "
            "source_line_id, provenance, payload_sha256 "
            "FROM contest_locked_lines WHERE id = ?",
            (line.id,),
        )

    original = get_original_locked_line(conn, line.id)
    assert original.home_spread == -3.5
    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 1
    conn.close()


def test_corrections_append_full_snapshots_and_never_change_the_original(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    original = _lock(conn, contest_id=_contest(conn).id).line

    first = correct_locked_line(
        conn,
        original.id,
        home_spread=-4.0,
        reason="Contest operator corrected the displayed spread.",
        author="operations@example.test",
        source="splashsports",
        source_line_id="correction-101-a",
        provenance="fixture://splashsports/2026/week-1/correction-a.csv",
        payload_sha256=PAYLOAD_B,
        corrected_at=CORRECTED_AT,
    )
    second = correct_locked_line(
        conn,
        original.id,
        total=51.5,
        reason="Contest operator added the omitted total.",
        author="operations@example.test",
        source="splashsports",
        source_line_id="correction-101-b",
        provenance="fixture://splashsports/2026/week-1/correction-b.csv",
        payload_sha256=PAYLOAD_C,
        corrected_at=datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc),
    )

    assert first.sequence == 1
    assert first.supersedes_correction_id is None
    assert second.sequence == 2
    assert second.supersedes_correction_id == first.id
    assert second.home_spread == -4.0
    assert second.total == 51.5
    assert get_original_locked_line(conn, original.id).home_spread == -3.5
    effective = get_effective_locked_line(conn, original.id)
    assert effective.home_spread == -4.0
    assert effective.total == 51.5
    assert effective.correction_id == second.id
    assert effective.correction_sequence == 2
    assert list_line_corrections(conn, original.id) == (first, second)
    conn.close()


def test_raw_sql_cannot_rewrite_delete_replace_or_skip_correction_history(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    line = _lock(conn, contest_id=_contest(conn).id).line
    correction = correct_locked_line(
        conn,
        line.id,
        home_spread=-4.0,
        reason="Documented source correction.",
        author="operations@example.test",
        source="splashsports",
        provenance="fixture://correction.csv",
        payload_sha256=PAYLOAD_B,
        corrected_at=CORRECTED_AT,
    )

    with pytest.raises(sqlite3.IntegrityError, match="corrections are immutable"):
        conn.execute(
            "UPDATE contest_line_corrections SET home_spread = -9 WHERE id = ?",
            (correction.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute(
            "DELETE FROM contest_line_corrections WHERE id = ?", (correction.id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="correction"):
        conn.execute(
            "INSERT OR REPLACE INTO contest_line_corrections "
            "SELECT id, locked_line_id, sequence, supersedes_correction_id, game_id, "
            "raw_home_team, raw_away_team, normalized_home_team, normalized_away_team, "
            "-9, total, reason, author, corrected_at, source, source_line_id, provenance, "
            "payload_sha256 FROM contest_line_corrections WHERE id = ?",
            (correction.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="correction"):
        conn.execute(
            "INSERT INTO contest_line_corrections "
            "(locked_line_id, sequence, game_id, raw_home_team, raw_away_team, "
            "normalized_home_team, normalized_away_team, home_spread, reason, author, "
            "corrected_at, source, provenance, payload_sha256) "
            "SELECT locked_line_id, 3, game_id, raw_home_team, raw_away_team, "
            "normalized_home_team, normalized_away_team, home_spread, reason, author, "
            "corrected_at, source, provenance, payload_sha256 "
            "FROM contest_line_corrections WHERE id = ?",
            (correction.id,),
        )
    assert list_line_corrections(conn, line.id) == (correction,)
    conn.close()


def test_contest_identity_is_immutable_and_conflicting_replay_fails(temp_db):
    conn = temp_db.get_connection()
    contest = _contest(conn)
    replay = _contest(conn)
    assert replay == contest

    with pytest.raises(ContestConflictError, match="different immutable metadata"):
        create_contest(
            conn,
            contest_key=contest.contest_key,
            name="Renamed contest",
            season=contest.season,
            week=contest.week,
            source=contest.source,
            source_contest_id=contest.source_contest_id,
            provenance=contest.provenance,
        )
    with pytest.raises(sqlite3.IntegrityError, match="contests are immutable"):
        conn.execute("UPDATE contests SET week = 2 WHERE id = ?", (contest.id,))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute("DELETE FROM contests WHERE id = ?", (contest.id,))
    conn.close()


def test_game_identity_and_reversed_matchup_duplicates_are_rejected(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    contest = _contest(conn)

    with pytest.raises(ContestLineError, match="does not match"):
        lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=101,
            raw_home_team="Clemson Tigers",
            raw_away_team="Georgia Bulldogs",
            normalized_home_team="Clemson",
            normalized_away_team="Georgia",
            home_spread=3.5,
            source="splashsports",
            provenance="fixture://bad-orientation.csv",
            payload_sha256=PAYLOAD_A,
            locked_at=CAPTURED_AT,
        )

    first = _lock(conn, contest_id=contest.id, game_id=None)
    with pytest.raises(LineAlreadyLockedError, match="already locked"):
        lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=None,
            raw_home_team="Clemson Tigers",
            raw_away_team="Georgia Bulldogs",
            normalized_home_team="Clemson",
            normalized_away_team="Georgia",
            home_spread=3.5,
            source="splashsports",
            provenance="fixture://reversed.csv",
            payload_sha256=PAYLOAD_B,
            locked_at=CAPTURED_AT,
        )
    assert first.created is True
    conn.close()


def test_unresolved_lock_can_be_corrected_to_a_verified_game_id(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    line = _lock(conn, contest_id=_contest(conn).id, game_id=None).line

    correction = correct_locked_line(
        conn,
        line.id,
        game_id=101,
        reason="Resolved the provider matchup to the canonical game.",
        author="normalization@example.test",
        source="splashsports",
        provenance="fixture://resolved-matchup.csv",
        payload_sha256=PAYLOAD_B,
        corrected_at=CORRECTED_AT,
    )

    assert line.game_id is None
    assert correction.game_id == 101
    assert get_effective_locked_line(conn, line.id).game_id == 101
    conn.close()


def test_corrected_matchups_cannot_collide_or_be_relocked(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    _insert_game(conn, game_id=202, home="Alabama", away="Auburn")
    contest = _contest(conn)
    georgia_line = _lock(conn, contest_id=contest.id).line
    alabama_line = lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=202,
        raw_home_team="Alabama Crimson Tide",
        raw_away_team="Auburn Tigers",
        normalized_home_team="Alabama",
        normalized_away_team="Auburn",
        home_spread=-7.0,
        source="splashsports",
        provenance="fixture://card.csv#game-202",
        payload_sha256=PAYLOAD_A,
        locked_at=CAPTURED_AT,
    ).line

    with pytest.raises(LineCorrectionError, match="conflicts with another"):
        correct_locked_line(
            conn,
            alabama_line.id,
            game_id=101,
            raw_home_team="Georgia Bulldogs",
            raw_away_team="Clemson Tigers",
            normalized_home_team="Georgia",
            normalized_away_team="Clemson",
            home_spread=-3.5,
            reason="Invalid duplicate correction fixture.",
            author="operations@example.test",
            source="splashsports",
            provenance="fixture://duplicate-correction.csv",
            payload_sha256=PAYLOAD_B,
            corrected_at=CORRECTED_AT,
        )

    correction = correct_locked_line(
        conn,
        alabama_line.id,
        game_id=None,
        raw_home_team="Florida Gators",
        raw_away_team="Florida State Seminoles",
        normalized_home_team="Florida",
        normalized_away_team="Florida State",
        reason="Provider initially attached the line to the wrong matchup.",
        author="operations@example.test",
        source="splashsports",
        provenance="fixture://identity-correction.csv",
        payload_sha256=PAYLOAD_C,
        corrected_at=CORRECTED_AT,
    )
    assert correction.sequence == 1

    with pytest.raises(LineCorrectionError, match="conflicts with another"):
        correct_locked_line(
            conn,
            georgia_line.id,
            game_id=202,
            raw_home_team="Alabama Crimson Tide",
            raw_away_team="Auburn Tigers",
            normalized_home_team="Alabama",
            normalized_away_team="Auburn",
            home_spread=-7.0,
            reason="Invalid reuse of another line's original matchup.",
            author="operations@example.test",
            source="splashsports",
            provenance="fixture://original-identity-collision.csv",
            payload_sha256=PAYLOAD_B,
            corrected_at=datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc),
        )

    with pytest.raises(LineAlreadyLockedError, match="already locked"):
        lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=None,
            raw_home_team="Florida Gators",
            raw_away_team="Florida State Seminoles",
            normalized_home_team="Florida",
            normalized_away_team="Florida State",
            home_spread=-2.5,
            source="splashsports",
            provenance="fixture://relock-corrected-identity.csv",
            payload_sha256=PAYLOAD_B,
            locked_at=CAPTURED_AT,
        )
    assert get_original_locked_line(conn, georgia_line.id).home_spread == -3.5
    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 2
    conn.close()


def test_market_table_accepts_only_opening_current_and_closing(temp_db):
    conn = temp_db.get_connection()
    for index, line_type in enumerate(("opening", "current", "closing"), start=1):
        conn.execute(
            "INSERT INTO betting_lines "
            "(season, week, home_team, away_team, book, home_spread, line_type, source, "
            "fetched_at) VALUES (2026, 1, 'A', 'B', ?, -3, ?, 'fixture', 'now')",
            (f"book-{index}", line_type),
        )
    with pytest.raises(sqlite3.IntegrityError, match="only opening, current, or closing"):
        conn.execute(
            "INSERT INTO betting_lines "
            "(season, week, home_team, away_team, book, home_spread, line_type, source, "
            "fetched_at) VALUES (2026, 1, 'A', 'B', 'contest', -3, 'locked', "
            "'fixture', 'now')"
        )
    with pytest.raises(sqlite3.IntegrityError, match="only opening, current, or closing"):
        conn.execute("UPDATE betting_lines SET line_type = 'locked' WHERE book = 'book-1'")
    assert conn.execute("SELECT COUNT(*) FROM betting_lines").fetchone()[0] == 3
    conn.close()


def test_invalid_capture_metadata_and_noop_correction_are_rejected(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn)
    contest = _contest(conn)
    with pytest.raises(ContestLineError, match="64 hexadecimal"):
        lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=101,
            raw_home_team="Georgia Bulldogs",
            raw_away_team="Clemson Tigers",
            normalized_home_team="Georgia",
            normalized_away_team="Clemson",
            home_spread=-3.5,
            source="splashsports",
            provenance="fixture://card.csv",
            payload_sha256="not-a-checksum",
        )
    with pytest.raises(ContestLineError, match="timezone-aware"):
        lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=101,
            raw_home_team="Georgia Bulldogs",
            raw_away_team="Clemson Tigers",
            normalized_home_team="Georgia",
            normalized_away_team="Clemson",
            home_spread=-3.5,
            source="splashsports",
            provenance="fixture://card.csv",
            payload_sha256=PAYLOAD_A,
            locked_at=datetime(2026, 8, 25, 15, 30),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        conn.execute(
            "INSERT INTO contest_locked_lines "
            "(contest_id, game_id, season, week, raw_home_team, raw_away_team, "
            "normalized_home_team, normalized_away_team, home_spread, locked_at, "
            "source, provenance, payload_sha256) "
            "VALUES (?, 101, 2026, 1, 'Georgia Bulldogs', 'Clemson Tigers', "
            "'Georgia', 'Clemson', -3.5, 'not-utc', 'splashsports', "
            "'fixture://card.csv', ?)",
            (contest.id, PAYLOAD_A),
        )

    line = _lock(conn, contest_id=contest.id).line
    with pytest.raises(LineCorrectionError, match="timestamp must follow"):
        correct_locked_line(
            conn,
            line.id,
            home_spread=-4.0,
            reason="Correction timestamp predates the lock.",
            author="operations@example.test",
            source="splashsports",
            provenance="fixture://early-correction.csv",
            payload_sha256=PAYLOAD_B,
            corrected_at=datetime(2026, 8, 25, 15, 29, tzinfo=timezone.utc),
        )
    with pytest.raises(LineCorrectionError, match="change at least one"):
        correct_locked_line(
            conn,
            line.id,
            reason="No actual change.",
            author="operations@example.test",
            source="splashsports",
            provenance="fixture://noop.csv",
            payload_sha256=PAYLOAD_B,
            corrected_at=CORRECTED_AT,
        )
    assert list_line_corrections(conn, line.id) == ()
    conn.close()
