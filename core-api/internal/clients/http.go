// Package clients реализует HTTP-контракты core-api с соседними сервисами.
package clients

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	"aibuddy/core-api/internal/diagnostics"
)

type HTTPError int

func (e HTTPError) Error() string {
	return fmt.Sprintf("HTTP %d", int(e))
}

type endpoint struct {
	baseURL string
	http    *http.Client
}

func newEndpoint(baseURL string, timeout time.Duration) endpoint {
	return endpoint{baseURL: strings.TrimRight(baseURL, "/"), http: &http.Client{
		Timeout: timeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}}
}

func (e endpoint) request(ctx context.Context, method, path, bearer, requestID, key string, body, out any) error {
	var input io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return err
		}
		input = bytes.NewReader(data)
	}
	req, err := http.NewRequestWithContext(ctx, method, e.baseURL+path, input)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", bearer)
	req.Header.Set("X-Request-Id", requestID)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	res, err := e.http.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return HTTPError(res.StatusCode)
	}
	const maxBody = 1 << 20
	data, err := io.ReadAll(io.LimitReader(res.Body, maxBody+1))
	if err != nil {
		return err
	}
	if len(data) > maxBody {
		return errors.New("ответ сервиса слишком большой")
	}
	return json.Unmarshal(data, out)
}

func logCall(ctx context.Context, service, operation string, started time.Time, err error) {
	fields := []any{"upstream", service, "operation", operation, "duration_ms", time.Since(started).Milliseconds()}
	if err == nil {
		diagnostics.Log(ctx, slog.LevelInfo, "upstream_call", append(fields, "http_status", http.StatusOK)...)
		return
	}
	var status HTTPError
	var transport *url.Error
	code := "invalid_response"
	switch {
	case errors.As(err, &status):
		code = "upstream_http"
		fields = append(fields, "http_status", int(status))
	case errors.Is(err, context.DeadlineExceeded):
		code = "timeout"
	case errors.Is(err, context.Canceled):
		code = "cancelled"
	case errors.As(err, &transport):
		code = "transport"
	}
	diagnostics.Log(ctx, slog.LevelWarn, "upstream_call", append(fields, "error_code", code)...)
}
