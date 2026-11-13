package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/store"
)

// B1, B2, B4: чтение источника, отметка уведомления и повтор сообщения с Idempotency-Key.
func TestPostgresInterfaceAdditions(t *testing.T) {
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
	const owner = "u_b124"
	var ntf int64
	if _, err := db.ExecContext(ctx, `
		INSERT INTO core.users (id, login, password_hash, name, role, team_id, start_date)
		SELECT 'u_b124', 'test_b124', password_hash, 'Тест B', 'intern', team_id, start_date FROM core.users WHERE id = 'u_anna'
	`); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRowContext(ctx, `
		INSERT INTO core.notifications (owner_id, kind, event_key, text) VALUES ($1, 'reminder', 'b2', 'Проверка') RETURNING id
	`, owner).Scan(&ntf); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`
			DELETE FROM core.notifications WHERE owner_id = 'u_b124';
			DELETE FROM core.chat_requests WHERE owner_id = 'u_b124';
			DELETE FROM core.messages WHERE owner_id = 'u_b124';
			DELETE FROM core.chat_state WHERE owner_id = 'u_b124';
			DELETE FROM core.users WHERE id = 'u_b124';
		`); err != nil {
			t.Error(err)
		}
	}()

	var bearer string
	knowledge := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != bearer || r.Header.Get("X-Request-Id") == "" {
			t.Errorf("knowledge-service должен получить JWT и X-Request-Id пользователя: %v", r.Header)
		}
		switch r.URL.Path {
		case "/v1/documents/kb_open":
			WriteJSON(w, 200, map[string]any{"doc_id": "kb_open", "title": "Открытый", "updated_at": "2026-11-01"})
		case "/v1/documents/kb_closed":
			WriteError(w, 403, "forbidden", "секретный заголовок документа")
		case "/v1/documents/kb_down":
			w.WriteHeader(http.StatusInternalServerError)
		default:
			WriteError(w, 404, "not_found", "нет")
		}
	}))
	defer knowledge.Close()

	var agentCalls atomic.Int32
	release := make(chan struct{})
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req clients.AgentRequest
		_ = json.NewDecoder(r.Body).Decode(&req)
		agentCalls.Add(1)
		for _, item := range req.History {
			if item.Text == req.Message {
				t.Errorf("текущее сообщение не должно попасть в историю: %+v", req.History)
			}
		}
		if req.Message == "Долгий вопрос" {
			<-release
		}
		WriteJSON(w, 200, clients.AgentResponse{Text: "Ответ на «" + req.Message + "»", Sources: []store.Source{},
			Suggestions: []string{}, TaskUpdates: []store.TaskUpdate{}, Drafts: []store.Draft{}, State: json.RawMessage(`null`), Status: "ok"})
	}))
	defer agent.Close()

	now := func() time.Time {
		return time.Date(2026, time.November, 13, 10, 0, 0, 0, time.FixedZone("Europe/Moscow", 3*3600))
	}
	handler := NewHandler("0.1.0", store.New(db), "secret-for-b-tests", now, Dependencies{
		Agent: clients.NewAgent(agent.URL), Knowledge: clients.NewKnowledge(knowledge.URL),
	})
	call := func(method, path, token, key, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		if token != "" {
			req.Header.Set("Authorization", token)
		}
		if key != "" {
			req.Header.Set("Idempotency-Key", key)
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
	login := func(name string) string {
		var data struct{ Token string }
		_ = json.Unmarshal([]byte(expect(call("POST", "/api/auth/login", "", "", `{"login":"`+name+`","password":"buddy2026"}`), 200)), &data)
		return "Bearer " + data.Token
	}
	bearer = login("test_b124")
	foreign := login("intern_max")

	// B1: документ через core-api.
	rec := call("GET", "/api/knowledge/documents/kb_open", bearer, "", "")
	if body := expect(rec, 200); !strings.Contains(body, `"title":"Открытый"`) || rec.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("документ: %s %v", body, rec.Header())
	}
	if body := expect(call("GET", "/api/knowledge/documents/kb_closed", bearer, "", ""), 403); strings.Contains(body, "секретный") {
		t.Fatalf("текст отказа knowledge-service не должен уходить клиенту: %s", body)
	}
	expect(call("GET", "/api/knowledge/documents/kb_missing", bearer, "", ""), 404)
	expect(call("GET", "/api/knowledge/documents/kb%2F..%2F..%2Fhealth", bearer, "", ""), 404)
	expect(call("GET", "/api/knowledge/documents/kb_down", bearer, "", ""), 503)
	expect(call("GET", "/api/knowledge/documents/kb_open", "", "", ""), 401)

	// B2: прочтение уведомления.
	path := "/api/notifications/ntf_" + strconv.FormatInt(ntf, 10)
	expect(call("PATCH", path, bearer, "", `{"read":false}`), 422)
	expect(call("PATCH", path, foreign, "", `{"read":true}`), 404)
	expect(call("PATCH", "/api/notifications/ntf_bad", bearer, "", `{"read":true}`), 404)
	for i := 0; i < 2; i++ {
		if body := expect(call("PATCH", path, bearer, "", `{"read":true}`), 200); !strings.Contains(body, `"read":true`) {
			t.Fatal(body)
		}
	}
	if list := expect(call("GET", "/api/notifications", bearer, "", ""), 200); !strings.Contains(list, `"read":true`) {
		t.Fatalf("прочтение должно сохраниться: %s", list)
	}

	// B4: повтор с тем же ключом не зовёт агента и не создаёт второй ход.
	post := func(key, text string) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]string{"text": text})
		return call("POST", "/api/chat/messages", bearer, key, string(body))
	}
	first := expect(post("key-b4-0001", "Что дальше?"), 200)
	if again := expect(post("key-b4-0001", "Что дальше?"), 200); !sameJSON(again, first) {
		t.Fatalf("повтор должен вернуть тот же ответ:\n%s\n%s", first, again)
	}
	expect(post("key-b4-0001", "Другой текст"), 409)
	expect(post("short", "Что дальше?"), 422)
	expect(post("", "Без ключа"), 200)
	if agentCalls.Load() != 2 {
		t.Fatalf("агент вызван %d раз, ожидалось 2", agentCalls.Load())
	}

	// Ответ потерялся: сообщение и ключ сохранены, ответа нет. Повтор продолжает тот же ход.
	if _, err := db.Exec(`
		INSERT INTO core.messages (id, owner_id, role, text, status) VALUES ('msg_b4_lost_u', 'u_b124', 'user', 'Потерянный ответ', 'ok');
		INSERT INTO core.chat_requests (owner_id, idempotency_key, request_id, user_message_id) VALUES ('u_b124', 'key-b4-lost', 'rq_b4lost', 'msg_b4_lost_u');
	`); err != nil {
		t.Fatal(err)
	}
	resumed := expect(post("key-b4-lost", "Потерянный ответ"), 200)
	if !strings.Contains(resumed, `"id":"msg_b4_lost_u"`) || !strings.Contains(resumed, `"id":"msg_b4lost_a"`) {
		t.Fatalf("ход должен продолжиться с исходным сообщением: %s", resumed)
	}
	var userMessages int
	if err := db.QueryRow(`SELECT count(*) FROM core.messages WHERE owner_id = 'u_b124' AND text = 'Потерянный ответ'`).Scan(&userMessages); err != nil || userMessages != 1 {
		t.Fatalf("сообщение не должно дублироваться: %d (%v)", userMessages, err)
	}

	// Пока ход идёт, повтор с тем же ключом получает 429, после — сохранённый ответ.
	var wg sync.WaitGroup
	var slow string
	wg.Add(1)
	go func() {
		defer wg.Done()
		slow = post("key-b4-slow", "Долгий вопрос").Body.String()
	}()
	deadline := time.Now().Add(5 * time.Second)
	for agentCalls.Load() != 4 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	expect(post("key-b4-slow", "Долгий вопрос"), 429)
	close(release)
	wg.Wait()
	if again := expect(post("key-b4-slow", "Долгий вопрос"), 200); !sameJSON(again, slow) {
		t.Fatalf("после завершения повтор возвращает сохранённый ответ:\n%s\n%s", slow, again)
	}
	if agentCalls.Load() != 4 {
		t.Fatalf("агент вызван %d раз, ожидалось 4", agentCalls.Load())
	}
}

// sameJSON сравнивает данные, а не байты: PostgreSQL хранит jsonb со своим порядком ключей.
func sameJSON(a, b string) bool {
	var x, y any
	return json.Unmarshal([]byte(a), &x) == nil && json.Unmarshal([]byte(b), &y) == nil && reflect.DeepEqual(x, y)
}
