package store

import (
	"context"
	"log/slog"

	"aibuddy/core-api/internal/diagnostics"
)

type statusEvent struct {
	entity string
	id     string
	from   string
	to     string
}

func logStatusEvents(ctx context.Context, events []statusEvent) {
	for _, event := range events {
		diagnostics.Log(ctx, slog.LevelInfo, "status_changed",
			"entity", event.entity, "id", event.id, "from_status", event.from, "to_status", event.to)
	}
}
