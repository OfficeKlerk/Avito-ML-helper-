package clients

import (
	"context"
	"errors"
	"net/http"
	"time"

	"aibuddy/core-api/internal/store"
)

type Corp struct {
	endpoint
}

func NewCorp(baseURL string) *Corp {
	ep := newEndpoint(baseURL, 3*time.Second)
	transport := http.DefaultTransport.(*http.Transport).Clone()
	// Повтор POST выполняется приложением после проверки статуса, а не транспортом.
	transport.DisableKeepAlives = true
	ep.http.Transport = transport
	return &Corp{ep}
}

type CorpRequest struct {
	ID       string     `json:"id"`
	Type     string     `json:"type"`
	OwnerID  string     `json:"owner_id"`
	Status   string     `json:"status"`
	Approver *store.Ref `json:"approver"`
	Payload  struct {
		System string `json:"system"`
	} `json:"payload"`
	FulfilledAt *time.Time `json:"fulfilled_at"`
	ExternalRef *string    `json:"external_ref"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

// Request читает заявку либо выполняет переход из контракта D.
func (c *Corp) Request(ctx context.Context, bearer, requestID string, action store.ActionRecord, transition, key string) (out CorpRequest, err error) {
	started := time.Now()
	operation := "request_get"
	if transition != "" {
		operation = "request_" + transition
	}
	defer func() { logCall(ctx, "corp-mock", operation, started, err) }()
	if action.ExternalID == nil || !requestIDPattern.MatchString(*action.ExternalID) {
		return out, errors.New("у карточки отсутствует идентификатор заявки")
	}
	path, method := "/api/v1/requests/"+*action.ExternalID, http.MethodGet
	if transition != "" {
		path += "/" + transition
		method = http.MethodPost
	}
	if err := c.request(ctx, method, path, bearer, requestID, key, nil, &out); err != nil {
		return CorpRequest{}, err
	}
	if out.ID != *action.ExternalID || out.OwnerID != action.OwnerID || out.Type != action.Type || out.UpdatedAt.IsZero() {
		return CorpRequest{}, errors.New("ответ относится к другой заявке или неполон")
	}
	switch out.Status {
	case "draft", "submitted", "approved", "rejected", "cancelled":
		return out, nil
	default:
		return CorpRequest{}, errors.New("неизвестный статус заявки")
	}
}
