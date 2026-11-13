package store

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"database/sql/driver"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"aibuddy/core-api/internal/onboarding"
)

var ErrChatBusy = errors.New("chat busy")

// ErrKeyConflict — Idempotency-Key уже использован для другого текста.
var ErrKeyConflict = errors.New("idempotency key reused with another text")

type HistoryItem struct {
	Role string `json:"role"`
	Text string `json:"text"`
}

type Source struct {
	DocID   string  `json:"doc_id"`
	ChunkID string  `json:"chunk_id"`
	Title   string  `json:"title"`
	Section *string `json:"section,omitempty"`
}

type Message struct {
	ID          string            `json:"id"`
	Role        string            `json:"role"`
	Text        string            `json:"text"`
	Sources     []Source          `json:"sources"`
	Actions     []json.RawMessage `json:"actions"`
	Suggestions []string          `json:"suggestions"`
	Status      string            `json:"status"`
	CreatedAt   time.Time         `json:"created_at"`
}

type Draft struct {
	Type       string            `json:"type"`
	Title      string            `json:"title"`
	ExternalID string            `json:"external_id"`
	Fields     map[string]string `json:"fields"`
}

type TaskUpdate struct {
	TaskID string `json:"task_id"`
	Status string `json:"status"`
}

type Reply struct {
	Message
	State       json.RawMessage
	Drafts      []Draft
	TaskUpdates []TaskUpdate
	// Product — сценарий метрик, к которому клиент привязал ход.
	Product Product
}

type ChatSession struct {
	conn    *sql.Conn
	ownerID string
}

const chatLock = `hashtextextended('core-chat:' || $1, 0)`

// WithChat резервирует один диалог. Сообщение пользователя можно зафиксировать
// до обращения к агенту, сохранив порядок ходов между экземплярами core-api.
func (s *Store) WithChat(ctx context.Context, ownerID string, run func(*ChatSession) error) error {
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return err
	}
	defer conn.Close()
	discard := func() {
		_ = conn.Raw(func(any) error { return driver.ErrBadConn })
	}
	var locked bool
	err = conn.QueryRowContext(ctx, `SELECT pg_try_advisory_lock(`+chatLock+`)`, ownerID).Scan(&locked)
	if err != nil {
		discard()
		return err
	}
	if !locked {
		return ErrChatBusy
	}
	defer func() {
		release, cancel := context.WithTimeout(context.WithoutCancel(ctx), 2*time.Second)
		defer cancel()
		if _, err := conn.ExecContext(release, `SELECT pg_advisory_unlock(`+chatLock+`)`, ownerID); err != nil {
			discard()
		}
	}()
	return run(&ChatSession{conn: conn, ownerID: ownerID})
}

// Context — план, последние сообщения и состояние диалога. excludeID — сообщение текущего хода,
// если оно уже сохранено (продолжение прерванного хода): в историю для агента оно не входит.
func (s *ChatSession) Context(ctx context.Context, limit int, excludeID string) ([]onboarding.Stage, []HistoryItem, json.RawMessage, error) {
	stages, err := loadStages(ctx, s.conn, s.ownerID)
	if err != nil {
		return nil, nil, nil, err
	}
	var historyJSON, state json.RawMessage
	err = s.conn.QueryRowContext(ctx, `
		SELECT COALESCE((
		    SELECT jsonb_agg(jsonb_build_object('role', role, 'text', text) ORDER BY created_at, id)
		    FROM (SELECT id, role, text, created_at FROM core.messages WHERE owner_id = $1 AND id <> $3
		          ORDER BY created_at DESC, id DESC LIMIT $2) recent
		), '[]'), COALESCE((SELECT state FROM core.chat_state WHERE owner_id = $1), 'null')
	`, s.ownerID, limit, excludeID).Scan(&historyJSON, &state)
	if err != nil {
		return nil, nil, nil, err
	}
	var history []HistoryItem
	err = json.Unmarshal(historyJSON, &history)
	return stages, history, state, err
}

func userMessage(id, text string) Message {
	return Message{ID: id, Role: "user", Text: text, Status: "ok",
		Sources: []Source{}, Suggestions: []string{}, Actions: []json.RawMessage{}}
}

// AddUserMessage сохраняет сообщение. С ключом в том же запросе запоминается начатый ход.
func (s *ChatSession) AddUserMessage(ctx context.Context, id, text, key, requestID string) (Message, error) {
	msg := userMessage(id, text)
	err := s.conn.QueryRowContext(ctx, `
		WITH msg AS (
			INSERT INTO core.messages (id, owner_id, role, text, status, created_at)
			VALUES ($1, $2, 'user', $3, 'ok', clock_timestamp()) RETURNING created_at
		), turn AS (
			INSERT INTO core.chat_requests (owner_id, idempotency_key, request_id, user_message_id)
			SELECT $2, $4, $5, $1 WHERE $4 <> ''
		)
		SELECT created_at FROM msg
	`, id, s.ownerID, text, key, requestID).Scan(&msg.CreatedAt)
	return msg, err
}

// Turn — ход, начатый раньше с тем же ключом.
type Turn struct {
	RequestID   string
	UserMessage Message
	// Response — сохранённый ответ; nil, если ход прервался до ответа помощника.
	Response json.RawMessage
}

// Turn ищет ход по ключу. found=false — ключ новый; другой текст с тем же ключом — ErrKeyConflict.
func (s *ChatSession) Turn(ctx context.Context, key, text string) (turn Turn, found bool, err error) {
	var storedText string
	var response []byte
	err = s.conn.QueryRowContext(ctx, `
		SELECT r.request_id, r.response, m.id, m.text, m.created_at
		FROM core.chat_requests r JOIN core.messages m ON m.owner_id = r.owner_id AND m.id = r.user_message_id
		WHERE r.owner_id = $1 AND r.idempotency_key = $2
	`, s.ownerID, key).Scan(&turn.RequestID, &response, &turn.UserMessage.ID, &storedText, &turn.UserMessage.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return Turn{}, false, nil
	}
	if err != nil {
		return Turn{}, false, err
	}
	if storedText != text {
		return Turn{}, true, ErrKeyConflict
	}
	createdAt := turn.UserMessage.CreatedAt
	turn.UserMessage = userMessage(turn.UserMessage.ID, storedText)
	turn.UserMessage.CreatedAt = createdAt
	turn.Response = response
	return turn, true, nil
}

// Finish сохраняет ответ, карточки, предложения по задачам и состояние диалога атомарно.
// С ключом в той же транзакции запоминается весь ответ хода — повтор вернёт его без агента.
func (s *ChatSession) Finish(ctx context.Context, userMessage Message, reply Reply, key string) (Message, error) {
	tx, err := s.conn.BeginTx(ctx, nil)
	if err != nil {
		return Message{}, err
	}
	defer tx.Rollback()
	msg := reply.Message
	msg.Actions = []json.RawMessage{}
	sources, err := json.Marshal(msg.Sources)
	if err != nil {
		return Message{}, err
	}
	suggestions, err := json.Marshal(msg.Suggestions)
	if err != nil {
		return Message{}, err
	}
	err = tx.QueryRowContext(ctx, `
		INSERT INTO core.messages (id, owner_id, role, text, sources, suggestions, status, created_at)
		VALUES ($1, $2, 'assistant', $3, $4, $5, $6, greatest(clock_timestamp(), $7::timestamptz + interval '1 microsecond'))
		RETURNING created_at
	`, msg.ID, s.ownerID, msg.Text, string(sources), string(suggestions), msg.Status, userMessage.CreatedAt).Scan(&msg.CreatedAt)
	if err != nil {
		return Message{}, err
	}
	seen := make(map[string]bool)
	var events []statusEvent
	for _, draft := range reply.Drafts {
		if seen[draft.ExternalID] {
			continue
		}
		seen[draft.ExternalID] = true
		card, createdID, err := saveDraft(ctx, tx, s.ownerID, msg.ID, len(msg.Actions), draft, msg.CreatedAt, reply.Product)
		if err != nil {
			return Message{}, err
		}
		msg.Actions = append(msg.Actions, card)
		if createdID != "" {
			events = append(events, statusEvent{"action", createdID, "", "draft"})
		}
	}
	if reply.State != nil {
		if string(reply.State) == "null" {
			_, err = tx.ExecContext(ctx, `DELETE FROM core.chat_state WHERE owner_id = $1`, s.ownerID)
		} else {
			_, err = tx.ExecContext(ctx, `
				INSERT INTO core.chat_state (owner_id, state) VALUES ($1, $2)
				ON CONFLICT (owner_id) DO UPDATE SET state = EXCLUDED.state
			`, s.ownerID, string(reply.State))
		}
		if err != nil {
			return Message{}, err
		}
	}
	for _, update := range reply.TaskUpdates {
		if !onboarding.ValidStatus(update.Status) {
			continue
		}
		var oldStatus string
		err := tx.QueryRowContext(ctx, `
			WITH previous AS (
			    SELECT status FROM core.tasks
			    WHERE owner_id = $1 AND id = $2 AND status NOT IN ('done', $3)
			      AND ($3 <> 'done' OR related_action_type IS NULL)
			    FOR NO KEY UPDATE
			)
			UPDATE core.tasks SET status = $3 FROM previous
			WHERE owner_id = $1 AND id = $2 RETURNING previous.status
		`, s.ownerID, update.TaskID, update.Status).Scan(&oldStatus)
		if errors.Is(err, sql.ErrNoRows) {
			continue
		}
		if err != nil {
			return Message{}, err
		}
		events = append(events, statusEvent{"task", update.TaskID, oldStatus, update.Status})
	}
	if err := recordAnswerEvent(ctx, tx, s.ownerID, reply.Product, msg); err != nil {
		return Message{}, err
	}
	if key != "" {
		exchange, err := json.Marshal(map[string]Message{"user_message": userMessage, "assistant_message": msg})
		if err != nil {
			return Message{}, err
		}
		_, err = tx.ExecContext(ctx, `
			UPDATE core.chat_requests SET response = $3 WHERE owner_id = $1 AND idempotency_key = $2
		`, s.ownerID, key, string(exchange))
		if err != nil {
			return Message{}, err
		}
	}
	if err := tx.Commit(); err != nil {
		return Message{}, err
	}
	logStatusEvents(ctx, events)
	return msg, nil
}

func saveDraft(ctx context.Context, tx *sql.Tx, ownerID, messageID string, position int, draft Draft, created time.Time, product Product) (json.RawMessage, string, error) {
	hash := sha256.Sum256([]byte(ownerID + ":" + draft.ExternalID))
	id := fmt.Sprintf("act_%x", hash[:16])
	fields, err := json.Marshal(draft.Fields)
	if err != nil {
		return nil, "", err
	}
	result, err := tx.ExecContext(ctx, `
		INSERT INTO core.actions (id, owner_id, type, status, title, fields, external_id, created_at, updated_at,
		                          product_session_id, product_scenario_id)
		VALUES ($1, $2, $3, 'draft', $4, $5, $6, $7, $7, NULLIF($8, '')::uuid, NULLIF($9, '')::uuid)
		ON CONFLICT (owner_id, external_id) DO NOTHING
	`, id, ownerID, draft.Type, draft.Title, string(fields), draft.ExternalID, created, product.SessionID, product.ScenarioID)
	if err != nil {
		return nil, "", err
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return nil, "", err
	}
	var card json.RawMessage
	err = tx.QueryRowContext(ctx, `
		SELECT card.id, to_jsonb(card)
		FROM (SELECT `+actionFields+` FROM core.actions a WHERE a.owner_id = $1 AND a.external_id = $2) card
	`, ownerID, draft.ExternalID).Scan(&id, &card)
	if err != nil {
		return nil, "", err
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO core.message_actions (owner_id, message_id, action_id, position) VALUES ($1, $2, $3, $4)
	`, ownerID, messageID, id, position)
	createdID := ""
	if inserted > 0 {
		createdID = id
	}
	return card, createdID, err
}
