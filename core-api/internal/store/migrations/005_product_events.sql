-- B3: события для измерения пользы. Без текста диалога, JWT и паролей.
-- Клиент присылает начало сценария, открытие источника и обращение к человеку;
-- ответ помощника, подтверждение и итог заявки записывает сервер по сохранённым данным.
ALTER TABLE core.actions
    ADD COLUMN product_session_id uuid,
    ADD COLUMN product_scenario_id uuid;

CREATE TABLE core.product_events (
    owner_id text NOT NULL REFERENCES core.users(id),
    event_id uuid NOT NULL,
    session_id uuid NOT NULL,
    scenario_id uuid NOT NULL,
    -- У ответа помощника сценарий известен, только если клиент прислал scenario_started.
    scenario text CHECK (scenario IN ('onboarding', 'knowledge', 'absence', 'access')),
    event text NOT NULL CHECK (event IN ('scenario_started', 'source_opened', 'human_help_requested',
        'assistant_answered', 'action_confirmed', 'action_succeeded', 'action_failed')),
    source text NOT NULL CHECK (source IN ('client', 'server')),
    message_id text,
    action_id text,
    -- Статус ответа помощника (ok, degraded, error) или карточки после перехода.
    status text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_id, event_id)
);

CREATE INDEX product_events_scenario_idx ON core.product_events (owner_id, scenario_id, recorded_at);
