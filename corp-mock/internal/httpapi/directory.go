package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"aibuddy/corp-mock/internal/corporate"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func (a *API) mcpHandler(version string) http.Handler {
	server := mcp.NewServer(&mcp.Implementation{Name: ServiceName, Version: version}, nil)
	server.AddTool(&mcp.Tool{
		Name: "directory_get_me", Description: "Профиль текущего пользователя, команда, наставник и руководитель.",
		InputSchema: json.RawMessage(emptySchema),
	}, a.mcpTool(func(_ context.Context, user corporate.User, arguments json.RawMessage) (any, error) {
		if err := decodeArguments(arguments, &struct{}{}); err != nil {
			return nil, err
		}
		return a.Directory.Profile(user), nil
	}))
	server.AddTool(&mcp.Tool{
		Name: "directory_find_contact", Description: "Разрешённые контакты по теме для текущего пользователя.",
		InputSchema: json.RawMessage(`{
			"type":"object","additionalProperties":false,"required":["topic"],
			"properties":{"topic":{"type":"string","enum":["accesses","absence","onboarding"]}}
		}`),
	}, a.mcpTool(func(_ context.Context, user corporate.User, arguments json.RawMessage) (any, error) {
		var input struct {
			Topic string `json:"topic"`
		}
		if err := decodeArguments(arguments, &input); err != nil {
			return nil, err
		}
		return a.Directory.FindContacts(user, input.Topic)
	}))

	if a.Drafts != nil {
		a.addRequestTools(server)
	}

	transport := mcp.NewStreamableHTTPHandler(func(*http.Request) *mcp.Server { return server },
		&mcp.StreamableHTTPOptions{Stateless: true, JSONResponse: true})
	return a.authorized(func(w http.ResponseWriter, r *http.Request, _ corporate.User) {
		r.Body = http.MaxBytesReader(w, r.Body, 64<<10)
		transport.ServeHTTP(w, r)
	})
}

func (a *API) mcpTool(run func(context.Context, corporate.User, json.RawMessage) (any, error)) mcp.ToolHandler {
	return func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		if req.Extra == nil {
			return toolResult(errorBody{Error: errorDetail{Code: "forbidden", Message: "Нет доступа."}}, true)
		}
		u, err := a.Auth.Authenticate(req.Extra.Header.Values("Authorization"))
		if err != nil {
			return toolResult(errorBody{Error: errorDetail{Code: "forbidden", Message: "Нет доступа."}}, true)
		}
		ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		out, err := run(ctx, u, req.Params.Arguments)
		if err != nil {
			return toolResult(mcpError(err), true)
		}
		return toolResult(out, false)
	}
}

func decodeArguments(arguments json.RawMessage, out any) error {
	arguments = bytes.TrimSpace(arguments)
	if len(arguments) == 0 {
		arguments = json.RawMessage(`{}`)
	}
	if arguments[0] != '{' {
		return corporate.ErrValidation
	}
	decoder := json.NewDecoder(bytes.NewReader(arguments))
	decoder.DisallowUnknownFields()
	if decoder.Decode(out) != nil || decoder.Decode(new(any)) != io.EOF {
		return corporate.ErrValidation
	}
	return nil
}

func toolResult(out any, failed bool) (*mcp.CallToolResult, error) {
	body, err := json.Marshal(out)
	if err != nil {
		return nil, err
	}
	return &mcp.CallToolResult{
		StructuredContent: out, Content: []mcp.Content{&mcp.TextContent{Text: string(body)}}, IsError: failed,
	}, nil
}

func mcpError(err error) errorBody {
	detail := errorDetail{Code: "unavailable", Message: "Сервис временно недоступен. Попробуй ещё раз."}
	switch {
	case errors.Is(err, corporate.ErrValidation):
		detail = errorDetail{Code: "validation", Message: "Проверь параметры инструмента."}
	case errors.Is(err, corporate.ErrForbidden):
		detail = errorDetail{Code: "forbidden", Message: "Нет доступа."}
	case errors.Is(err, corporate.ErrConflict):
		detail = errorDetail{Code: "conflict", Message: "Операция конфликтует с текущим состоянием заявки."}
	case errors.Is(err, corporate.ErrNotFound):
		detail = errorDetail{Code: "not_found", Message: "Заявка не найдена."}
	}
	var policy *corporate.PolicyError
	if errors.As(err, &policy) {
		detail.Message = policy.Text
	}
	return errorBody{Error: detail}
}
