package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func do(t *testing.T, method, path string) (*httptest.ResponseRecorder, map[string]any) {
	t.Helper()
	rec := httptest.NewRecorder()
	NewHandler("0.1.0", nil).ServeHTTP(rec, httptest.NewRequest(method, path, nil))
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("ответ не JSON: %v: %s", err, rec.Body.String())
	}
	return rec, body
}

func TestHealth(t *testing.T) {
	rec, body := do(t, http.MethodGet, "/health")
	if rec.Code != http.StatusOK {
		t.Fatalf("статус %d, ожидался 200", rec.Code)
	}
	if body["status"] != "ok" || body["service"] != "corp-mock" || body["version"] != "0.1.0" {
		t.Fatalf("неожиданный ответ: %v", body)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("Content-Type %q", ct)
	}
}

func TestUnknownRouteUsesContractErrorFormat(t *testing.T) {
	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/nope"},
		{http.MethodPost, "/health"},
	} {
		rec, body := do(t, tc.method, tc.path)
		if rec.Code != http.StatusNotFound {
			t.Fatalf("%s %s: статус %d, ожидался 404", tc.method, tc.path, rec.Code)
		}
		detail, ok := body["error"].(map[string]any)
		if !ok || detail["code"] != "not_found" || detail["message"] == "" {
			t.Fatalf("%s %s: неожиданный ответ: %v", tc.method, tc.path, body)
		}
	}
}

func TestWriteError(t *testing.T) {
	rec := httptest.NewRecorder()
	WriteError(rec, http.StatusForbidden, "forbidden", "Нет доступа.")
	if rec.Code != http.StatusForbidden || !strings.Contains(rec.Body.String(), "\"code\":\"forbidden\"") {
		t.Fatalf("неожиданный ответ: %d %s", rec.Code, rec.Body.String())
	}
}
