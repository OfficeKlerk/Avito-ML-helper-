package store

import (
	"context"
	"database/sql"
	"encoding/json"

	"aibuddy/corp-mock/internal/corporate"
)

func accessState(requests []corporate.Request, system, seedStatus string) (status string, requestID *string, draft corporate.Request) {
	status = seedStatus
	var latest, granted, pending *string
	for _, request := range requests {
		// PostgreSQL хранит payload в соответствии с типом заявки.
		if requestSystem(request) != system {
			continue
		}
		id := request.ID
		if latest == nil {
			latest = &id
		}
		switch request.Status {
		case corporate.Draft:
			if draft.ID == "" {
				draft = request
			}
		case corporate.Submitted:
			if pending == nil {
				pending = &id
			}
		case corporate.Approved:
			if request.FulfilledAt != nil {
				if granted == nil {
					granted = &id
				}
			} else {
				if pending == nil {
					pending = &id
				}
			}
		}
	}
	switch {
	case granted != nil || seedStatus == "granted":
		return "granted", granted, draft
	case pending != nil:
		return "pending", pending, draft
	case latest != nil:
		status = "missing"
	}
	return status, latest, draft
}

func (s *Store) Accesses(ctx context.Context, user corporate.User, catalog corporate.AccessCatalog) ([]corporate.AccessItem, error) {
	requests, err := s.List(ctx, user, "access_request")
	if err != nil {
		return nil, err
	}
	items := []corporate.AccessItem{}
	if user.TeamID == nil {
		return items, nil
	}
	for _, system := range catalog.Systems {
		required := catalog.Required(user, system.System)
		status, requestID, _ := accessState(requests, system.System, catalog.SeedStatus(user, system.System))
		if required || status != "missing" || requestID != nil {
			items = append(items, corporate.AccessItem{AccessSystem: system, Required: required, Status: status, RequestID: requestID})
		}
	}
	return items, nil
}

func existingAccessDraft(ctx context.Context, tx *sql.Tx, user corporate.User, input DraftInput) (corporate.Request, error) {
	requests, err := listRequests(ctx, tx, user, "access_request")
	if err != nil {
		return corporate.Request{}, err
	}
	status, _, draft := accessState(requests, input.System, input.Catalog.SeedStatus(user, input.System))
	switch status {
	case "granted":
		return corporate.Request{}, corporate.Deny(corporate.ErrConflict, "Доступ к этой системе уже выдан.")
	case "pending":
		return corporate.Request{}, corporate.Deny(corporate.ErrConflict, "Заявка на этот доступ уже отправлена.")
	default:
		return draft, nil
	}
}

func requestSystem(request corporate.Request) string {
	var payload corporate.AccessPayload
	_ = json.Unmarshal(request.Payload, &payload)
	return payload.System
}
