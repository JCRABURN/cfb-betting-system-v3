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
SUPPORTED_INPUT_FORMATS = ("csv", "xlsx", "screenshot_transcription")
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


def _table_rows(path: Path, input_format: str) -> list[dict[str, str]]:
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
    if request.input_format in ("csv", "screenshot_transcription") and source_path.suffix.casefold() != ".csv":
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
    resolver = CanonicalTeamResolver.from_connection(conn)
    source_sha256 = _file_sha256(request.source_path.resolve())
    seen_raw: set[tuple[str, str]] = set()
    seen_normalized: set[tuple[str, str]] = set()
    seen_source_ids: set[str] = set()
    lines: list[dict[str, object]] = []
    for record in rows:
        row_number = int(record["_row_number"])
        raw_away = record["Away Team"].strip()
        raw_home = record["Home Team"].strip()
        if not raw_away or not raw_home or raw_away.casefold() == raw_home.casefold():
            raise SplashSportsImportError(
                f"row {row_number} requires distinct away and home teams"
            )
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
        supplied_id = record.get("SplashSports Game ID", "").strip()
        source_line_id = supplied_id or "manual-" + hashlib.sha256(
            f"{request.source_contest_id}|{raw_away}|{raw_home}".encode("utf-8")
        ).hexdigest()[:24]
        if source_line_id in seen_source_ids:
            raise SplashSportsImportError(
                f"row {row_number} duplicates a SplashSports game identifier"
            )
        seen_source_ids.add(source_line_id)
        lines.append(
            {
                "source_line_id": source_line_id,
                "raw_away_team": raw_away,
                "raw_home_team": raw_home,
                "normalized_away_team": normalized_away,
                "normalized_home_team": normalized_home,
                "game_id": int(exact[0][0]),
                "home_spread": _spread(record["Spread"], f"row {row_number} Spread"),
                "total": _optional_total(record.get("Total", ""), f"row {row_number} Total"),
                "game_date": record.get("Game Date", "") or None,
                "game_time": record.get("Game Time", "") or None,
                "notes": record.get("Notes", "") or None,
                "source_row_number": row_number,
            }
        )
    evidence = [
        {
            "path": str(path.resolve()),
            "sha256": _file_sha256(path.resolve()),
        }
        for path in request.screenshot_evidence_paths
    ]
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
            "importer_version": IMPORTER_VERSION,
            "input_format": request.input_format,
            "source_path": str(request.source_path.resolve()),
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
