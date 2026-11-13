package store

import (
	"context"
	"encoding/json"
	"time"

	"aibuddy/core-api/internal/diagnostics"
)

func (s *Store) Notifications(ctx context.Context, ownerID string) (json.RawMessage, error) {
	var items json.RawMessage
	err := s.db.QueryRowContext(ctx, `
		SELECT COALESCE(jsonb_agg(to_jsonb(item) - 'seq' ORDER BY item.created_at DESC, item.seq DESC), '[]')
		FROM (
			SELECT 'ntf_' || id AS id, id AS seq, kind, text, task_id, action_id, created_at, read
			FROM core.notifications WHERE owner_id = $1
		) item
	`, ownerID).Scan(&items)
	return items, err
}

// CreateOverdueReminders создаёт одно напоминание на задачу и дату её срока.
func (s *Store) CreateOverdueReminders(ctx context.Context, now time.Time) (int64, error) {
	result, err := s.db.ExecContext(ctx, `
		INSERT INTO core.notifications (owner_id, kind, event_key, text, task_id, request_id, created_at)
		SELECT owner_id, 'reminder', id || ':' || to_char(due_date, 'YYYY-MM-DD'),
		       'Просрочена задача «' || title || '» (срок ' || to_char(due_date, 'DD.MM.YYYY') || ').',
		       id, NULLIF($3, ''), $2
		FROM core.tasks
		WHERE due_date < $1::date AND status <> 'done'
		ON CONFLICT (owner_id, kind, event_key) DO NOTHING
	`, now.Format(time.DateOnly), now, diagnostics.ID(ctx))
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}
