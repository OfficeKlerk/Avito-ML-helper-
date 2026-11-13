// Package httpapi — HTTP-слой сервиса core-api: авторизация, история, адаптация и карточки действий (контракт A).
package httpapi

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/onboarding"
	"aibuddy/core-api/internal/store"
)

// ServiceName — имя сервиса в ответе /health (contracts/common.yaml, Health).
const ServiceName = "core-api"

type errorDetail struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type errorBody struct {
	Error errorDetail `json:"error"`
}

type healthBody struct {
	Status  string `json:"status"`
	Service string `json:"service"`
	Version string `json:"version"`
}

type Backend interface {
	Credentials(context.Context, string) (string, string, error)
	User(context.Context, string) (store.User, error)
	Stages(context.Context, string) ([]onboarding.Stage, error)
	SetTaskStatus(context.Context, string, string, string) (onboarding.Task, error)
	Messages(context.Context, string, int) (json.RawMessage, error)
	Actions(context.Context, string) (json.RawMessage, error)
	Action(context.Context, string, string) (json.RawMessage, error)
	PendingActions(context.Context, string, string) ([]store.ActionRecord, error)
	SyncAction(context.Context, store.ActionRecord, store.ActionChange) error
	Notifications(context.Context, string) (json.RawMessage, error)
	MarkNotificationRead(context.Context, string, int64) (json.RawMessage, error)
	RecordClientEvent(context.Context, string, store.ClientEvent) (time.Time, error)
	WithChat(context.Context, string, func(*store.ChatSession) error) error
	ChangeAction(context.Context, string, string, string, func(store.ActionRecord) (store.ActionChange, error)) (json.RawMessage, error)
}

type Dependencies struct {
	Agent     *clients.Agent
	Corp      *clients.Corp
	Knowledge *clients.Knowledge
	Logger    *slog.Logger
}

type api struct {
	db        Backend
	secret    []byte
	now       func() time.Time
	agent     *clients.Agent
	corp      *clients.Corp
	knowledge *clients.Knowledge
}

// NewHandler собирает маршруты сервиса.
func NewHandler(version string, db Backend, jwtSecret string, now func() time.Time, deps Dependencies) http.Handler {
	a := api{db: db, secret: []byte(jwtSecret), now: now, agent: deps.Agent, corp: deps.Corp, knowledge: deps.Knowledge}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		WriteJSON(w, http.StatusOK, healthBody{Status: "ok", Service: ServiceName, Version: version})
	})
	mux.HandleFunc("POST /api/auth/login", a.login)
	mux.HandleFunc("GET /api/me", a.requireUser(a.me))
	mux.HandleFunc("GET /api/onboarding", a.requireUser(a.getOnboarding))
	mux.HandleFunc("PATCH /api/onboarding/tasks/{task_id}", a.requireUser(a.patchTask))
	mux.HandleFunc("GET /api/chat/messages", a.requireUser(a.listMessages))
	mux.HandleFunc("POST /api/chat/messages", a.requireUser(a.postMessage))
	mux.HandleFunc("GET /api/actions", a.requireUser(a.listActions))
	mux.HandleFunc("GET /api/actions/{action_id}", a.requireUser(a.getAction))
	mux.HandleFunc("POST /api/actions/{action_id}/confirm", a.requireUser(a.confirmAction))
	mux.HandleFunc("POST /api/actions/{action_id}/cancel", a.requireUser(a.cancelAction))
	mux.HandleFunc("GET /api/notifications", a.requireUser(a.listNotifications))
	mux.HandleFunc("PATCH /api/notifications/{notification_id}", a.requireUser(a.markNotificationRead))
	mux.HandleFunc("GET /api/knowledge/documents/{doc_id}", a.requireUser(a.getDocument))
	mux.HandleFunc("POST /api/metrics/events", a.requireUser(a.postEvent))
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		WriteError(w, http.StatusNotFound, "not_found", "Не найдено.")
	})
	return traceRequests(deps.Logger, mux)
}

// WriteJSON отправляет ответ в формате JSON.
func WriteJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

// WriteError отправляет ошибку в едином формате (contracts/common.yaml, ErrorResponse).
func WriteError(w http.ResponseWriter, status int, code, message string) {
	WriteJSON(w, status, errorBody{Error: errorDetail{Code: code, Message: message}})
}

func readJSON(w http.ResponseWriter, r *http.Request, maxBytes int64, body any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	return decoder.Decode(body) == nil && decoder.Decode(new(any)) == io.EOF
}

func internalError(w http.ResponseWriter) {
	WriteError(w, http.StatusInternalServerError, "internal", "Не удалось обработать запрос.")
}
