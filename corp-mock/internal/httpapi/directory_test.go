package httpapi

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"aibuddy/corp-mock/internal/corporate"

	"github.com/golang-jwt/jwt/v5"
)

const testSecret = "test-secret-corp-mock-shared-with-core"

var testNow = time.Date(2026, 11, 13, 10, 0, 0, 0, time.UTC)

func testSeedDir() string {
	if dir := os.Getenv("SEED_DIR"); dir != "" {
		return dir
	}
	return "../../../data/seed"
}

func testAPI(t *testing.T) *API {
	t.Helper()
	directory, err := corporate.LoadDirectory(testSeedDir())
	if err != nil {
		t.Fatal(err)
	}
	now := func() time.Time { return testNow }
	auth, err := corporate.NewAuthenticator(directory, testSecret, now)
	if err != nil {
		t.Fatal(err)
	}
	return &API{Auth: auth, Directory: directory, Now: now}
}

func signed(t *testing.T, u corporate.User, method jwt.SigningMethod, secret string, change func(jwt.MapClaims)) string {
	t.Helper()
	c := jwt.MapClaims{"sub": u.ID, "login": u.Login, "role": u.Role, "team_id": u.TeamID, "exp": testNow.Add(time.Hour).Unix()}
	if change != nil {
		change(c)
	}
	token, err := jwt.NewWithClaims(method, c).SignedString([]byte(secret))
	if err != nil {
		t.Fatal(err)
	}
	return token
}

func testToken(t *testing.T, a *API, id string) string {
	t.Helper()
	user, ok := a.Directory.User(id)
	if !ok {
		t.Fatalf("no user %s", id)
	}
	return signed(t, user, jwt.SigningMethodHS256, testSecret, nil)
}

func TestJWTRejections(t *testing.T) {
	a := testAPI(t)
	handler := NewHandler("test", a)
	u, _ := a.Directory.User("u_anna")
	for _, tc := range []struct {
		name   string
		method jwt.SigningMethod
		secret string
		change func(jwt.MapClaims)
	}{
		{"signature", jwt.SigningMethodHS256, "different-secret", nil},
		{"algorithm", jwt.SigningMethodHS384, testSecret, nil},
		{"expired", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { c["exp"] = testNow.Unix() }},
		{"no expiration", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { delete(c, "exp") }},
		{"no team claim", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { delete(c, "team_id") }},
		{"wrong team", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { c["team_id"] = "team_auto" }},
		{"wrong role", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { c["role"] = "manager" }},
		{"wrong login", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { c["login"] = "intern_max" }},
		{"unknown user", jwt.SigningMethodHS256, testSecret, func(c jwt.MapClaims) { c["sub"] = "u_missing" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for _, path := range []string{"/mcp", "/api/v1/requests/req_anna_jira_1"} {
				req := httptest.NewRequest(http.MethodGet, path, nil)
				req.Header.Set("Authorization", "Bearer "+signed(t, u, tc.method, tc.secret, tc.change))
				rec := httptest.NewRecorder()
				handler.ServeHTTP(rec, req)
				if rec.Code != 401 {
					t.Errorf("%s: %d %s", path, rec.Code, rec.Body)
				}
			}
		})
	}
}

func TestMCPDirectory(t *testing.T) {
	a := testAPI(t)
	handler := NewHandler("test", a)
	rpc := func(user, body string, want int) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(http.MethodPost, "/mcp", strings.NewReader(body))
		req.Header.Set("Accept", "application/json, text/event-stream")
		req.Header.Set("Content-Type", "application/json")
		if user != "" {
			req.Header.Set("Authorization", "Bearer "+testToken(t, a, user))
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != want {
			t.Fatalf("MCP status %d: %s", rec.Code, rec.Body)
		}
		return rec
	}
	rpc("", `{}`, 401)
	rpc("u_anna", `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}`, 200)
	list := rpc("u_anna", `{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`, 200).Body.String()
	if !strings.Contains(list, "directory_get_me") || !strings.Contains(list, "directory_find_contact") || strings.Contains(list, "absence_create_draft") {
		t.Fatalf("tools: %s", list)
	}
	call := func(user, tool, args string) (json.RawMessage, bool) {
		t.Helper()
		rec := rpc(user, `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"`+tool+`","arguments":`+args+`}}`, 200)
		var reply struct {
			Result struct {
				Structured json.RawMessage `json:"structuredContent"`
				IsError    bool            `json:"isError"`
				Content    []struct{ Text string }
			}
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &reply); err != nil || len(reply.Result.Content) != 1 ||
			!json.Valid([]byte(reply.Result.Content[0].Text)) || len(reply.Result.Structured) == 0 {
			t.Fatalf("MCP response: %s (%v)", rec.Body, err)
		}
		return reply.Result.Structured, reply.Result.IsError
	}
	for _, tc := range []struct {
		user, topic, contact string
	}{
		{"u_anna", "absence", "u_olga"},
		{"u_max", "absence", "u_pavel"},
		{"u_anna", "accesses", "u_igor"},
		{"u_max", "accesses", "u_dina"},
		{"u_elena", "onboarding", "u_elena"},
		{"u_elena", "accesses", ""},
	} {
		raw, failed := call(tc.user, "directory_find_contact", `{"topic":"`+tc.topic+`"}`)
		var out corporate.ContactList
		err := json.Unmarshal(raw, &out)
		if failed || err != nil || out.Topic != tc.topic || out.Contacts == nil {
			t.Fatalf("contacts: %s (%v)", raw, err)
		}
		if tc.contact == "" {
			if len(out.Contacts) != 0 {
				t.Fatal(string(raw))
			}
		} else if len(out.Contacts) != 1 || out.Contacts[0].ID == nil || *out.Contacts[0].ID != tc.contact {
			t.Fatal(string(raw))
		}
	}
	raw, failed := call("u_anna", "directory_get_me", `{}`)
	var p corporate.Profile
	if err := json.Unmarshal(raw, &p); failed || err != nil || p.ID != "u_anna" || p.Team == nil ||
		p.Team.ID != "team_delivery" || p.Mentor == nil || p.Mentor.ID != "u_igor" || p.Manager == nil || p.Manager.ID != "u_olga" {
		t.Fatalf("profile: %s (%v)", raw, err)
	}
	for _, tc := range []struct{ tool, args string }{
		{"directory_get_me", `{"user_id":"u_max"}`},
		{"directory_find_contact", `{"topic":"accesses","team_id":"team_auto"}`},
		{"directory_find_contact", `{"topic":"unknown"}`},
	} {
		raw, failed = call("u_anna", tc.tool, tc.args)
		if !failed || !strings.Contains(string(raw), "validation") {
			t.Fatal(string(raw))
		}
	}
}
