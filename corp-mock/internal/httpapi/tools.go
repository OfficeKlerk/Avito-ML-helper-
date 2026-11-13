package httpapi

import (
	"context"
	"encoding/json"
	"strings"
	"time"
	"unicode/utf8"

	"aibuddy/corp-mock/internal/corporate"
	"aibuddy/corp-mock/internal/store"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const emptySchema = `{"type":"object","additionalProperties":false,"properties":{}}`

func (a *API) addRequestTools(server *mcp.Server) {
	for _, tool := range []struct {
		name, description, schema string
		call                      func(context.Context, corporate.User, json.RawMessage) (any, error)
	}{
		{"absence_get_rules", "Тестовые правила оформления отгула и отпуска.", emptySchema, a.absenceRules},
		{"absence_list_my", "Заявки текущего пользователя на отсутствие.", emptySchema, a.absenceList},
		{"absence_create_draft", "Создать черновик отгула или отпуска.", absenceDraftSchema, a.absenceDraft},
		{"access_list_my", "Необходимые и имеющиеся доступы текущего пользователя.", emptySchema, a.accessList},
		{"access_create_draft", "Создать черновик заявки на разрешённую систему.", accessDraftSchema, a.accessDraft},
	} {
		server.AddTool(&mcp.Tool{Name: tool.name, Description: tool.description, InputSchema: json.RawMessage(tool.schema)}, a.mcpTool(tool.call))
	}
}

func (a *API) absenceRules(_ context.Context, _ corporate.User, args json.RawMessage) (any, error) {
	if err := decodeArguments(args, &struct{}{}); err != nil {
		return nil, err
	}
	return a.Rules, nil
}

func (a *API) absenceList(ctx context.Context, user corporate.User, args json.RawMessage) (any, error) {
	if err := decodeArguments(args, &struct{}{}); err != nil {
		return nil, err
	}
	list, err := a.Drafts.List(ctx, user, "absence_request")
	return struct {
		Requests []corporate.Request `json:"requests"`
	}{list}, err
}

const absenceDraftSchema = `{"type":"object","additionalProperties":false,
	"required":["kind","date_from","date_to","idempotency_key"],"properties":{
	"kind":{"type":"string","enum":["day_off","vacation"]},
	"date_from":{"type":"string","format":"date"},"date_to":{"type":"string","format":"date"},
	"comment":{"type":"string","maxLength":500},"idempotency_key":{"type":"string","minLength":8,"maxLength":128}}}`

func (a *API) absenceDraft(ctx context.Context, user corporate.User, args json.RawMessage) (any, error) {
	var in struct {
		corporate.AbsencePayload
		Key string `json:"idempotency_key"`
	}
	if decodeArguments(args, &in) != nil || !validKey(in.Key) {
		return nil, corporate.ErrValidation
	}
	now := a.Now()
	return a.Drafts.CreateDraft(ctx, user, store.DraftInput{
		Kind: "absence_request", Key: in.Key,
		Build: func() (json.RawMessage, string, *corporate.Ref, error) {
			rule, err := a.Rules.ValidateDates(in.AbsencePayload, now)
			if err != nil {
				return nil, "", nil, err
			}
			manager, err := a.Directory.Approver(user, rule.ApproverRole)
			if err != nil {
				return nil, "", nil, err
			}
			payload, err := json.Marshal(in.AbsencePayload)
			from, _ := time.Parse(time.DateOnly, in.DateFrom)
			to, _ := time.Parse(time.DateOnly, in.DateTo)
			title := rule.Title + " " + from.Format("02.01.2006")
			if !from.Equal(to) {
				title += "–" + to.Format("02.01.2006")
			}
			return payload, title, manager, err
		},
	}, now)
}

func (a *API) accessList(ctx context.Context, user corporate.User, args json.RawMessage) (any, error) {
	if err := decodeArguments(args, &struct{}{}); err != nil {
		return nil, err
	}
	items, err := a.Drafts.Accesses(ctx, user, a.Access)
	return struct {
		Accesses []corporate.AccessItem `json:"accesses"`
	}{items}, err
}

const accessDraftSchema = `{"type":"object","additionalProperties":false,
	"required":["system","reason","idempotency_key"],"properties":{
	"system":{"type":"string","enum":["confluence","jira","gitlab","vpn","team_space"]},
	"reason":{"type":"string","minLength":3,"maxLength":500},
	"idempotency_key":{"type":"string","minLength":8,"maxLength":128}}}`

func (a *API) accessDraft(ctx context.Context, user corporate.User, args json.RawMessage) (any, error) {
	var in struct {
		corporate.AccessPayload
		Key string `json:"idempotency_key"`
	}
	if decodeArguments(args, &in) != nil || !validKey(in.Key) {
		return nil, corporate.ErrValidation
	}
	return a.Drafts.CreateDraft(ctx, user, store.DraftInput{
		Kind: "access_request", Key: in.Key, System: in.System, Catalog: a.Access,
		Build: func() (json.RawMessage, string, *corporate.Ref, error) {
			system, exists := a.Access.System(in.System)
			reasonLength := utf8.RuneCountInString(in.Reason)
			if !exists || reasonLength > 500 || utf8.RuneCountInString(strings.TrimSpace(in.Reason)) < 3 || strings.ContainsRune(in.Reason, 0) {
				return nil, "", nil, corporate.ErrValidation
			}
			if !a.Access.Required(user, system.System) {
				return nil, "", nil, corporate.Deny(corporate.ErrForbidden, "Доступ к "+system.Title+" не предусмотрен для твоей команды.")
			}
			manager, err := a.Directory.Approver(user, "manager")
			if err != nil {
				return nil, "", nil, err
			}
			payload, err := json.Marshal(in.AccessPayload)
			return payload, "Доступ к " + system.Title, manager, err
		},
	}, a.Now())
}
