package httpapi

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/diagnostics"
	"aibuddy/core-api/internal/store"
)

var errCorpUnavailable = errors.New("corp-mock unavailable")

type actionConflict string

func (e actionConflict) Error() string { return string(e) }

func (a api) confirmAction(w http.ResponseWriter, r *http.Request, u store.User) {
	keys := r.Header.Values("Idempotency-Key")
	if len(keys) != 1 || strings.TrimSpace(keys[0]) != keys[0] || !utf8.ValidString(keys[0]) ||
		utf8.RuneCountInString(keys[0]) < 8 || utf8.RuneCountInString(keys[0]) > 128 {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Укажи Idempotency-Key длиной от 8 до 128 символов.")
		return
	}
	a.changeAction(w, r, u, "submit", keys[0])
}

func (a api) cancelAction(w http.ResponseWriter, r *http.Request, u store.User) {
	a.changeAction(w, r, u, "cancel", "")
}

func (a api) changeAction(w http.ResponseWriter, r *http.Request, u store.User, transition, key string) {
	id := diagnostics.ID(r.Context())
	// Даём завершить запись результата, если клиент потерял соединение после отправки.
	ctx, cancel := context.WithTimeout(context.WithoutCancel(r.Context()), 12*time.Second)
	defer cancel()
	card, err := a.db.ChangeAction(ctx, u.ID, r.PathValue("action_id"), key,
		func(record store.ActionRecord) (store.ActionChange, error) {
			return a.changeCorpRequest(ctx, r.Header.Get("Authorization"), id, transition, record)
		})
	var conflict actionConflict
	switch {
	case err == nil:
		WriteJSON(w, http.StatusOK, card)
	case errors.Is(err, sql.ErrNoRows):
		WriteError(w, http.StatusNotFound, "not_found", "Действие не найдено.")
	case errors.As(err, &conflict):
		WriteError(w, http.StatusConflict, "conflict", conflict.Error())
	case errors.Is(err, errCorpUnavailable), errors.Is(err, context.DeadlineExceeded):
		WriteError(w, http.StatusServiceUnavailable, "unavailable",
			"Не удалось проверить результат операции с заявкой. Попробуй ещё раз.")
	default:
		internalError(w)
	}
}

func (a api) changeCorpRequest(ctx context.Context, bearer, id, transition string, card store.ActionRecord) (store.ActionChange, error) {
	submit := transition == "submit"
	if !submit && card.Status == "cancelled" {
		return store.ActionChange{}, nil
	}
	if !allowedTransition(card.Status, submit) {
		return store.ActionChange{}, transitionConflict(card.Status, submit)
	}
	if a.corp == nil || card.ExternalID == nil {
		return store.ActionChange{}, errCorpUnavailable
	}

	// Даже после падения процесса карточка может остаться черновиком при уже
	// отправленной заявке. Перед каждой попыткой запрашиваем состояние в corp-mock.
	remote, err := a.corp.Request(ctx, bearer, id, card, "", "")
	if err != nil {
		return store.ActionChange{}, errCorpUnavailable
	}
	if reachedStatus(remote.Status, submit) {
		return actionChange(remote, submit), nil
	}
	if !allowedTransition(remote.Status, submit) {
		return store.ActionChange{}, transitionConflict(remote.Status, submit)
	}

	var downstreamKey string
	if submit {
		hash := sha256.Sum256([]byte(card.OwnerID + ":" + *card.ExternalID))
		downstreamKey = fmt.Sprintf("core-confirm-%x", hash)
	}
	remote, sendErr := a.corp.Request(ctx, bearer, id, card, transition, downstreamKey)
	if sendErr == nil && reachedStatus(remote.Status, submit) {
		return actionChange(remote, submit), nil
	}

	// Ответ мог потеряться после выполнения. Читаем заявку вместо повтора POST.
	remote, err = a.corp.Request(ctx, bearer, id, card, "", "")
	if err == nil {
		if reachedStatus(remote.Status, submit) {
			return actionChange(remote, submit), nil
		}
		if !allowedTransition(remote.Status, submit) {
			return store.ActionChange{}, transitionConflict(remote.Status, submit)
		}
	}
	if errors.Is(sendErr, clients.HTTPError(http.StatusConflict)) {
		return store.ActionChange{}, transitionConflict(remote.Status, submit)
	}
	return store.ActionChange{}, errCorpUnavailable
}

func allowedTransition(status string, submit bool) bool {
	return status == "draft" || (!submit && status == "submitted")
}

func reachedStatus(status string, submit bool) bool {
	if submit {
		return status == "submitted" || status == "approved" || status == "rejected"
	}
	return status == "cancelled"
}

func transitionConflict(status string, submit bool) actionConflict {
	switch {
	case submit && status == "cancelled":
		return "Это действие уже отменено."
	case !submit && status == "approved":
		return "Заявка уже согласована, отменить её нельзя."
	default:
		return "Текущий статус заявки не допускает эту операцию."
	}
}

func actionChange(remote clients.CorpRequest, submit bool) store.ActionChange {
	change := store.ActionChange{Status: remote.Status, UpdatedAt: remote.UpdatedAt,
		FulfilledAt: remote.FulfilledAt, AccessSystem: remote.Payload.System}
	if submit {
		message := "Заявка отправлена на согласование."
		if remote.Status == "submitted" && remote.Approver != nil && remote.Approver.Name != "" {
			message += " Согласует " + remote.Approver.Name + "."
		}
		change.Result = &store.ActionResult{Message: message, ExternalRef: remote.ExternalRef}
	}
	return change
}
