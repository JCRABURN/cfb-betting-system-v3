"""Verify the ordered managed-PostgreSQL migration inventory offline."""

from __future__ import annotations

from operations.cloud_persistence import load_cloud_migrations


REQUIRED_SCHEMA_CONTROLS = (
    "cfb_v3_state_snapshots",
    "cfb_v3_state_heads",
    "cfb_v3_operation_commits",
    "UNIQUE (stream_key, generation)",
    "UNIQUE (stream_key, operation_key)",
    "REFERENCES cfb_v3_state_snapshots(id) ON DELETE RESTRICT",
    "cfb_v3_state_snapshots_immutable",
    "cfb_v3_operation_commits_immutable",
)


def main() -> int:
    migrations = load_cloud_migrations()
    combined = "\n".join(migration.sql for migration in migrations)
    missing = [control for control in REQUIRED_SCHEMA_CONTROLS if control not in combined]
    if missing:
        raise RuntimeError("cloud migration controls missing: " + ", ".join(missing))
    print(
        "Managed PostgreSQL migration inventory verified: "
        + ", ".join(
            f"v{migration.version:04d}:{migration.checksum[:12]}"
            for migration in migrations
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
