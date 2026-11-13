// Package store хранит заявки corp-mock в отдельной схеме PostgreSQL.
package store

import (
	"context"
	"database/sql"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"aibuddy/corp-mock/internal/corporate"

	_ "github.com/lib/pq"
)

//go:embed migrations/*.sql
var migrations embed.FS

type Store struct {
	db *sql.DB
}

func New(db *sql.DB) *Store {
	return &Store{db: db}
}

func (s *Store) Initialize(ctx context.Context, dir string, directory *corporate.Directory) error {
	data, err := os.ReadFile(filepath.Join(dir, "requests.json"))
	if err != nil {
		return err
	}
	var seed struct {
		Preloaded []corporate.Request `json:"preloaded"`
	}
	if err := json.Unmarshal(data, &seed); err != nil {
		return err
	}
	for _, r := range seed.Preloaded {
		if err := directory.CheckRequest(r); err != nil {
			return fmt.Errorf("seed request %s: %w", r.ID, err)
		}
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err := tx.ExecContext(ctx, `
		-- Схемы core и corp создаются в общей базе при старте.
		SELECT pg_advisory_xact_lock(52801908);
		CREATE SCHEMA IF NOT EXISTS corp;
		CREATE TABLE IF NOT EXISTS corp.schema_migrations (version integer PRIMARY KEY);
	`); err != nil {
		return err
	}
	for version, name := range []string{"001_requests.sql", "002_drafts.sql"} {
		var applied bool
		if err := tx.QueryRowContext(ctx, `SELECT EXISTS (SELECT 1 FROM corp.schema_migrations WHERE version = $1)`, version+1).Scan(&applied); err != nil {
			return err
		}
		if applied {
			continue
		}
		body, err := migrations.ReadFile("migrations/" + name)
		if err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, string(body)); err != nil {
			return fmt.Errorf("migration %s: %w", name, err)
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO corp.schema_migrations (version) VALUES ($1)`, version+1); err != nil {
			return err
		}
	}
	for _, r := range seed.Preloaded {
		approver, err := json.Marshal(r.Approver)
		if err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, `
			INSERT INTO corp.requests (id, type, status, owner_id, team_id, approver, payload, summary,
			    external_ref, fulfilled_at, created_at, updated_at)
			VALUES ($1,$2,$3,$4,$5,NULLIF($6::jsonb,'null'::jsonb),$7,$8,$9,$10,$11,$12)
			ON CONFLICT (id) DO NOTHING
		`, r.ID, r.Type, r.Status, r.OwnerID, r.TeamID, string(approver), string(r.Payload), r.Summary,
			r.ExternalRef, r.FulfilledAt, r.CreatedAt, r.UpdatedAt)
		if err != nil {
			return err
		}
	}
	return tx.Commit()
}

const requestColumns = `id, type, status, owner_id, team_id, approver, payload, summary,
	external_ref, fulfilled_at, created_at, updated_at`

const requestSelect = `SELECT ` + requestColumns + ` FROM corp.requests WHERE id = $1`

func (s *Store) Get(ctx context.Context, user corporate.User, id string) (corporate.Request, error) {
	return s.getAuthorized(ctx, user, id, corporate.Read)
}

func (s *Store) Authorize(ctx context.Context, user corporate.User, id string, op corporate.Operation) error {
	_, err := s.getAuthorized(ctx, user, id, op)
	return err
}

func (s *Store) getAuthorized(ctx context.Context, user corporate.User, id string, op corporate.Operation) (corporate.Request, error) {
	r, err := scanRequest(s.db.QueryRowContext(ctx, requestSelect, id))
	if err != nil {
		return corporate.Request{}, err
	}
	if err := r.Authorize(user, op); err != nil {
		return corporate.Request{}, err
	}
	return r, nil
}

func (s *Store) Change(ctx context.Context, user corporate.User, id string, op corporate.Operation, key string, now time.Time) (corporate.Request, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return corporate.Request{}, err
	}
	defer tx.Rollback()
	r, err := scanRequest(tx.QueryRowContext(ctx, requestSelect+" FOR UPDATE", id))
	if err != nil {
		return corporate.Request{}, err
	}
	if err := r.Authorize(user, op); err != nil {
		return corporate.Request{}, err
	}
	if op == corporate.Submit {
		var replay bool
		err := tx.QueryRowContext(ctx, `
			SELECT EXISTS (SELECT 1 FROM corp.request_submissions WHERE request_id = $1 AND idempotency_key = $2)
		`, r.ID, key).Scan(&replay)
		if err != nil {
			return corporate.Request{}, err
		}
		if replay {
			return r, nil
		}
		if r.Status == corporate.Submitted {
			if err := saveSubmission(ctx, tx, r.ID, key); err != nil {
				return corporate.Request{}, err
			}
			return r, tx.Commit()
		}
	}
	changed, err := r.Transition(op, now)
	if err != nil {
		return corporate.Request{}, err
	}
	if op == corporate.Submit {
		prefix := "ABS"
		if r.Type == "access_request" {
			prefix = "ACC"
		}
		var reference string
		err = tx.QueryRowContext(ctx, `
			SELECT $1::text || '-' || $2::text || '-MOCK-' || nextval('corp.request_reference_seq')::text
		`, prefix, now.Year()).Scan(&reference)
		if err != nil {
			return corporate.Request{}, err
		}
		changed.ExternalRef = &reference
	}
	err = tx.QueryRowContext(ctx, `
		UPDATE corp.requests SET status = $2, external_ref = $3, updated_at = $4, fulfilled_at = $5
		WHERE id = $1 RETURNING updated_at, fulfilled_at
	`, changed.ID, changed.Status, changed.ExternalRef, changed.UpdatedAt, changed.FulfilledAt).
		Scan(&changed.UpdatedAt, &changed.FulfilledAt)
	if err != nil {
		return corporate.Request{}, err
	}
	if op == corporate.Submit {
		if err := saveSubmission(ctx, tx, r.ID, key); err != nil {
			return corporate.Request{}, err
		}
	}
	return changed, tx.Commit()
}

func saveSubmission(ctx context.Context, tx *sql.Tx, id, key string) error {
	_, err := tx.ExecContext(ctx, `INSERT INTO corp.request_submissions (request_id, idempotency_key) VALUES ($1, $2)`, id, key)
	return err
}

func scanRequest(row interface{ Scan(...any) error }) (corporate.Request, error) {
	var r corporate.Request
	var approver []byte
	err := row.Scan(&r.ID, &r.Type, &r.Status, &r.OwnerID, &r.TeamID, &approver, &r.Payload, &r.Summary,
		&r.ExternalRef, &r.FulfilledAt, &r.CreatedAt, &r.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return corporate.Request{}, corporate.ErrNotFound
	}
	if err != nil {
		return corporate.Request{}, err
	}
	if len(approver) > 0 {
		err = json.Unmarshal(approver, &r.Approver)
	}
	return r, err
}
