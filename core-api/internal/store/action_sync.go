package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"

	"aibuddy/core-api/internal/diagnostics"
	"aibuddy/core-api/internal/onboarding"
)

func (s *Store) PendingActions(ctx context.Context, ownerID, actionID string) ([]ActionRecord, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT id, type, status, external_id
		FROM core.actions
		WHERE owner_id = $1 AND ($2 = '' OR id = $2) AND external_id IS NOT NULL
		  AND (status = 'submitted' OR (status = 'approved' AND type = 'access_request' AND fulfilled_at IS NULL))
		ORDER BY corp_updated_at NULLS FIRST, created_at, id
	`, ownerID, actionID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var actions []ActionRecord
	for rows.Next() {
		record := ActionRecord{OwnerID: ownerID}
		if err := rows.Scan(&record.ID, &record.Type, &record.Status, &record.ExternalID); err != nil {
			return nil, err
		}
		actions = append(actions, record)
	}
	return actions, rows.Err()
}

func applyActionChange(ctx context.Context, tx *sql.Tx, record ActionRecord, update ActionChange) ([]statusEvent, error) {
	if update.Status == "" || !mayAdvance(record.Status, update.Status) ||
		(record.CorpUpdatedAt != nil && update.UpdatedAt.Before(*record.CorpUpdatedAt)) {
		return nil, nil
	}

	statusChanged := update.Status != record.Status
	granted := record.Type == "access_request" && update.Status == "approved" &&
		update.FulfilledAt != nil && record.FulfilledAt == nil
	taskID := record.TaskID
	if record.Type == "access_request" && taskID == nil && (update.Status == "submitted" ||
		update.Status == "approved" || record.Status == "submitted" || update.Result != nil) {
		var err error
		taskID, err = findAccessTask(ctx, tx, record, update.AccessSystem)
		if err != nil {
			return nil, err
		}
	}

	var result any
	if update.Result != nil {
		data, err := json.Marshal(update.Result)
		if err != nil {
			return nil, err
		}
		result = string(data)
	}
	if !granted {
		update.FulfilledAt = nil
	}
	_, err := tx.ExecContext(ctx, `
		UPDATE core.actions
		SET status = $3, result = COALESCE($4::jsonb, result), error = NULL, corp_updated_at = $5,
		    fulfilled_at = COALESCE(fulfilled_at, $6), task_id = $7,
		    access_system = COALESCE(access_system, NULLIF($8, '')),
		    updated_at = CASE WHEN $9 THEN greatest(updated_at, $5::timestamptz) ELSE updated_at END
		WHERE owner_id = $1 AND id = $2
	`, record.OwnerID, record.ID, update.Status, result, update.UpdatedAt, update.FulfilledAt,
		taskID, update.AccessSystem, statusChanged || granted)
	if err != nil {
		return nil, err
	}

	var events []statusEvent
	if statusChanged {
		events = append(events, statusEvent{"action", record.ID, record.Status, update.Status})
	}
	if granted {
		events = append(events, statusEvent{"access", record.ID, "pending", "granted"})
	}
	if statusChanged || granted {
		key := record.ID + ":" + update.Status
		if !statusChanged && granted {
			key += ":fulfilled"
		}
		_, err = tx.ExecContext(ctx, `
			INSERT INTO core.notifications (owner_id, kind, event_key, text, task_id, action_id, request_id)
			VALUES ($1, 'action_status', $2, $3, $4, $5, NULLIF($6, ''))
			ON CONFLICT (owner_id, kind, event_key) DO NOTHING
		`, record.OwnerID, key, actionNotice(record.Title, update.Status, granted), taskID, record.ID, diagnostics.ID(ctx))
		if err != nil {
			return nil, err
		}
		if event := actionOutcome(record, update.Status, statusChanged, granted); event != "" {
			if err := recordActionEvent(ctx, tx, record, event, update.Status); err != nil {
				return nil, err
			}
		}
	}
	if taskID != nil {
		taskEvents, err := syncAccessTask(ctx, tx, record.OwnerID, *taskID)
		if err != nil {
			return nil, err
		}
		events = append(events, taskEvents...)
	}
	return events, nil
}

func mayAdvance(current, next string) bool {
	if current == next {
		return true
	}
	switch current {
	case "draft", "failed":
		return next == "submitted" || next == "approved" || next == "rejected" || next == "cancelled"
	case "submitted":
		return next == "approved" || next == "rejected" || next == "cancelled"
	default:
		return false
	}
}

func actionNotice(title, status string, granted bool) string {
	if granted {
		return "Доступ по заявке «" + title + "» выдан."
	}
	prefix := "Заявка «" + title + "» "
	switch status {
	case "submitted":
		return prefix + "отправлена на согласование."
	case "approved":
		return prefix + "согласована."
	case "rejected":
		return prefix + "отклонена."
	default:
		return prefix + "отменена."
	}
}

func findAccessTask(ctx context.Context, tx *sql.Tx, record ActionRecord, system string) (*string, error) {
	target := "t_request_accesses"
	if system == "team_space" {
		target = "t_team_space"
	}
	var taskID string
	err := tx.QueryRowContext(ctx, `
		SELECT id
		FROM core.tasks
		WHERE owner_id = $1 AND related_action_type = 'access_request'
		  AND (related_action_id = $2 OR (id = $3 AND $4 <> '') OR (
		      SELECT count(*) FROM core.tasks WHERE owner_id = $1 AND related_action_type = 'access_request'
		  ) = 1 AND id NOT IN ('t_request_accesses', 't_team_space'))
		ORDER BY (related_action_id IS NOT DISTINCT FROM $2) DESC, id
		LIMIT 1
	`, record.OwnerID, record.ID, target, system).Scan(&taskID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &taskID, nil
}

// accessTaskOutcome учитывает последнюю связанную заявку для каждой системы.
func accessTaskOutcome(ctx context.Context, tx *sql.Tx, ownerID, taskID string) (status, actionID string, err error) {
	err = tx.QueryRowContext(ctx, `
		WITH latest AS (
		    SELECT DISTINCT ON (COALESCE(access_system, id)) id, created_at,
		        CASE WHEN status = 'approved' AND fulfilled_at IS NOT NULL THEN 'done'
		             WHEN status IN ('submitted', 'approved') THEN 'in_progress'
		             ELSE 'blocked' END AS task_status
		    FROM core.actions WHERE owner_id = $1 AND task_id = $2
		      AND status IN ('submitted', 'approved', 'rejected', 'cancelled')
		    ORDER BY COALESCE(access_system, id), created_at DESC, id DESC
		)
		SELECT task_status, id FROM latest
		ORDER BY CASE task_status WHEN 'in_progress' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END, created_at DESC, id DESC
		LIMIT 1
	`, ownerID, taskID).Scan(&status, &actionID)
	return status, actionID, err
}

func syncAccessTask(ctx context.Context, tx *sql.Tx, ownerID, taskID string) ([]statusEvent, error) {
	var oldStatus string
	err := tx.QueryRowContext(ctx, `
		SELECT status FROM core.tasks WHERE owner_id = $1 AND id = $2 FOR NO KEY UPDATE
	`, ownerID, taskID).Scan(&oldStatus)
	if err != nil {
		return nil, err
	}
	status, actionID, err := accessTaskOutcome(ctx, tx, ownerID, taskID)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if oldStatus == onboarding.Done {
		status = oldStatus
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE core.tasks SET status = $3, related_action_id = $4
		WHERE owner_id = $1 AND id = $2 AND (status <> $3 OR related_action_id IS DISTINCT FROM $4)
	`, ownerID, taskID, status, actionID); err != nil {
		return nil, err
	}
	if oldStatus == status {
		return nil, nil
	}
	return []statusEvent{{"task", taskID, oldStatus, status}}, nil
}

func (s *Store) SyncAction(ctx context.Context, record ActionRecord, update ActionChange) error {
	_, err := s.ChangeAction(ctx, record.OwnerID, record.ID, "", func(ActionRecord) (ActionChange, error) {
		return update, nil
	})
	return err
}
