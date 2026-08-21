CREATE TABLE IF NOT EXISTS cfb_v3_state_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_key TEXT NOT NULL,
    generation BIGINT NOT NULL CHECK (generation >= 0),
    parent_snapshot_id BIGINT REFERENCES cfb_v3_state_snapshots(id) ON DELETE RESTRICT,
    payload BYTEA NOT NULL CHECK (octet_length(payload) > 0),
    payload_sha256 CHAR(64) NOT NULL
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload_bytes BIGINT NOT NULL CHECK (payload_bytes = octet_length(payload)),
    domain_schema_version INTEGER NOT NULL CHECK (domain_schema_version > 0),
    code_commit_sha CHAR(40) NOT NULL
        CHECK (code_commit_sha ~ '^[0-9a-f]{40}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stream_key, generation),
    UNIQUE (stream_key, payload_sha256),
    CHECK (
        (generation = 0 AND parent_snapshot_id IS NULL)
        OR (generation > 0 AND parent_snapshot_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS cfb_v3_state_heads (
    stream_key TEXT PRIMARY KEY,
    snapshot_id BIGINT NOT NULL UNIQUE
        REFERENCES cfb_v3_state_snapshots(id) ON DELETE RESTRICT,
    generation BIGINT NOT NULL CHECK (generation >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cfb_v3_operation_commits (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_key TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    snapshot_id BIGINT NOT NULL
        REFERENCES cfb_v3_state_snapshots(id) ON DELETE RESTRICT,
    result_sha256 CHAR(64) NOT NULL
        CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    actor TEXT NOT NULL,
    code_commit_sha CHAR(40) NOT NULL
        CHECK (code_commit_sha ~ '^[0-9a-f]{40}$'),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (stream_key, operation_key)
);

CREATE INDEX IF NOT EXISTS cfb_v3_state_snapshots_parent_idx
    ON cfb_v3_state_snapshots(parent_snapshot_id);

CREATE INDEX IF NOT EXISTS cfb_v3_operation_commits_snapshot_idx
    ON cfb_v3_operation_commits(snapshot_id);
