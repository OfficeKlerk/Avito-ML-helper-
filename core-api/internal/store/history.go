package store

import (
	"context"
	"encoding/json"
)

const actionFields = `a.id, a.type, a.status, a.title, a.fields, a.external_id, a.result, a.error,
	a.created_at, a.updated_at`

func (s *Store) Actions(ctx context.Context, ownerID string) (json.RawMessage, error) {
	var payload json.RawMessage
	err := s.db.QueryRowContext(ctx, `
		SELECT COALESCE(jsonb_agg(to_jsonb(card) ORDER BY card.created_at DESC, card.id DESC), '[]')
		FROM (SELECT `+actionFields+` FROM core.actions a WHERE a.owner_id = $1) card
	`, ownerID).Scan(&payload)
	return payload, err
}

func (s *Store) Action(ctx context.Context, ownerID, actionID string) (json.RawMessage, error) {
	var payload json.RawMessage
	err := s.db.QueryRowContext(ctx, `
		SELECT to_jsonb(card)
		FROM (SELECT `+actionFields+` FROM core.actions a WHERE a.owner_id = $1 AND a.id = $2) card
	`, ownerID, actionID).Scan(&payload)
	return payload, err
}

func (s *Store) Messages(ctx context.Context, ownerID string, limit int) (json.RawMessage, error) {
	var payload json.RawMessage
	err := s.db.QueryRowContext(ctx, `
		WITH recent AS (
			SELECT id, owner_id, role, text, sources, suggestions, status, created_at
			FROM core.messages WHERE owner_id = $1 ORDER BY created_at DESC, id DESC LIMIT $2
		)
		SELECT COALESCE(jsonb_agg(to_jsonb(message) ORDER BY message.created_at, message.id), '[]')
		FROM (
			SELECT m.id, m.role, m.text, m.sources, m.suggestions, m.status, m.created_at,
			       COALESCE((
			           SELECT jsonb_agg(to_jsonb(card) - 'position' ORDER BY card.position, card.id)
			           FROM (
			               SELECT `+actionFields+`, ma.position
			               FROM core.message_actions ma
			               JOIN core.actions a ON (a.owner_id, a.id) = (ma.owner_id, ma.action_id)
			               WHERE ma.owner_id = m.owner_id AND ma.message_id = m.id
			           ) card
			       ), '[]') AS actions
			FROM recent m
		) message
	`, ownerID, limit).Scan(&payload)
	return payload, err
}
