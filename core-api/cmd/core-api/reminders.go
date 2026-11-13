package main

import (
	"context"
	"log/slog"
	"time"

	"aibuddy/core-api/internal/diagnostics"
	"aibuddy/core-api/internal/store"
)

func runReminders(ctx context.Context, data *store.Store, logger *slog.Logger, now func() time.Time) {
	ticker := time.NewTicker(time.Minute)
	defer ticker.Stop()
	for ctx.Err() == nil {
		runReminderBatch(ctx, data, logger, now())
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func runReminderBatch(ctx context.Context, data *store.Store, logger *slog.Logger, now time.Time) {
	trace, err := diagnostics.Start(ctx, logger)
	if err != nil {
		logger.Error("reminder_run", "error_code", "request_id_generation_failed")
		return
	}
	batch, cancel := context.WithTimeout(trace, 10*time.Second)
	defer cancel()
	started := time.Now()
	count, err := data.CreateOverdueReminders(batch, now)
	if err != nil {
		diagnostics.Log(trace, slog.LevelWarn, "reminder_run", "error_code", "save_reminders",
			"duration_ms", time.Since(started).Milliseconds())
		return
	}
	diagnostics.Log(trace, slog.LevelInfo, "reminder_run", "created", count,
		"duration_ms", time.Since(started).Milliseconds())
}
