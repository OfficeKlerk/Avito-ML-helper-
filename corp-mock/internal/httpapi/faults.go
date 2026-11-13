package httpapi

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"

	"aibuddy/corp-mock/internal/corporate"
)

const (
	faultUnavailable  = "unavailable"
	faultDelay        = "delay"
	faultDropResponse = "drop_response"
)

var (
	errInjectedUnavailable = errors.New("injected unavailable")
	faultRequestID         = regexp.MustCompile(`^req_[a-z0-9_]+$`)
)

type faultRule struct {
	RequestID string              `json:"request_id"`
	Operation corporate.Operation `json:"operation"`
	Mode      string              `json:"mode"`
	DelayMS   int                 `json:"delay_ms,omitempty"`
}

type Faults struct {
	token  [sha256.Size]byte
	logger *slog.Logger
	mu     sync.Mutex
	next   *faultRule
}

// NewFaults enables the test control route when a separate token is configured.
func NewFaults(token string, logger *slog.Logger) *Faults {
	if strings.TrimSpace(token) == "" {
		return nil
	}
	return &Faults{token: sha256.Sum256([]byte(token)), logger: logger}
}

func (f *Faults) arm(w http.ResponseWriter, r *http.Request) {
	keys := r.Header.Values("X-Corp-Fault-Token")
	if len(keys) != 1 {
		WriteError(w, http.StatusForbidden, "forbidden", "Нет доступа к управлению сбоями.")
		return
	}
	provided := sha256.Sum256([]byte(keys[0]))
	if subtle.ConstantTimeCompare(f.token[:], provided[:]) != 1 {
		WriteError(w, http.StatusForbidden, "forbidden", "Нет доступа к управлению сбоями.")
		return
	}
	var rule faultRule
	r.Body = http.MaxBytesReader(w, r.Body, 4096)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if decoder.Decode(&rule) != nil || decoder.Decode(new(any)) != io.EOF || !rule.valid() {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Проверь параметры сбоя.")
		return
	}
	f.mu.Lock()
	f.next = &rule
	f.mu.Unlock()
	w.WriteHeader(http.StatusNoContent)
}

func (rule faultRule) valid() bool {
	if len(rule.RequestID) > 128 || !faultRequestID.MatchString(rule.RequestID) {
		return false
	}
	switch rule.Operation {
	case corporate.Read, corporate.Submit, corporate.Cancel, corporate.Approve, corporate.Reject:
	default:
		return false
	}
	switch rule.Mode {
	case faultDelay:
		return rule.DelayMS > 0 && rule.DelayMS <= 5000
	case faultUnavailable:
		return rule.DelayMS == 0
	case faultDropResponse:
		return rule.Operation != corporate.Read && rule.DelayMS == 0
	default:
		return false
	}
}

func (a *API) takeFault(ctx context.Context, user corporate.User, id string, op corporate.Operation) (faultRule, error) {
	f := a.Faults
	if f == nil {
		return faultRule{}, nil
	}
	f.mu.Lock()
	rule := f.next
	f.mu.Unlock()
	if rule == nil || rule.RequestID != id || rule.Operation != op {
		return faultRule{}, nil
	}

	check, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	if err := a.Requests.Authorize(check, user, id, op); err != nil {
		return faultRule{}, err
	}
	f.mu.Lock()
	if f.next != rule {
		f.mu.Unlock()
		return faultRule{}, nil
	}
	f.next = nil
	f.mu.Unlock()
	if f.logger != nil {
		f.logger.Info("fault_injected", "mode", rule.Mode, "operation", rule.Operation, "request", rule.RequestID)
	}
	return *rule, nil
}
