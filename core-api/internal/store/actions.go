package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"
)

type ActionRecord struct {
	ID            string
	OwnerID       string
	Type          string
	Status        string
	ExternalID    *string
	Title         string
	TaskID        *string
	CorpUpdatedAt *time.Time
	FulfilledAt   *time.Time
}

type ActionResult struct {
	Message     string  `json:"message"`
	ExternalRef *string `json:"external_ref"`
}

type ActionChange struct {
	Status       string
	Result       *ActionResult
	UpdatedAt    time.Time
	FulfilledAt  *time.Time
	AccessSystem string
}

// ChangeAction сериализует переходы одной карточки. Подтверждение и снимок
// ответа для повторов фиксируются в одной транзакции.
func (s *Store) ChangeAction(ctx context.Context, ownerID, actionID, confirmKey string,
	change func(ActionRecord) (ActionChange, error)) (json.RawMessage, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	record := ActionRecord{ID: actionID, OwnerID: ownerID}
	err = tx.QueryRowContext(ctx, `
		SELECT type, status, external_id, title, task_id, corp_updated_at, fulfilled_at
		FROM core.actions WHERE owner_id = $1 AND id = $2 FOR NO KEY UPDATE
	`, ownerID, actionID).Scan(&record.Type, &record.Status, &record.ExternalID, &record.Title, &record.TaskID,
		&record.CorpUpdatedAt, &record.FulfilledAt)
	if err != nil {
		return nil, err
	}

	var payload json.RawMessage
	if confirmKey != "" {
		err = tx.QueryRowContext(ctx, `
			SELECT response FROM core.action_confirmations WHERE owner_id = $1 AND action_id = $2 AND idempotency_key = $3
		`, ownerID, actionID, confirmKey).Scan(&payload)
		if err == nil {
			return payload, nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return nil, err
		}
	}
	update, err := change(record)
	if err != nil {
		return nil, err
	}
	events, err := applyActionChange(ctx, tx, record, update)
	if err != nil {
		return nil, err
	}

	err = tx.QueryRowContext(ctx, `
		SELECT to_jsonb(card)
		FROM (SELECT `+actionFields+` FROM core.actions a WHERE a.owner_id = $1 AND a.id = $2) card
	`, ownerID, actionID).Scan(&payload)
	if err != nil {
		return nil, err
	}
	if confirmKey != "" {
		_, err = tx.ExecContext(ctx, `
			INSERT INTO core.action_confirmations (owner_id, action_id, idempotency_key, response)
			VALUES ($1, $2, $3, $4)
		`, ownerID, actionID, confirmKey, string(payload))
		if err != nil {
			return nil, err
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	logStatusEvents(ctx, events)
	return payload, nil
}
