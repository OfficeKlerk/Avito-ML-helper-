package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/store"
)

// B3: клиентские события с проверкой и дедупликацией, серверные — по сохранённым ответу и карточкам.
func TestPostgresProductEvents(t *testing.T) {
	url := os.Getenv("CORE_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("CORE_TEST_DATABASE_URL не задан")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	if err := store.Initialize(ctx, db, "../../../data/seed"); err != nil {
		t.Fatal(err)
	}
	const owner = "u_b3"
	if _, err := db.ExecContext(ctx, `
		INSERT INTO core.users (id, login, password_hash, name, role, team_id, start_date)
		SELECT 'u_b3', 'test_b3', password_hash, 'Тест B3', 'intern', team_id, start_date FROM core.users WHERE id = 'u_anna'
	`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`
			DELETE FROM core.product_events WHERE owner_id = 'u_b3';
			DELETE FROM core.notifications WHERE owner_id = 'u_b3';
			DELETE FROM core.messages WHERE owner_id = 'u_b3';
			DELETE FROM core.actions WHERE owner_id = 'u_b3';
			DELETE FROM core.chat_state WHERE owner_id = 'u_b3';
			DELETE FROM core.users WHERE id = 'u_b3';
		`); err != nil {
			t.Error(err)
		}
	}()

	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req clients.AgentRequest
		_ = json.NewDecoder(r.Body).Decode(&req)
		drafts := []store.Draft{}
		if strings.HasPrefix(req.Message, "Отгул") {
			id := "req_b3_" + strings.TrimPrefix(req.Message, "Отгул ")
			drafts = append(drafts, store.Draft{Type: "absence_request", Title: "Отгул", ExternalID: id, Fields: map[string]string{}})
		}
		WriteJSON(w, 200, clients.AgentResponse{Text: "Готово", Sources: []store.Source{}, Suggestions: []string{},
			TaskUpdates: []store.TaskUpdate{}, Drafts: drafts, State: json.RawMessage(`null`), Status: "ok"})
	}))
	defer agent.Close()

	var corpMu sync.Mutex
	corpStatus := map[string]string{}
	corp := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		corpMu.Lock()
		defer corpMu.Unlock()
		id, op, _ := strings.Cut(strings.TrimPrefix(r.URL.Path, "/api/v1/requests/"), "/")
		switch op {
		case "submit":
			corpStatus[id] = "submitted"
		case "cancel":
			corpStatus[id] = "cancelled"
		}
		if corpStatus[id] == "" {
			corpStatus[id] = "draft"
		}
		WriteJSON(w, 200, clients.CorpRequest{ID: id, Type: "absence_request", OwnerID: owner, Status: corpStatus[id], UpdatedAt: time.Now()})
	}))
	defer corp.Close()

	now := func() time.Time {
		return time.Date(2026, time.November, 13, 10, 0, 0, 0, time.FixedZone("Europe/Moscow", 3*3600))
	}
	handler := NewHandler("0.1.0", store.New(db), "secret-for-b3", now, Dependencies{
		Agent: clients.NewAgent(agent.URL), Corp: clients.NewCorp(corp.URL),
	})
	call := func(method, path, token string, headers map[string]string, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", token)
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		return rec
	}
	expect := func(rec *httptest.ResponseRecorder, status int) string {
		t.Helper()
		if rec.Code != status {
			t.Fatalf("HTTP %d, ожидался %d: %s", rec.Code, status, rec.Body)
		}
		return rec.Body.String()
	}
	var auth struct{ Token string }
	_ = json.Unmarshal([]byte(expect(call("POST", "/api/auth/login", "", nil, `{"login":"test_b3","password":"buddy2026"}`), 200)), &auth)
	token := "Bearer " + auth.Token

	const session, scenario = "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"
	event := func(id, kind string) string {
		return `{"event_id":"` + id + `","session_id":"` + session + `","scenario_id":"` + scenario + `","scenario":"absence","event":"` + kind + `"}`
	}

	// Клиентские события: проверка схемы и дедупликация.
	first := expect(call("POST", "/api/metrics/events", token, nil, event("11111111-1111-4111-8111-111111111111", "scenario_started")), 200)
	if again := expect(call("POST", "/api/metrics/events", token, nil, event("11111111-1111-4111-8111-111111111111", "scenario_started")), 200); again != first {
		t.Fatalf("повтор должен вернуть прежнее время:\n%s\n%s", first, again)
	}
	expect(call("POST", "/api/metrics/events", token, nil, event("11111111-1111-4111-8111-111111111111", "source_opened")), 409)

	// Двойной клик: одинаковые события одновременно — все получают 200 и одно время.
	var parallel sync.WaitGroup
	answers := make(chan [2]string, 40)
	for i := 0; i < 40; i++ {
		parallel.Add(1)
		go func(n int) {
			defer parallel.Done()
			id := "6666666" + strconv.Itoa(n%5) + "-6666-4666-8666-666666666666"
			rec := call("POST", "/api/metrics/events", token, nil, event(id, "source_opened"))
			answers <- [2]string{id, strconv.Itoa(rec.Code) + " " + rec.Body.String()}
		}(i)
	}
	parallel.Wait()
	close(answers)
	byID := map[string]string{}
	for answer := range answers {
		if !strings.HasPrefix(answer[1], "200 ") || (byID[answer[0]] != "" && byID[answer[0]] != answer[1]) {
			t.Fatalf("параллельный повтор: %q и %q", byID[answer[0]], answer[1])
		}
		byID[answer[0]] = answer[1]
	}
	expect(call("POST", "/api/metrics/events", token, nil, event("44444444-4444-4444-8444-444444444444", "action_succeeded")), 422)
	expect(call("POST", "/api/metrics/events", token, nil, event("not-a-uuid", "source_opened")), 422)
	expect(call("POST", "/api/metrics/events", token, nil, `{"event_id":"55555555-5555-4555-8555-555555555555","session_id":"`+session+`","scenario_id":"`+scenario+`","scenario":"absence","event":"source_opened","text":"Хочу отгул"}`), 422)

	// Ход с привязкой к сценарию: ответ помощника и созданные карточки получают его идентификаторы.
	product := map[string]string{"X-Product-Session-Id": session, "X-Product-Scenario-Id": scenario}
	expect(call("POST", "/api/chat/messages", token, map[string]string{"X-Product-Session-Id": session}, `{"text":"Отгул a"}`), 422)
	turn := expect(call("POST", "/api/chat/messages", token, product, `{"text":"Отгул a"}`), 200)
	var exchange struct {
		Assistant store.Message `json:"assistant_message"`
	}
	_ = json.Unmarshal([]byte(turn), &exchange)
	var card struct{ ID string }
	if len(exchange.Assistant.Actions) != 1 || json.Unmarshal(exchange.Assistant.Actions[0], &card) != nil {
		t.Fatalf("ожидалась карточка: %s", turn)
	}
	expect(call("POST", "/api/actions/"+card.ID+"/confirm", token, map[string]string{"Idempotency-Key": "confirm-b3-0001"}, ""), 200)
	corpMu.Lock()
	corpStatus["req_b3_a"] = "approved"
	corpMu.Unlock()
	expect(call("GET", "/api/actions", token, nil, ""), 200) // синхронизация узнаёт итог

	second := expect(call("POST", "/api/chat/messages", token, product, `{"text":"Отгул b"}`), 200)
	_ = json.Unmarshal([]byte(second), &exchange)
	_ = json.Unmarshal(exchange.Assistant.Actions[0], &card)
	expect(call("POST", "/api/actions/"+card.ID+"/cancel", token, nil, ""), 200)

	expect(call("POST", "/api/chat/messages", token, nil, `{"text":"Без сценария"}`), 200)

	rows, err := db.Query(`
		SELECT event, source, COALESCE(scenario, ''), COALESCE(status, ''), session_id::text
		FROM core.product_events WHERE owner_id = $1 ORDER BY recorded_at`, owner)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var got []string
	for rows.Next() {
		var kind, source, name, status, sessionID string
		if err := rows.Scan(&kind, &source, &name, &status, &sessionID); err != nil {
			t.Fatal(err)
		}
		if sessionID != session {
			t.Errorf("событие без сессии сценария: %s", kind)
		}
		got = append(got, strings.Join([]string{kind, source, name, status}, "/"))
	}
	want := []string{
		"scenario_started/client/absence/",
		"source_opened/client/absence/",
		"source_opened/client/absence/",
		"source_opened/client/absence/",
		"source_opened/client/absence/",
		"source_opened/client/absence/",
		"assistant_answered/server/absence/ok",
		"action_confirmed/server/absence/submitted",
		"action_succeeded/server/absence/approved",
		"assistant_answered/server/absence/ok",
		"action_failed/server/absence/cancelled",
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("события:\n%s\nожидались:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}
