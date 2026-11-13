package store

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"aibuddy/corp-mock/internal/corporate"
)

func (s *Store) List(ctx context.Context, user corporate.User, kind string) ([]corporate.Request, error) {
	return listRequests(ctx, s.db, user, kind)
}

func listRequests(ctx context.Context, db interface {
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}, user corporate.User, kind string) ([]corporate.Request, error) {
	result := []corporate.Request{}
	if user.TeamID == nil {
		return result, nil
	}
	rows, err := db.QueryContext(ctx, `
		SELECT `+requestColumns+` FROM corp.requests
		WHERE owner_id = $1 AND team_id = $2 AND type = $3
		ORDER BY created_at DESC, id DESC
	`, user.ID, *user.TeamID, kind)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		request, err := scanRequest(rows)
		if err != nil {
			return nil, err
		}
		result = append(result, request)
	}
	return result, rows.Err()
}

type DraftInput struct {
	Kind    string
	Key     string
	System  string
	Catalog corporate.AccessCatalog
	Build   func() (json.RawMessage, string, *corporate.Ref, error)
}

// CreateDraft сериализует создание для владельца и фиксирует черновик и ключ в одной транзакции.
func (s *Store) CreateDraft(ctx context.Context, user corporate.User, input DraftInput, now time.Time) (corporate.Request, error) {
	if user.TeamID == nil {
		return corporate.Request{}, corporate.Deny(corporate.ErrForbidden, "Подать заявку может только сотрудник команды.")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return corporate.Request{}, err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtextextended('corp-drafts:' || $1, 0))`, user.ID); err != nil {
		return corporate.Request{}, err
	}
	replay, err := scanRequest(tx.QueryRowContext(ctx, `
		SELECT `+requestColumns+` FROM corp.requests
		WHERE id = (SELECT request_id FROM corp.draft_keys
		            WHERE owner_id = $1 AND team_id = $2 AND type = $3 AND idempotency_key = $4)
	`, user.ID, *user.TeamID, input.Kind, input.Key))
	if err == nil {
		return replay, nil
	}
	if !errors.Is(err, corporate.ErrNotFound) {
		return corporate.Request{}, err
	}
	payload, summary, approver, err := input.Build()
	if err != nil {
		return corporate.Request{}, err
	}
	var draft corporate.Request
	if input.Kind == "access_request" {
		draft, err = existingAccessDraft(ctx, tx, user, input)
		if err != nil {
			return corporate.Request{}, err
		}
	}
	if draft.ID == "" {
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			return corporate.Request{}, err
		}
		approverJSON, err := json.Marshal(approver)
		if err != nil {
			return corporate.Request{}, err
		}
		draft, err = scanRequest(tx.QueryRowContext(ctx, `
			INSERT INTO corp.requests (id, type, status, owner_id, team_id, approver, payload, summary, created_at, updated_at)
			VALUES ($1,$2,'draft',$3,$4,$5,$6,$7,$8,$8)
			RETURNING `+requestColumns, fmt.Sprintf("req_%x", random), input.Kind, user.ID, *user.TeamID,
			string(approverJSON), string(payload), summary, now))
		if err != nil {
			return corporate.Request{}, err
		}
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO corp.draft_keys (owner_id, team_id, type, idempotency_key, request_id)
		VALUES ($1,$2,$3,$4,$5)
	`, user.ID, *user.TeamID, input.Kind, input.Key, draft.ID); err != nil {
		return corporate.Request{}, err
	}
	return draft, tx.Commit()
}
