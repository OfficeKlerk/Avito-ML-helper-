package httpapi

import (
	"database/sql"
	"errors"
	"net/http"

	"aibuddy/core-api/internal/onboarding"
	"aibuddy/core-api/internal/store"
)

func (a api) getOnboarding(w http.ResponseWriter, r *http.Request, u store.User) {
	a.syncPending(r, u.ID, "")
	stages, err := a.db.Stages(r.Context(), u.ID)
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, onboarding.Calculate(stages, a.now()))
}

func (a api) patchTask(w http.ResponseWriter, r *http.Request, u store.User) {
	var body struct {
		Status string `json:"status"`
	}
	if !readJSON(w, r, 4096, &body) || !onboarding.ValidStatus(body.Status) {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Такого статуса задачи нет.")
		return
	}
	if body.Status == onboarding.Done {
		a.syncPending(r, u.ID, "")
	}
	task, err := a.db.SetTaskStatus(r.Context(), u.ID, r.PathValue("task_id"), body.Status)
	if errors.Is(err, sql.ErrNoRows) {
		WriteError(w, http.StatusNotFound, "not_found", "Задача не найдена.")
		return
	}
	if errors.Is(err, store.ErrAccessNotGranted) {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Задачу можно завершить после выдачи доступа.")
		return
	}
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, task)
}
