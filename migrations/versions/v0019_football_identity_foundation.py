"""Add the dormant, sport-aware canonical football identity foundation.

The migration is additive. It seeds only the immutable NCAA/NFL sport registry,
creates no legacy-game links, and does not alter any Product A table or row.
Recovery is restoration of the verified pre-migration database copy followed by
a new forward migration; accepted identity history is never edited in place.
"""

from __future__ import annotations

import sqlite3


VERSION = 19
NAME = "football_identity_foundation"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_KEY_CHECK = (
    "length({column}) > 0 "
    "AND {column} = lower(trim({column})) "
    "AND {column} NOT GLOB '*[^a-z0-9-]*'"
)


STATEMENTS = (
    f"""
    CREATE TABLE football_sports (
        sport_code TEXT PRIMARY KEY
            CHECK (sport_code IN ('NCAA', 'NFL')),
        league_name TEXT NOT NULL CHECK (length(trim(league_name)) > 0),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    INSERT INTO football_sports
        (sport_code, league_name, display_name, created_at, provenance)
    VALUES
        (
            'NCAA',
            'National Collegiate Athletic Association football',
            'NCAA Football',
            '2026-08-27T00:00:00+00:00',
            'migration:v0019:approved-phase-0-registry'
        ),
        (
            'NFL',
            'National Football League',
            'NFL',
            '2026-08-27T00:00:00+00:00',
            'migration:v0019:approved-phase-0-registry'
        )
    """,
    f"""
    CREATE TABLE football_franchises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport_code TEXT NOT NULL,
        canonical_key TEXT NOT NULL
            CHECK ({_KEY_CHECK.format(column='canonical_key')}),
        display_label TEXT NOT NULL CHECK (length(trim(display_label)) > 0),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (sport_code, canonical_key),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code)
    )
    """,
    f"""
    CREATE TABLE football_teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        franchise_id INTEGER NOT NULL,
        sport_code TEXT NOT NULL,
        canonical_key TEXT NOT NULL
            CHECK ({_KEY_CHECK.format(column='canonical_key')}),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        effective_from_season INTEGER NOT NULL
            CHECK (effective_from_season >= 1869),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (sport_code, canonical_key),
        UNIQUE (franchise_id, effective_from_season),
        FOREIGN KEY (franchise_id) REFERENCES football_franchises(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code)
    )
    """,
    f"""
    CREATE TABLE football_team_seasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        sport_code TEXT NOT NULL,
        league_season INTEGER NOT NULL CHECK (league_season >= 1869),
        effective_from_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='effective_from_at')}),
        conference_name TEXT CHECK (
            conference_name IS NULL OR length(trim(conference_name)) > 0
        ),
        division_name TEXT CHECK (
            division_name IS NULL OR length(trim(division_name)) > 0
        ),
        classification TEXT CHECK (
            classification IS NULL
            OR (
                sport_code = 'NCAA'
                AND classification IN ('FBS', 'FCS', 'other')
            )
            OR (
                sport_code = 'NFL'
                AND classification IN ('NFL', 'other')
            )
        ),
        recorded_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (julianday(recorded_at) >= julianday(effective_from_at)),
        UNIQUE (team_id, league_season, effective_from_at),
        FOREIGN KEY (team_id) REFERENCES football_teams(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code)
    )
    """,
    f"""
    CREATE TABLE football_team_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        sport_code TEXT NOT NULL,
        raw_alias TEXT NOT NULL CHECK (length(trim(raw_alias)) > 0),
        alias_key TEXT NOT NULL CHECK (
            length(alias_key) > 0
            AND alias_key = lower(trim(raw_alias))
        ),
        team_id INTEGER NOT NULL,
        effective_from_season INTEGER NOT NULL
            CHECK (effective_from_season >= 1869),
        supersedes_alias_id INTEGER UNIQUE,
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (provider, sport_code, alias_key, effective_from_season),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (team_id) REFERENCES football_teams(id),
        FOREIGN KEY (supersedes_alias_id) REFERENCES football_team_aliases(id)
    )
    """,
    f"""
    CREATE TABLE football_venues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_key TEXT NOT NULL UNIQUE
            CHECK ({_KEY_CHECK.format(column='canonical_key')}),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE football_venue_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        venue_id INTEGER NOT NULL,
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        latitude_e6 INTEGER CHECK (
            latitude_e6 IS NULL
            OR (latitude_e6 >= -90000000 AND latitude_e6 <= 90000000)
        ),
        longitude_e6 INTEGER CHECK (
            longitude_e6 IS NULL
            OR (longitude_e6 >= -180000000 AND longitude_e6 <= 180000000)
        ),
        time_zone TEXT NOT NULL CHECK (
            time_zone = 'UTC'
            OR (
                instr(time_zone, '/') > 1
                AND instr(time_zone, ' ') = 0
            )
        ),
        roof_type TEXT CHECK (
            roof_type IS NULL
            OR roof_type IN ('outdoor', 'dome', 'retractable')
        ),
        surface TEXT CHECK (
            surface IS NULL OR length(trim(surface)) > 0
        ),
        effective_from_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='effective_from_at')}),
        supersedes_venue_version_id INTEGER UNIQUE,
        recorded_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (julianday(recorded_at) >= julianday(effective_from_at)),
        UNIQUE (venue_id, effective_from_at),
        FOREIGN KEY (venue_id) REFERENCES football_venues(id),
        FOREIGN KEY (supersedes_venue_version_id)
            REFERENCES football_venue_versions(id)
    )
    """,
    f"""
    CREATE TABLE football_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_event_key TEXT NOT NULL
            CHECK (length(trim(canonical_event_key)) > 0),
        sport_code TEXT NOT NULL,
        league_season INTEGER NOT NULL CHECK (league_season >= 1869),
        season_type TEXT NOT NULL CHECK (
            season_type IN ('preseason', 'regular', 'postseason', 'other')
        ),
        sport_week INTEGER CHECK (sport_week IS NULL OR sport_week >= 0),
        sport_round_label TEXT CHECK (
            sport_round_label IS NULL OR length(trim(sport_round_label)) > 0
        ),
        home_team_id INTEGER NOT NULL,
        away_team_id INTEGER NOT NULL,
        kickoff_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='kickoff_at')}),
        venue_id INTEGER,
        neutral_site INTEGER NOT NULL DEFAULT 0
            CHECK (neutral_site IN (0, 1)),
        status TEXT NOT NULL CHECK (
            status IN (
                'scheduled', 'in_progress', 'final',
                'postponed', 'cancelled', 'suspended'
            )
        ),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (home_team_id != away_team_id),
        CHECK (sport_week IS NOT NULL OR sport_round_label IS NOT NULL),
        UNIQUE (sport_code, canonical_event_key),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (home_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (away_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (venue_id) REFERENCES football_venues(id)
    )
    """,
    f"""
    CREATE TABLE football_event_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
        supersedes_revision_id INTEGER UNIQUE,
        home_team_id INTEGER NOT NULL,
        away_team_id INTEGER NOT NULL,
        kickoff_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='kickoff_at')}),
        venue_id INTEGER,
        neutral_site INTEGER NOT NULL CHECK (neutral_site IN (0, 1)),
        status TEXT NOT NULL CHECK (
            status IN (
                'scheduled', 'in_progress', 'final',
                'postponed', 'cancelled', 'suspended'
            )
        ),
        recorded_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        recorded_by TEXT NOT NULL CHECK (length(trim(recorded_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (home_team_id != away_team_id),
        UNIQUE (event_id, revision_number),
        FOREIGN KEY (event_id) REFERENCES football_events(id),
        FOREIGN KEY (supersedes_revision_id)
            REFERENCES football_event_revisions(id),
        FOREIGN KEY (home_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (away_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (venue_id) REFERENCES football_venues(id)
    )
    """,
    f"""
    CREATE TABLE football_provider_event_ids (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        sport_code TEXT NOT NULL,
        provider_event_id TEXT NOT NULL
            CHECK (length(trim(provider_event_id)) > 0),
        event_id INTEGER NOT NULL,
        observed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='observed_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (provider, sport_code, provider_event_id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (event_id) REFERENCES football_events(id)
    )
    """,
    f"""
    CREATE TABLE legacy_cfb_game_links (
        legacy_game_id INTEGER PRIMARY KEY,
        football_event_id INTEGER NOT NULL UNIQUE,
        link_policy_version TEXT NOT NULL
            CHECK (link_policy_version = 'legacy_cfb_exact_v1'),
        linked_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='linked_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (legacy_game_id) REFERENCES games(game_id),
        FOREIGN KEY (football_event_id) REFERENCES football_events(id)
    )
    """,
    """
    CREATE INDEX idx_football_teams_effective
    ON football_teams (sport_code, franchise_id, effective_from_season)
    """,
    """
    CREATE INDEX idx_football_team_seasons_alignment
    ON football_team_seasons (
        sport_code, league_season, team_id, effective_from_at
    )
    """,
    """
    CREATE INDEX idx_football_team_aliases_resolution
    ON football_team_aliases (
        provider, sport_code, alias_key, effective_from_season
    )
    """,
    """
    CREATE INDEX idx_football_venue_versions_effective
    ON football_venue_versions (venue_id, effective_from_at)
    """,
    """
    CREATE INDEX idx_football_events_schedule
    ON football_events (
        sport_code, league_season, season_type, sport_week, kickoff_at
    )
    """,
    """
    CREATE INDEX idx_football_event_revisions_history
    ON football_event_revisions (event_id, revision_number, recorded_at)
    """,
    """
    CREATE INDEX idx_football_provider_event_ids_event
    ON football_provider_event_ids (event_id, provider, sport_code)
    """,
    """
    CREATE TRIGGER football_teams_validate_franchise_sport
    BEFORE INSERT ON football_teams
    WHEN NOT EXISTS (
        SELECT 1
        FROM football_franchises AS franchise
        WHERE franchise.id = NEW.franchise_id
          AND franchise.sport_code = NEW.sport_code
    )
    BEGIN
        SELECT RAISE(ABORT, 'football team sport does not match its franchise');
    END
    """,
    """
    CREATE TRIGGER football_team_seasons_validate_team_sport
    BEFORE INSERT ON football_team_seasons
    WHEN NOT EXISTS (
        SELECT 1
        FROM football_teams AS team
        WHERE team.id = NEW.team_id
          AND team.sport_code = NEW.sport_code
          AND team.effective_from_season <= NEW.league_season
          AND NOT EXISTS (
              SELECT 1
              FROM football_teams AS newer
              WHERE newer.franchise_id = team.franchise_id
                AND newer.effective_from_season <= NEW.league_season
                AND newer.effective_from_season > team.effective_from_season
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'team-season alignment does not match active team sport');
    END
    """,
    """
    CREATE TRIGGER football_team_aliases_validate_target
    BEFORE INSERT ON football_team_aliases
    WHEN NOT EXISTS (
        SELECT 1
        FROM football_teams AS team
        WHERE team.id = NEW.team_id
          AND team.sport_code = NEW.sport_code
          AND team.effective_from_season <= NEW.effective_from_season
          AND NOT EXISTS (
              SELECT 1
              FROM football_teams AS newer
              WHERE newer.franchise_id = team.franchise_id
                AND newer.effective_from_season <= NEW.effective_from_season
                AND newer.effective_from_season > team.effective_from_season
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'football alias target does not match active team sport');
    END
    """,
    """
    CREATE TRIGGER football_team_aliases_validate_chain
    BEFORE INSERT ON football_team_aliases
    WHEN NOT (
        (
            NEW.supersedes_alias_id IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM football_team_aliases AS existing
                WHERE existing.provider = NEW.provider
                  AND existing.sport_code = NEW.sport_code
                  AND existing.alias_key = NEW.alias_key
            )
        )
        OR EXISTS (
            SELECT 1
            FROM football_team_aliases AS prior
            WHERE prior.id = NEW.supersedes_alias_id
              AND prior.provider = NEW.provider
              AND prior.sport_code = NEW.sport_code
              AND prior.alias_key = NEW.alias_key
              AND prior.effective_from_season < NEW.effective_from_season
              AND prior.id = (
                  SELECT latest.id
                  FROM football_team_aliases AS latest
                  WHERE latest.provider = NEW.provider
                    AND latest.sport_code = NEW.sport_code
                    AND latest.alias_key = NEW.alias_key
                  ORDER BY latest.effective_from_season DESC, latest.id DESC
                  LIMIT 1
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'football alias is ambiguous or lacks explicit supersession');
    END
    """,
    """
    CREATE TRIGGER football_venue_versions_validate_chain
    BEFORE INSERT ON football_venue_versions
    WHEN NOT (
        (
            NEW.supersedes_venue_version_id IS NULL
            AND NOT EXISTS (
                SELECT 1
                FROM football_venue_versions AS existing
                WHERE existing.venue_id = NEW.venue_id
            )
        )
        OR EXISTS (
            SELECT 1
            FROM football_venue_versions AS prior
            WHERE prior.id = NEW.supersedes_venue_version_id
              AND prior.venue_id = NEW.venue_id
              AND julianday(prior.effective_from_at)
                    < julianday(NEW.effective_from_at)
              AND prior.id = (
                  SELECT latest.id
                  FROM football_venue_versions AS latest
                  WHERE latest.venue_id = NEW.venue_id
                  ORDER BY julianday(latest.effective_from_at) DESC, latest.id DESC
                  LIMIT 1
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'venue version is ambiguous or lacks explicit supersession');
    END
    """,
    """
    CREATE TRIGGER football_events_validate_teams
    BEFORE INSERT ON football_events
    WHEN NOT (
        EXISTS (
            SELECT 1
            FROM football_teams AS team
            WHERE team.id = NEW.home_team_id
              AND team.sport_code = NEW.sport_code
              AND team.effective_from_season <= NEW.league_season
              AND NOT EXISTS (
                  SELECT 1
                  FROM football_teams AS newer
                  WHERE newer.franchise_id = team.franchise_id
                    AND newer.effective_from_season <= NEW.league_season
                    AND newer.effective_from_season > team.effective_from_season
              )
        )
        AND EXISTS (
            SELECT 1
            FROM football_teams AS team
            WHERE team.id = NEW.away_team_id
              AND team.sport_code = NEW.sport_code
              AND team.effective_from_season <= NEW.league_season
              AND NOT EXISTS (
                  SELECT 1
                  FROM football_teams AS newer
                  WHERE newer.franchise_id = team.franchise_id
                    AND newer.effective_from_season <= NEW.league_season
                    AND newer.effective_from_season > team.effective_from_season
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'football event teams do not match active sport identity');
    END
    """,
    """
    CREATE TRIGGER football_event_revisions_validate
    BEFORE INSERT ON football_event_revisions
    WHEN NOT EXISTS (
        SELECT 1
        FROM football_events AS event
        WHERE event.id = NEW.event_id
          AND NEW.revision_number = COALESCE(
              (
                  SELECT MAX(existing.revision_number)
                  FROM football_event_revisions AS existing
                  WHERE existing.event_id = NEW.event_id
              ),
              0
          ) + 1
          AND (
              (
                  NEW.revision_number = 1
                  AND NEW.supersedes_revision_id IS NULL
              )
              OR EXISTS (
                  SELECT 1
                  FROM football_event_revisions AS prior
                  WHERE prior.id = NEW.supersedes_revision_id
                    AND prior.event_id = NEW.event_id
                    AND prior.revision_number = NEW.revision_number - 1
                    AND prior.revision_number = (
                        SELECT MAX(latest.revision_number)
                        FROM football_event_revisions AS latest
                        WHERE latest.event_id = NEW.event_id
                    )
              )
          )
          AND julianday(NEW.recorded_at) > julianday(
              COALESCE(
                  (
                      SELECT latest.recorded_at
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.created_at
              )
          )
          AND EXISTS (
              SELECT 1
              FROM football_teams AS team
              WHERE team.id = NEW.home_team_id
                AND team.sport_code = event.sport_code
                AND team.effective_from_season <= event.league_season
                AND NOT EXISTS (
                    SELECT 1
                    FROM football_teams AS newer
                    WHERE newer.franchise_id = team.franchise_id
                      AND newer.effective_from_season <= event.league_season
                      AND newer.effective_from_season > team.effective_from_season
                )
          )
          AND EXISTS (
              SELECT 1
              FROM football_teams AS team
              WHERE team.id = NEW.away_team_id
                AND team.sport_code = event.sport_code
                AND team.effective_from_season <= event.league_season
                AND NOT EXISTS (
                    SELECT 1
                    FROM football_teams AS newer
                    WHERE newer.franchise_id = team.franchise_id
                      AND newer.effective_from_season <= event.league_season
                      AND newer.effective_from_season > team.effective_from_season
                )
          )
          AND (
              NEW.home_team_id IS NOT COALESCE(
                  (
                      SELECT latest.home_team_id
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.home_team_id
              )
              OR NEW.away_team_id IS NOT COALESCE(
                  (
                      SELECT latest.away_team_id
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.away_team_id
              )
              OR NEW.kickoff_at IS NOT COALESCE(
                  (
                      SELECT latest.kickoff_at
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.kickoff_at
              )
              OR NEW.venue_id IS NOT CASE
                  WHEN EXISTS (
                      SELECT 1
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                  )
                  THEN (
                      SELECT latest.venue_id
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  )
                  ELSE event.venue_id
              END
              OR NEW.neutral_site IS NOT COALESCE(
                  (
                      SELECT latest.neutral_site
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.neutral_site
              )
              OR NEW.status IS NOT COALESCE(
                  (
                      SELECT latest.status
                      FROM football_event_revisions AS latest
                      WHERE latest.event_id = NEW.event_id
                      ORDER BY latest.revision_number DESC
                      LIMIT 1
                  ),
                  event.status
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'event revision is invalid, unchanged, or out of sequence');
    END
    """,
    """
    CREATE TRIGGER football_provider_event_ids_validate_sport
    BEFORE INSERT ON football_provider_event_ids
    WHEN NOT EXISTS (
        SELECT 1
        FROM football_events AS event
        WHERE event.id = NEW.event_id
          AND event.sport_code = NEW.sport_code
    )
    BEGIN
        SELECT RAISE(ABORT, 'provider event identity sport does not match event');
    END
    """,
    """
    CREATE TRIGGER legacy_cfb_game_links_validate
    BEFORE INSERT ON legacy_cfb_game_links
    WHEN NOT EXISTS (
        SELECT 1
        FROM games AS legacy
        JOIN football_events AS event
          ON event.id = NEW.football_event_id
        WHERE legacy.game_id = NEW.legacy_game_id
          AND event.sport_code = 'NCAA'
          AND event.league_season = legacy.season
          AND event.season_type = lower(
              COALESCE(NULLIF(trim(legacy.season_type), ''), 'regular')
          )
          AND event.sport_week = legacy.week
          AND julianday(legacy.start_date) IS NOT NULL
          AND julianday(legacy.start_date) = julianday(
              COALESCE(
                  (
                      SELECT revision.kickoff_at
                      FROM football_event_revisions AS revision
                      WHERE revision.event_id = event.id
                        AND julianday(revision.recorded_at)
                            <= julianday(NEW.linked_at)
                      ORDER BY revision.revision_number DESC
                      LIMIT 1
                  ),
                  event.kickoff_at
              )
          )
          AND COALESCE(legacy.neutral_site, 0) = COALESCE(
              (
                  SELECT revision.neutral_site
                  FROM football_event_revisions AS revision
                  WHERE revision.event_id = event.id
                    AND julianday(revision.recorded_at) <= julianday(NEW.linked_at)
                  ORDER BY revision.revision_number DESC
                  LIMIT 1
              ),
              event.neutral_site
          )
          AND EXISTS (
              SELECT 1
              FROM football_team_aliases AS alias
              WHERE alias.provider = 'legacy_cfb'
                AND alias.sport_code = 'NCAA'
                AND alias.alias_key = lower(trim(legacy.home_team))
                AND alias.team_id = COALESCE(
                    (
                        SELECT revision.home_team_id
                        FROM football_event_revisions AS revision
                        WHERE revision.event_id = event.id
                          AND julianday(revision.recorded_at)
                              <= julianday(NEW.linked_at)
                        ORDER BY revision.revision_number DESC
                        LIMIT 1
                    ),
                    event.home_team_id
                )
                AND alias.effective_from_season <= legacy.season
                AND alias.id = (
                    SELECT latest.id
                    FROM football_team_aliases AS latest
                    WHERE latest.provider = alias.provider
                      AND latest.sport_code = alias.sport_code
                      AND latest.alias_key = alias.alias_key
                      AND latest.effective_from_season <= legacy.season
                    ORDER BY latest.effective_from_season DESC, latest.id DESC
                    LIMIT 1
                )
          )
          AND EXISTS (
              SELECT 1
              FROM football_team_aliases AS alias
              WHERE alias.provider = 'legacy_cfb'
                AND alias.sport_code = 'NCAA'
                AND alias.alias_key = lower(trim(legacy.away_team))
                AND alias.team_id = COALESCE(
                    (
                        SELECT revision.away_team_id
                        FROM football_event_revisions AS revision
                        WHERE revision.event_id = event.id
                          AND julianday(revision.recorded_at)
                              <= julianday(NEW.linked_at)
                        ORDER BY revision.revision_number DESC
                        LIMIT 1
                    ),
                    event.away_team_id
                )
                AND alias.effective_from_season <= legacy.season
                AND alias.id = (
                    SELECT latest.id
                    FROM football_team_aliases AS latest
                    WHERE latest.provider = alias.provider
                      AND latest.sport_code = alias.sport_code
                      AND latest.alias_key = alias.alias_key
                      AND latest.effective_from_season <= legacy.season
                    ORDER BY latest.effective_from_season DESC, latest.id DESC
                    LIMIT 1
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'legacy CFB link is not an exact NCAA identity match');
    END
    """,
)


for _table in (
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
):
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_update
        BEFORE UPDATE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable');
        END
        """,
        f"""
        CREATE TRIGGER {_table}_no_delete
        BEFORE DELETE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable and cannot be deleted');
        END
        """,
    )


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def _schema_object(statement: str) -> tuple[str, str] | None:
    words = statement.split()
    if len(words) >= 3 and words[0:2] == ["CREATE", "TABLE"]:
        return "table", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "TRIGGER"]:
        return "trigger", words[2]
    return None


EXPECTED_OBJECT_SQL = {
    schema_object: _normalize_sql(statement)
    for statement in STATEMENTS
    if (schema_object := _schema_object(statement)) is not None
}


def upgrade(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    for (object_type, name), expected_sql in EXPECTED_OBJECT_SQL.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(f"required {object_type} is missing: {name}")
        if _normalize_sql(str(row[0])) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")

    sports = tuple(
        conn.execute(
            "SELECT sport_code, league_name, display_name, provenance "
            "FROM football_sports ORDER BY sport_code"
        )
    )
    if sports != (
        (
            "NCAA",
            "National Collegiate Athletic Association football",
            "NCAA Football",
            "migration:v0019:approved-phase-0-registry",
        ),
        (
            "NFL",
            "National Football League",
            "NFL",
            "migration:v0019:approved-phase-0-registry",
        ),
    ):
        raise RuntimeError("football sport registry differs from approved NCAA/NFL seed")
