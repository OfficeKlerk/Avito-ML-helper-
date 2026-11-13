package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"

	"aibuddy/core-api/internal/onboarding"
)

const taskFields = `t.id, t.stage_id, t.title, t.description, t.status, to_char(t.due_date, 'YYYY-MM-DD'),
	t.links, t.related_action_type, t.related_action_id`

func (s *Store) Stages(ctx context.Context, ownerID string) ([]onboarding.Stage, error) {
	return loadStages(ctx, s.db, ownerID)
}

func loadStages(ctx context.Context, db interface {
	QueryContext(context.Context, string, ...any) (*sql.Rows, error)
}, ownerID string) ([]onboarding.Stage, error) {
	rows, err := db.QueryContext(ctx, `
		SELECT st.id, st.title, st.period, `+taskFields+`
		FROM core.tasks t JOIN core.stages st ON st.id = t.stage_id
		WHERE t.owner_id = $1
		ORDER BY st.position, st.id, t.position, t.id
	`, ownerID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var stages []onboarding.Stage
	for rows.Next() {
		var stage onboarding.Stage
		task, err := scanTask(rows, &stage.ID, &stage.Title, &stage.Period)
		if err != nil {
			return nil, err
		}
		if len(stages) == 0 || stages[len(stages)-1].ID != stage.ID {
			stages = append(stages, stage)
		}
		last := &stages[len(stages)-1]
		last.Tasks = append(last.Tasks, task)
	}
	return stages, rows.Err()
}

var ErrAccessNotGranted = errors.New("access has not been granted")

func (s *Store) SetTaskStatus(ctx context.Context, ownerID, taskID, status string) (onboarding.Task, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return onboarding.Task{}, err
	}
	defer tx.Rollback()
	var oldStatus string
	var actionType *string
	err = tx.QueryRowContext(ctx, `
		SELECT status, related_action_type FROM core.tasks WHERE owner_id = $1 AND id = $2 FOR NO KEY UPDATE
	`, ownerID, taskID).Scan(&oldStatus, &actionType)
	if err != nil {
		return onboarding.Task{}, err
	}
	if status == onboarding.Done && oldStatus != onboarding.Done && actionType != nil && *actionType == "access_request" {
		verified, _, err := accessTaskOutcome(ctx, tx, ownerID, taskID)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return onboarding.Task{}, err
		}
		if verified != onboarding.Done {
			return onboarding.Task{}, ErrAccessNotGranted
		}
	}
	task, err := scanTask(tx.QueryRowContext(ctx, `
		UPDATE core.tasks AS t SET status = $3 WHERE t.owner_id = $1 AND t.id = $2
		RETURNING `+taskFields, ownerID, taskID, status))
	if err != nil {
		return onboarding.Task{}, err
	}
	if err := tx.Commit(); err != nil {
		return onboarding.Task{}, err
	}
	if oldStatus != status {
		logStatusEvents(ctx, []statusEvent{{"task", taskID, oldStatus, status}})
	}
	return task, nil
}

func scanTask(row interface{ Scan(...any) error }, prefix ...any) (onboarding.Task, error) {
	var task onboarding.Task
	var links []byte
	err := row.Scan(append(prefix, &task.ID, &task.StageID, &task.Title, &task.Description, &task.Status,
		&task.DueDate, &links, &task.RelatedActionType, &task.RelatedActionID)...)
	if err != nil {
		return onboarding.Task{}, err
	}
	err = json.Unmarshal(links, &task.Links)
	return task, err
}
