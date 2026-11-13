ALTER TABLE core.actions
    ADD COLUMN corp_updated_at timestamptz,
    ADD COLUMN fulfilled_at timestamptz,
    ADD COLUMN access_system text,
    ADD COLUMN task_id text,
    ADD FOREIGN KEY (owner_id, task_id) REFERENCES core.tasks(owner_id, id) ON DELETE SET NULL (task_id);

CREATE INDEX actions_task_idx ON core.actions (owner_id, task_id) WHERE task_id IS NOT NULL;

CREATE TABLE core.notifications (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_id text NOT NULL REFERENCES core.users(id),
    kind text NOT NULL CHECK (kind IN ('reminder', 'action_status')),
    event_key text NOT NULL,
    text text NOT NULL,
    task_id text,
    action_id text,
    request_id text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    read boolean NOT NULL DEFAULT false,
    UNIQUE (owner_id, kind, event_key),
    FOREIGN KEY (owner_id, task_id) REFERENCES core.tasks(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, action_id) REFERENCES core.actions(owner_id, id) ON DELETE CASCADE
);

CREATE INDEX notifications_owner_created_idx ON core.notifications (owner_id, created_at DESC, id DESC);
