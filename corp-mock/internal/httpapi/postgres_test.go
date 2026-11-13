package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"aibuddy/corp-mock/internal/corporate"
	"aibuddy/corp-mock/internal/store"
)

func TestPostgresRequests(t *testing.T) {
	dsn := os.Getenv("CORP_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("CORP_TEST_DATABASE_URL не задан")
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	a := testAPI(t)
	data := store.New(db)
	a.Requests = data
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := data.Initialize(ctx, testSeedDir(), a.Directory); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if t.Failed() {
		return
	}

	const drafts = `
		INSERT INTO corp.requests (id, type, status, owner_id, team_id, approver, payload, summary, created_at, updated_at)
		SELECT id, 'absence_request', 'draft', 'u_anna', 'team_delivery',
		       '{"id":"u_olga","name":"Ольга Крылова"}',
		       '{"kind":"day_off","date_from":"2026-11-20","date_to":"2026-11-20"}', 'Тестовый отгул',
		       '2026-11-13T08:00:00Z', '2026-11-13T08:00:00Z'
		FROM unnest(ARRAY['req_t1_approve','req_t1_reject','req_t1_cancel']) AS id
	`
	if _, err := db.ExecContext(ctx, drafts); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`DELETE FROM corp.requests WHERE id IN ('req_t1_approve','req_t1_reject','req_t1_cancel')`); err != nil {
			t.Error(err)
		}
	}()
	handler := NewHandler("test", a)
	tokens := make(map[string]string)
	for _, id := range []string{"u_anna", "u_max", "u_olga", "u_pavel", "u_igor", "u_elena"} {
		tokens[id] = testToken(t, a, id)
	}
	call := func(user, id, op, key string) *httptest.ResponseRecorder {
		path, method := "/api/v1/requests/"+id, http.MethodGet
		if op != "" {
			path, method = path+"/"+op, http.MethodPost
		}
		req := httptest.NewRequest(method, path, nil)
		if user != "" {
			req.Header.Set("Authorization", "Bearer "+tokens[user])
		}
		if key != "" {
			req.Header.Set("Idempotency-Key", key)
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec
	}
	expect := func(rec *httptest.ResponseRecorder, code int) corporate.Request {
		t.Helper()
		if rec.Code != code {
			t.Fatalf("wanted HTTP %d, got %d %s", code, rec.Code, rec.Body)
		}
		var out corporate.Request
		if code == 200 {
			if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
				t.Fatal(err)
			}
			if err := out.Validate(); err != nil {
				t.Fatalf("invalid request response: %s", rec.Body)
			}
		}
		return out
	}
	anna, manager, id := "u_anna", "u_olga", "req_t1_approve"
	key := "confirmation-key"
	expect(call("", id, "", ""), 401)
	for _, id := range []string{"req_anna_jira_1", "req_max_vacation_1", "req_max_gitlab_1"} {
		u := anna
		if strings.HasPrefix(id, "req_max") {
			u = "u_max"
		}
		expect(call(u, id, "", ""), 200)
	}
	expect(call(anna, "req_anna_dayoff_1", "", ""), 404)
	expect(call(anna, "req_missing", "", ""), 404)
	for _, u := range []string{"u_max", "u_igor", manager, "u_elena"} {
		rec := call(u, id, "", "")
		expect(rec, 403)
		if strings.Contains(rec.Body.String(), "Тестовый отгул") || strings.Contains(rec.Body.String(), "u_anna") {
			t.Fatalf("foreign data leaked: %s", rec.Body)
		}
		expect(call(u, id, "submit", key), 403)
		expect(call(u, id, "cancel", ""), 403)
	}
	for _, u := range []string{anna, "u_pavel", "u_igor"} {
		expect(call(u, id, "approve", ""), 403)
		expect(call(u, id, "reject", ""), 403)
	}
	expect(call(manager, id, "approve", ""), 409)
	expect(call(anna, id, "submit", "short"), 422)

	replies := make(chan *httptest.ResponseRecorder, 4)
	for range 4 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			replies <- call(anna, id, "submit", key)
		}()
	}
	wg.Wait()
	close(replies)
	ref := ""
	for rec := range replies {
		out := expect(rec, 200)
		if out.Status != corporate.Submitted || out.ExternalRef == nil || (ref != "" && *out.ExternalRef != ref) {
			t.Fatalf("parallel submission: %+v", out)
		}
		ref = *out.ExternalRef
	}
	if out := expect(call(manager, id, "approve", ""), 200); out.Status != corporate.Approved || out.FulfilledAt != nil {
		t.Fatalf("approval: %+v", out)
	}
	expect(call(anna, id, "cancel", ""), 409)
	expect(call(anna, id, "submit", "different-key"), 409)
	expect(call(anna, "req_t1_reject", "submit", key), 200)
	if out := expect(call(manager, "req_t1_reject", "reject", ""), 200); out.Status != corporate.Rejected {
		t.Fatal(out.Status)
	}
	if out := expect(call(anna, "req_t1_cancel", "cancel", ""), 200); out.Status != corporate.Cancelled {
		t.Fatal(out.Status)
	}
	expect(call(anna, "req_t1_cancel", "submit", key), 409)

	if err := store.New(db).Initialize(ctx, testSeedDir(), a.Directory); err != nil {
		t.Fatal(err)
	}
	if out := expect(call(anna, id, "submit", key), 200); out.Status != corporate.Approved || *out.ExternalRef != ref {
		t.Fatalf("persisted replay: %+v", out)
	}
	var count int
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM corp.requests`).Scan(&count); err != nil || count != 6 {
		t.Fatalf("request count: %d (%v)", count, err)
	}
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM corp.request_submissions WHERE request_id = $1`, id).Scan(&count); err != nil || count != 1 {
		t.Fatalf("submission count: %d (%v)", count, err)
	}
}
