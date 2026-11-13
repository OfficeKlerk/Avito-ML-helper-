// Package diagnostics передаёт идентификатор запроса и пишет структурированные события.
package diagnostics

import (
	"context"
	"crypto/rand"
	"fmt"
	"log/slog"
)

type trace struct {
	id     string
	logger *slog.Logger
}

type traceKey struct{}

func Start(ctx context.Context, logger *slog.Logger) (context.Context, error) {
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return ctx, err
	}
	if logger == nil {
		logger = slog.Default()
	}
	return context.WithValue(ctx, traceKey{}, trace{id: fmt.Sprintf("rq_%x", id), logger: logger}), nil
}

func ID(ctx context.Context) string {
	value, _ := ctx.Value(traceKey{}).(trace)
	return value.id
}

// Log принимает только атрибуты, разрешённые конкретным событием.
func Log(ctx context.Context, level slog.Level, event string, fields ...any) {
	value, ok := ctx.Value(traceKey{}).(trace)
	if ok {
		value.logger.Log(ctx, level, event, append([]any{"request_id", value.id}, fields...)...)
	}
}
