// Package onboarding рассчитывает состояние и следующие шаги адаптации.
package onboarding

import (
	"sort"
	"time"
)

const (
	Todo       = "todo"
	InProgress = "in_progress"
	Done       = "done"
	Blocked    = "blocked"
)

func ValidStatus(status string) bool {
	switch status {
	case Todo, InProgress, Done, Blocked:
		return true
	default:
		return false
	}
}

type Link struct {
	Title string `json:"title"`
	URL   string `json:"url"`
}

type Task struct {
	ID                string  `json:"id"`
	StageID           string  `json:"stage_id"`
	Title             string  `json:"title"`
	Description       string  `json:"description"`
	Status            string  `json:"status"`
	DueDate           *string `json:"due_date"`
	Links             []Link  `json:"links"`
	RelatedActionType *string `json:"related_action_type"`
	RelatedActionID   *string `json:"related_action_id"`
}

type Stage struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Period string `json:"period"`
	Status string `json:"status"`
	Tasks  []Task `json:"tasks"`
}

type NextStep struct {
	TaskID string `json:"task_id"`
	Title  string `json:"title"`
	Reason string `json:"reason"`
}

type State struct {
	Stages    []Stage    `json:"stages"`
	Progress  int        `json:"progress"`
	NextSteps []NextStep `json:"next_steps"`
}

// Calculate получает этапы и задачи в порядке чек-листа и добавляет сводку.
func Calculate(stages []Stage, now time.Time) State {
	state := State{Stages: make([]Stage, 0, len(stages)), NextSteps: []NextStep{}}
	var candidates []Task
	total, done := 0, 0
	for _, stage := range stages {
		complete := 0
		stage.Status = Todo
		for _, task := range stage.Tasks {
			if task.Status != Todo {
				stage.Status = InProgress
			}
			if task.Status == Done {
				complete++
			} else {
				candidates = append(candidates, task)
			}
		}
		if len(stage.Tasks) > 0 && complete == len(stage.Tasks) {
			stage.Status = Done
		}
		state.Stages = append(state.Stages, stage)
		total += len(stage.Tasks)
		done += complete
	}
	if total > 0 {
		state.Progress = (done*100 + total/2) / total
	}

	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		if (a.Status == Blocked) != (b.Status == Blocked) {
			return a.Status != Blocked
		}
		if (a.DueDate == nil) != (b.DueDate == nil) {
			return a.DueDate != nil
		}
		if a.DueDate != nil && *a.DueDate != *b.DueDate {
			return *a.DueDate < *b.DueDate
		}
		return a.Status == InProgress && b.Status != InProgress
	})

	for _, task := range candidates[:min(3, len(candidates))] {
		state.NextSteps = append(state.NextSteps, NextStep{TaskID: task.ID, Title: task.Title, Reason: reason(task, now)})
	}
	return state
}

func reason(task Task, now time.Time) string {
	if task.Status == Blocked {
		return "Задача заблокирована. Обсуди с наставником, что мешает её выполнить."
	}
	if task.DueDate == nil {
		if task.Status == InProgress {
			return "Задача уже в работе."
		}
		return "Следующая задача в чек-листе."
	}
	today := now.Format(time.DateOnly)
	switch {
	case *task.DueDate < today:
		return "Срок прошёл (" + *task.DueDate + ")."
	case *task.DueDate == today:
		if task.Status == InProgress {
			return "Задача уже в работе, срок — сегодня."
		}
		return "Срок — сегодня."
	case *task.DueDate == now.AddDate(0, 0, 1).Format(time.DateOnly):
		return "Срок — завтра."
	default:
		return "Ближайший срок — " + *task.DueDate + "."
	}
}
