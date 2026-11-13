// Package httpapi — HTTP-слой сервиса corp-mock: имитация корпоративных сервисов: REST (контракт D) и MCP (контракт C).
package httpapi

import (
	"encoding/json"
	"net/http"

	"aibuddy/corp-mock/internal/corporate"
)

// ServiceName — имя сервиса в ответе /health (contracts/common.yaml, Health).
const ServiceName = "corp-mock"

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

// NewHandler собирает маршруты сервиса.
func NewHandler(version string, api *API) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		WriteJSON(w, http.StatusOK, healthBody{Status: "ok", Service: ServiceName, Version: version})
	})
	if api != nil {
		if api.Faults != nil {
			mux.HandleFunc("POST /test/faults", api.Faults.arm)
		}
		mux.Handle("/mcp", api.mcpHandler(version))
		mux.HandleFunc("GET /api/v1/requests/{request_id}", api.request(corporate.Read))
		for _, operation := range []corporate.Operation{corporate.Submit, corporate.Cancel, corporate.Approve, corporate.Reject} {
			mux.HandleFunc("POST /api/v1/requests/{request_id}/"+string(operation), api.request(operation))
		}
	}
	mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		WriteError(w, http.StatusNotFound, "not_found", "Не найдено.")
	})
	return mux
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
