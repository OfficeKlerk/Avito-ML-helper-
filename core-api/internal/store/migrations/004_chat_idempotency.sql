-- B4: ход чата с Idempotency-Key. Строка появляется вместе с сообщением пользователя,
-- ответ — в той же транзакции, что и ответ помощника. response IS NULL — ход прервался, его можно продолжить.
CREATE TABLE core.chat_requests (
    owner_id text NOT NULL REFERENCES core.users(id),
    idempotency_key text NOT NULL,
    request_id text NOT NULL,
    user_message_id text NOT NULL,
    response jsonb CHECK (response IS NULL OR jsonb_typeof(response) = 'object'),
    PRIMARY KEY (owner_id, idempotency_key),
    FOREIGN KEY (owner_id, user_message_id) REFERENCES core.messages(owner_id, id) ON DELETE CASCADE
);
