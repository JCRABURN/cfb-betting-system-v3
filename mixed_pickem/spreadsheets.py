"""Strict offline CSV/XLSX reader for the mixed Pick'em v1 source contract."""

from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from mixed_pickem.common import (
    MixedPickemValidationError,
    canonical_json,
    parse_explicit_timestamp,
    sha256_text,
)


PARSER_VERSION = "mixed-pickem-slate-v1"
SUPPORTED_MEDIA_TYPES = ("CSV", "XLSX")
REQUIRED_COLUMNS = ("away_team", "home_team", "spread", "spread_side")
OPTIONAL_COLUMNS = ("sport", "kickoff", "source_event_id", "notes")
HEADER_ALIASES = {
    "away team": "away_team",
    "away": "away_team",
    "visitor": "away_team",
    "home team": "home_team",
    "home": "home_team",
    "spread": "spread",
    "contest spread": "spread",
    "spread side": "spread_side",
    "listed side": "spread_side",
    "sport": "sport",
    "kickoff": "kickoff",
    "kickoff utc": "kickoff",
    "source event id": "source_event_id",
    "event id": "source_event_id",
    "notes": "notes",
}

_CELL_REFERENCE = re.compile(r"^([A-Z]+)([0-9]+)$")
_SPREAD = re.compile(r"^[+-]?(?:[0-9]+(?:\.0|\.5)?|\.5)$")
_XML_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XML_OFFICE_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_XML_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


class SpreadsheetContractError(MixedPickemValidationError):
    """Raised when source media violates the governed v1 spreadsheet contract."""


@dataclass(frozen=True)
class SpreadValue:
    normalized_side: str
    displayed_millipoints: int
    home_millipoints: int


@dataclass(frozen=True)
class SourceRow:
    source_row_number: int
    source_order: int
    raw_cells: tuple[str, ...]
    values: dict[str, str]
    raw_row_json: str
    row_sha256: str
    formula_present: bool = False


@dataclass(frozen=True)
class ParsedSource:
    media_type: str
    original_filename: str
    source_sha256: str
    selected_worksheet: str | None
    rows: tuple[SourceRow, ...]
    header_errors: tuple[str, ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SpreadsheetContractError("source file cannot be read") from exc
    return digest.hexdigest()


def normalize_spread(
    raw_spread: str,
    raw_side: str,
    raw_away_team: str,
    raw_home_team: str,
) -> SpreadValue:
    """Normalize one exact v1 spread to integer home-team millipoints."""
    folded = " ".join(raw_spread.casefold().replace("’", "'").split())
    if folded in ("pk", "pick", "pick'em", "pickem", "even"):
        points = Decimal("0")
    else:
        if _SPREAD.fullmatch(raw_spread.strip()) is None:
            raise SpreadsheetContractError("SPREAD_MALFORMED")
        try:
            points = Decimal(raw_spread.strip())
        except InvalidOperation as exc:  # pragma: no cover - guarded by regex
            raise SpreadsheetContractError("SPREAD_MALFORMED") from exc
    millipoints = int(points * 1000)
    if millipoints < -100000 or millipoints > 100000:
        raise SpreadsheetContractError("SPREAD_OUT_OF_RANGE")
    if millipoints % 500 != 0:
        raise SpreadsheetContractError("SPREAD_INCREMENT_UNSUPPORTED")

    side = raw_side.strip().casefold()
    if side == "home" or side == raw_home_team.strip().casefold():
        normalized_side = "HOME"
    elif side == "away" or side == raw_away_team.strip().casefold():
        normalized_side = "AWAY"
    elif not side:
        raise SpreadsheetContractError("SPREAD_SIDE_MISSING")
    else:
        raise SpreadsheetContractError("SPREAD_SIDE_INVALID")
    home_millipoints = millipoints if normalized_side == "HOME" else -millipoints
    return SpreadValue(normalized_side, millipoints, home_millipoints)


def normalize_sport_hint(raw: str) -> str | None:
    if not raw.strip():
        return None
    value = raw.strip().upper()
    if value not in ("NCAA", "NFL"):
        raise SpreadsheetContractError("SPORT_HINT_INVALID")
    return value


def normalize_kickoff(raw: str) -> str | None:
    if not raw.strip():
        return None
    value = raw.strip()
    try:
        return parse_explicit_timestamp(value)
    except MixedPickemValidationError as exc:
        message = str(exc)
        if "timezone" in message:
            raise SpreadsheetContractError("KICKOFF_TIMEZONE_MISSING") from exc
        raise SpreadsheetContractError("KICKOFF_MALFORMED") from exc


def _normalized_header(value: str) -> str:
    return " ".join(value.casefold().split())


def _column_index(reference: str) -> tuple[int, int]:
    match = _CELL_REFERENCE.fullmatch(reference)
    if match is None:
        raise SpreadsheetContractError("XLSX_CELL_REFERENCE_INVALID")
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - ord("A") + 1
    return column - 1, int(match.group(2))


def _csv_rows(path: Path) -> list[tuple[int, list[str], bool]]:
    rows: list[tuple[int, list[str], bool]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for row_number, row in enumerate(csv.reader(source), start=1):
                rows.append((row_number, list(row), False))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SpreadsheetContractError("CSV_INVALID_UTF8_OR_STRUCTURE") from exc
    return rows


def _xlsx_sheet_rows(
    path: Path, worksheet: str | None
) -> tuple[str, list[tuple[int, list[str], bool]]]:
    if path.suffix.casefold() != ".xlsx":
        raise SpreadsheetContractError("XLSX_EXTENSION_REQUIRED")
    if worksheet is None or not worksheet.strip():
        raise SpreadsheetContractError("XLSX_WORKSHEET_REQUIRED")
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SpreadsheetContractError("XLSX_ARCHIVE_INVALID") from exc
    with archive:
        names = set(archive.namelist())
        if any(
            name.casefold().endswith("vbaproject.bin")
            or name.casefold().startswith("xl/externallinks/")
            for name in names
        ):
            raise SpreadsheetContractError("XLSX_ACTIVE_OR_EXTERNAL_CONTENT_REJECTED")
        for relationship_name in (name for name in names if name.endswith(".rels")):
            try:
                relationship_root = ElementTree.fromstring(
                    archive.read(relationship_name)
                )
            except ElementTree.ParseError as exc:
                raise SpreadsheetContractError("XLSX_RELATIONSHIP_INVALID") from exc
            for relation in relationship_root:
                if relation.attrib.get("TargetMode", "").casefold() == "external":
                    raise SpreadsheetContractError("XLSX_EXTERNAL_LINK_REJECTED")
        try:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            relationships = ElementTree.fromstring(
                archive.read("xl/_rels/workbook.xml.rels")
            )
        except (KeyError, ElementTree.ParseError) as exc:
            raise SpreadsheetContractError("XLSX_WORKBOOK_STRUCTURE_INVALID") from exc
        ns = {"x": _XML_MAIN}
        rels = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall(f"{{{_XML_PACKAGE_REL}}}Relationship")
        }
        target = None
        for sheet in workbook.findall("x:sheets/x:sheet", ns):
            if sheet.attrib.get("name") == worksheet:
                relationship_id = sheet.attrib.get(f"{{{_XML_OFFICE_REL}}}id")
                target = rels.get(str(relationship_id))
                break
        if target is None:
            raise SpreadsheetContractError("XLSX_WORKSHEET_NOT_FOUND")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        try:
            sheet_root = ElementTree.fromstring(archive.read(target))
        except (KeyError, ElementTree.ParseError) as exc:
            raise SpreadsheetContractError("XLSX_WORKSHEET_INVALID") from exc

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            try:
                shared_root = ElementTree.fromstring(
                    archive.read("xl/sharedStrings.xml")
                )
            except ElementTree.ParseError as exc:
                raise SpreadsheetContractError("XLSX_SHARED_STRINGS_INVALID") from exc
            for item in shared_root.findall(f"{{{_XML_MAIN}}}si"):
                shared.append(
                    "".join(
                        node.text or "" for node in item.iter(f"{{{_XML_MAIN}}}t")
                    )
                )

        rows: list[tuple[int, list[str], bool]] = []
        for ordinal, row in enumerate(
            sheet_root.findall(f".//{{{_XML_MAIN}}}sheetData/{{{_XML_MAIN}}}row"),
            start=1,
        ):
            row_number = int(row.attrib.get("r", ordinal))
            values: dict[int, str] = {}
            formula_present = False
            for cell in row.findall(f"{{{_XML_MAIN}}}c"):
                column, reference_row = _column_index(cell.attrib.get("r", ""))
                if reference_row != row_number:
                    raise SpreadsheetContractError("XLSX_ROW_REFERENCE_INVALID")
                cell_type = cell.attrib.get("t")
                value_node = cell.find(f"{{{_XML_MAIN}}}v")
                formula = cell.find(f"{{{_XML_MAIN}}}f")
                formula_present = formula_present or formula is not None
                raw = "" if value_node is None else value_node.text or ""
                if cell_type == "s":
                    try:
                        raw = shared[int(raw)]
                    except (ValueError, IndexError) as exc:
                        raise SpreadsheetContractError(
                            "XLSX_SHARED_STRING_INDEX_INVALID"
                        ) from exc
                elif cell_type == "inlineStr":
                    raw = "".join(
                        node.text or ""
                        for node in cell.iter(f"{{{_XML_MAIN}}}t")
                    )
                elif cell_type == "b":
                    raw = "TRUE" if raw == "1" else "FALSE"
                values[column] = str(raw)
            width = max(values, default=-1) + 1
            rows.append(
                (
                    row_number,
                    [values.get(index, "") for index in range(width)],
                    formula_present,
                )
            )
        return worksheet, rows


def read_source(
    path: Path,
    *,
    media_type: str,
    worksheet: str | None = None,
) -> ParsedSource:
    """Read one source without guessing headers, sheets, formulas, or timezones."""
    path = path.resolve()
    if not path.is_file():
        raise SpreadsheetContractError("SOURCE_FILE_NOT_FOUND")
    media_type = media_type.strip().upper()
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise SpreadsheetContractError("SOURCE_MEDIA_TYPE_UNSUPPORTED")
    if media_type == "CSV":
        if path.suffix.casefold() != ".csv":
            raise SpreadsheetContractError("CSV_EXTENSION_REQUIRED")
        selected_worksheet = None
        physical_rows = _csv_rows(path)
    else:
        selected_worksheet, physical_rows = _xlsx_sheet_rows(path, worksheet)

    populated = [item for item in physical_rows if any(cell.strip() for cell in item[1])]
    if not populated:
        raise SpreadsheetContractError("SOURCE_CONTAINS_NO_ROWS")
    _, header_cells, header_formula = populated[0]
    header_errors: list[str] = []
    if header_formula:
        header_errors.append("FORMULA_HEADER_UNTRUSTED")
    normalized_headers = [_normalized_header(cell) for cell in header_cells]
    if len(normalized_headers) != len(set(normalized_headers)):
        header_errors.append("DUPLICATE_HEADER")
    canonical_headers: list[str | None] = []
    seen_canonical: set[str] = set()
    for header in normalized_headers:
        canonical = HEADER_ALIASES.get(header)
        canonical_headers.append(canonical)
        if canonical is None:
            header_errors.append("UNSUPPORTED_HEADER")
        elif canonical in seen_canonical:
            header_errors.append("DUPLICATE_CANONICAL_HEADER")
        else:
            seen_canonical.add(canonical)
    if any(column not in seen_canonical for column in REQUIRED_COLUMNS):
        header_errors.append("REQUIRED_HEADER_MISSING")

    source_rows: list[SourceRow] = []
    for source_order, (row_number, cells, formula_present) in enumerate(
        populated[1:], start=1
    ):
        padded = cells + [""] * max(0, len(canonical_headers) - len(cells))
        values = {
            canonical_headers[index]: padded[index]
            for index in range(min(len(canonical_headers), len(padded)))
            if canonical_headers[index] is not None
        }
        raw_payload = {
            "cells": cells,
            "source_order": source_order,
            "source_row_number": row_number,
        }
        raw_json = canonical_json(raw_payload)
        source_rows.append(
            SourceRow(
                source_row_number=row_number,
                source_order=source_order,
                raw_cells=tuple(cells),
                values=values,
                raw_row_json=raw_json,
                row_sha256=sha256_text(raw_json),
                formula_present=formula_present,
            )
        )
    if not source_rows:
        raise SpreadsheetContractError("SOURCE_CONTAINS_NO_GAME_ROWS")
    return ParsedSource(
        media_type=media_type,
        original_filename=path.name,
        source_sha256=file_sha256(path),
        selected_worksheet=selected_worksheet,
        rows=tuple(source_rows),
        header_errors=tuple(sorted(set(header_errors))),
    )
