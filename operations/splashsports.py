"""Controlled manual SplashSports input converging on one lock manifest."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from ingestion import CanonicalTeamResolver

from operations.config import EXPECTED_REPOSITORY


MANIFEST_VERSION = "v3-contest-lines-v1"
IMPORTER_VERSION = "splashsports-manual-import-v1"
OWNER_MODEL_IMPORT_FORMAT = "owner_reviewed_model_import_csv"
OWNER_MODEL_IMPORT_VERSION = "splashsports-owner-model-import-v1"
SUPPORTED_INPUT_FORMATS = (
    "csv",
    "xlsx",
    "screenshot_transcription",
    OWNER_MODEL_IMPORT_FORMAT,
)
REQUIRED_COLUMNS = ("Away Team", "Home Team", "Spread")
OPTIONAL_COLUMNS = (
    "Game Date",
    "Game Time",
    "Total",
    "SplashSports Game ID",
    "Notes",
)
_COLUMN_BY_NORMALIZED = {
    "away team": "Away Team",
    "home team": "Home Team",
    "spread": "Spread",
    "game date": "Game Date",
    "game time": "Game Time",
    "total": "Total",
    "splashsports game id": "SplashSports Game ID",
    "notes": "Notes",
}
_CELL_REFERENCE = re.compile(r"^([A-Z]+)[0-9]+$")
_SPREAD_PATTERN = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)$")
_OWNER_GAME_ID_PATTERN = re.compile(
    r"^(?P<season>[0-9]{4})_W(?P<week>[0-9]{2})_(?P<sequence>[0-9]{2})$"
)
_OWNER_COLUMNS = (
    "game_id",
    "season",
    "week",
    "game_date",
    "start_time",
    "away_team",
    "home_team",
    "away_spread",
    "home_spread",
    "locked_total",
    "favorite",
    "favorite_line",
    "underdog",
    "source",
    "locked_at",
    "source_image",
    "lock_status",
)
_OWNER_GAME_ID_NAMESPACE = 8_000_000_000_000


class SplashSportsImportError(RuntimeError):
    """Raised when manual contest input cannot be locked without guessing."""


@dataclass(frozen=True)
class SplashSportsImportRequest:
    source_path: Path
    input_format: str
    season: int
    week: int
    contest_key: str
    contest_name: str
    source_contest_id: str
    expected_lined_game_count: int
    captured_at: datetime
    imported_by: str
    provenance: str
    screenshot_evidence_paths: tuple[Path, ...] = ()
    screenshot_reviewed_by: str | None = None
    screenshot_reviewed_at: datetime | None = None


@dataclass(frozen=True)
class SplashSportsManifest:
    payload: dict[str, object]
    canonical_json: str
    sha256: str
    parsed_line_count: int


@dataclass(frozen=True)
class SplashSportsScheduleIngestion:
    source_sha256: str
    requested_count: int
    inserted_count: int
    existing_count: int
    game_ids: tuple[int, ...]


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SplashSportsImportError("manifest is not canonical JSON") from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SplashSportsImportError(f"{field} must be timezone-aware UTC")
    converted = value.astimezone(timezone.utc)
    if value.utcoffset() != timedelta(0):
        raise SplashSportsImportError(f"{field} must use a UTC offset")
    return converted


def _column_index(reference: str) -> int:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise SplashSportsImportError(f"invalid XLSX cell reference: {reference}")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _xlsx_rows(path: Path) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SplashSportsImportError("input is not a valid XLSX workbook") from exc
    with archive:
        try:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        except (KeyError, ElementTree.ParseError) as exc:
            raise SplashSportsImportError("XLSX workbook structure is invalid") from exc
        namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rel_namespace = {
            "r": "http://schemas.openxmlformats.org/package/2006/relationships"
        }
        relation_by_id = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall("r:Relationship", rel_namespace)
        }
        sheets = workbook.findall("x:sheets/x:sheet", namespace)
        if not sheets:
            raise SplashSportsImportError("XLSX workbook contains no worksheet")
        relationship_id = sheets[0].attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = relation_by_id.get(str(relationship_id), "")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        try:
            sheet = ElementTree.fromstring(archive.read(target))
        except (KeyError, ElementTree.ParseError) as exc:
            raise SplashSportsImportError("first XLSX worksheet is invalid") from exc

        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            try:
                strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            except ElementTree.ParseError as exc:
                raise SplashSportsImportError("XLSX shared strings are invalid") from exc
            for item in strings.findall("x:si", namespace):
                shared.append("".join(node.text or "" for node in item.iterfind(".//x:t", namespace)))

        rows: list[list[str]] = []
        for row in sheet.findall(".//x:sheetData/x:row", namespace):
            values: dict[int, str] = {}
            for cell in row.findall("x:c", namespace):
                reference = cell.attrib.get("r", "")
                column = _column_index(reference)
                cell_type = cell.attrib.get("t")
                value_node = cell.find("x:v", namespace)
                inline = cell.find("x:is/x:t", namespace)
                raw = "" if value_node is None else value_node.text or ""
                if cell_type == "s":
                    try:
                        raw = shared[int(raw)]
                    except (ValueError, IndexError) as exc:
                        raise SplashSportsImportError("XLSX shared-string index is invalid") from exc
                elif cell_type == "inlineStr":
                    raw = "" if inline is None else inline.text or ""
                elif cell.find("x:f", namespace) is not None and value_node is None:
                    raise SplashSportsImportError("XLSX formulas require cached values")
                values[column] = str(raw).strip()
            if values:
                width = max(values) + 1
                rows.append([values.get(index, "") for index in range(width)])
        return rows


def _csv_rows(path: Path) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            return [[cell.strip() for cell in row] for row in csv.reader(source)]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SplashSportsImportError("input is not valid UTF-8 CSV") from exc


def _owner_model_import_rows(path: Path) -> list[dict[str, str]]:
    rows = _csv_rows(path)
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise SplashSportsImportError("input contains no rows")
    headers = [cell.strip().casefold() for cell in rows[0]]
    if tuple(headers) != _OWNER_COLUMNS:
        raise SplashSportsImportError(
            "owner model import columns must match the governed v1 schema exactly"
        )
    parsed: list[dict[str, str]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(headers):
            raise SplashSportsImportError(
                f"row {row_number} does not match the governed v1 column count"
            )
        record = dict(zip(headers, (cell.strip() for cell in row)))
        record["_row_number"] = str(row_number)
        parsed.append(record)
    if not parsed:
        raise SplashSportsImportError("input contains no contest-line rows")
    return parsed


def _table_rows(path: Path, input_format: str) -> list[dict[str, str]]:
    if input_format == OWNER_MODEL_IMPORT_FORMAT:
        return _owner_model_import_rows(path)
    if input_format in ("csv", "screenshot_transcription"):
        rows = _csv_rows(path)
    elif input_format == "xlsx":
        rows = _xlsx_rows(path)
    else:
        raise SplashSportsImportError(
            f"input_format must be one of: {', '.join(SUPPORTED_INPUT_FORMATS)}"
        )
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise SplashSportsImportError("input contains no rows")
    normalized_headers = [" ".join(cell.casefold().split()) for cell in rows[0]]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise SplashSportsImportError("input contains duplicate column headers")
    unknown = [header for header in normalized_headers if header not in _COLUMN_BY_NORMALIZED]
    if unknown:
        raise SplashSportsImportError(f"input contains unsupported columns: {unknown}")
    canonical_headers = [_COLUMN_BY_NORMALIZED[header] for header in normalized_headers]
    missing = [header for header in REQUIRED_COLUMNS if header not in canonical_headers]
    if missing:
        raise SplashSportsImportError(f"input is missing required columns: {missing}")
    parsed: list[dict[str, str]] = []
    for row_number, row in enumerate(rows[1:], start=2):
        padded = row + [""] * (len(canonical_headers) - len(row))
        if any(cell.strip() for cell in padded[len(canonical_headers) :]):
            raise SplashSportsImportError(f"row {row_number} has too many columns")
        record = {
            canonical_headers[index]: padded[index].strip()
            for index in range(len(canonical_headers))
        }
        record["_row_number"] = str(row_number)
        parsed.append(record)
    if not parsed:
        raise SplashSportsImportError("input contains no contest-line rows")
    return parsed


def _owner_timestamp(value: str, field: str) -> datetime:
    match = re.fullmatch(
        r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}) "
        r"(?P<time>[0-9]{2}:[0-9]{2}) (?P<zone>CDT|CST)",
        value,
    )
    if match is None:
        raise SplashSportsImportError(
            f"{field} must use YYYY-MM-DD HH:MM CDT/CST"
        )
    offset = timedelta(hours=-5 if match.group("zone") == "CDT" else -6)
    parsed = datetime.strptime(
        f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=timezone(offset))
    return parsed.astimezone(timezone.utc)


def _owner_kickoff(record: dict[str, str], row_number: int) -> datetime:
    try:
        local = datetime.strptime(
            f"{record['game_date']} {record['start_time']}",
            "%Y-%m-%d %I:%M %p",
        )
    except (KeyError, ValueError) as exc:
        raise SplashSportsImportError(
            f"row {row_number} has an invalid game date or start time"
        ) from exc
    # The governed file names CDT/CST explicitly. Preserve that numeric offset
    # for the displayed kickoff time instead of consulting mutable machine TZ data.
    source_offset = timedelta(
        hours=-5 if record["locked_at"].endswith(" CDT") else -6
    )
    return local.replace(tzinfo=timezone(source_offset)).astimezone(timezone.utc)


def _validate_owner_record(
    record: dict[str, str], request: SplashSportsImportRequest
) -> tuple[int, datetime]:
    row_number = int(record["_row_number"])
    match = _OWNER_GAME_ID_PATTERN.fullmatch(record["game_id"])
    if match is None:
        raise SplashSportsImportError(
            f"row {row_number} game_id does not match YYYY_Www_nn"
        )
    season = int(match.group("season"))
    week = int(match.group("week"))
    sequence = int(match.group("sequence"))
    try:
        row_season = int(record["season"])
        row_week = int(record["week"])
    except ValueError as exc:
        raise SplashSportsImportError(
            f"row {row_number} season/week must be integers"
        ) from exc
    if (season, week) != (row_season, row_week) or (season, week) != (
        request.season,
        request.week,
    ):
        raise SplashSportsImportError(
            f"row {row_number} season/week identity is inconsistent"
        )
    if sequence < 1:
        raise SplashSportsImportError(f"row {row_number} sequence must be positive")
    if record["source"] != "SplashSports" or record["lock_status"] != "LOCKED":
        raise SplashSportsImportError(
            f"row {row_number} is not an authoritative locked SplashSports row"
        )
    if not record["source_image"].strip():
        raise SplashSportsImportError(
            f"row {row_number} requires source-image provenance"
        )
    away_spread = _spread(record["away_spread"], f"row {row_number} away_spread")
    home_spread = _spread(record["home_spread"], f"row {row_number} home_spread")
    total = _optional_total(record["locked_total"], f"row {row_number} locked_total")
    if total is None:
        raise SplashSportsImportError(f"row {row_number} requires a locked total")
    if abs(away_spread + home_spread) >= 1e-9:
        raise SplashSportsImportError(
            f"row {row_number} away/home spreads do not sum to zero"
        )
    if home_spread < 0:
        expected_favorite, expected_underdog, expected_line = (
            record["home_team"],
            record["away_team"],
            home_spread,
        )
    elif away_spread < 0:
        expected_favorite, expected_underdog, expected_line = (
            record["away_team"],
            record["home_team"],
            away_spread,
        )
    else:
        raise SplashSportsImportError(
            f"row {row_number} pick'em requires a different governed schema"
        )
    favorite_line = _spread(
        record["favorite_line"], f"row {row_number} favorite_line"
    )
    if (
        record["favorite"] != expected_favorite
        or record["underdog"] != expected_underdog
        or abs(favorite_line - expected_line) >= 1e-9
    ):
        raise SplashSportsImportError(
            f"row {row_number} favorite/underdog custody disagrees with its spreads"
        )
    locked_at = _owner_timestamp(record["locked_at"], f"row {row_number} locked_at")
    if locked_at != request.captured_at:
        raise SplashSportsImportError(
            f"row {row_number} locked_at disagrees with captured_at"
        )
    kickoff = _owner_kickoff(record, row_number)
    if kickoff <= locked_at:
        raise SplashSportsImportError(
            f"row {row_number} kickoff must follow the locked timestamp"
        )
    game_id = (
        _OWNER_GAME_ID_NAMESPACE + season * 10_000 + week * 100 + sequence
    )
    return game_id, kickoff


def _validate_owner_file_identity(
    rows: list[dict[str, str]], request: SplashSportsImportRequest
) -> None:
    expected = {
        f"{request.season}_W{request.week:02d}_{sequence:02d}"
        for sequence in range(1, request.expected_lined_game_count + 1)
    }
    supplied = {record["game_id"] for record in rows}
    if supplied != expected:
        missing = sorted(expected - supplied)
        unexpected = sorted(supplied - expected)
        raise SplashSportsImportError(
            "owner model import game_id sequence is incomplete or unexpected: "
            f"missing={missing}, unexpected={unexpected}"
        )


def _resolve_owner_team(
    conn: sqlite3.Connection,
    resolver: CanonicalTeamResolver,
    raw_name: str,
    *,
    row_number: str,
    side: str,
) -> str:
    """Resolve a governed owner row without broadening provider normalization.

    The canonical FBS inventory remains authoritative. A named historical FCS
    opponent may be reused only when that exact identity already exists in the
    game ledger; no ``teams`` row is fabricated to make an import pass.
    """
    resolution = resolver.resolve("SplashSports", raw_name)
    if resolution.status == "resolved" and resolution.canonical_name is not None:
        return str(resolution.canonical_name)
    historical = {
        str(row[0])
        for row in conn.execute(
            "SELECT home_team FROM games WHERE home_team = ? COLLATE NOCASE "
            "UNION SELECT away_team FROM games WHERE away_team = ? COLLATE NOCASE",
            (raw_name, raw_name),
        )
        if row[0]
    }
    if len(historical) == 1:
        return next(iter(historical))
    status = "ambiguous" if resolution.status == "ambiguous" or historical else "unknown"
    raise SplashSportsImportError(
        f"row {row_number} {side} team is {status}: {raw_name}"
    )


def _spread(value: str, field: str) -> float:
    folded = " ".join(value.casefold().replace("’", "'").split())
    if folded in ("pk", "pick", "pick'em", "pickem", "even"):
        return 0.0
    if _SPREAD_PATTERN.fullmatch(value.strip()) is None:
        raise SplashSportsImportError(f"{field} is not a valid home-team spread")
    converted = float(value)
    if not math.isfinite(converted) or not -100 <= converted <= 100:
        raise SplashSportsImportError(f"{field} must be finite within [-100, 100]")
    return converted


def _optional_total(value: str, field: str) -> float | None:
    if not value.strip():
        return None
    if _SPREAD_PATTERN.fullmatch(value.strip()) is None:
        raise SplashSportsImportError(f"{field} is not a valid total")
    total = float(value)
    if not math.isfinite(total) or total < 0:
        raise SplashSportsImportError(f"{field} must be finite and nonnegative")
    return total


def _validate_request(request: SplashSportsImportRequest) -> SplashSportsImportRequest:
    source_path = request.source_path.resolve()
    if not source_path.is_file():
        raise SplashSportsImportError("manual input file does not exist")
    if request.input_format not in SUPPORTED_INPUT_FORMATS:
        raise SplashSportsImportError("unsupported manual input format")
    if request.input_format == "xlsx" and source_path.suffix.casefold() != ".xlsx":
        raise SplashSportsImportError("XLSX input must use the .xlsx extension")
    if request.input_format in (
        "csv",
        "screenshot_transcription",
        OWNER_MODEL_IMPORT_FORMAT,
    ) and source_path.suffix.casefold() != ".csv":
        raise SplashSportsImportError("CSV input must use the .csv extension")
    if request.season < 1869 or not 0 <= request.week <= 20:
        raise SplashSportsImportError("season/week are outside valid bounds")
    if request.expected_lined_game_count < 1:
        raise SplashSportsImportError("expected_lined_game_count must be positive")
    _utc(request.captured_at, "captured_at")
    if not request.imported_by.strip() or not request.provenance.strip():
        raise SplashSportsImportError("imported_by and provenance are required")
    if request.input_format == "screenshot_transcription":
        if not request.screenshot_evidence_paths:
            raise SplashSportsImportError("screenshot transcription requires image evidence")
        if not request.screenshot_reviewed_by or not request.screenshot_reviewed_by.strip():
            raise SplashSportsImportError("screenshot transcription requires a reviewer")
        if request.screenshot_reviewed_at is None:
            raise SplashSportsImportError("screenshot transcription requires a review timestamp")
        reviewed_at = _utc(request.screenshot_reviewed_at, "screenshot_reviewed_at")
        if reviewed_at < request.captured_at:
            raise SplashSportsImportError("screenshot review cannot precede capture")
        for evidence in request.screenshot_evidence_paths:
            evidence = evidence.resolve()
            if not evidence.is_file() or evidence.suffix.casefold() not in (
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            ):
                raise SplashSportsImportError(
                    "screenshot evidence must be an existing PNG, JPEG, or WebP file"
                )
    return request


def build_splashsports_manifest(
    conn: sqlite3.Connection,
    request: SplashSportsImportRequest,
) -> SplashSportsManifest:
    """Validate manual rows against canonical games and produce immutable custody."""
    request = _validate_request(request)
    rows = _table_rows(request.source_path.resolve(), request.input_format)
    if len(rows) != request.expected_lined_game_count:
        raise SplashSportsImportError(
            "expected versus parsed lined-game count differs: "
            f"expected={request.expected_lined_game_count}, parsed={len(rows)}"
        )
    if request.input_format == OWNER_MODEL_IMPORT_FORMAT:
        _validate_owner_file_identity(rows, request)
    resolver = CanonicalTeamResolver.from_connection(conn)
    source_sha256 = _file_sha256(request.source_path.resolve())
    seen_raw: set[tuple[str, str]] = set()
    seen_normalized: set[tuple[str, str]] = set()
    seen_source_ids: set[str] = set()
    lines: list[dict[str, object]] = []
    for record in rows:
        row_number = int(record["_row_number"])
        if request.input_format == OWNER_MODEL_IMPORT_FORMAT:
            _validate_owner_record(record, request)
            raw_away = record["away_team"].strip()
            raw_home = record["home_team"].strip()
            supplied_id = record["game_id"].strip()
            spread_value = record["home_spread"]
            total_value = record["locked_total"]
            game_date = record["game_date"]
            game_time = record["start_time"]
            notes = None
        else:
            raw_away = record["Away Team"].strip()
            raw_home = record["Home Team"].strip()
            supplied_id = record.get("SplashSports Game ID", "").strip()
            spread_value = record["Spread"]
            total_value = record.get("Total", "")
            game_date = record.get("Game Date", "") or None
            game_time = record.get("Game Time", "") or None
            notes = record.get("Notes", "") or None
        if not raw_away or not raw_home or raw_away.casefold() == raw_home.casefold():
            raise SplashSportsImportError(
                f"row {row_number} requires distinct away and home teams"
            )
        if request.input_format == OWNER_MODEL_IMPORT_FORMAT:
            normalized_away = _resolve_owner_team(
                conn,
                resolver,
                raw_away,
                row_number=str(row_number),
                side="away",
            )
            normalized_home = _resolve_owner_team(
                conn,
                resolver,
                raw_home,
                row_number=str(row_number),
                side="home",
            )
        else:
            away = resolver.resolve("SplashSports", raw_away)
            home = resolver.resolve("SplashSports", raw_home)
            for side, resolution in (("away", away), ("home", home)):
                if resolution.status != "resolved" or resolution.canonical_name is None:
                    candidates = ",".join(resolution.candidates) or "none"
                    raise SplashSportsImportError(
                        f"row {row_number} {side} team is {resolution.status}; "
                        f"raw={resolution.raw_name}; candidates={candidates}"
                    )
            normalized_away = str(away.canonical_name)
            normalized_home = str(home.canonical_name)
        exact = conn.execute(
            "SELECT game_id, start_date FROM games WHERE season = ? AND week = ? "
            "AND home_team = ? AND away_team = ?",
            (request.season, request.week, normalized_home, normalized_away),
        ).fetchall()
        reversed_rows = conn.execute(
            "SELECT game_id FROM games WHERE season = ? AND week = ? "
            "AND home_team = ? AND away_team = ?",
            (request.season, request.week, normalized_away, normalized_home),
        ).fetchall()
        if reversed_rows:
            raise SplashSportsImportError(
                f"row {row_number} reverses the canonical home/away matchup"
            )
        if len(exact) != 1:
            raise SplashSportsImportError(
                f"row {row_number} does not map to exactly one lined FBS game"
            )
        raw_pair = (raw_home.casefold(), raw_away.casefold())
        normalized_pair = (normalized_home, normalized_away)
        if raw_pair in seen_raw or (raw_pair[1], raw_pair[0]) in seen_raw:
            raise SplashSportsImportError(f"row {row_number} duplicates a raw matchup")
        if normalized_pair in seen_normalized or (
            normalized_pair[1], normalized_pair[0]
        ) in seen_normalized:
            raise SplashSportsImportError(
                f"row {row_number} duplicates a normalized matchup"
            )
        seen_raw.add(raw_pair)
        seen_normalized.add(normalized_pair)
        source_line_id = supplied_id or "manual-" + hashlib.sha256(
            f"{request.source_contest_id}|{raw_away}|{raw_home}".encode("utf-8")
        ).hexdigest()[:24]
        if source_line_id in seen_source_ids:
            raise SplashSportsImportError(
                f"row {row_number} duplicates a SplashSports game identifier"
            )
        seen_source_ids.add(source_line_id)
        line = {
            "source_line_id": source_line_id,
            "raw_away_team": raw_away,
            "raw_home_team": raw_home,
            "normalized_away_team": normalized_away,
            "normalized_home_team": normalized_home,
            "game_id": int(exact[0][0]),
            "home_spread": _spread(
                spread_value, f"row {row_number} home-team spread"
            ),
            "total": _optional_total(
                total_value, f"row {row_number} locked total"
            ),
            "game_date": game_date,
            "game_time": game_time,
            "notes": notes,
            "source_row_number": row_number,
        }
        if request.input_format == OWNER_MODEL_IMPORT_FORMAT:
            line["owner_reviewed_custody"] = {
                "away_spread": float(record["away_spread"]),
                "favorite": record["favorite"],
                "favorite_line": float(record["favorite_line"]),
                "underdog": record["underdog"],
                "locked_at": record["locked_at"],
                "source_image": record["source_image"],
                "lock_status": record["lock_status"],
                "import_version": OWNER_MODEL_IMPORT_VERSION,
            }
        lines.append(line)
    evidence = [
        {
            "path": str(path.resolve()),
            "sha256": _file_sha256(path.resolve()),
        }
        for path in request.screenshot_evidence_paths
    ]
    source_path = request.source_path.resolve()
    source_reference = str(source_path)
    if request.input_format == OWNER_MODEL_IMPORT_FORMAT:
        try:
            source_reference = source_path.relative_to(
                Path(__file__).resolve().parents[1]
            ).as_posix()
        except ValueError:
            pass
    payload: dict[str, object] = {
        "manifest_version": MANIFEST_VERSION,
        "repository": EXPECTED_REPOSITORY,
        "source": "SplashSports",
        "season": request.season,
        "week": request.week,
        "contest_key": request.contest_key,
        "contest_name": request.contest_name,
        "source_contest_id": request.source_contest_id,
        "expected_lined_game_count": request.expected_lined_game_count,
        "input_custody": {
            "importer_version": (
                OWNER_MODEL_IMPORT_VERSION
                if request.input_format == OWNER_MODEL_IMPORT_FORMAT
                else IMPORTER_VERSION
            ),
            "input_format": request.input_format,
            "source_path": source_reference,
            "source_sha256": source_sha256,
            "captured_at": request.captured_at.isoformat(),
            "imported_by": request.imported_by,
            "provenance": request.provenance,
            "screenshot_evidence": evidence,
            "screenshot_reviewed_by": request.screenshot_reviewed_by,
            "screenshot_reviewed_at": (
                request.screenshot_reviewed_at.isoformat()
                if request.screenshot_reviewed_at is not None
                else None
            ),
        },
        "lines": lines,
    }
    canonical = _canonical_json(payload)
    return SplashSportsManifest(
        payload=payload,
        canonical_json=canonical,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        parsed_line_count=len(lines),
    )


def ingest_owner_reviewed_schedule(
    conn: sqlite3.Connection,
    request: SplashSportsImportRequest,
    *,
    imported_at: datetime,
) -> SplashSportsScheduleIngestion:
    """Materialize the exact owner-reviewed slate into the legacy game boundary.

    Existing canonical games win over the deterministic local namespace. New
    rows are permitted only when the complete governed source file resolves to
    one canonical orientation and no other Week/game identity exists.
    """
    request = _validate_request(request)
    if request.input_format != OWNER_MODEL_IMPORT_FORMAT:
        raise SplashSportsImportError(
            "schedule ingestion requires owner_reviewed_model_import_csv"
        )
    rows = _table_rows(request.source_path.resolve(), request.input_format)
    if len(rows) != request.expected_lined_game_count:
        raise SplashSportsImportError(
            "expected versus parsed lined-game count differs: "
            f"expected={request.expected_lined_game_count}, parsed={len(rows)}"
        )
    _validate_owner_file_identity(rows, request)
    imported_value = _utc(imported_at, "imported_at").isoformat()
    source_sha256 = _file_sha256(request.source_path.resolve())
    ingestion_source = f"{OWNER_MODEL_IMPORT_VERSION}:{source_sha256}"
    resolver = CanonicalTeamResolver.from_connection(conn)
    resolved: list[tuple[dict[str, str], int, datetime, str, str]] = []
    seen_source_ids: set[str] = set()
    seen_matchups: set[tuple[str, str]] = set()
    for record in rows:
        game_id, kickoff = _validate_owner_record(record, request)
        raw_home = record["home_team"]
        raw_away = record["away_team"]
        home = _resolve_owner_team(
            conn,
            resolver,
            raw_home,
            row_number=record["_row_number"],
            side="home",
        )
        away = _resolve_owner_team(
            conn,
            resolver,
            raw_away,
            row_number=record["_row_number"],
            side="away",
        )
        source_id = record["game_id"]
        matchup = tuple(sorted((home.casefold(), away.casefold())))
        if source_id in seen_source_ids or matchup in seen_matchups:
            raise SplashSportsImportError(
                f"row {record['_row_number']} duplicates an owner-reviewed identity"
            )
        seen_source_ids.add(source_id)
        seen_matchups.add(matchup)
        resolved.append((record, game_id, kickoff, home, away))

    inserted = 0
    existing = 0
    game_ids: list[int] = []
    try:
        conn.execute("SAVEPOINT owner_reviewed_schedule")
        for record, proposed_game_id, kickoff, home, away in resolved:
            exact = conn.execute(
                "SELECT game_id, start_date FROM games WHERE season = ? AND week = ? "
                "AND home_team = ? AND away_team = ? ORDER BY game_id",
                (request.season, request.week, home, away),
            ).fetchall()
            reversed_rows = conn.execute(
                "SELECT game_id FROM games WHERE season = ? AND week = ? "
                "AND home_team = ? AND away_team = ?",
                (request.season, request.week, away, home),
            ).fetchall()
            if reversed_rows or len(exact) > 1:
                raise SplashSportsImportError(
                    f"row {record['_row_number']} has ambiguous/reversed game custody"
                )
            if exact:
                if exact[0][1] != kickoff.isoformat():
                    raise SplashSportsImportError(
                        f"row {record['_row_number']} kickoff conflicts with canonical game"
                    )
                game_id = int(exact[0][0])
                existing += 1
            else:
                collision = conn.execute(
                    "SELECT season, week, home_team, away_team FROM games WHERE game_id = ?",
                    (proposed_game_id,),
                ).fetchone()
                if collision is not None:
                    raise SplashSportsImportError(
                        f"row {record['_row_number']} deterministic game ID collides"
                    )
                conn.execute(
                    "INSERT INTO games "
                    "(game_id, season, week, season_type, start_date, home_team, "
                    "away_team, neutral_site, conference_game, completed) "
                    "VALUES (?, ?, ?, 'regular', ?, ?, ?, 0, 0, 0)",
                    (
                        proposed_game_id,
                        request.season,
                        request.week,
                        kickoff.isoformat(),
                        home,
                        away,
                    ),
                )
                game_id = proposed_game_id
                inserted += 1
            game_ids.append(game_id)
        prior_ingestion = conn.execute(
            "SELECT rows_added FROM ingestion_runs "
            "WHERE source = ? AND started_at = ? AND finished_at = ? "
            "AND status = 'success' AND error IS NULL ORDER BY id LIMIT 1",
            (ingestion_source, imported_value, imported_value),
        ).fetchone()
        if prior_ingestion is None:
            conn.execute(
                "INSERT INTO ingestion_runs "
                "(source, started_at, finished_at, rows_added, status, error) "
                "VALUES (?, ?, ?, ?, 'success', NULL)",
                (
                    ingestion_source,
                    imported_value,
                    imported_value,
                    inserted,
                ),
            )
        elif int(prior_ingestion[0]) not in (0, len(rows)):
            raise SplashSportsImportError(
                "prior owner-reviewed ingestion has an incomplete row count"
            )
        conn.execute("RELEASE SAVEPOINT owner_reviewed_schedule")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT owner_reviewed_schedule")
        conn.execute("RELEASE SAVEPOINT owner_reviewed_schedule")
        raise
    return SplashSportsScheduleIngestion(
        source_sha256=source_sha256,
        requested_count=len(rows),
        inserted_count=inserted,
        existing_count=existing,
        game_ids=tuple(game_ids),
    )
