package httpapi

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"aibuddy/core-api/internal/diagnostics"
	"aibuddy/core-api/internal/store"
)

// syncPending читает состояние только своих заявок и с токеном текущего пользователя.
func (a api) syncPending(r *http.Request, ownerID, actionID string) {
	if a.corp == nil {
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 4*time.Second)
	defer cancel()
	actions, err := a.db.PendingActions(ctx, ownerID, actionID)
	if err != nil {
		diagnostics.Log(ctx, slog.LevelWarn, "action_sync_error", "error_code", "load_pending")
		return
	}
	if len(actions) == 0 {
		return
	}
	bearer, id := r.Header.Get("Authorization"), diagnostics.ID(ctx)
	queue := make(chan store.ActionRecord, len(actions))
	for _, action := range actions {
		queue <- action
	}
	close(queue)
	var wg sync.WaitGroup
	for range min(4, len(actions)) {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for action := range queue {
				if ctx.Err() != nil {
					return
				}
				remote, err := a.corp.Request(ctx, bearer, id, action, "", "")
				if err != nil {
					continue
				}
				if err := a.db.SyncAction(ctx, action, actionChange(remote, false)); err != nil {
					diagnostics.Log(ctx, slog.LevelWarn, "action_sync_error", "error_code", "save_status",
						"action_id", action.ID)
				}
			}
		}()
	}
	wg.Wait()
}

func (a api) listNotifications(w http.ResponseWriter, r *http.Request, u store.User) {
	a.syncPending(r, u.ID, "")
	items, err := a.db.Notifications(r.Context(), u.ID)
	if err != nil {
		internalError(w)
		return
	}
	WriteJSON(w, http.StatusOK, map[string]json.RawMessage{"items": items})
}
