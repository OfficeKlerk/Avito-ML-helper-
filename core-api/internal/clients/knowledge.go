package clients

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"aibuddy/core-api/internal/diagnostics"
)

// Knowledge — клиент knowledge-service (контракт E).
type Knowledge struct {
	endpoint
}

func NewKnowledge(baseURL string) *Knowledge {
	return &Knowledge{newEndpoint(baseURL, 10*time.Second)}
}

// Document читает документ с правами пользователя: его JWT уходит в knowledge-service как есть.
// Неверный doc_id — HTTPError(404), отказ сервиса — HTTPError с его статусом.
func (k *Knowledge) Document(ctx context.Context, bearer, docID string) (doc json.RawMessage, err error) {
	if !docIDPattern.MatchString(docID) {
		return nil, HTTPError(http.StatusNotFound)
	}
	started := time.Now()
	defer func() { logCall(ctx, "knowledge-service", "document_get", started, err) }()
	err = k.request(ctx, http.MethodGet, "/v1/documents/"+docID, bearer, diagnostics.ID(ctx), "", nil, &doc)
	return doc, err
}
