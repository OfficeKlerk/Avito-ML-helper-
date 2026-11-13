package httpapi

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	"aibuddy/core-api/internal/store"
)

func (a api) listMessages(w http.ResponseWriter, r *http.Request, u store.User) {
	limit := 50
	if values, supplied := r.URL.Query()["limit"]; supplied {
		var err error
		limit, err = strconv.Atoi(values[0])
		if err != nil || len(values) != 1 || limit < 1 || limit > 200 {
			WriteError(w, http.StatusUnprocessableEntity, "validation", "Лимит должен быть целым числом от 1 до 200.")
			return
		}
	}
	a.syncPending(r, u.ID, "")
	messages, err := a.db.Messages(r.Context(), u.ID, limit)
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, map[string]json.RawMessage{"messages": messages})
}

func (a api) listActions(w http.ResponseWriter, r *http.Request, u store.User) {
	a.syncPending(r, u.ID, "")
	actions, err := a.db.Actions(r.Context(), u.ID)
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, map[string]json.RawMessage{"actions": actions})
}

func (a api) getAction(w http.ResponseWriter, r *http.Request, u store.User) {
	id := r.PathValue("action_id")
	a.syncPending(r, u.ID, id)
	action, err := a.db.Action(r.Context(), u.ID, id)
	if errors.Is(err, sql.ErrNoRows) {
		WriteError(w, http.StatusNotFound, "not_found", "Действие не найдено.")
		return
	}
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, action)
}

func (a api) markNotificationRead(w http.ResponseWriter, r *http.Request, u store.User) {
	var input struct {
		Read *bool `json:"read"`
	}
	if !readJSON(w, r, 1<<10, &input) || input.Read == nil || !*input.Read {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Укажи read=true.")
		return
	}
	// Чужое, несуществующее и неверное уведомление неразличимы.
	notFound := func() { WriteError(w, http.StatusNotFound, "not_found", "Уведомление не найдено.") }
	id, found := strings.CutPrefix(r.PathValue("notification_id"), "ntf_")
	seq, err := strconv.ParseUint(id, 10, 63)
	if !found || err != nil {
		notFound()
		return
	}
	item, err := a.db.MarkNotificationRead(r.Context(), u.ID, int64(seq))
	switch {
	case errors.Is(err, sql.ErrNoRows):
		notFound()
	case err != nil:
		internalError(w)
	default:
		WriteJSON(w, http.StatusOK, item)
	}
}
