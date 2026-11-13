package onboarding

import (
	"slices"
	"testing"
	"time"
)

func TestCalculateOrdersAndExplainsNextSteps(t *testing.T) {
	now := time.Date(2026, time.November, 11, 10, 0, 0, 0, time.FixedZone("MSK", 3*3600))
	yesterday, today, tomorrow := "2026-11-10", "2026-11-11", "2026-11-12"
	stages := []Stage{
		{ID: "finished", Tasks: []Task{{ID: "done", Status: Done, DueDate: &yesterday}}},
		{ID: "current", Tasks: []Task{
			{ID: "blocked", Status: Blocked, DueDate: &yesterday},
			{ID: "same_deadline", Status: Todo, DueDate: &today},
			{ID: "started", Status: InProgress, DueDate: &today},
			{ID: "overdue", Status: Todo, DueDate: &yesterday},
		}},
		{ID: "future", Tasks: []Task{{ID: "future", Status: Todo, DueDate: &tomorrow}}},
	}

	got := Calculate(stages, now)
	if got.Progress != 17 || got.Stages[0].Status != Done || got.Stages[1].Status != InProgress || got.Stages[2].Status != Todo {
		t.Fatalf("состояние адаптации: %+v", got)
	}
	var ids []string
	for _, step := range got.NextSteps {
		ids = append(ids, step.TaskID)
	}
	if !slices.Equal(ids, []string{"overdue", "started", "same_deadline"}) {
		t.Fatalf("порядок задач: %v", ids)
	}
	if got.NextSteps[1].Reason != "Задача уже в работе, срок — сегодня." {
		t.Fatalf("объяснение: %s", got.NextSteps[1].Reason)
	}
}

func TestCalculateWithEmptyOrFinishedPlan(t *testing.T) {
	if got := Calculate(nil, time.Now()); got.Stages == nil || got.NextSteps == nil || got.Progress != 0 {
		t.Fatalf("пустой план: %+v", got)
	}
	plan := []Stage{{Tasks: []Task{{Status: Done}}}}
	if got := Calculate(plan, time.Now()); got.Progress != 100 || len(got.NextSteps) != 0 {
		t.Fatalf("выполненный план: %+v", got)
	}
}
