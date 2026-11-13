package httpapi

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

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
