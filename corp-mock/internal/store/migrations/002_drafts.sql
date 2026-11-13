ALTER TABLE corp.requests ADD UNIQUE (owner_id, team_id, type, id);

CREATE TABLE corp.draft_keys (
    owner_id text NOT NULL,
    team_id text NOT NULL,
    type text NOT NULL,
    idempotency_key text NOT NULL,
    request_id text NOT NULL,
    PRIMARY KEY (owner_id, team_id, type, idempotency_key),
    FOREIGN KEY (owner_id, team_id, type, request_id)
        REFERENCES corp.requests (owner_id, team_id, type, id) ON DELETE CASCADE
);

CREATE INDEX requests_owner_type_idx ON corp.requests (owner_id, team_id, type, created_at DESC, id DESC);
