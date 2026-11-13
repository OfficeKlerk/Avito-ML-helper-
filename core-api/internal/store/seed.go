package store

import (
	"context"
	"database/sql"
	"embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"golang.org/x/crypto/bcrypt"
)

//go:embed demo/*.json
var demo embed.FS

type seedUser struct {
	ID        string  `json:"id"`
	Login     string  `json:"login"`
	Password  string  `json:"test_password"`
	Name      string  `json:"name"`
	Role      string  `json:"role"`
	TeamID    *string `json:"team_id"`
	MentorID  *string `json:"mentor_id"`
	ManagerID *string `json:"manager_id"`
	StartDate *string `json:"start_date"`
	Program   *string `json:"program"`
}

type checklist struct {
	Stages []struct {
		ID     string `json:"id"`
		Title  string `json:"title"`
		Period string `json:"period"`
		Order  int    `json:"order"`
	} `json:"stages"`
	Tasks []struct {
		ID                string          `json:"id"`
		StageID           string          `json:"stage_id"`
		Title             string          `json:"title"`
		Description       string          `json:"description"`
		Order             int             `json:"order"`
		DueOffsetDays     *int            `json:"due_offset_days"`
		Links             json.RawMessage `json:"links"`
		RelatedActionType *string         `json:"related_action_type"`
	} `json:"tasks"`
}

func seed(ctx context.Context, tx *sql.Tx, dir string) error {
	var teams []Ref
	var users []seedUser
	var plan checklist
	var statuses map[string]map[string]string
	for _, file := range []struct {
		name string
		dest any
	}{
		{"teams.json", &teams},
		{"users.json", &users},
		{"checklist.json", &plan},
		{"onboarding_state.json", &statuses},
	} {
		path := filepath.Join(dir, file.name)
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if err := json.Unmarshal(data, file.dest); err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}
	}
	for _, team := range teams {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO core.teams (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING
		`, team.ID, team.Name); err != nil {
			return err
		}
	}
	for _, user := range users {
		if err := insertUser(ctx, tx, user); err != nil {
			return fmt.Errorf("пользователь %s: %w", user.ID, err)
		}
	}
	for _, stage := range plan.Stages {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO core.stages (id, title, period, position) VALUES ($1, $2, $3, $4)
			ON CONFLICT (id) DO NOTHING
		`, stage.ID, stage.Title, stage.Period, stage.Order); err != nil {
			return err
		}
	}
	for _, user := range users {
		if user.Role != "intern" {
			continue
		}
		var start time.Time
		if user.StartDate != nil {
			var err error
			start, err = time.Parse(time.DateOnly, *user.StartDate)
			if err != nil {
				return fmt.Errorf("дата начала стажировки %s: %w", user.ID, err)
			}
		}
		for _, task := range plan.Tasks {
			status := statuses[user.ID][task.ID]
			if status == "" {
				status = "todo"
			}
			var dueDate *string
			if !start.IsZero() && task.DueOffsetDays != nil {
				value := start.AddDate(0, 0, *task.DueOffsetDays).Format(time.DateOnly)
				dueDate = &value
			}
			_, err := tx.ExecContext(ctx, `
				INSERT INTO core.tasks
				    (owner_id, id, stage_id, title, description, status, due_date, position, links, related_action_type)
				VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
				ON CONFLICT (owner_id, id) DO NOTHING
			`, user.ID, task.ID, task.StageID, task.Title, task.Description, status, dueDate,
				task.Order, string(task.Links), task.RelatedActionType)
			if err != nil {
				return fmt.Errorf("задача %s пользователя %s: %w", task.ID, user.ID, err)
			}
		}
	}
	return seedHistory(ctx, tx)
}

func insertUser(ctx context.Context, tx *sql.Tx, user seedUser) error {
	var exists bool
	err := tx.QueryRowContext(ctx, `SELECT EXISTS (SELECT 1 FROM core.users WHERE id = $1)`, user.ID).Scan(&exists)
	if err != nil || exists {
		return err
	}
	if user.Password == "" {
		return fmt.Errorf("пустой тестовый пароль")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(user.Password), bcrypt.DefaultCost)
	if err != nil {
		return err
	}
	_, err = tx.ExecContext(ctx, `
		INSERT INTO core.users (id, login, password_hash, name, role, team_id, mentor_id, manager_id, start_date, program)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) ON CONFLICT (id) DO NOTHING
	`, user.ID, user.Login, string(hash), user.Name, user.Role, user.TeamID, user.MentorID,
		user.ManagerID, user.StartDate, user.Program)
	return err
}

func seedHistory(ctx context.Context, tx *sql.Tx) error {
	var actions []struct {
		ID         string          `json:"id"`
		OwnerID    string          `json:"owner_id"`
		Type       string          `json:"type"`
		Status     string          `json:"status"`
		Title      string          `json:"title"`
		Fields     json.RawMessage `json:"fields"`
		ExternalID *string         `json:"external_id"`
		Result     json.RawMessage `json:"result"`
		Error      *string         `json:"error"`
		CreatedAt  time.Time       `json:"created_at"`
		UpdatedAt  time.Time       `json:"updated_at"`
	}
	data, err := demo.ReadFile("demo/actions.json")
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, &actions); err != nil {
		return err
	}
	for _, action := range actions {
		_, err := tx.ExecContext(ctx, `
			INSERT INTO core.actions (id, owner_id, type, status, title, fields, external_id, result, error, created_at, updated_at)
			VALUES ($1, $2, $3, $4, $5, $6, $7, NULLIF($8::jsonb, 'null'::jsonb), $9, $10, $11)
			ON CONFLICT (id) DO NOTHING
		`, action.ID, action.OwnerID, action.Type, action.Status, action.Title, string(action.Fields), action.ExternalID,
			string(action.Result), action.Error, action.CreatedAt, action.UpdatedAt)
		if err != nil {
			return fmt.Errorf("карточка %s: %w", action.ID, err)
		}
	}

	var messages []struct {
		ID          string          `json:"id"`
		OwnerID     string          `json:"owner_id"`
		Role        string          `json:"role"`
		Text        string          `json:"text"`
		Sources     json.RawMessage `json:"sources"`
		Suggestions json.RawMessage `json:"suggestions"`
		ActionIDs   []string        `json:"action_ids"`
		Status      string          `json:"status"`
		CreatedAt   time.Time       `json:"created_at"`
	}
	data, err = demo.ReadFile("demo/messages.json")
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, &messages); err != nil {
		return err
	}
	for _, message := range messages {
		_, err := tx.ExecContext(ctx, `
			INSERT INTO core.messages (id, owner_id, role, text, sources, suggestions, status, created_at)
			VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT (id) DO NOTHING
		`, message.ID, message.OwnerID, message.Role, message.Text, string(message.Sources),
			string(message.Suggestions), message.Status, message.CreatedAt)
		if err != nil {
			return fmt.Errorf("сообщение %s: %w", message.ID, err)
		}
		for position, actionID := range message.ActionIDs {
			_, err := tx.ExecContext(ctx, `
				INSERT INTO core.message_actions (owner_id, message_id, action_id, position)
				VALUES ($1, $2, $3, $4) ON CONFLICT (owner_id, message_id, action_id) DO NOTHING
			`, message.OwnerID, message.ID, actionID, position)
			if err != nil {
				return fmt.Errorf("карточка сообщения %s: %w", message.ID, err)
			}
		}
	}
	return nil
}
