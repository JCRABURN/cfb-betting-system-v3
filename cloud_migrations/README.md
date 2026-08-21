# Managed PostgreSQL persistence migrations

These ordered SQL migrations govern the durable V3 production-state boundary.
They do not replace the existing SQLite domain migrations. A GitHub-hosted job
uses PostgreSQL for durable, append-only snapshot history and cross-run locking,
then materializes the current snapshot in its ephemeral workspace so the
existing audited betting engine can execute unchanged.

`operations.cloud_persistence.apply_cloud_migrations` applies each file in one
PostgreSQL transaction, records its SHA-256 in
`cfb_v3_cloud_schema_migrations`, and rejects missing, reordered, or changed
history. Production operations apply and verify this inventory before reading
state.

The schema preserves:

- immutable snapshot and operation-commit history;
- one generation per production stream;
- one completion per idempotency key;
- an atomically updated current-state pointer; and
- transaction-scoped PostgreSQL advisory locking across ephemeral runners.

The PostgreSQL credentials are supplied only through `CFB_V3_DATABASE_URL` in
the protected `v3-production` GitHub Environment.
