import json
import sqlite3
from pathlib import Path

import pytest

from migrations.runner import MigrationError, apply_migrations


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "football_identity"
    / "identity_v1.json"
)
RECORDED_AT = "2026-08-27T12:00:00+00:00"
PROVENANCE = "fixture://football-identity/v1"


def _load_fixture(conn):
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    franchise_ids = {}
    for item in payload["franchises"]:
        cursor = conn.execute(
            "INSERT INTO football_franchises "
            "(sport_code, canonical_key, display_label, created_at, provenance) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                item["sport_code"],
                item["canonical_key"],
                item["display_label"],
                RECORDED_AT,
                PROVENANCE,
            ),
        )
        franchise_ids[item["ref"]] = cursor.lastrowid

    team_ids = {}
    for item in payload["teams"]:
        cursor = conn.execute(
            "INSERT INTO football_teams "
            "(franchise_id, sport_code, canonical_key, display_name, "
            "effective_from_season, created_at, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                franchise_ids[item["franchise_ref"]],
                item["sport_code"],
                item["canonical_key"],
                item["display_name"],
                item["effective_from_season"],
                RECORDED_AT,
                PROVENANCE,
            ),
        )
        team_ids[item["ref"]] = cursor.lastrowid

    venue_ids = {}
    venue_version_ids = {}
    for item in payload["venues"]:
        cursor = conn.execute(
            "INSERT INTO football_venues "
            "(canonical_key, created_at, provenance) VALUES (?, ?, ?)",
            (item["canonical_key"], RECORDED_AT, PROVENANCE),
        )
        venue_id = cursor.lastrowid
        venue_ids[item["ref"]] = venue_id
        prior_id = None
        for version in item["versions"]:
            cursor = conn.execute(
                "INSERT INTO football_venue_versions "
                "(venue_id, display_name, latitude_e6, longitude_e6, time_zone, "
                "roof_type, surface, effective_from_at, "
                "supersedes_venue_version_id, recorded_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    venue_id,
                    version["display_name"],
                    version["latitude_e6"],
                    version["longitude_e6"],
                    version["time_zone"],
                    version["roof_type"],
                    version["surface"],
                    version["effective_from_at"],
                    prior_id,
                    RECORDED_AT,
                    PROVENANCE,
                ),
            )
            prior_id = cursor.lastrowid
        venue_version_ids[item["ref"]] = prior_id
    conn.commit()
    return {
        "franchises": franchise_ids,
        "teams": team_ids,
        "venues": venue_ids,
        "venue_versions": venue_version_ids,
    }


def _insert_alias(
    conn,
    *,
    provider,
    sport_code,
    raw_alias,
    team_id,
    season,
    supersedes=None,
):
    return conn.execute(
        "INSERT INTO football_team_aliases "
        "(provider, sport_code, raw_alias, alias_key, team_id, "
        "effective_from_season, supersedes_alias_id, created_at, provenance) "
        "VALUES (?, ?, ?, lower(trim(?)), ?, ?, ?, ?, ?)",
        (
            provider,
            sport_code,
            raw_alias,
            raw_alias,
            team_id,
            season,
            supersedes,
            RECORDED_AT,
            PROVENANCE,
        ),
    ).lastrowid


def _resolve_alias(conn, *, provider, sport_code, raw_alias, season):
    row = conn.execute(
        "SELECT team_id FROM football_team_aliases "
        "WHERE provider = ? AND sport_code = ? AND alias_key = lower(trim(?)) "
        "AND effective_from_season <= ? "
        "ORDER BY effective_from_season DESC, id DESC LIMIT 1",
        (provider, sport_code, raw_alias, season),
    ).fetchone()
    return None if row is None else row[0]


def _insert_event(
    conn,
    *,
    key,
    sport_code,
    season,
    home_team_id,
    away_team_id,
    venue_id,
    week=1,
    neutral=0,
    kickoff="2026-08-30T17:00:00+00:00",
    created_at="2026-08-20T12:00:00+00:00",
):
    return conn.execute(
        "INSERT INTO football_events "
        "(canonical_event_key, sport_code, league_season, season_type, "
        "sport_week, home_team_id, away_team_id, kickoff_at, venue_id, "
        "neutral_site, status, created_at, provenance) "
        "VALUES (?, ?, ?, 'regular', ?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)",
        (
            key,
            sport_code,
            season,
            week,
            home_team_id,
            away_team_id,
            kickoff,
            venue_id,
            neutral,
            created_at,
            PROVENANCE,
        ),
    ).lastrowid


def _event_state_as_of(conn, event_id, as_of):
    revision = conn.execute(
        "SELECT home_team_id, away_team_id, kickoff_at, venue_id, neutral_site, status "
        "FROM football_event_revisions "
        "WHERE event_id = ? AND julianday(recorded_at) <= julianday(?) "
        "ORDER BY revision_number DESC LIMIT 1",
        (event_id, as_of),
    ).fetchone()
    if revision is not None:
        return tuple(revision)
    return tuple(
        conn.execute(
            "SELECT home_team_id, away_team_id, kickoff_at, venue_id, "
            "neutral_site, status FROM football_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    )


def test_sport_registry_seeds_only_immutable_ncaa_and_nfl(temp_db):
    conn = temp_db.get_connection()
    assert list(
        conn.execute(
            "SELECT sport_code, display_name FROM football_sports ORDER BY sport_code"
        )
    ) == [("NCAA", "NCAA Football"), ("NFL", "NFL")]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO football_sports VALUES "
            "('CFL', 'Canadian Football League', 'CFL', ?, ?)",
            (RECORDED_AT, PROVENANCE),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE football_sports SET display_name = 'Changed' "
            "WHERE sport_code = 'NCAA'"
        )
    conn.close()


def test_franchise_team_history_represents_ncaa_program_and_nfl_relocation(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)

    ncaa = conn.execute(
        "SELECT franchise.sport_code, team.display_name, team.effective_from_season "
        "FROM football_franchises AS franchise "
        "JOIN football_teams AS team ON team.franchise_id = franchise.id "
        "WHERE franchise.id = ?",
        (refs["franchises"]["fixture_state"],),
    ).fetchall()
    nfl_history = conn.execute(
        "SELECT display_name, effective_from_season FROM football_teams "
        "WHERE franchise_id = ? ORDER BY effective_from_season",
        (refs["franchises"]["nomads"],),
    ).fetchall()

    assert ncaa == [("NCAA", "Fixture State", 1900)]
    assert nfl_history == [
        ("Coast City Nomads", 1995),
        ("Mountain City Nomads", 2020),
    ]
    conn.close()


def test_team_and_season_alignment_require_active_same_sport_identity(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)

    with pytest.raises(sqlite3.IntegrityError, match="franchise"):
        conn.execute(
            "INSERT INTO football_teams "
            "(franchise_id, sport_code, canonical_key, display_name, "
            "effective_from_season, created_at, provenance) "
            "VALUES (?, 'NFL', 'invalid-cross-sport', 'Invalid', 2020, ?, ?)",
            (refs["franchises"]["fixture_state"], RECORDED_AT, PROVENANCE),
        )

    conn.execute(
        "INSERT INTO football_team_seasons "
        "(team_id, sport_code, league_season, effective_from_at, "
        "conference_name, division_name, classification, recorded_at, provenance) "
        "VALUES (?, 'NCAA', 2026, '2026-07-01T00:00:00+00:00', "
        "'Fixture Conference', 'East', 'FBS', ?, ?)",
        (refs["teams"]["fixture_state"], RECORDED_AT, PROVENANCE),
    )
    conn.execute(
        "INSERT INTO football_team_seasons "
        "(team_id, sport_code, league_season, effective_from_at, "
        "conference_name, division_name, classification, recorded_at, provenance) "
        "VALUES (?, 'NFL', 2019, '2019-07-01T00:00:00+00:00', "
        "'AFC', 'West', 'NFL', ?, ?)",
        (refs["teams"]["coast_nomads"], RECORDED_AT, PROVENANCE),
    )
    conn.execute(
        "INSERT INTO football_team_seasons "
        "(team_id, sport_code, league_season, effective_from_at, "
        "conference_name, division_name, classification, recorded_at, provenance) "
        "VALUES (?, 'NFL', 2026, '2026-07-01T00:00:00+00:00', "
        "'AFC', 'West', 'NFL', ?, ?)",
        (refs["teams"]["mountain_nomads"], RECORDED_AT, PROVENANCE),
    )

    with pytest.raises(sqlite3.IntegrityError, match="active team sport"):
        conn.execute(
            "INSERT INTO football_team_seasons "
            "(team_id, sport_code, league_season, effective_from_at, "
            "classification, recorded_at, provenance) "
            "VALUES (?, 'NFL', 2026, '2026-07-01T00:00:00+00:00', "
            "'NFL', ?, ?)",
            (refs["teams"]["coast_nomads"], RECORDED_AT, PROVENANCE),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO football_team_seasons "
            "(team_id, sport_code, league_season, effective_from_at, "
            "classification, recorded_at, provenance) "
            "VALUES (?, 'NCAA', 2027, '2027-07-01T00:00:00+00:00', "
            "'NFL', '2027-07-02T00:00:00+00:00', ?)",
            (refs["teams"]["fixture_state"], PROVENANCE),
        )
    conn.close()


def test_alias_resolution_is_exact_sport_scoped_and_revision_controlled(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    ncaa_alias = _insert_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tigers",
        team_id=refs["teams"]["fixture_state"],
        season=1900,
    )
    _insert_alias(
        conn,
        provider="fixture-admin",
        sport_code="NFL",
        raw_alias="Tigers",
        team_id=refs["teams"]["mountain_nomads"],
        season=2020,
    )

    assert _resolve_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tigers",
        season=2026,
    ) == refs["teams"]["fixture_state"]
    assert _resolve_alias(
        conn,
        provider="fixture-admin",
        sport_code="NFL",
        raw_alias="Tigers",
        season=2026,
    ) == refs["teams"]["mountain_nomads"]
    assert _resolve_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tiger",
        season=2026,
    ) is None

    with pytest.raises(sqlite3.IntegrityError, match="ambiguous"):
        _insert_alias(
            conn,
            provider="fixture-admin",
            sport_code="NCAA",
            raw_alias="Tigers",
            team_id=refs["teams"]["lake_tech"],
            season=2020,
        )
    later = _insert_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tigers",
        team_id=refs["teams"]["lake_tech"],
        season=2030,
        supersedes=ncaa_alias,
    )
    assert later > ncaa_alias
    assert _resolve_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tigers",
        season=2029,
    ) == refs["teams"]["fixture_state"]
    assert _resolve_alias(
        conn,
        provider="fixture-admin",
        sport_code="NCAA",
        raw_alias="Tigers",
        season=2030,
    ) == refs["teams"]["lake_tech"]
    conn.close()


def test_venue_versions_preserve_exact_location_and_rename_history(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    rows = list(
        conn.execute(
            "SELECT display_name, latitude_e6, longitude_e6, time_zone, "
            "roof_type, surface, effective_from_at "
            "FROM football_venue_versions WHERE venue_id = ? "
            "ORDER BY effective_from_at",
            (refs["venues"]["fixture_stadium"],),
        )
    )
    assert rows == [
        (
            "Old Fixture Stadium",
            40123456,
            -75123456,
            "America/New_York",
            "outdoor",
            "grass",
            "2000-01-01T00:00:00+00:00",
        ),
        (
            "Fixture Stadium",
            40123456,
            -75123456,
            "America/New_York",
            "outdoor",
            "grass",
            "2020-01-01T00:00:00+00:00",
        ),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO football_venue_versions "
            "(venue_id, display_name, latitude_e6, longitude_e6, time_zone, "
            "effective_from_at, supersedes_venue_version_id, recorded_at, provenance) "
            "VALUES (?, 'Invalid Coordinates', 90000001, 0, 'UTC', "
            "'2030-01-01T00:00:00+00:00', ?, '2030-01-01T00:00:00+00:00', ?)",
            (
                refs["venues"]["fixture_stadium"],
                refs["venue_versions"]["fixture_stadium"],
                PROVENANCE,
            ),
        )
    conn.close()


def test_ncaa_nfl_and_neutral_events_are_distinct_and_sport_safe(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    ncaa_event = _insert_event(
        conn,
        key="ncaa-2026-fixture-state-lake-tech",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["fixture_state"],
        away_team_id=refs["teams"]["lake_tech"],
        venue_id=refs["venues"]["fixture_stadium"],
        neutral=1,
    )
    nfl_event = _insert_event(
        conn,
        key="nfl-2026-nomads-capitals",
        sport_code="NFL",
        season=2026,
        home_team_id=refs["teams"]["mountain_nomads"],
        away_team_id=refs["teams"]["capital_club"],
        venue_id=refs["venues"]["international_ground"],
    )

    assert conn.execute(
        "SELECT sport_code, neutral_site FROM football_events WHERE id = ?",
        (ncaa_event,),
    ).fetchone() == ("NCAA", 1)
    assert conn.execute(
        "SELECT sport_code, neutral_site FROM football_events WHERE id = ?",
        (nfl_event,),
    ).fetchone() == ("NFL", 0)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_event(
            conn,
            key="invalid-same-team",
            sport_code="NCAA",
            season=2026,
            home_team_id=refs["teams"]["fixture_state"],
            away_team_id=refs["teams"]["fixture_state"],
            venue_id=refs["venues"]["fixture_stadium"],
        )
    with pytest.raises(sqlite3.IntegrityError, match="active sport"):
        _insert_event(
            conn,
            key="invalid-cross-sport",
            sport_code="NCAA",
            season=2026,
            home_team_id=refs["teams"]["fixture_state"],
            away_team_id=refs["teams"]["capital_club"],
            venue_id=refs["venues"]["fixture_stadium"],
        )
    conn.close()


def test_provider_event_ids_are_unique_and_match_event_sport(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    event_id = _insert_event(
        conn,
        key="nfl-provider-id-fixture",
        sport_code="NFL",
        season=2026,
        home_team_id=refs["teams"]["mountain_nomads"],
        away_team_id=refs["teams"]["capital_club"],
        venue_id=refs["venues"]["fixture_stadium"],
    )
    conn.execute(
        "INSERT INTO football_provider_event_ids "
        "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
        "VALUES ('fixture-provider', 'NFL', 'event-123', ?, ?, ?)",
        (event_id, RECORDED_AT, PROVENANCE),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO football_provider_event_ids "
            "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
            "VALUES ('fixture-provider', 'NFL', 'event-123', ?, ?, ?)",
            (event_id, RECORDED_AT, PROVENANCE),
        )
    with pytest.raises(sqlite3.IntegrityError, match="sport"):
        conn.execute(
            "INSERT INTO football_provider_event_ids "
            "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
            "VALUES ('fixture-provider', 'NCAA', 'event-456', ?, ?, ?)",
            (event_id, RECORDED_AT, PROVENANCE),
        )
    conn.close()


def test_legacy_cfb_link_requires_exact_ncaa_alias_match_and_kickoff(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    for team_id, school in ((1, "Fixture State"), (2, "Lake Tech")):
        conn.execute(
            "INSERT INTO teams (team_id, school, conference) VALUES (?, ?, 'Fixture')",
            (team_id, school),
        )
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site) VALUES "
        "(7001, 2026, 1, 'regular', '2026-08-30T17:00:00+00:00', "
        "'Fixture State', 'Lake Tech', 1)"
    )
    _insert_alias(
        conn,
        provider="legacy_cfb",
        sport_code="NCAA",
        raw_alias="Fixture State",
        team_id=refs["teams"]["fixture_state"],
        season=1900,
    )
    _insert_alias(
        conn,
        provider="legacy_cfb",
        sport_code="NCAA",
        raw_alias="Lake Tech",
        team_id=refs["teams"]["lake_tech"],
        season=1900,
    )
    ncaa_event = _insert_event(
        conn,
        key="legacy-cfb-7001",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["fixture_state"],
        away_team_id=refs["teams"]["lake_tech"],
        venue_id=refs["venues"]["fixture_stadium"],
        neutral=1,
    )
    conn.execute(
        "INSERT INTO legacy_cfb_game_links "
        "(legacy_game_id, football_event_id, link_policy_version, linked_at, provenance) "
        "VALUES (7001, ?, 'legacy_cfb_exact_v1', ?, ?)",
        (ncaa_event, RECORDED_AT, PROVENANCE),
    )

    nfl_event = _insert_event(
        conn,
        key="nfl-not-a-legacy-cfb-link",
        sport_code="NFL",
        season=2026,
        home_team_id=refs["teams"]["mountain_nomads"],
        away_team_id=refs["teams"]["capital_club"],
        venue_id=refs["venues"]["fixture_stadium"],
        neutral=1,
    )
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site) VALUES "
        "(7002, 2026, 1, 'regular', '2026-08-30T17:00:00+00:00', "
        "'Fixture State', 'Lake Tech', 1)"
    )
    with pytest.raises(sqlite3.IntegrityError, match="exact NCAA"):
        conn.execute(
            "INSERT INTO legacy_cfb_game_links "
            "(legacy_game_id, football_event_id, link_policy_version, "
            "linked_at, provenance) "
            "VALUES (7002, ?, 'legacy_cfb_exact_v1', ?, ?)",
            (nfl_event, RECORDED_AT, PROVENANCE),
        )

    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site) VALUES "
        "(7003, 2026, 1, 'regular', '2026-08-30T17:00:00+00:00', "
        "'Fixture State', 'Lake Tech', 1)"
    )
    wrong_kickoff_event = _insert_event(
        conn,
        key="legacy-cfb-7003-wrong-kickoff",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["fixture_state"],
        away_team_id=refs["teams"]["lake_tech"],
        venue_id=refs["venues"]["fixture_stadium"],
        neutral=1,
        kickoff="2026-08-30T17:00:01+00:00",
    )
    with pytest.raises(sqlite3.IntegrityError, match="exact NCAA"):
        conn.execute(
            "INSERT INTO legacy_cfb_game_links "
            "(legacy_game_id, football_event_id, link_policy_version, "
            "linked_at, provenance) "
            "VALUES (7003, ?, 'legacy_cfb_exact_v1', ?, ?)",
            (wrong_kickoff_event, RECORDED_AT, PROVENANCE),
        )

    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site) VALUES "
        "(7004, 2026, 1, 'regular', '2026-08-30T17:00:00+00:00', "
        "'Fixture State', 'Lake Tech', 1)"
    )
    reversed_event = _insert_event(
        conn,
        key="legacy-cfb-7004-reversed-teams",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["lake_tech"],
        away_team_id=refs["teams"]["fixture_state"],
        venue_id=refs["venues"]["fixture_stadium"],
        neutral=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="exact NCAA"):
        conn.execute(
            "INSERT INTO legacy_cfb_game_links "
            "(legacy_game_id, football_event_id, link_policy_version, "
            "linked_at, provenance) "
            "VALUES (7004, ?, 'legacy_cfb_exact_v1', ?, ?)",
            (reversed_event, RECORDED_AT, PROVENANCE),
        )
    conn.close()


def test_event_revisions_are_append_only_sequential_and_reconstruct_as_of(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    event_id = _insert_event(
        conn,
        key="ncaa-event-revision-fixture",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["fixture_state"],
        away_team_id=refs["teams"]["lake_tech"],
        venue_id=refs["venues"]["fixture_stadium"],
    )
    revision_1 = conn.execute(
        "INSERT INTO football_event_revisions "
        "(event_id, revision_number, supersedes_revision_id, home_team_id, "
        "away_team_id, kickoff_at, venue_id, neutral_site, status, recorded_at, "
        "reason, recorded_by, provenance) "
        "VALUES (?, 1, NULL, ?, ?, '2026-08-30T18:00:00+00:00', ?, 0, "
        "'scheduled', '2026-08-21T12:00:00+00:00', "
        "'Verified kickoff correction', 'fixture-reviewer', ?)",
        (
            event_id,
            refs["teams"]["fixture_state"],
            refs["teams"]["lake_tech"],
            refs["venues"]["fixture_stadium"],
            PROVENANCE,
        ),
    ).lastrowid
    revision_2 = conn.execute(
        "INSERT INTO football_event_revisions "
        "(event_id, revision_number, supersedes_revision_id, home_team_id, "
        "away_team_id, kickoff_at, venue_id, neutral_site, status, recorded_at, "
        "reason, recorded_by, provenance) "
        "VALUES (?, 2, ?, ?, ?, '2026-08-30T18:00:00+00:00', ?, 1, "
        "'scheduled', '2026-08-22T12:00:00+00:00', "
        "'Verified neutral-site correction', 'fixture-reviewer', ?)",
        (
            event_id,
            revision_1,
            refs["teams"]["fixture_state"],
            refs["teams"]["lake_tech"],
            refs["venues"]["international_ground"],
            PROVENANCE,
        ),
    ).lastrowid

    assert _event_state_as_of(
        conn, event_id, "2026-08-20T18:00:00+00:00"
    )[2:] == (
        "2026-08-30T17:00:00+00:00",
        refs["venues"]["fixture_stadium"],
        0,
        "scheduled",
    )
    assert _event_state_as_of(
        conn, event_id, "2026-08-21T18:00:00+00:00"
    )[2:] == (
        "2026-08-30T18:00:00+00:00",
        refs["venues"]["fixture_stadium"],
        0,
        "scheduled",
    )
    assert _event_state_as_of(
        conn, event_id, "2026-08-22T18:00:00+00:00"
    )[2:] == (
        "2026-08-30T18:00:00+00:00",
        refs["venues"]["international_ground"],
        1,
        "scheduled",
    )

    with pytest.raises(sqlite3.IntegrityError, match="out of sequence"):
        conn.execute(
            "INSERT INTO football_event_revisions "
            "(event_id, revision_number, supersedes_revision_id, home_team_id, "
            "away_team_id, kickoff_at, venue_id, neutral_site, status, recorded_at, "
            "reason, recorded_by, provenance) "
            "VALUES (?, 4, ?, ?, ?, '2026-08-30T19:00:00+00:00', ?, 1, "
            "'scheduled', '2026-08-23T12:00:00+00:00', "
            "'Invalid skipped revision', 'fixture-reviewer', ?)",
            (
                event_id,
                revision_2,
                refs["teams"]["fixture_state"],
                refs["teams"]["lake_tech"],
                refs["venues"]["international_ground"],
                PROVENANCE,
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE football_event_revisions SET reason = 'Changed' WHERE id = ?",
            (revision_1,),
        )
    conn.close()


def test_all_accepted_identity_records_reject_update_and_delete(temp_db):
    conn = temp_db.get_connection()
    refs = _load_fixture(conn)
    team_season_id = conn.execute(
        "INSERT INTO football_team_seasons "
        "(team_id, sport_code, league_season, effective_from_at, "
        "conference_name, classification, recorded_at, provenance) "
        "VALUES (?, 'NCAA', 2026, '2026-07-01T00:00:00+00:00', "
        "'Fixture Conference', 'FBS', ?, ?)",
        (refs["teams"]["fixture_state"], RECORDED_AT, PROVENANCE),
    ).lastrowid
    home_alias_id = _insert_alias(
        conn,
        provider="legacy_cfb",
        sport_code="NCAA",
        raw_alias="Fixture State",
        team_id=refs["teams"]["fixture_state"],
        season=1900,
    )
    _insert_alias(
        conn,
        provider="legacy_cfb",
        sport_code="NCAA",
        raw_alias="Lake Tech",
        team_id=refs["teams"]["lake_tech"],
        season=1900,
    )
    event_id = _insert_event(
        conn,
        key="immutable-identity-event",
        sport_code="NCAA",
        season=2026,
        home_team_id=refs["teams"]["fixture_state"],
        away_team_id=refs["teams"]["lake_tech"],
        venue_id=refs["venues"]["fixture_stadium"],
    )
    revision_id = conn.execute(
        "INSERT INTO football_event_revisions "
        "(event_id, revision_number, home_team_id, away_team_id, kickoff_at, "
        "venue_id, neutral_site, status, recorded_at, reason, recorded_by, provenance) "
        "VALUES (?, 1, ?, ?, '2026-08-30T18:00:00+00:00', ?, 0, 'scheduled', "
        "'2026-08-21T12:00:00+00:00', 'Verified kickoff', 'fixture-reviewer', ?)",
        (
            event_id,
            refs["teams"]["fixture_state"],
            refs["teams"]["lake_tech"],
            refs["venues"]["fixture_stadium"],
            PROVENANCE,
        ),
    ).lastrowid
    provider_id = conn.execute(
        "INSERT INTO football_provider_event_ids "
        "(provider, sport_code, provider_event_id, event_id, observed_at, provenance) "
        "VALUES ('fixture-provider', 'NCAA', 'immutable-event-id', ?, ?, ?)",
        (event_id, RECORDED_AT, PROVENANCE),
    ).lastrowid
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site) VALUES "
        "(7101, 2026, 1, 'regular', '2026-08-30T18:00:00+00:00', "
        "'Fixture State', 'Lake Tech', 0)"
    )
    conn.execute(
        "INSERT INTO legacy_cfb_game_links "
        "(legacy_game_id, football_event_id, link_policy_version, linked_at, provenance) "
        "VALUES (7101, ?, 'legacy_cfb_exact_v1', ?, ?)",
        (event_id, RECORDED_AT, PROVENANCE),
    )
    conn.commit()

    records = (
        ("football_sports", "sport_code", "NCAA"),
        ("football_franchises", "id", refs["franchises"]["fixture_state"]),
        ("football_teams", "id", refs["teams"]["fixture_state"]),
        ("football_team_seasons", "id", team_season_id),
        ("football_team_aliases", "id", home_alias_id),
        ("football_venues", "id", refs["venues"]["fixture_stadium"]),
        (
            "football_venue_versions",
            "id",
            refs["venue_versions"]["fixture_stadium"],
        ),
        ("football_events", "id", event_id),
        ("football_event_revisions", "id", revision_id),
        ("football_provider_event_ids", "id", provider_id),
        ("legacy_cfb_game_links", "legacy_game_id", 7101),
    )
    for table, key_column, key_value in records:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                f"UPDATE {table} SET provenance = provenance WHERE {key_column} = ?",
                (key_value,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                f"DELETE FROM {table} WHERE {key_column} = ?",
                (key_value,),
            )
    conn.close()


def test_migration_seeds_no_identity_data_or_legacy_links_beyond_sports(temp_db):
    conn = temp_db.get_connection()
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "football_sports",
            "football_franchises",
            "football_teams",
            "football_team_seasons",
            "football_team_aliases",
            "football_venues",
            "football_venue_versions",
            "football_events",
            "football_event_revisions",
            "football_provider_event_ids",
            "legacy_cfb_game_links",
        )
    }
    assert counts == {
        "football_sports": 2,
        "football_franchises": 0,
        "football_teams": 0,
        "football_team_seasons": 0,
        "football_team_aliases": 0,
        "football_venues": 0,
        "football_venue_versions": 0,
        "football_events": 0,
        "football_event_revisions": 0,
        "football_provider_event_ids": 0,
        "legacy_cfb_game_links": 0,
    }
    conn.close()


def test_migration_registration_and_schema_drift_verification(temp_db):
    conn = temp_db.get_connection()
    assert conn.execute(
        "SELECT name FROM schema_migrations WHERE version = 19"
    ).fetchone() == ("football_identity_foundation",)

    conn.execute("DROP TRIGGER legacy_cfb_game_links_validate")
    conn.commit()
    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()
