CREATE SEQUENCE corp.request_reference_seq;

CREATE TABLE corp.requests (
    id text PRIMARY KEY CHECK (id ~ '^req_[a-z0-9_]+$'),
    type text NOT NULL CHECK (type IN ('absence_request', 'access_request')),
    status text NOT NULL CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'cancelled')),
    owner_id text NOT NULL,
    team_id text NOT NULL,
    approver jsonb CHECK (jsonb_typeof(approver) = 'object'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    summary text NOT NULL,
    external_ref text UNIQUE,
    fulfilled_at timestamptz CHECK (fulfilled_at IS NULL OR (type = 'access_request' AND status = 'approved')),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= created_at)
);

CREATE TABLE corp.request_submissions (
    request_id text NOT NULL REFERENCES corp.requests(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    PRIMARY KEY (request_id, idempotency_key)
);
