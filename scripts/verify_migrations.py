"""Verify every migration against a disposable copy of a SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from migrations.runner import apply_migrations, table_row_counts


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "cfb.db"


@dataclass(frozen=True)
class VerificationResult:
    source_hash: str
    applied_versions: tuple[int, ...]
    before_counts: dict[str, int]
    after_counts: dict[str, int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as database_file:
        for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_database_integrity(conn: sqlite3.Connection, label: str) -> None:
    integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise RuntimeError(f"{label} integrity check failed: {integrity}")
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    if violations:
        raise RuntimeError(f"{label} has {len(violations)} foreign-key violation(s)")


def verify_database_copy(source: Path = DEFAULT_DATABASE) -> VerificationResult:
    """Migrate a temporary copy and prove the source and its rows are preserved."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"database does not exist: {source}")

    source_hash_before = _sha256(source)
    with tempfile.TemporaryDirectory(prefix="cfb-migration-verification-") as temp_dir:
        copy_path = Path(temp_dir) / source.name
        shutil.copy2(source, copy_path)

        conn = sqlite3.connect(copy_path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            _verify_database_integrity(conn, "pre-migration copy")
            before_counts = table_row_counts(conn)
            results = apply_migrations(conn)
            after_counts = table_row_counts(conn)
            _verify_database_integrity(conn, "post-migration copy")

            changed = {
                table: (count, after_counts.get(table))
                for table, count in before_counts.items()
                if after_counts.get(table) != count
            }
            if changed:
                raise RuntimeError(f"migration changed existing row counts: {changed}")

            applied_versions = tuple(
                row[0]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            )
        finally:
            conn.close()

    source_hash_after = _sha256(source)
    if source_hash_after != source_hash_before:
        raise RuntimeError("source database changed during disposable-copy verification")

    return VerificationResult(
        source_hash=source_hash_before,
        applied_versions=applied_versions,
        before_counts=before_counts,
        after_counts=after_counts,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply and verify migrations on a disposable database copy."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="source database to copy; the source is never opened for writing",
    )
    args = parser.parse_args()

    result = verify_database_copy(args.database)
    print(f"Source SHA-256: {result.source_hash}")
    print(f"Applied migration versions: {list(result.applied_versions)}")
    print("Existing table row counts preserved:")
    for table, count in result.before_counts.items():
        print(f"  {table}: {count}")
    print("Migration verification passed on a disposable copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
