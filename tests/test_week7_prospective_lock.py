"""Adversarial lock custody and strict pre-kickoff checks for Week 7."""

import csv
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts import run_week7_execution as week7


def source_files(tmp_path, rows):
    source = tmp_path / "week7.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*week7.REQUIRED_COLUMNS, "Notes"])
        writer.writeheader()
        writer.writerows(rows)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"season": 2026, "week": 7,
                                    "contest_key": week7.CONTEST_KEY,
                                    "source": "SplashSports", "source_received_at_utc": "2026-10-13T14:00:00+00:00",
                                    "authoritative_locked_lines": True, "game_count": len(rows),
                                    "spread_convention": "home_team_spread",
                                    "total_convention": "contest_over_under",
                                    "game_time_zone": "America/Chicago",
                                    "source_timestamp_kind": "file_received",
                                    "canonical_csv_sha256": week7.canonical_sha(source),
                                    "raw_file_sha256": week7.sha(source.read_bytes())}))
    return source, metadata


def test_source_requires_exact_hash_identity_and_unique_owner_locks(tmp_path):
    row = {"Away Team": "Delaware", "Home Team": "Middle Tennessee", "Spread": "-7.5",
           "Game Date": "2026-10-13", "Game Time": "6:00 PM", "Total": "52.5", "Notes": "owner source"}
    source, metadata = source_files(tmp_path, [row])
    assert len(week7.read_source(source, metadata)[0]) == 1
    source.write_text(source.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        week7.read_source(source, metadata)
    duplicate, duplicate_meta = source_files(tmp_path, [row, row])
    with pytest.raises(ValueError, match="duplicate locked matchup"):
        week7.read_source(duplicate, duplicate_meta)


def test_reconcile_requires_strict_pre_kickoff_and_never_fabricates_total(monkeypatch):
    class Resolver:
        @staticmethod
        def from_connection(conn):
            return Resolver()

        def resolve(self, provider, name):
            return SimpleNamespace(status="resolved", canonical_name=name)

    monkeypatch.setattr(week7, "CanonicalTeamResolver", Resolver)
    game = {"week": 7, "id": 1, "awayTeam": "Delaware", "homeTeam": "Middle Tennessee",
            "awayClassification": "fbs", "homeClassification": "fbs",
            "startDate": "2026-10-13T23:00:00.000Z"}
    row = {"Away Team": "Delaware", "Home Team": "Middle Tennessee", "Spread": "-7.5",
           "Game Date": "2026-10-13", "Game Time": "6:00 PM", "Total": "", "Notes": ""}
    just_before = datetime.fromisoformat("2026-10-13T22:59:59+00:00")
    result = week7.reconcile(None, [game], [row], generation_time=just_before)
    assert result[0]["locked_total"] is None
    assert result[0]["total_status"] == "SOURCE_TOTAL_UNAVAILABLE"
    for timestamp in ("2026-10-13T23:00:00+00:00", "2026-10-13T23:00:01+00:00"):
        with pytest.raises(ValueError, match="kickoff elapsed"):
            week7.reconcile(None, [game], [row], generation_time=datetime.fromisoformat(timestamp))
