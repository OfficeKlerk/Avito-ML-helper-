package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"aibuddy/core-api/internal/onboarding"
	"aibuddy/core-api/internal/store"

	"github.com/golang-jwt/jwt/v5"
)

func TestPostgresOnboardingAndOwnership(t *testing.T) {
	url := os.Getenv("CORE_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("CORE_TEST_DATABASE_URL не задан")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	const seedDir = "../../../data/seed"

	// Два запуска используют одну базу, в том числе при создании схемы с нуля.
	results := make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() { results <- store.Initialize(ctx, db, seedDir) }()
	}
	for i := 0; i < 2; i++ {
		if err := <-results; err != nil {
			t.Fatal(err)
		}
	}

	const secret = "integration-test-secret"
	now := time.Date(2026, time.November, 11, 10, 0, 0, 0, time.FixedZone("MSK", 3*3600))
	handler := NewHandler("0.1.0", store.New(db), secret, func() time.Time { return now }, Dependencies{})
	call := func(method, path, token, input string, status int) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(method, path, strings.NewReader(input))
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != status {
			t.Fatalf("%s %s: ожидали %d, получили %d (%s)", method, path, status, rec.Code, rec.Body)
		}
		return rec
	}

	login := func(login, id string) string {
		t.Helper()
		rec := call(http.MethodPost, "/api/auth/login", "", `{"login":"`+login+`","password":"buddy2026"}`, 200)
		var result struct {
			Token string     `json:"token"`
			User  store.User `json:"user"`
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &result); err != nil || result.Token == "" || result.User.ID != id {
			t.Fatalf("ответ входа: %s (%v)", rec.Body, err)
		}
		return result.Token
	}
	call(http.MethodPost, "/api/auth/login", "", `{"login":"intern_anna","password":"bad"}`, 401)
	call(http.MethodPost, "/api/auth/login", "", `{"login":"","password":"buddy2026"}`, 422)
	call(http.MethodGet, "/api/onboarding", "", "", 401)
	anna := login("intern_anna", "u_anna")
	maxToken := login("intern_max", "u_max")
	mentor := login("mentor_igor", "u_igor")
	hr := login("hr_elena", "u_elena")
	call(http.MethodGet, "/api/me", hr, "", 200)
	me := call(http.MethodGet, "/api/me?user_id=u_max", anna, "", 200)
	if !strings.Contains(me.Body.String(), `"id":"u_anna"`) || !strings.Contains(me.Body.String(), `"internship_week":1`) {
		t.Fatalf("профиль: %s", me.Body)
	}

	for _, test := range []struct {
		secret string
		exp    time.Time
		role   string
	}{
		{"wrong-secret", now.Add(time.Hour), "intern"},
		{secret, now, "intern"},
		{secret, now.Add(time.Hour), "manager"},
	} {
		token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
			"sub": "u_anna", "login": "intern_anna", "role": test.role,
			"team_id": "team_delivery", "exp": test.exp.Unix(),
		}).SignedString([]byte(test.secret))
		if err != nil {
			t.Fatal(err)
		}
		call(http.MethodGet, "/api/me", token, "", 401)
	}

	state := func(token string) onboarding.State {
		t.Helper()
		rec := call(http.MethodGet, "/api/onboarding", token, "", 200)
		var result onboarding.State
		if err := json.Unmarshal(rec.Body.Bytes(), &result); err != nil {
			t.Fatal(err)
		}
		return result
	}
	before := state(anna)
	if len(before.Stages) != 5 || before.Progress != 7 || len(before.NextSteps) != 3 ||
		before.NextSteps[0].TaskID != "t_join_channels" || before.NextSteps[1].TaskID != "t_request_accesses" ||
		before.NextSteps[2].TaskID != "t_team_space" {
		t.Fatalf("начальный план Анны: %+v", before)
	}
	if got := state(mentor); got.Progress != 0 || got.Stages == nil || len(got.Stages) != 0 || got.NextSteps == nil || len(got.NextSteps) != 0 {
		t.Fatalf("план наставника: %+v", got)
	}
	const task = "/api/onboarding/tasks/t_join_channels"
	call(http.MethodPatch, task, mentor, `{"status":"done"}`, 404)
	call(http.MethodPatch, task, maxToken, `{"status":"done","owner_id":"u_anna"}`, 422)
	call(http.MethodPatch, task, anna, `{"status":"finished"}`, 422)
	call(http.MethodPatch, task, anna, `{"status":"done"}`, 200)
	defer call(http.MethodPatch, task, anna, `{"status":"in_progress"}`, 200)
	if err := store.Initialize(ctx, db, seedDir); err != nil {
		t.Fatal(err)
	}
	if got := state(anna); got.Progress != 13 || got.NextSteps[0].TaskID != "t_request_accesses" {
		t.Fatalf("после перезапуска: %+v", got)
	}
	if got := state(maxToken); got.Progress != 47 {
		t.Fatalf("прогресс Максима: %d", got.Progress)
	}

	const card = "/api/actions/act_anna_dayoff_1"
	if call(http.MethodGet, card, maxToken, "", 404).Body.String() !=
		call(http.MethodGet, "/api/actions/act_missing", maxToken, "", 404).Body.String() {
		t.Fatal("чужая карточка отличается от отсутствующей")
	}
	action := call(http.MethodGet, card, anna, "", 200)
	if strings.Contains(action.Body.String(), "owner_id") || !strings.Contains(action.Body.String(), "req_anna_dayoff_1") {
		t.Fatalf("карточка Анны: %s", action.Body)
	}
	if got := call(http.MethodGet, "/api/actions?owner_id=u_anna", maxToken, "", 200).Body.String(); got != "{\"actions\":[]}\n" {
		t.Fatalf("список карточек Максима: %s", got)
	}
	if got := call(http.MethodGet, "/api/chat/messages?owner_id=u_anna", maxToken, "", 200).Body.String(); got != "{\"messages\":[]}\n" {
		t.Fatalf("чат Максима: %s", got)
	}
	history := call(http.MethodGet, "/api/chat/messages?limit=2", anna, "", 200)
	var messages struct {
		Messages []struct {
			ID      string            `json:"id"`
			Actions []json.RawMessage `json:"actions"`
		} `json:"messages"`
	}
	if err := json.Unmarshal(history.Body.Bytes(), &messages); err != nil || len(messages.Messages) != 2 ||
		messages.Messages[0].ID != "msg_anna_003" || messages.Messages[1].ID != "msg_anna_004" ||
		len(messages.Messages[1].Actions) != 1 {
		t.Fatalf("последние сообщения: %s (%v)", history.Body, err)
	}
	call(http.MethodGet, "/api/chat/messages?limit=201", anna, "", 422)

	var users, tasks, storedMessages, actions, migrations int
	err = db.QueryRowContext(ctx, `SELECT (SELECT count(*) FROM core.users), (SELECT count(*) FROM core.tasks),
		(SELECT count(*) FROM core.messages), (SELECT count(*) FROM core.actions), (SELECT count(*) FROM core.schema_migrations)`).
		Scan(&users, &tasks, &storedMessages, &actions, &migrations)
	if err != nil || users != 7 || tasks != 30 || storedMessages != 4 || actions != 2 || migrations != 3 {
		t.Fatalf("количество строк после повторных загрузок: %d/%d/%d/%d/%d (%v)", users, tasks, storedMessages, actions, migrations, err)
	}
}
