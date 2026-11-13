package httpapi

import (
	"errors"
	"net/http"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/store"
)

// getDocument — источник из ответа помощника. Права проверяет knowledge-service по JWT пользователя.
func (a api) getDocument(w http.ResponseWriter, r *http.Request, _ store.User) {
	// Документ виден не всем: ни браузер, ни прокси не должны отдать его другому пользователю.
	w.Header().Set("Cache-Control", "no-store")
	if a.knowledge == nil {
		WriteError(w, http.StatusServiceUnavailable, "unavailable", "База знаний временно недоступна. Попробуй чуть позже.")
		return
	}
	doc, err := a.knowledge.Document(r.Context(), r.Header.Get("Authorization"), r.PathValue("doc_id"))
	var status clients.HTTPError
	errors.As(err, &status)
	switch {
	case err == nil:
		WriteJSON(w, http.StatusOK, doc)
	case status == http.StatusForbidden:
		WriteError(w, http.StatusForbidden, "forbidden", "У тебя нет доступа к этому документу.")
	case status == http.StatusNotFound:
		WriteError(w, http.StatusNotFound, "not_found", "Документ не найден.")
	default:
		WriteError(w, http.StatusServiceUnavailable, "unavailable", "База знаний временно недоступна. Попробуй чуть позже.")
	}
}
