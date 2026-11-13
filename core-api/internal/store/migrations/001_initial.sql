CREATE TABLE core.teams (
    id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE core.users (
    id text PRIMARY KEY,
    login text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    name text NOT NULL,
    role text NOT NULL CHECK (role IN ('intern', 'mentor', 'manager', 'hr')),
    team_id text REFERENCES core.teams(id),
    mentor_id text REFERENCES core.users(id) DEFERRABLE INITIALLY DEFERRED,
    manager_id text REFERENCES core.users(id) DEFERRABLE INITIALLY DEFERRED,
    start_date date,
    program text CHECK (program IN ('6m', '9m'))
);

CREATE TABLE core.stages (
    id text PRIMARY KEY,
    title text NOT NULL,
    period text NOT NULL,
    position integer NOT NULL
);

CREATE TABLE core.actions (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES core.users(id),
    type text NOT NULL CHECK (type IN ('absence_request', 'access_request')),
    status text NOT NULL CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'cancelled', 'failed')),
    title text NOT NULL,
    fields jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(fields) = 'object'),
    external_id text,
    result jsonb CHECK (jsonb_typeof(result) = 'object'),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, id)
);
CREATE INDEX actions_owner_created_idx ON core.actions (owner_id, created_at DESC, id DESC);

CREATE TABLE core.tasks (
    owner_id text NOT NULL REFERENCES core.users(id),
    id text NOT NULL,
    stage_id text NOT NULL REFERENCES core.stages(id),
    title text NOT NULL,
    description text NOT NULL,
    status text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done', 'blocked')),
    due_date date,
    position integer NOT NULL,
    links jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(links) = 'array'),
    related_action_type text CHECK (related_action_type IN ('absence_request', 'access_request')),
    related_action_id text,
    PRIMARY KEY (owner_id, id),
    FOREIGN KEY (owner_id, related_action_id) REFERENCES core.actions(owner_id, id)
);

CREATE TABLE core.messages (
    id text PRIMARY KEY,
    owner_id text NOT NULL REFERENCES core.users(id),
    role text NOT NULL CHECK (role IN ('user', 'assistant')),
    text text NOT NULL,
    sources jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(sources) = 'array'),
    suggestions jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(suggestions) = 'array'),
    status text NOT NULL CHECK (status IN ('ok', 'degraded', 'error')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner_id, id)
);
CREATE INDEX messages_owner_created_idx ON core.messages (owner_id, created_at DESC, id DESC);

CREATE TABLE core.message_actions (
    owner_id text NOT NULL,
    message_id text NOT NULL,
    action_id text NOT NULL,
    position integer NOT NULL,
    PRIMARY KEY (owner_id, message_id, action_id),
    FOREIGN KEY (owner_id, message_id) REFERENCES core.messages(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY (owner_id, action_id) REFERENCES core.actions(owner_id, id)
);
