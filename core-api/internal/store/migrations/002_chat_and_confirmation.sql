ALTER TABLE core.actions ADD UNIQUE (owner_id, external_id);

CREATE TABLE core.chat_state (
    owner_id text PRIMARY KEY REFERENCES core.users(id),
    state jsonb NOT NULL CHECK (jsonb_typeof(state) = 'object')
);

CREATE TABLE core.action_confirmations (
    owner_id text NOT NULL,
    action_id text NOT NULL,
    idempotency_key text NOT NULL,
    response jsonb NOT NULL CHECK (jsonb_typeof(response) = 'object'),
    PRIMARY KEY (owner_id, action_id, idempotency_key),
    FOREIGN KEY (owner_id, action_id) REFERENCES core.actions(owner_id, id) ON DELETE CASCADE
);
