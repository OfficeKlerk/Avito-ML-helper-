package store

import (
	"context"
	"database/sql"
	"errors"
	"time"
)

// ErrEventConflict — event_id уже использован для другого события.
var ErrEventConflict = errors.New("event id reused with other fields")

// Product связывает ход чата и созданные в нём карточки со сценарием метрик (B3). Пустой — связи нет.
type Product struct {
	SessionID  string
	ScenarioID string
}

type ClientEvent struct {
	EventID, SessionID, ScenarioID, Scenario, Event string
}

// RecordClientEvent сохраняет событие клиента. Повтор с теми же полями возвращает прежнее время,
// с другими — ErrEventConflict.
func (s *Store) RecordClientEvent(ctx context.Context, ownerID string, e ClientEvent) (time.Time, error) {
	var recordedAt time.Time
	var same bool
	// Строки, вставленные в WITH, этот же запрос в таблице не видит: второй SELECT находит только прежнюю запись.
	// Если такой же запрос вставил её параллельно, наш снимок данных старше и не видит ничего —
	// тогда повторяем: новый запрос уже видит сохранённую запись.
	query := func() error {
		return s.db.QueryRowContext(ctx, `
		WITH inserted AS (
			INSERT INTO core.product_events (owner_id, event_id, session_id, scenario_id, scenario, event, source)
			VALUES ($1, $2, $3, $4, $5, $6, 'client')
			ON CONFLICT (owner_id, event_id) DO NOTHING
			RETURNING recorded_at
		)
		SELECT recorded_at, true FROM inserted
		UNION ALL
		SELECT recorded_at, session_id = $3::uuid AND scenario_id = $4::uuid AND scenario = $5 AND event = $6 AND source = 'client'
		FROM core.product_events WHERE owner_id = $1 AND event_id = $2::uuid AND NOT EXISTS (SELECT 1 FROM inserted)
	`, ownerID, e.EventID, e.SessionID, e.ScenarioID, e.Scenario, e.Event).Scan(&recordedAt, &same)
	}
	err := query()
	if errors.Is(err, sql.ErrNoRows) {
		err = query()
	}
	if err != nil {
		return time.Time{}, err
	}
	if !same {
		return time.Time{}, ErrEventConflict
	}
	return recordedAt, nil
}

// actionOutcome — серверное событие для смены статуса карточки. Пусто — событие не нужно.
// Доступ считается выданным только при fulfilled_at, отгул — при согласовании.
func actionOutcome(record ActionRecord, status string, statusChanged, granted bool) string {
	switch {
	case granted, statusChanged && status == "approved" && record.Type == "absence_request":
		return "action_succeeded"
	case statusChanged && status == "submitted":
		return "action_confirmed"
	case statusChanged && (status == "rejected" || status == "cancelled"):
		return "action_failed"
	}
	return ""
}

// recordActionEvent пишет событие карточки, если её создали в ходе, привязанном к сценарию.
func recordActionEvent(ctx context.Context, tx *sql.Tx, record ActionRecord, event, status string) error {
	_, err := tx.ExecContext(ctx, `
		INSERT INTO core.product_events (owner_id, event_id, session_id, scenario_id, scenario, event, source, action_id, status)
		SELECT owner_id, gen_random_uuid(), product_session_id, product_scenario_id,
		       CASE type WHEN 'absence_request' THEN 'absence' ELSE 'access' END, $3, 'server', id, $4
		FROM core.actions WHERE owner_id = $1 AND id = $2 AND product_scenario_id IS NOT NULL
	`, record.OwnerID, record.ID, event, status)
	return err
}

// recordAnswerEvent пишет ответ помощника в ходе, привязанном к сценарию.
func recordAnswerEvent(ctx context.Context, tx *sql.Tx, ownerID string, product Product, msg Message) error {
	if product.ScenarioID == "" {
		return nil
	}
	_, err := tx.ExecContext(ctx, `
		INSERT INTO core.product_events (owner_id, event_id, session_id, scenario_id, scenario, event, source, message_id, status)
		VALUES ($1, gen_random_uuid(), $2, $3, (
			SELECT scenario FROM core.product_events
			WHERE owner_id = $1 AND scenario_id = $3::uuid AND scenario IS NOT NULL ORDER BY recorded_at LIMIT 1
		), 'assistant_answered', 'server', $4, $5)
	`, ownerID, product.SessionID, product.ScenarioID, msg.ID, msg.Status)
	return err
}
