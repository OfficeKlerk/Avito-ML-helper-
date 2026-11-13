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

func TestPostgresMCPRequests(t *testing.T) {
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
	a.Rules, a.Access, err = corporate.LoadServices(testSeedDir())
	if err != nil {
		t.Fatal(err)
	}
	data := store.New(db)
	a.Requests, a.Drafts = data, data
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	if err := data.Initialize(ctx, testSeedDir(), a.Directory); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`DELETE FROM corp.requests r USING corp.draft_keys k WHERE r.id=k.request_id AND k.idempotency_key IN ('absence-20261114','access-12345678','access-87654321','access-33333333')`); err != nil {
			t.Error(err)
		}
	}()

	handler := NewHandler("test", a)
	manager := testToken(t, a, "u_olga")
	anna, maxToken, hr := testToken(t, a, "u_anna"), testToken(t, a, "u_max"), testToken(t, a, "u_elena")
	rpc := func(token, tool, args string) *httptest.ResponseRecorder {
		body := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"` + tool + `","arguments":` + args + `}}`
		req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body))
		req.Header.Set("Accept", "application/json, text/event-stream")
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+token)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec
	}
	expect := func(rec *httptest.ResponseRecorder, code string, out any) {
		t.Helper()
		var reply struct {
			Result struct {
				Body  json.RawMessage `json:"structuredContent"`
				Error bool            `json:"isError"`
			}
		}
		if rec.Code != 200 || json.Unmarshal(rec.Body.Bytes(), &reply) != nil || len(reply.Result.Body) == 0 {
			t.Fatalf("MCP result: %d %s", rec.Code, rec.Body)
		}
		if code != "" {
			var body errorBody
			if !reply.Result.Error || json.Unmarshal(reply.Result.Body, &body) != nil || body.Error.Code != code {
				t.Fatalf("wanted %s: %s", code, rec.Body)
			}
			return
		}
		if reply.Result.Error || json.Unmarshal(reply.Result.Body, out) != nil {
			t.Fatalf("MCP success: %s", rec.Body)
		}
	}

	var rules corporate.AbsenceRules
	expect(rpc(anna, "absence_get_rules", `{}`), "", &rules)
	if len(rules.Rules) != 2 || rules.Disclaimer == "" {
		t.Fatalf("rules: %+v", rules)
	}
	const absence = `{"kind":"day_off","date_from":"2026-11-14","date_to":"2026-11-15","idempotency_key":"absence-20261114"}`
	expect(rpc(anna, "absence_create_draft", strings.ReplaceAll(absence, "2026-11-14", "2026-11-12")), "validation", nil)
	expect(rpc(hr, "absence_create_draft", absence), "forbidden", nil)

	responses := make(chan *httptest.ResponseRecorder, 4)
	var wg sync.WaitGroup
	for range 4 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			responses <- rpc(anna, "absence_create_draft", absence)
		}()
	}
	wg.Wait()
	close(responses)
	var id string
	for rec := range responses {
		var draft corporate.Request
		expect(rec, "", &draft)
		if draft.Status != corporate.Draft || draft.ExternalRef != nil || draft.ID == "" || id != "" && draft.ID != id {
			t.Fatalf("draft: %+v", draft)
		}
		id = draft.ID
	}
	var other corporate.Request
	expect(rpc(maxToken, "absence_create_draft", absence), "", &other)
	if other.OwnerID != "u_max" || other.ID == id {
		t.Fatalf("foreign replay: %+v", other)
	}
	var list struct{ Requests []corporate.Request }
	expect(rpc(anna, "absence_list_my", `{}`), "", &list)
	if len(list.Requests) != 1 || list.Requests[0].ID != id {
		t.Fatalf("absence list: %+v", list.Requests)
	}

	readAccess := func(token, system string) corporate.AccessItem {
		t.Helper()
		var result struct{ Accesses []corporate.AccessItem }
		expect(rpc(token, "access_list_my", `{}`), "", &result)
		for _, item := range result.Accesses {
			if item.System == system {
				return item
			}
		}
		return corporate.AccessItem{}
	}
	if item := readAccess(anna, "jira"); item.Status != "pending" || item.RequestID == nil || *item.RequestID != "req_anna_jira_1" {
		t.Fatalf("Jira: %+v", item)
	}
	if item := readAccess(hr, "jira"); item.System != "" {
		t.Fatalf("HR accesses: %+v", item)
	}
	if item := readAccess(maxToken, "gitlab"); item.Status != "granted" {
		t.Fatalf("existing access: %+v", item)
	}
	const access = `{"system":"gitlab","reason":"Рабочие репозитории","idempotency_key":"access-12345678"}`
	expect(rpc(maxToken, "access_create_draft", strings.Replace(access, "gitlab", "vpn", 1)), "forbidden", nil)
	expect(rpc(maxToken, "access_create_draft", access), "conflict", nil)
	expect(rpc(anna, "access_create_draft", strings.Replace(access, "gitlab", "jira", 1)), "conflict", nil)
	var draft, duplicate corporate.Request
	expect(rpc(anna, "access_create_draft", access), "", &draft)
	expect(rpc(anna, "access_create_draft", strings.Replace(access, "12345678", "87654321", 1)), "", &duplicate)
	if draft.ID == "" || draft.ID != duplicate.ID || draft.Status != corporate.Draft {
		t.Fatalf("access drafts: %+v %+v", draft, duplicate)
	}

	change := func(token, id, operation string) corporate.Request {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/requests/"+id+"/"+operation, nil)
		req.Header.Set("Authorization", "Bearer "+token)
		if operation == "submit" {
			req.Header.Set("Idempotency-Key", "test-confirm-key")
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		var request corporate.Request
		if rec.Code != 200 || json.Unmarshal(rec.Body.Bytes(), &request) != nil {
			t.Fatalf("REST %s: %d %s", operation, rec.Code, rec.Body)
		}
		return request
	}
	if out := change(anna, id, "submit"); out.Status != corporate.Submitted || out.ExternalRef == nil {
		t.Fatalf("absence submit: %+v", out)
	}
	if out := change(anna, id, "cancel"); out.Status != corporate.Cancelled {
		t.Fatalf("absence cancel: %+v", out)
	}
	if item := readAccess(anna, "gitlab"); item.Status != "missing" || item.RequestID == nil || *item.RequestID != draft.ID {
		t.Fatalf("draft access: %+v", item)
	}
	change(anna, draft.ID, "submit")
	if item := readAccess(anna, "gitlab"); item.Status != "pending" {
		t.Fatalf("submitted access: %+v", item)
	}
	change(anna, draft.ID, "cancel")
	if item := readAccess(anna, "gitlab"); item.Status != "missing" {
		t.Fatalf("cancelled access: %+v", item)
	}
	// Отправка и согласование новой заявки после отмены предыдущей.
	const secondKey = "access-33333333"
	newAccess := strings.Replace(access, "access-12345678", secondKey, 1)
	var granted corporate.Request
	expect(rpc(anna, "access_create_draft", newAccess), "", &granted)
	change(anna, granted.ID, "submit")
	approved := change(manager, granted.ID, "approve")
	if approved.Status != corporate.Approved || approved.FulfilledAt == nil ||
		!approved.FulfilledAt.Equal(approved.UpdatedAt) {
		t.Fatalf("grant: %+v", approved)
	}
	if item := readAccess(anna, "gitlab"); item.Status != "granted" || item.RequestID == nil || *item.RequestID != granted.ID {
		t.Fatalf("granted access: %+v", item)
	}

	if err := data.Initialize(ctx, testSeedDir(), a.Directory); err != nil {
		t.Fatal(err)
	}
	a.Now = func() time.Time { return testNow.AddDate(0, 0, 10) }
	var replay corporate.Request
	expect(rpc(anna, "absence_create_draft", absence), "", &replay)
	if replay.ID != id || replay.Status != corporate.Cancelled {
		t.Fatalf("persisted replay: %+v", replay)
	}
	expect(rpc(anna, "access_create_draft", newAccess), "", &replay)
	if replay.ID != granted.ID || replay.Status != corporate.Approved || replay.FulfilledAt == nil {
		t.Fatalf("grant after restart: %+v", replay)
	}
}
