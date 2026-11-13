package httpapi

import (
	"log/slog"
	"net/http"
	"time"

	"aibuddy/core-api/internal/diagnostics"
)

type responseStatus struct {
	http.ResponseWriter
	status int
}

func (w *responseStatus) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
		w.ResponseWriter.WriteHeader(status)
	}
}

func (w *responseStatus) Write(p []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(p)
}

func traceRequests(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, err := diagnostics.Start(r.Context(), logger)
		if err != nil {
			internalError(w)
			return
		}
		started := time.Now()
		w.Header().Set("X-Request-Id", diagnostics.ID(ctx))
		rec := &responseStatus{ResponseWriter: w}
		request := r.WithContext(ctx)
		next.ServeHTTP(rec, request)
		status := rec.status
		if status == 0 {
			status = http.StatusOK
		}
		fields := []any{"route", request.Pattern, "http_status", status, "duration_ms", time.Since(started).Milliseconds()}
		if status >= 400 {
			level := slog.LevelInfo
			if status >= 500 {
				level = slog.LevelError
			}
			diagnostics.Log(ctx, level, "http_error", fields...)
		} else {
			diagnostics.Log(ctx, slog.LevelInfo, "http_request", fields...)
		}
	})
}
