package httpapi

import (
	"errors"
	"net/http"
	"regexp"
	"slices"

	"aibuddy/core-api/internal/store"
)

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

var (
	scenarios = []string{"onboarding", "knowledge", "absence", "access"}
	// Ответ помощника, подтверждение и итог заявки клиент не присылает: их записывает сервер.
	clientEvents = []string{"scenario_started", "source_opened", "human_help_requested"}
)

// postEvent принимает событие метрик от клиента (B3).
func (a api) postEvent(w http.ResponseWriter, r *http.Request, u store.User) {
	var input struct {
		EventID    string `json:"event_id"`
		SessionID  string `json:"session_id"`
		ScenarioID string `json:"scenario_id"`
		Scenario   string `json:"scenario"`
		Event      string `json:"event"`
	}
	if !readJSON(w, r, 1<<10, &input) || !uuidPattern.MatchString(input.EventID) ||
		!uuidPattern.MatchString(input.SessionID) || !uuidPattern.MatchString(input.ScenarioID) ||
		!slices.Contains(scenarios, input.Scenario) {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Событие не прошло проверку: нужны UUID и известный сценарий.")
		return
	}
	if !slices.Contains(clientEvents, input.Event) {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Недопустимый тип события.")
		return
	}
	recordedAt, err := a.db.RecordClientEvent(r.Context(), u.ID, store.ClientEvent{
		EventID: input.EventID, SessionID: input.SessionID, ScenarioID: input.ScenarioID,
		Scenario: input.Scenario, Event: input.Event,
	})
	switch {
	case errors.Is(err, store.ErrEventConflict):
		WriteError(w, http.StatusConflict, "conflict", "Идентификатор уже использован для другого события.")
	case err != nil:
		internalError(w)
	default:
		WriteJSON(w, http.StatusOK, map[string]any{"event_id": input.EventID, "recorded_at": recordedAt.In(a.now().Location())})
	}
}

// productHeaders читает пару X-Product-Session-Id и X-Product-Scenario-Id. ok=false — пара неполная или не UUID.
func productHeaders(r *http.Request) (store.Product, bool) {
	p := store.Product{SessionID: r.Header.Get("X-Product-Session-Id"), ScenarioID: r.Header.Get("X-Product-Scenario-Id")}
	if p.SessionID == "" && p.ScenarioID == "" {
		return p, true
	}
	return p, uuidPattern.MatchString(p.SessionID) && uuidPattern.MatchString(p.ScenarioID)
}
