package corporate

import (
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
)

type Status string

const (
	Draft     Status = "draft"
	Submitted Status = "submitted"
	Approved  Status = "approved"
	Rejected  Status = "rejected"
	Cancelled Status = "cancelled"
)

type Operation string

const (
	Read    Operation = "read"
	Submit  Operation = "submit"
	Approve Operation = "approve"
	Reject  Operation = "reject"
	Cancel  Operation = "cancel"
)

var (
	ErrForbidden  = errors.New("forbidden")
	ErrNotFound   = errors.New("not_found")
	ErrConflict   = errors.New("conflict")
	ErrValidation = errors.New("validation")
	requestID     = regexp.MustCompile(`^req_[a-z0-9_]+$`)
)

type AbsencePayload struct {
	Kind     string  `json:"kind"`
	DateFrom string  `json:"date_from"`
	DateTo   string  `json:"date_to"`
	Comment  *string `json:"comment,omitempty"`
}

type AccessPayload struct {
	System string `json:"system"`
	Reason string `json:"reason"`
}

type Request struct {
	ID          string          `json:"id"`
	Type        string          `json:"type"`
	Status      Status          `json:"status"`
	OwnerID     string          `json:"owner_id"`
	TeamID      string          `json:"team_id"`
	Approver    *Ref            `json:"approver"`
	Payload     json.RawMessage `json:"payload"`
	Summary     string          `json:"summary"`
	ExternalRef *string         `json:"external_ref"`
	FulfilledAt *time.Time      `json:"fulfilled_at"`
	CreatedAt   time.Time       `json:"created_at"`
	UpdatedAt   time.Time       `json:"updated_at"`
}

func (r Request) Validate() error {
	if !requestID.MatchString(r.ID) || r.OwnerID == "" || r.TeamID == "" || strings.TrimSpace(r.Summary) == "" ||
		r.CreatedAt.IsZero() || r.UpdatedAt.Before(r.CreatedAt) ||
		!json.Valid(r.Payload) || !strings.HasPrefix(strings.TrimSpace(string(r.Payload)), "{") {
		return ErrValidation
	}
	switch r.Type {
	case "absence_request":
		var payload AbsencePayload
		if err := json.Unmarshal(r.Payload, &payload); err != nil || (payload.Kind != "day_off" && payload.Kind != "vacation") {
			return ErrValidation
		}
		from, fromErr := time.Parse(time.DateOnly, payload.DateFrom)
		to, toErr := time.Parse(time.DateOnly, payload.DateTo)
		if fromErr != nil || toErr != nil || to.Before(from) {
			return ErrValidation
		}
	case "access_request":
		var payload AccessPayload
		if err := json.Unmarshal(r.Payload, &payload); err != nil {
			return ErrValidation
		}
		switch payload.System {
		case "confluence", "jira", "gitlab", "vpn", "team_space":
		default:
			return ErrValidation
		}
	default:
		return ErrValidation
	}
	switch r.Status {
	case Draft, Submitted, Approved, Rejected, Cancelled:
	default:
		return ErrValidation
	}
	if r.FulfilledAt != nil && (r.Type != "access_request" || r.Status != Approved) {
		return ErrValidation
	}
	return nil
}

// Authorize проверяет владельца либо назначенного согласующего из той же команды.
func (r Request) Authorize(user User, op Operation) error {
	if user.ID == "" || user.TeamID == nil || *user.TeamID != r.TeamID {
		return ErrForbidden
	}
	switch op {
	case Read, Submit, Cancel:
		if user.ID == r.OwnerID {
			return nil
		}
	case Approve, Reject:
		if user.Role == "manager" && user.ID != r.OwnerID && r.Approver != nil && r.Approver.ID == user.ID {
			return nil
		}
	}
	return ErrForbidden
}

func (r Request) Transition(op Operation, now time.Time) (Request, error) {
	var next Status
	switch {
	case op == Submit && r.Status == Draft:
		next = Submitted
	case op == Cancel && (r.Status == Draft || r.Status == Submitted):
		next = Cancelled
	case op == Approve && (r.Status == Submitted ||
		(r.Status == Approved && r.Type == "access_request" && r.FulfilledAt == nil)):
		next = Approved
	case op == Reject && r.Status == Submitted:
		next = Rejected
	default:
		return Request{}, ErrConflict
	}
	r.Status = next
	if now.After(r.UpdatedAt) {
		r.UpdatedAt = now
	}
	if op == Approve && r.Type == "access_request" {
		fulfilled := r.UpdatedAt
		r.FulfilledAt = &fulfilled
	}
	return r, nil
}

func (d *Directory) CheckRequest(r Request) error {
	if err := r.Validate(); err != nil {
		return err
	}
	u, ok := d.User(r.OwnerID)
	if !ok || u.TeamID == nil || *u.TeamID != r.TeamID {
		return fmt.Errorf("request owner or team: %w", ErrValidation)
	}
	if r.Approver != nil {
		manager, ok := d.User(r.Approver.ID)
		if !ok || manager.ID == u.ID || manager.Role != "manager" || !sameTeam(manager.TeamID, u.TeamID) {
			return fmt.Errorf("request approver: %w", ErrValidation)
		}
	}
	return nil
}
