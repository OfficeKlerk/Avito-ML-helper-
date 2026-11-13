package httpapi

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"aibuddy/corp-mock/internal/corporate"
	"aibuddy/corp-mock/internal/store"
)

type Requests interface {
	Authorize(context.Context, corporate.User, string, corporate.Operation) error
	Get(context.Context, corporate.User, string) (corporate.Request, error)
	Change(context.Context, corporate.User, string, corporate.Operation, string, time.Time) (corporate.Request, error)
}

type Drafts interface {
	List(context.Context, corporate.User, string) ([]corporate.Request, error)
	CreateDraft(context.Context, corporate.User, store.DraftInput, time.Time) (corporate.Request, error)
	Accesses(context.Context, corporate.User, corporate.AccessCatalog) ([]corporate.AccessItem, error)
}

type API struct {
	Auth      *corporate.Authenticator
	Directory *corporate.Directory
	Requests  Requests
	Drafts    Drafts
	Rules     corporate.AbsenceRules
	Access    corporate.AccessCatalog
	Now       func() time.Time
	Faults    *Faults
}

func (a *API) authorized(next func(http.ResponseWriter, *http.Request, corporate.User)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		user, err := a.Auth.Authenticate(r.Header.Values("Authorization"))
		if err != nil {
			w.Header().Set("WWW-Authenticate", "Bearer")
			WriteError(w, http.StatusUnauthorized, "unauthorized", "Нужно войти заново.")
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		next(w, r, user)
	}
}

func (a *API) request(op corporate.Operation) http.HandlerFunc {
	return a.authorized(func(w http.ResponseWriter, r *http.Request, user corporate.User) {
		id := r.PathValue("request_id")
		var key string
		if op == corporate.Submit {
			keys := r.Header.Values("Idempotency-Key")
			if len(keys) != 1 || !validKey(keys[0]) {
				WriteError(w, http.StatusUnprocessableEntity, "validation", "Укажи Idempotency-Key длиной от 8 до 128 символов.")
				return
			}
			key = keys[0]
		}
		fault, err := a.takeFault(r.Context(), user, id, op)
		if err != nil {
			writeRequestError(w, err)
			return
		}
		switch fault.Mode {
		case faultUnavailable:
			writeRequestError(w, errInjectedUnavailable)
			return
		case faultDelay:
			timer := time.NewTimer(time.Duration(fault.DelayMS) * time.Millisecond)
			defer timer.Stop()
			select {
			case <-timer.C:
			case <-r.Context().Done():
				return
			}
		}

		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		var out corporate.Request
		if op == corporate.Read {
			out, err = a.Requests.Get(ctx, user, id)
		} else {
			out, err = a.Requests.Change(ctx, user, id, op, key, a.Now())
		}
		if err != nil {
			writeRequestError(w, err)
			return
		}
		if fault.Mode == faultDropResponse {
			// net/http closes the connection or resets the stream after the transaction commits.
			panic(http.ErrAbortHandler)
		}
		WriteJSON(w, http.StatusOK, out)
	})
}

func writeRequestError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, corporate.ErrNotFound):
		WriteError(w, http.StatusNotFound, "not_found", "Заявка не найдена.")
	case errors.Is(err, corporate.ErrForbidden):
		WriteError(w, http.StatusForbidden, "forbidden", "Нет доступа к этой операции с заявкой.")
	case errors.Is(err, corporate.ErrConflict):
		WriteError(w, http.StatusConflict, "conflict", "Текущий статус заявки не допускает эту операцию.")
	default:
		WriteError(w, http.StatusServiceUnavailable, "unavailable", "Сервис заявок временно недоступен.")
	}
}

func validKey(key string) bool {
	length := utf8.RuneCountInString(key)
	return length >= 8 && length <= 128 && utf8.ValidString(key) && strings.TrimSpace(key) == key && !strings.ContainsRune(key, 0)
}
