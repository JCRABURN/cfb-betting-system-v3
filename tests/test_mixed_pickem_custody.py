import hashlib
import json
import sqlite3
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from migrations.runner import apply_migrations
from mixed_pickem import (
    ManifestBuildRequest,
    MixedPickemCustodyError,
    approve_manifest,
    build_manifest,
    create_contest_round,
    create_contest_season,
    inspect_manifest,
    lock_approved_manifest,
)
from mixed_pickem.spreadsheets import (
    PARSER_VERSION,
    SpreadsheetContractError,
    normalize_spread,
    read_source,
)
from scripts.build_mixed_pickem_manifest import main as build_manifest_cli


FIXTURES = Path(__file__).parent / "fixtures" / "mixed_pickem"
VALID_CSV = FIXTURES / "valid_mixed_4.csv"
VALID_XLSX = FIXTURES / "valid_mixed_4.xlsx"
INVALID_CSV = FIXTURES / "invalid_cases.csv"
UTC = timezone.utc
CREATED_AT = "2026-08-01T00:00:00+00:00"
RECEIVED_AT = datetime(2026, 8, 20, 0, 0, tzinfo=UTC)
IMPORTED_AT = datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
APPROVED_AT = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
LOCKED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)
PROVENANCE = "fixture://mixed-pickem/phase-2"
EVENT_PROVIDER = "fixture_schedule"


BASE_EVENTS = (
    (
        "NCAA",
        "Atlas State",
        "Beacon Tech",
        "2026-09-02T22:00:00+00:00",
        "fixture-ncaa-1",
        1,
    ),
    (
        "NFL",
        "Harbor Hounds",
        "Metro Meteors",
        "2026-09-03T18:00:00+00:00",
        "fixture-nfl-1",
        4,
    ),
    (
        "NCAA",
        "Cedar College",
        "Delta Institute",
        "2026-09-05T16:00:00+00:00",
        "fixture-ncaa-2",
        2,
    ),
    (
        "NFL",
        "Prairie Pros",
        "Union United",
        "2026-09-06T17:00:00+00:00",
        "fixture-nfl-2",
        5,
    ),
)


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    return conn


def _key(value):
    return value.casefold().replace(" ", "-")


def _insert_team(conn, *, sport, name, sequence):
    franchise = conn.execute(
        "INSERT INTO football_franchises "
        "(sport_code, canonical_key, display_label, created_at, provenance) "
        "VALUES (?, ?, ?, ?, ?)",
        (sport, f"{_key(name)}-franchise-{sequence}", name, CREATED_AT, PROVENANCE),
    ).lastrowid
    return conn.execute(
        "INSERT INTO football_teams "
        "(franchise_id, sport_code, canonical_key, display_name, "
        "effective_from_season, created_at, provenance) "
        "VALUES (?, ?, ?, ?, 2020, ?, ?)",
        (franchise, sport, _key(name), name, CREATED_AT, PROVENANCE),
    ).lastrowid


def _insert_event(
    conn,
    *,
    sport,
    away,
    home,
    kickoff,
    source_id,
    sport_week,
    sequence,
    neutral=False,
):
    away_id = _insert_team(conn, sport=sport, name=away, sequence=sequence * 2)
    home_id = _insert_team(conn, sport=sport, name=home, sequence=sequence * 2 + 1)
    event_id = conn.execute(
        "INSERT INTO football_events "
        "(canonical_event_key, sport_code, league_season, season_type, "
        "sport_week, home_team_id, away_team_id, kickoff_at, neutral_site, "
        "status, created_at, provenance) "
        "VALUES (?, ?, 2026, 'regular', ?, ?, ?, ?, ?, 'scheduled', ?, ?)",
        (
            f"{sport.casefold()}-fixture-event-{sequence}",
            sport,
            sport_week,
            home_id,
            away_id,
            kickoff,
            int(neutral),
            "2026-08-10T00:00:00+00:00",
            PROVENANCE,
        ),
    ).lastrowid
    conn.execute(
        "INSERT INTO football_provider_event_ids "
        "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
        "VALUES (?, ?, ?, ?, '2026-08-11T00:00:00+00:00', ?)",
        (EVENT_PROVIDER, sport, source_id, event_id, PROVENANCE),
    )
    return int(event_id), int(away_id), int(home_id)


def _seed_base_events(conn):
    result = {}
    for sequence, (sport, away, home, kickoff, source_id, week) in enumerate(
        BASE_EVENTS, start=1
    ):
        result[source_id] = _insert_event(
            conn,
            sport=sport,
            away=away,
            home=home,
            kickoff=kickoff,
            source_id=source_id,
            sport_week=week,
            sequence=sequence,
            neutral=sequence == 1,
        )
    return result


def _season_and_round(conn, *, suffix="one", round_number=7):
    season_id = create_contest_season(
        conn,
        season_key=f"mixed-2026-{suffix}",
        display_label=f"Fictional Mixed 2026 {suffix}",
        planned_round_count=20,
        policy_version="mixed-season-v1",
        actor="fixture-owner",
        provenance=PROVENANCE,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    round_id = create_contest_round(
        conn,
        contest_season_id=season_id,
        round_number=round_number,
        round_label=f"Contest Round {round_number}",
        actor="fixture-owner",
        provenance=PROVENANCE,
        created_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    return season_id, round_id


def _request(
    source_path,
    round_id,
    *,
    media_type="CSV",
    worksheet=None,
    import_key="mixed-round-7-source-v1",
    expected_count=None,
):
    return ManifestBuildRequest(
        source_path=Path(source_path),
        media_type=media_type,
        worksheet=worksheet,
        contest_round_id=round_id,
        import_key=import_key,
        resolution_window_start_at=WINDOW_START,
        resolution_window_end_at=WINDOW_END,
        received_at=RECEIVED_AT,
        imported_at=IMPORTED_AT,
        generated_at=GENERATED_AT,
        actor="fixture-importer",
        provenance=PROVENANCE,
        expected_source_row_count=expected_count,
        source_event_provider=EVENT_PROVIDER,
    )


def _build_valid(conn, *, source=VALID_CSV, media_type="CSV", worksheet=None):
    _seed_base_events(conn)
    _, round_id = _season_and_round(conn)
    result = build_manifest(
        conn,
        _request(
            source,
            round_id,
            media_type=media_type,
            worksheet=worksheet,
            expected_count=4,
        ),
    )
    return round_id, result


def _approve(conn, result, *, key="mixed-round-7-approval-v1"):
    return approve_manifest(
        conn,
        manifest_id=result.manifest_id,
        approval_key=key,
        expected_source_sha256=result.source_sha256,
        expected_manifest_sha256=result.manifest_sha256,
        expected_row_count=result.source_row_count,
        reviewer="fixture-owner",
        approved_at=APPROVED_AT,
        provenance=PROVENANCE,
    )


def _lock(conn, result, approval, *, key="mixed-round-7-lock-v1"):
    return lock_approved_manifest(
        conn,
        approval_id=approval.approval_id,
        lock_key=key,
        expected_manifest_sha256=result.manifest_sha256,
        expected_line_count=result.source_row_count,
        actor="fixture-owner",
        locked_at=LOCKED_AT,
        provenance=PROVENANCE,
    )


def _write_csv(path, rows):
    header = (
        "Away Team,Home Team,Spread,Spread Side,Sport,Kickoff UTC,"
        "Source Event ID,Notes\n"
    )
    path.write_text(header + "\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _corrected_kickoff_csv(path):
    rows = []
    spreads = (("-3", "Away"), ("+3", "Home"), ("-3.5", "Home"), ("PK", "Away"))
    notes = (
        "Fictional neutral-site opener",
        "Fictional professional game",
        "Fictional college game",
        "Fictional pick'em",
    )
    for index, (event, spread) in enumerate(zip(BASE_EVENTS, spreads, strict=True)):
        sport, away, home, kickoff, source_id, _ = event
        if index == 0:
            kickoff = "2026-09-02T20:00:00+00:00"
        rows.append((away, home, spread[0], spread[1], sport, kickoff, source_id, notes[index]))
    return _write_csv(path, rows)


def test_product_registry_season_policy_and_round_identity_are_product_b_only():
    conn = _connection()
    product = conn.execute(
        "SELECT product_key, display_name FROM mixed_contest_products"
    ).fetchone()
    sports = conn.execute(
        "SELECT sport_code FROM mixed_contest_product_sports ORDER BY sport_code"
    ).fetchall()
    season_id, round_id = _season_and_round(conn, round_number=17)

    assert product == ("mixed_pickem", "Mixed NCAA + NFL ATS Pick'em")
    assert sports == [("NCAA",), ("NFL",)]
    assert conn.execute(
        "SELECT planned_round_count, policy_version FROM mixed_contest_seasons "
        "WHERE id = ?", (season_id,)
    ).fetchone() == (20, "mixed-season-v1")
    assert conn.execute(
        "SELECT round_number, round_label FROM mixed_contest_rounds WHERE id = ?",
        (round_id,),
    ).fetchone() == (17, "Contest Round 17")
    assert not {"sport_week", "ncaa_week", "nfl_week"} & {
        row[1] for row in conn.execute("PRAGMA table_info(mixed_contest_rounds)")
    }
    assert conn.execute("SELECT COUNT(*) FROM contests").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize(
    ("spread", "side", "expected"),
    (
        ("-3", "Away", 3000),
        ("+3", "Home", 3000),
        ("-3.5", "Home", -3500),
        ("PK", "Away", 0),
        ("PICK", "Home", 0),
        ("EVEN", "Atlas State", 0),
    ),
)
def test_versioned_spread_contract_is_exact(spread, side, expected):
    value = normalize_spread(spread, side, "Atlas State", "Beacon Tech")
    assert value.home_millipoints == expected


@pytest.mark.parametrize(
    ("spread", "side", "error"),
    (
        ("NaN", "Home", "SPREAD_MALFORMED"),
        ("inf", "Home", "SPREAD_MALFORMED"),
        ("101", "Home", "SPREAD_OUT_OF_RANGE"),
        ("-3.25", "Home", "SPREAD_MALFORMED"),
        ("-3", "", "SPREAD_SIDE_MISSING"),
        ("-3", "Visitor", "SPREAD_SIDE_INVALID"),
    ),
)
def test_versioned_spread_contract_rejects_untrusted_values(spread, side, error):
    with pytest.raises(SpreadsheetContractError, match=error):
        normalize_spread(spread, side, "Atlas State", "Beacon Tech")


def test_csv_pipeline_preserves_every_row_and_locks_complete_mixed_slate():
    conn = _connection()
    round_id, result = _build_valid(conn)

    assert result.source_sha256 == hashlib.sha256(VALID_CSV.read_bytes()).hexdigest()
    assert result.source_row_count == result.accepted_count == 4
    assert result.rejected_count == result.ambiguous_count == result.duplicate_count == 0
    assert result.manifest_state == "MANIFEST_READY"
    assert result.earliest_kickoff_at == "2026-09-02T22:00:00+00:00"
    assert result.review == inspect_manifest(conn, result.manifest_id)
    assert [row[0] for row in conn.execute(
        "SELECT state FROM mixed_slate_import_states WHERE import_id = ? ORDER BY sequence",
        (result.import_id,),
    )] == ["RECEIVED", "PARSED", "RESOLVED"]
    assert [row["sport_code"] for row in result.review["rows"]] == [
        "NCAA", "NFL", "NCAA", "NFL"
    ]
    assert conn.execute(
        "SELECT neutral_site FROM football_events ORDER BY id LIMIT 1"
    ).fetchone()[0] == 1

    approval = _approve(conn, result)
    lock = _lock(conn, result, approval)
    assert lock.line_count == 4
    assert conn.execute(
        "SELECT COUNT(*) FROM mixed_contest_lines WHERE contest_round_id = ?",
        (round_id,),
    ).fetchone()[0] == 4
    assert conn.execute(
        "SELECT expected_line_count, locked_line_count FROM mixed_line_lock_batches"
    ).fetchone() == (4, 4)
    assert conn.execute(
        "SELECT COUNT(*) FROM mixed_line_lock_completions"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT state FROM mixed_round_state_events WHERE contest_round_id = ? "
        "ORDER BY sequence DESC LIMIT 1", (round_id,)
    ).fetchone()[0] == "LOCKED"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_xlsx_requires_explicit_sheet_and_builds_the_same_four_row_contract():
    parsed = read_source(VALID_XLSX, media_type="XLSX", worksheet="Weekly Slate")
    assert parsed.source_sha256 == hashlib.sha256(VALID_XLSX.read_bytes()).hexdigest()
    assert parsed.selected_worksheet == "Weekly Slate"
    assert len(parsed.rows) == 4
    assert parsed.header_errors == ()
    assert parsed.rows[0].values["kickoff"].startswith(" ")
    with pytest.raises(SpreadsheetContractError, match="XLSX_WORKSHEET_REQUIRED"):
        read_source(VALID_XLSX, media_type="XLSX")
    with pytest.raises(SpreadsheetContractError, match="XLSX_WORKSHEET_NOT_FOUND"):
        read_source(VALID_XLSX, media_type="XLSX", worksheet="Wrong Sheet")

    conn = _connection()
    _, result = _build_valid(
        conn, source=VALID_XLSX, media_type="XLSX", worksheet="Weekly Slate"
    )
    assert result.accepted_count == result.source_row_count == 4
    assert result.review["selected_worksheet"] == "Weekly Slate"
    assert conn.execute(
        "SELECT raw_kickoff, parsed_kickoff_at FROM mixed_slate_import_rows "
        "WHERE import_id = ? ORDER BY source_order LIMIT 1", (result.import_id,)
    ).fetchone() == (
        " 2026-09-02T22:00:00+00:00",
        "2026-09-02T22:00:00+00:00",
    )
    conn.close()


def test_xlsx_rejects_macro_or_external_link_members(tmp_path):
    for unsafe_member, expected in (
        ("xl/vbaProject.bin", "XLSX_ACTIVE_OR_EXTERNAL_CONTENT_REJECTED"),
        ("xl/externalLinks/externalLink1.xml", "XLSX_ACTIVE_OR_EXTERNAL_CONTENT_REJECTED"),
    ):
        target = tmp_path / f"unsafe-{Path(unsafe_member).name}.xlsx"
        with zipfile.ZipFile(VALID_XLSX) as source, zipfile.ZipFile(target, "w") as sink:
            for info in source.infolist():
                sink.writestr(info, source.read(info.filename))
            sink.writestr(unsafe_member, b"fixture-only")
        with pytest.raises(SpreadsheetContractError, match=expected):
            read_source(target, media_type="XLSX", worksheet="Weekly Slate")


def test_xlsx_formula_cell_is_retained_but_never_trusted_for_approval(tmp_path):
    target = tmp_path / "formula-cell.xlsx"
    worksheet_member = "xl/worksheets/sheet1.xml"
    with zipfile.ZipFile(VALID_XLSX) as source, zipfile.ZipFile(target, "w") as sink:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == worksheet_member:
                text = payload.decode("utf-8")
                text = text.replace(
                    '<x:c r="C2" s="12" t="str"><x:v>-3</x:v></x:c>',
                    '<x:c r="C2" s="12" t="str"><x:f>1-4</x:f><x:v>-3</x:v></x:c>',
                    1,
                )
                payload = text.encode("utf-8")
            sink.writestr(info, payload)
    parsed = read_source(target, media_type="XLSX", worksheet="Weekly Slate")
    assert parsed.rows[0].formula_present is True

    conn = _connection()
    _seed_base_events(conn)
    _, round_id = _season_and_round(conn)
    result = build_manifest(
        conn,
        _request(
            target,
            round_id,
            media_type="XLSX",
            worksheet="Weekly Slate",
            expected_count=4,
        ),
    )
    assert result.manifest_state == "NEEDS_REVIEW"
    assert "FORMULA_CELL_UNTRUSTED" in result.review["rows"][0]["error_codes"]
    assert result.deadline_derivation_id is None
    conn.close()


def test_invalid_fixture_preserves_all_rows_and_blocks_partial_approval():
    conn = _connection()
    _seed_base_events(conn)
    _, round_id = _season_and_round(conn)
    result = build_manifest(
        conn,
        _request(INVALID_CSV, round_id, expected_count=7),
    )
    errors = [set(row["error_codes"]) for row in result.review["rows"]]

    assert result.source_row_count == 7
    assert len(result.review["rows"]) == 7
    assert result.accepted_count == 0
    assert result.manifest_state == "NEEDS_REVIEW"
    assert result.deadline_derivation_id is None
    assert any("UNKNOWN_TEAM" in item for item in errors)
    assert any("REVERSED_HOME_AWAY" in item for item in errors)
    assert any("SPORT_MISMATCH" in item for item in errors)
    assert any("KICKOFF_CONFLICT" in item for item in errors)
    assert any("SPREAD_MALFORMED" in item for item in errors)
    assert any("DUPLICATE_CANONICAL_EVENT" in item for item in errors)
    assert any("CONFLICTING_EVENT_SPREAD" in item for item in errors)
    with pytest.raises(MixedPickemCustodyError, match="deadline-complete"):
        _approve(conn, result)
    assert conn.execute("SELECT COUNT(*) FROM mixed_slate_approvals").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mixed_contest_lines").fetchone()[0] == 0
    conn.close()


def test_owner_supplied_expected_count_mismatch_blocks_manifest_readiness():
    conn = _connection()
    _seed_base_events(conn)
    _, round_id = _season_and_round(conn)
    result = build_manifest(
        conn,
        _request(VALID_CSV, round_id, expected_count=5),
    )
    assert result.source_row_count == result.accepted_count == 4
    assert result.review["expected_source_row_count"] == 5
    assert result.manifest_state == "NEEDS_REVIEW"
    assert result.deadline_derivation_id is None
    conn.close()


def test_unknown_ambiguous_cross_sport_reversed_and_wrong_sport_fail_closed(tmp_path):
    conn = _connection()
    refs = _seed_base_events(conn)
    atlas_id = refs["fixture-ncaa-1"][1]
    harbor_id = refs["fixture-nfl-1"][1]
    for sport, team_id in (("NCAA", atlas_id), ("NFL", harbor_id)):
        conn.execute(
            "INSERT INTO football_team_aliases "
            "(provider, sport_code, raw_alias, alias_key, team_id, "
            "effective_from_season, created_at, provenance) "
            "VALUES ('mixed_pickem_admin', ?, 'Stars', 'stars', ?, 2020, ?, ?)",
            (sport, team_id, CREATED_AT, PROVENANCE),
        )
    _, round_id = _season_and_round(conn)
    source = _write_csv(
        tmp_path / "fail-closed.csv",
        (
            ("Unknown Club", "Beacon Tech", "-3", "Away", "NCAA", "", "", "unknown"),
            ("Stars", "Metro Meteors", "+3", "Home", "", "", "", "collision"),
            ("Beacon Tech", "Atlas State", "-3", "Away", "NCAA", "2026-09-02T22:00:00+00:00", "fixture-ncaa-1", "reversed"),
            ("Harbor Hounds", "Metro Meteors", "+3", "Home", "NCAA", "2026-09-03T18:00:00+00:00", "fixture-nfl-1", "wrong sport"),
        ),
    )
    result = build_manifest(conn, _request(source, round_id, expected_count=4))
    codes = [set(row["error_codes"]) for row in result.review["rows"]]
    assert "UNKNOWN_TEAM" in codes[0]
    assert "AMBIGUOUS_TEAM" in codes[1]
    assert "REVERSED_HOME_AWAY" in codes[2]
    assert "SPORT_MISMATCH" in codes[3]
    assert result.ambiguous_count == 1
    assert result.accepted_count == 0
    conn.close()


def test_provider_event_id_collision_across_sports_is_ambiguous(tmp_path):
    conn = _connection()
    refs = _seed_base_events(conn)
    for sport, source_id in (("NCAA", "fixture-ncaa-1"), ("NFL", "fixture-nfl-1")):
        conn.execute(
            "INSERT INTO football_provider_event_ids "
            "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
            "VALUES (?, ?, 'shared-event-id', ?, '2026-08-11T00:00:00+00:00', ?)",
            (EVENT_PROVIDER, sport, refs[source_id][0], PROVENANCE),
        )
    _, round_id = _season_and_round(conn)
    source = _write_csv(
        tmp_path / "provider-id-collision.csv",
        ((
            "Atlas State", "Beacon Tech", "-3", "Away", "NCAA",
            "2026-09-02T22:00:00+00:00", "shared-event-id", "collision",
        ),),
    )
    result = build_manifest(conn, _request(source, round_id, expected_count=1))
    assert result.ambiguous_count == 1
    assert result.review["rows"][0]["error_codes"] == [
        "SOURCE_EVENT_ID_AMBIGUOUS"
    ]
    conn.close()


def test_future_alias_is_not_visible_to_point_in_time_resolution(tmp_path):
    conn = _connection()
    refs = _seed_base_events(conn)
    conn.execute(
        "INSERT INTO football_team_aliases "
        "(provider, sport_code, raw_alias, alias_key, team_id, "
        "effective_from_season, created_at, provenance) VALUES "
        "('mixed_pickem_admin', 'NCAA', 'Atlas Admin', 'atlas admin', ?, 2020, "
        "'2026-08-21T00:00:00+00:00', ?)",
        (refs["fixture-ncaa-1"][1], PROVENANCE),
    )
    _, round_id = _season_and_round(conn)
    source = _write_csv(
        tmp_path / "future-alias.csv",
        ((
            "Atlas Admin", "Beacon Tech", "-3", "Away", "NCAA",
            "2026-09-02T22:00:00+00:00", "", "future alias",
        ),),
    )
    result = build_manifest(conn, _request(source, round_id, expected_count=1))
    assert result.accepted_count == 0
    assert result.review["rows"][0]["error_codes"] == ["UNKNOWN_TEAM"]
    conn.close()


def test_kickoff_mismatch_and_missing_kickoff_ambiguity_both_fail(tmp_path):
    conn = _connection()
    refs = _seed_base_events(conn)
    first_event, away_id, home_id = refs["fixture-ncaa-1"]
    conn.execute(
        "INSERT INTO football_events "
        "(canonical_event_key, sport_code, league_season, season_type, sport_week, "
        "home_team_id, away_team_id, kickoff_at, neutral_site, status, created_at, provenance) "
        "VALUES ('ncaa-fixture-rematch', 'NCAA', 2026, 'regular', 3, ?, ?, "
        "'2026-09-07T22:00:00+00:00', 0, 'scheduled', "
        "'2026-08-10T00:00:00+00:00', ?)",
        (home_id, away_id, PROVENANCE),
    )
    _, round_id = _season_and_round(conn)
    source = _write_csv(
        tmp_path / "kickoff-errors.csv",
        (
            ("Atlas State", "Beacon Tech", "-3", "Away", "NCAA", "", "", "missing kickoff"),
            ("Cedar College", "Delta Institute", "-3.5", "Home", "NCAA", "2026-09-05T16:00:01+00:00", "", "mismatch"),
        ),
    )
    result = build_manifest(conn, _request(source, round_id, expected_count=2))
    codes = [set(row["error_codes"]) for row in result.review["rows"]]
    assert "KICKOFF_REQUIRED_FOR_UNIQUE_RESOLUTION" in codes[0]
    assert "KICKOFF_CONFLICT" in codes[1]
    assert result.ambiguous_count == 1
    assert first_event is not None
    conn.close()


def test_duplicate_raw_event_and_conflicting_spread_are_all_reported(tmp_path):
    conn = _connection()
    _seed_base_events(conn)
    _, round_id = _season_and_round(conn)
    common = (
        "Atlas State", "Beacon Tech", "-3", "Away", "NCAA",
        "2026-09-02T22:00:00+00:00", "fixture-ncaa-1", "duplicate",
    )
    conflicting = list(common)
    conflicting[2] = "-4"
    source = _write_csv(tmp_path / "duplicates.csv", (common, common, tuple(conflicting)))
    result = build_manifest(conn, _request(source, round_id, expected_count=3))
    all_codes = set().union(*(set(row["error_codes"]) for row in result.review["rows"]))
    assert {
        "DUPLICATE_RAW_ROW",
        "CONFLICTING_RAW_MATCHUP_SPREAD",
        "DUPLICATE_CANONICAL_EVENT",
        "CONFLICTING_EVENT_SPREAD",
    } <= all_codes
    assert result.duplicate_count == 3
    conn.close()


def test_manifest_hash_is_deterministic_for_same_exact_source_and_event_state():
    first_conn = _connection()
    second_conn = _connection()
    _seed_base_events(first_conn)
    _seed_base_events(second_conn)
    _, first_round = _season_and_round(first_conn, round_number=1)
    _, second_round = _season_and_round(second_conn, round_number=1)
    first = build_manifest(first_conn, _request(VALID_CSV, first_round))
    second = build_manifest(second_conn, _request(VALID_CSV, second_round))
    assert first.ordered_row_set_sha256 == second.ordered_row_set_sha256
    assert first.manifest_sha256 == second.manifest_sha256
    assert json.dumps(first.review["rows"], sort_keys=True) == json.dumps(
        second.review["rows"], sort_keys=True
    )
    first_conn.close()
    second_conn.close()


def test_approval_is_immutable_and_bound_to_exact_hashes_and_count():
    conn = _connection()
    _, result = _build_valid(conn)
    with pytest.raises(MixedPickemCustodyError, match="checksum or row count"):
        approve_manifest(
            conn,
            manifest_id=result.manifest_id,
            approval_key="wrong-hash",
            expected_source_sha256="a" * 64,
            expected_manifest_sha256=result.manifest_sha256,
            expected_row_count=4,
            reviewer="fixture-owner",
            approved_at=APPROVED_AT,
            provenance=PROVENANCE,
        )
    approval = _approve(conn, result)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE mixed_slate_approvals SET reviewer = 'changed' WHERE id = ?",
            (approval.approval_id,),
        )
    with pytest.raises(MixedPickemCustodyError):
        _approve(conn, result, key="second-approval")
    assert conn.execute("SELECT COUNT(*) FROM mixed_slate_approvals").fetchone()[0] == 1
    conn.close()


def test_ready_round_rejects_reimport_without_append_only_event_correction():
    conn = _connection()
    round_id, _ = _build_valid(conn)
    second_request = replace(
        _request(VALID_CSV, round_id, import_key="unjustified-reimport"),
        received_at=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        imported_at=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
        generated_at=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
    )
    with pytest.raises(MixedPickemCustodyError, match="cannot accept another import"):
        build_manifest(conn, second_request)
    assert conn.execute("SELECT COUNT(*) FROM mixed_slate_imports").fetchone()[0] == 1
    conn.close()


def _append_earlier_kickoff_revision(conn, event_id, *, recorded_at):
    event = conn.execute(
        "SELECT home_team_id, away_team_id, venue_id, neutral_site, status "
        "FROM football_events WHERE id = ?", (event_id,)
    ).fetchone()
    return conn.execute(
        "INSERT INTO football_event_revisions "
        "(event_id, revision_number, supersedes_revision_id, home_team_id, "
        "away_team_id, kickoff_at, venue_id, neutral_site, status, recorded_at, "
        "reason, recorded_by, provenance) VALUES (?, 1, NULL, ?, ?, "
        "'2026-09-02T20:00:00+00:00', ?, ?, ?, ?, "
        "'Verified earlier kickoff', 'fixture-reviewer', ?)",
        (event_id, event[0], event[1], event[2], event[3], event[4], recorded_at, PROVENANCE),
    ).lastrowid


def test_event_correction_blocks_stale_approval_and_allows_reviewed_replacement(tmp_path):
    conn = _connection()
    _, result = _build_valid(conn)
    event_id = result.review["rows"][0]["canonical_event_id"]
    _append_earlier_kickoff_revision(
        conn, event_id, recorded_at="2026-08-21T00:00:00+00:00"
    )
    with pytest.raises(MixedPickemCustodyError, match="deadline derivation is stale"):
        _approve(conn, result)
    assert conn.execute("SELECT COUNT(*) FROM mixed_slate_approvals").fetchone()[0] == 0

    corrected_source = _corrected_kickoff_csv(tmp_path / "corrected-before-approval.csv")
    round_id = conn.execute(
        "SELECT contest_round_id FROM mixed_slate_manifests WHERE id = ?",
        (result.manifest_id,),
    ).fetchone()[0]
    corrected_request = replace(
        _request(
            corrected_source,
            round_id,
            import_key="corrected-before-approval",
        ),
        received_at=datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
        imported_at=datetime(2026, 8, 21, 2, 0, tzinfo=UTC),
        generated_at=datetime(2026, 8, 21, 3, 0, tzinfo=UTC),
    )
    corrected = build_manifest(conn, corrected_request)
    corrected_approval = approve_manifest(
        conn,
        manifest_id=corrected.manifest_id,
        approval_key="corrected-before-approval-owner",
        expected_source_sha256=corrected.source_sha256,
        expected_manifest_sha256=corrected.manifest_sha256,
        expected_row_count=4,
        reviewer="fixture-owner",
        approved_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
        provenance=PROVENANCE,
    )
    corrected_lock = lock_approved_manifest(
        conn,
        approval_id=corrected_approval.approval_id,
        lock_key="corrected-before-approval-lock",
        expected_manifest_sha256=corrected.manifest_sha256,
        expected_line_count=4,
        actor="fixture-owner",
        locked_at=datetime(2026, 8, 21, 5, 0, tzinfo=UTC),
        provenance=PROVENANCE,
    )
    assert corrected.earliest_kickoff_at == "2026-09-02T20:00:00+00:00"
    assert corrected.manifest_sha256 != result.manifest_sha256
    assert corrected_lock.line_count == 4
    conn.close()


def test_event_correction_blocks_old_approval_lock_and_requires_new_approval(tmp_path):
    conn = _connection()
    _, result = _build_valid(conn)
    approval = _approve(conn, result)
    event_id = result.review["rows"][0]["canonical_event_id"]
    _append_earlier_kickoff_revision(
        conn, event_id, recorded_at="2026-08-22T00:00:00+00:00"
    )
    with pytest.raises(MixedPickemCustodyError, match="deadline derivation is stale"):
        _lock(conn, result, approval)
    assert conn.execute("SELECT COUNT(*) FROM mixed_line_lock_batches").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mixed_contest_lines").fetchone()[0] == 0

    corrected_source = _corrected_kickoff_csv(tmp_path / "corrected-after-approval.csv")
    round_id = conn.execute(
        "SELECT contest_round_id FROM mixed_slate_manifests WHERE id = ?",
        (result.manifest_id,),
    ).fetchone()[0]
    corrected = build_manifest(
        conn,
        replace(
            _request(
                corrected_source,
                round_id,
                import_key="corrected-after-approval",
            ),
            received_at=datetime(2026, 8, 22, 1, 0, tzinfo=UTC),
            imported_at=datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
            generated_at=datetime(2026, 8, 22, 3, 0, tzinfo=UTC),
        ),
    )
    new_approval = approve_manifest(
        conn,
        manifest_id=corrected.manifest_id,
        approval_key="corrected-after-approval-owner",
        expected_source_sha256=corrected.source_sha256,
        expected_manifest_sha256=corrected.manifest_sha256,
        expected_row_count=4,
        reviewer="fixture-owner",
        approved_at=datetime(2026, 8, 22, 4, 0, tzinfo=UTC),
        provenance=PROVENANCE,
    )
    new_lock = lock_approved_manifest(
        conn,
        approval_id=new_approval.approval_id,
        lock_key="corrected-after-approval-lock",
        expected_manifest_sha256=corrected.manifest_sha256,
        expected_line_count=4,
        actor="fixture-owner",
        locked_at=datetime(2026, 8, 22, 5, 0, tzinfo=UTC),
        provenance=PROVENANCE,
    )
    assert conn.execute("SELECT COUNT(*) FROM mixed_slate_approvals").fetchone()[0] == 2
    assert new_approval.approval_id != approval.approval_id
    assert new_lock.line_count == 4
    conn.close()


def test_one_bad_line_rolls_back_the_entire_lock_transaction():
    conn = _connection()
    _, result = _build_valid(conn)
    approval = _approve(conn, result)
    blocked_event = result.review["rows"][1]["canonical_event_id"]
    conn.execute(
        "CREATE TRIGGER fixture_force_second_line_failure "
        "BEFORE INSERT ON mixed_contest_lines WHEN NEW.football_event_id = "
        f"{int(blocked_event)} BEGIN SELECT RAISE(ABORT, 'fixture forced failure'); END"
    )
    with pytest.raises(MixedPickemCustodyError, match="atomic line lock was rejected"):
        _lock(conn, result, approval)
    assert conn.execute("SELECT COUNT(*) FROM mixed_line_lock_batches").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mixed_contest_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM mixed_line_lock_completions").fetchone()[0] == 0
    assert conn.execute(
        "SELECT state FROM mixed_round_state_events ORDER BY id DESC LIMIT 1"
    ).fetchone()[0] == "OWNER_APPROVED"
    conn.close()


def test_locked_lines_are_immutable_and_separate_from_product_a_and_book_lines():
    conn = _connection()
    _, result = _build_valid(conn)
    approval = _approve(conn, result)
    _lock(conn, result, approval)
    mixed_event = result.review["rows"][0]

    conn.execute("INSERT INTO teams VALUES (1, 'Beacon Tech', 'Fixture', 'FBS')")
    conn.execute("INSERT INTO teams VALUES (2, 'Atlas State', 'Fixture', 'FBS')")
    conn.execute(
        "INSERT INTO games (game_id, season, week, start_date, home_team, away_team) "
        "VALUES (7001, 2026, 1, '2026-09-02T22:00:00+00:00', "
        "'Beacon Tech', 'Atlas State')"
    )
    conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) VALUES "
        "(7001, 2026, 1, 'Beacon Tech', 'Atlas State', 'FixtureBook', -5, "
        "'current', 'fixture', '2026-08-23T00:00:00+00:00')"
    )
    contest_id = conn.execute(
        "INSERT INTO contests "
        "(contest_key, name, season, week, source, provenance, created_at) "
        "VALUES ('splash-fixture', 'Splash Fixture', 2026, 1, 'SplashSports', ?, ?)",
        (PROVENANCE, CREATED_AT),
    ).lastrowid
    conn.execute(
        "INSERT INTO contest_locked_lines "
        "(contest_id, game_id, season, week, raw_home_team, raw_away_team, "
        "normalized_home_team, normalized_away_team, home_spread, locked_at, "
        "source, provenance, payload_sha256) VALUES "
        "(?, 7001, 2026, 1, 'Beacon Tech', 'Atlas State', 'Beacon Tech', "
        "'Atlas State', -3.5, ?, 'SplashSports', ?, ?)",
        (contest_id, CREATED_AT, PROVENANCE, "b" * 64),
    )

    assert conn.execute("SELECT home_spread FROM contest_locked_lines").fetchone()[0] == -3.5
    assert conn.execute("SELECT home_spread FROM betting_lines").fetchone()[0] == -5.0
    assert conn.execute(
        "SELECT home_spread_millipoints FROM mixed_contest_lines "
        "WHERE football_event_id = ?", (mixed_event["canonical_event_id"],)
    ).fetchone()[0] == 3000
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE mixed_contest_lines SET home_spread_millipoints = -5000")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM mixed_contest_lines")
    conn.close()


@pytest.mark.parametrize("game_count", (15, 12))
def test_variable_card_sizes_have_no_fifteen_game_schema_constant(tmp_path, game_count):
    conn = _connection()
    rows = []
    for index in range(1, game_count + 1):
        sport = "NCAA" if index % 2 else "NFL"
        away = f"Fictional Away {index:02d}"
        home = f"Fictional Home {index:02d}"
        kickoff = f"2026-09-{2 + (index - 1) // 4:02d}T{12 + index % 8:02d}:00:00+00:00"
        source_id = f"variable-{game_count}-{index}"
        _insert_event(
            conn,
            sport=sport,
            away=away,
            home=home,
            kickoff=kickoff,
            source_id=source_id,
            sport_week=100 + index,
            sequence=index,
        )
        rows.append((away, home, "-2.5", "Home", sport, kickoff, source_id, "fictional"))
    _, round_id = _season_and_round(conn, suffix=f"size-{game_count}")
    source = _write_csv(tmp_path / f"valid-{game_count}.csv", rows)
    result = build_manifest(
        conn,
        _request(
            source,
            round_id,
            import_key=f"variable-size-{game_count}",
            expected_count=game_count,
        ),
    )
    approval = _approve(conn, result, key=f"variable-size-{game_count}-approval")
    lock = _lock(conn, result, approval, key=f"variable-size-{game_count}-lock")
    assert result.source_row_count == result.accepted_count == game_count
    assert lock.line_count == game_count
    conn.close()


def test_phase_ends_at_locks_without_cards_picks_or_model_runs():
    conn = _connection()
    _, result = _build_valid(conn)
    approval = _approve(conn, result)
    _lock(conn, result, approval)
    for table in (
        "model_runs",
        "model_predictions",
        "contest_cards",
        "contest_picks",
        "picks",
        "sportsbook_recommendations",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert not any("nfl" in row[0].casefold() for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND "
        "name LIKE '%model%'"
    ))
    conn.close()


def test_offline_cli_builds_review_only_and_has_no_approval_or_lock_path(tmp_path):
    database = tmp_path / "authorized-disposable.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    apply_migrations(connection)
    _seed_base_events(connection)
    _, round_id = _season_and_round(connection)
    connection.commit()
    connection.close()
    review = tmp_path / "manifest-review.json"

    exit_code = build_manifest_cli(
        [
            "--database", str(database),
            "--source", str(VALID_CSV),
            "--media-type", "CSV",
            "--contest-round-id", str(round_id),
            "--import-key", "cli-fixture-import",
            "--resolution-window-start", WINDOW_START.isoformat(),
            "--resolution-window-end", WINDOW_END.isoformat(),
            "--received-at", RECEIVED_AT.isoformat(),
            "--imported-at", IMPORTED_AT.isoformat(),
            "--generated-at", GENERATED_AT.isoformat(),
            "--actor", "fixture-cli",
            "--provenance", PROVENANCE,
            "--source-event-provider", EVENT_PROVIDER,
            "--expected-source-row-count", "4",
            "--review-output", str(review),
        ]
    )

    assert exit_code == 0
    payload = json.loads(review.read_text(encoding="utf-8"))
    assert payload["source_row_count"] == payload["accepted_count"] == 4
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM mixed_slate_approvals").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM mixed_contest_lines").fetchone()[0] == 0
    connection.close()


def test_migration_20_registration_seed_counts_immutability_and_verification():
    conn = _connection()
    assert conn.execute(
        "SELECT version, name FROM schema_migrations WHERE version = 20"
    ).fetchone() == (20, "mixed_pickem_custody")
    assert conn.execute("SELECT COUNT(*) FROM mixed_contest_products").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM mixed_contest_product_sports").fetchone()[0] == 2
    for table in (
        "mixed_contest_seasons",
        "mixed_contest_rounds",
        "mixed_slate_imports",
        "mixed_slate_manifests",
        "mixed_slate_approvals",
        "mixed_line_lock_batches",
        "mixed_contest_lines",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE mixed_contest_products SET display_name = 'Changed'")
    conn.rollback()
    apply_migrations(conn)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
