package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"aibuddy/corp-mock/internal/corporate"
)

type faultTestRequests struct {
	mu      sync.Mutex
	request corporate.Request
	changes int
}

func (s *faultTestRequests) Authorize(_ context.Context, user corporate.User, id string, op corporate.Operation) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.authorize(user, id, op)
}

func (s *faultTestRequests) authorize(user corporate.User, id string, op corporate.Operation) error {
	if id != s.request.ID {
		return corporate.ErrNotFound
	}
	return s.request.Authorize(user, op)
}

func (s *faultTestRequests) Get(ctx context.Context, user corporate.User, id string) (corporate.Request, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.request, s.authorize(user, id, corporate.Read)
}

func (s *faultTestRequests) Change(ctx context.Context, user corporate.User, id string, op corporate.Operation, _ string, now time.Time) (corporate.Request, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.authorize(user, id, op); err != nil {
		return corporate.Request{}, err
	}
	r, err := s.request.Transition(op, now)
	if err == nil {
		s.request = r
		s.changes++
	}
	return r, err
}

func TestFaultsAreScopedAndOneShot(t *testing.T) {
	api := testAPI(t)
	data := &faultTestRequests{request: corporate.Request{
		ID: "req_test_fault", OwnerID: "u_anna", TeamID: "team_delivery", Status: corporate.Draft,
	}}
	api.Requests = data
	const secret = "separate-fault-token"
	const path = "/api/v1/requests/req_test_fault"
	call := func(handler http.Handler, method, path, token, faultToken, body string) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-Corp-Fault-Token", faultToken)
		req.Header.Set("Idempotency-Key", "confirmation-test")
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec
	}
	check := func(rec *httptest.ResponseRecorder, code int) {
		t.Helper()
		if rec.Code != code {
			t.Fatalf("expected %d, got %d %s", code, rec.Code, rec.Body)
		}
	}
	const rule = `{"request_id":"req_test_fault","operation":"submit","mode":"unavailable"}`
	check(call(NewHandler("test", api), "POST", "/test/faults", "", secret, rule), 404)
	api.Faults = NewFaults(secret, nil)
	handler := NewHandler("test", api)
	anna, maximum := testToken(t, api, "u_anna"), testToken(t, api, "u_max")
	check(call(handler, "POST", "/test/faults", anna, "wrong", rule), 403)
	check(call(handler, "POST", "/test/faults", "", secret,
		`{"request_id":"req_test_fault","operation":"read","mode":"drop_response"}`), 422)
	check(call(handler, "POST", "/test/faults", "", secret,
		`{"request_id":"req_test_fault","operation":"read","mode":"delay","delay_ms":9000}`), 422)
	check(call(handler, "POST", "/test/faults", "", secret, rule), 204)
	check(call(handler, "POST", path+"/submit", maximum, "", ""), 403)
	check(call(handler, "GET", path, anna, "", ""), 200)
	check(call(handler, "POST", path+"/submit", anna, "", ""), 503)
	if data.changes != 0 {
		t.Fatal("refusal changed the request")
	}
	check(call(handler, "POST", path+"/submit", anna, "", ""), 200)
	if data.changes != 1 {
		t.Fatal("retry did not change the request")
	}

	check(call(handler, "POST", "/test/faults", "", secret,
		`{"request_id":"req_test_fault","operation":"read","mode":"delay","delay_ms":30}`), 204)
	started := time.Now()
	check(call(handler, "GET", path, anna, "", ""), 200)
	if time.Since(started) < 30*time.Millisecond {
		t.Fatal("delay was not applied")
	}

	check(call(handler, "POST", "/test/faults", "", secret,
		`{"request_id":"req_test_fault","operation":"cancel","mode":"drop_response"}`), 204)
	server := httptest.NewServer(handler)
	defer server.Close()
	req, err := http.NewRequest("POST", server.URL+path+"/cancel", nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+anna)
	res, err := server.Client().Do(req)
	if err == nil {
		res.Body.Close()
		t.Fatal("expected connection to close without a response")
	}
	rec := call(handler, "GET", path, anna, "", "")
	check(rec, 200)
	if !strings.Contains(rec.Body.String(), `"status":"cancelled"`) {
		t.Fatalf("operation was not applied before dropping response: %s", rec.Body)
	}
}
