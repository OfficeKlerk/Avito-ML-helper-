package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/diagnostics"
	"aibuddy/core-api/internal/onboarding"
	"aibuddy/core-api/internal/store"
)

func (a api) postMessage(w http.ResponseWriter, r *http.Request, u store.User) {
	var input struct {
		Text string `json:"text"`
	}
	if !readJSON(w, r, 64<<10, &input) || strings.TrimSpace(input.Text) == "" || utf8.RuneCountInString(input.Text) > 4000 ||
		strings.ContainsRune(input.Text, 0) {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Введи сообщение длиной от 1 до 4000 символов.")
		return
	}
	key, ok := idempotencyKey(r)
	if !ok {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Idempotency-Key должен быть длиной от 8 до 128 символов.")
		return
	}
	product, ok := productHeaders(r)
	if !ok {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Передай X-Product-Session-Id и X-Product-Scenario-Id вместе, в формате UUID.")
		return
	}
	id := diagnostics.ID(r.Context())
	a.syncPending(r, u.ID, "")

	var exchange struct {
		User      store.Message `json:"user_message"`
		Assistant store.Message `json:"assistant_message"`
	}
	var replay []byte
	ctx := r.Context()
	err := a.db.WithChat(ctx, u.ID, func(session *store.ChatSession) error {
		if key != "" {
			turn, found, err := session.Turn(ctx, key, input.Text)
			if err != nil || turn.Response != nil {
				replay = turn.Response
				return err
			}
			if found {
				// Прошлая попытка сохранила сообщение, но не ответ: продолжаем тот же ход с тем же request_id,
				// чтобы агент и corp-mock узнали уже созданные черновики.
				id, exchange.User = turn.RequestID, turn.UserMessage
			}
		}
		stages, history, state, err := session.Context(ctx, 20, exchange.User.ID)
		if err != nil {
			return err
		}
		if exchange.User.ID == "" {
			exchange.User, err = session.AddUserMessage(ctx, "msg_"+id[3:]+"_u", input.Text, key, id)
			if err != nil {
				return err
			}
		}

		// После сохранения сообщения завершаем ход даже при разрыве HTTP-соединения.
		work, cancel := context.WithTimeout(context.WithoutCancel(ctx), 45*time.Second)
		defer cancel()
		now := a.now()
		req := clients.AgentRequest{
			RequestID: id, Now: now, Timezone: now.Location().String(),
			User: agentUser(u.ProfileAt(now)), Onboarding: agentOnboarding(stages, now),
			History: history, State: state, Message: input.Text,
		}
		reply := a.agentReply(work, r.Header.Get("Authorization"), req)
		reply.ID = "msg_" + id[3:] + "_a"
		reply.Role = "assistant"
		reply.Product = product
		exchange.Assistant, err = session.Finish(work, exchange.User, reply, key)
		return err
	})
	if errors.Is(err, store.ErrKeyConflict) {
		WriteError(w, http.StatusConflict, "conflict", "Этот Idempotency-Key уже использован для другого сообщения.")
		return
	}
	if errors.Is(err, store.ErrChatBusy) {
		WriteError(w, http.StatusTooManyRequests, "rate_limited", "Предыдущее сообщение ещё обрабатывается. Попробуй чуть позже.")
		return
	}
	if err != nil {
		internalError(w)
		return
	}
	if replay != nil {
		WriteJSON(w, http.StatusOK, json.RawMessage(replay))
		return
	}
	WriteJSON(w, http.StatusOK, exchange)
}

func (a api) agentReply(ctx context.Context, bearer string, req clients.AgentRequest) store.Reply {
	if a.agent != nil {
		reply, err := a.agent.Chat(ctx, bearer, req)
		if err == nil {
			return store.Reply{
				Message: store.Message{Text: reply.Text, Sources: reply.Sources, Suggestions: reply.Suggestions, Status: reply.Status},
				State:   reply.State, Drafts: reply.Drafts, TaskUpdates: reply.TaskUpdates,
			}
		}
	}
	diagnostics.Log(ctx, slog.LevelWarn, "chat_fallback", "error_code", "agent_unavailable")
	return store.Reply{Message: store.Message{
		Text:    "Не удалось получить ответ помощника. Сообщение сохранено. Попробуй ещё раз чуть позже.",
		Sources: []store.Source{}, Suggestions: []string{}, Status: "error",
	}}
}

func agentUser(u store.User) clients.UserContext {
	user := clients.UserContext{ID: u.ID, Name: u.Name, Role: u.Role,
		InternshipWeek: u.InternshipWeek, Mentor: u.Mentor, Manager: u.Manager}
	if u.Team != nil {
		user.TeamID, user.TeamName = &u.Team.ID, &u.Team.Name
	}
	return user
}

func agentOnboarding(stages []onboarding.Stage, now time.Time) clients.OnboardingContext {
	plan := onboarding.Calculate(stages, now)
	result := clients.OnboardingContext{
		Progress: plan.Progress, NextSteps: plan.NextSteps, Tasks: []clients.TaskBrief{},
	}
	today := now.Format(time.DateOnly)
	currentFound := false
	for _, stage := range plan.Stages {
		current := !currentFound && stage.Status != onboarding.Done
		currentFound = currentFound || current
		for _, task := range stage.Tasks {
			overdue := task.DueDate != nil && *task.DueDate < today
			if task.Status != onboarding.Done && (current || overdue) {
				result.Tasks = append(result.Tasks, clients.TaskBrief{
					ID: task.ID, StageID: task.StageID, Title: task.Title, Status: task.Status, DueDate: task.DueDate,
				})
			}
		}
	}
	return result
}
