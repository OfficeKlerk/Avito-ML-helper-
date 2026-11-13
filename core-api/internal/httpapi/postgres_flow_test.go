package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/store"
)

const flowUser = "u_c4c6"
const flowDraft = "req_c4c6_dayoff"
const flowRetry = "req_c4c6_access"
const flowCancel = "req_c4c6_cancel"

func TestPostgresChatAndActionRecovery(t *testing.T) {
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
	if _, err := db.ExecContext(ctx, `
		INSERT INTO core.users (id, login, password_hash, name, role, team_id, start_date)
		SELECT 'u_c4c6', 'test_flow', password_hash, 'Тест C4–C6', 'intern', team_id, start_date
		FROM core.users WHERE id = 'u_anna';
		INSERT INTO core.tasks (owner_id, id, stage_id, title, description, position, related_action_type)
		VALUES ('u_c4c6', 't_flow', 'st_week1', 'Обычная задача', '', 1, NULL),
		       ('u_c4c6', 't_flow_access', 'st_week1', 'Получить доступ', '', 2, 'access_request');
	`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`
			DELETE FROM core.messages WHERE owner_id = 'u_c4c6';
			DELETE FROM core.tasks WHERE owner_id = 'u_c4c6';
			DELETE FROM core.actions WHERE owner_id = 'u_c4c6';
			DELETE FROM core.chat_state WHERE owner_id = 'u_c4c6';
			DELETE FROM core.users WHERE id = 'u_c4c6';
		`); err != nil {
			t.Error(err)
		}
	}()

	var agentMu sync.Mutex
	var bearer string
	var requestIDs []string
	agent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req clients.AgentRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Error(err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		agentMu.Lock()
		defer agentMu.Unlock()
		if req.RequestID != r.Header.Get("X-Request-Id") || r.Header.Get("Authorization") != bearer ||
			req.User.ID != flowUser || req.User.TeamID == nil || *req.User.TeamID != "team_delivery" ||
			req.Timezone != "Europe/Moscow" || len(req.Onboarding.Tasks) != 2 {
			t.Errorf("контекст агента: %+v", req)
		}
		if slices.Contains(requestIDs, req.RequestID) {
			t.Error("повторяющийся идентификатор запроса агента")
		}
		requestIDs = append(requestIDs, req.RequestID)
		var committed bool
		err := db.QueryRow(`SELECT EXISTS (SELECT 1 FROM core.messages WHERE owner_id=$1 AND role='user' AND text=$2)`,
			flowUser, req.Message).Scan(&committed)
		if err != nil || !committed {
			t.Errorf("сообщение должно быть сохранено до вызова агента: %v", err)
		}
		out := clients.AgentResponse{Text: "Какой день?", Sources: []store.Source{},
			Suggestions: []string{}, TaskUpdates: []store.TaskUpdate{}, Drafts: []store.Draft{}, Status: "ok"}
		switch req.Message {
		case "Хочу отгул":
			if len(req.History) != 0 || string(req.State) != "null" {
				t.Errorf("чужая история или состояние: %v, %s", req.History, req.State)
			}
			out.State = json.RawMessage(`{"pending":"absence"}`)
		case "Пока без ответа":
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		case "В пятницу":
			var state map[string]string
			_ = json.Unmarshal(req.State, &state)
			if state["pending"] != "absence" || len(req.History) != 4 || req.History[0].Text != "Хочу отгул" ||
				req.History[1].Text != "Какой день?" || req.History[2].Text != "Пока без ответа" {
				t.Errorf("история или состояние: %+v %s", req.History, req.State)
			}
			out.Text = "Подготовлены черновики."
			out.State = json.RawMessage(`null`)
			out.Drafts = []store.Draft{
				{ExternalID: flowDraft, Title: "Отгул", Type: "absence_request", Fields: map[string]string{}},
				{ExternalID: flowRetry, Title: "Доступ", Type: "access_request", Fields: map[string]string{}},
				{ExternalID: flowCancel, Title: "Отгул", Type: "absence_request", Fields: map[string]string{}},
				{ExternalID: flowDraft, Title: "Повтор", Type: "absence_request", Fields: map[string]string{}},
			}
			out.TaskUpdates = []store.TaskUpdate{{TaskID: "t_flow", Status: "done"},
				{TaskID: "t_flow_access", Status: "done"}, {TaskID: "t_join_channels", Status: "done"}}
		default:
			t.Errorf("неожиданное сообщение: %s", req.Message)
			w.WriteHeader(http.StatusBadRequest)
			return
		}
		WriteJSON(w, http.StatusOK, out)
	}))
	defer agent.Close()
	corp := newFlowCorp(t)
	defer corp.Close()
	deps := Dependencies{Agent: clients.NewAgent(agent.URL), Corp: clients.NewCorp(corp.URL)}
	loc := time.FixedZone("Europe/Moscow", 3*3600)
	now := func() time.Time { return time.Date(2026, time.November, 11, 10, 0, 0, 0, loc) }
	const secret = "secret-for-flow-test"
	newHandler := func() http.Handler { return NewHandler("0.1.0", store.New(db), secret, now, deps) }
	handler := newHandler()

	call := func(handler http.Handler, method, path, token, key, body string) *httptest.ResponseRecorder {
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
		rec := call(handler, http.MethodPost, "/api/auth/login", "", "", `{"login":"`+name+`","password":"buddy2026"}`)
		expect(rec, 200)
		var data struct{ Token string }
		if err := json.Unmarshal(rec.Body.Bytes(), &data); err != nil {
			t.Fatal(err)
		}
		return "Bearer " + data.Token
	}
	agentMu.Lock()
	bearer = login("test_flow")
	agentMu.Unlock()
	foreign := login("intern_max")
	post := func(text string) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]string{"text": text})
		return call(handler, http.MethodPost, "/api/chat/messages", bearer, "", string(body))
	}
	expect(post(strings.Repeat("я", 4001)), 422)
	if got := expect(post("Хочу отгул"), 200); !strings.Contains(got, "Какой день?") {
		t.Fatal(got)
	}
	if got := expect(post("Пока без ответа"), 200); !strings.Contains(got, `"status":"error"`) {
		t.Fatal(got)
	}
	rec := post("В пятницу")
	expect(rec, 200)
	var exchange struct {
		Assistant store.Message `json:"assistant_message"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &exchange); err != nil || len(exchange.Assistant.Actions) != 3 {
		t.Fatalf("ответ с черновиками: %s (%v)", rec.Body, err)
	}
	actionPaths := make([]string, 0, 3)
	for _, raw := range exchange.Assistant.Actions {
		var action struct{ ID, Status string }
		if err := json.Unmarshal(raw, &action); err != nil || action.Status != "draft" {
			t.Fatalf("ожидался черновик: %s (%v)", raw, err)
		}
		actionPaths = append(actionPaths, "/api/actions/"+action.ID)
	}
	plan := expect(call(handler, http.MethodGet, "/api/onboarding", bearer, "", ""), 200)
	if !strings.Contains(plan, `"progress":50`) {
		t.Fatalf("должна быть закрыта только обычная задача: %s", plan)
	}
	var stateExists bool
	if err := db.QueryRow(`SELECT EXISTS(SELECT 1 FROM core.chat_state WHERE owner_id=$1)`, flowUser).Scan(&stateExists); err != nil || stateExists {
		t.Fatalf("агент завершил диалог, состояние должно быть очищено: %v", err)
	}

	first, retry, cancelPath := actionPaths[0], actionPaths[1], actionPaths[2]
	const key = "confirmation-01"
	expect(call(handler, http.MethodPost, first+"/confirm", foreign, key, ""), 404)
	expect(call(handler, http.MethodPost, first+"/cancel", foreign, "", ""), 404)
	expect(call(handler, http.MethodPost, first+"/confirm", bearer, "short", ""), 422)
	expect(call(handler, http.MethodPost, first+"/confirm", bearer, key, ""), 503)
	if got := expect(call(handler, http.MethodGet, first, bearer, "", ""), 200); !strings.Contains(got, `"status":"draft"`) {
		t.Fatal(got)
	}
	// Новый обработчик симулирует повтор после перезапуска core-api.
	fresh := newHandler()
	result := expect(call(fresh, http.MethodPost, first+"/confirm", bearer, key, ""), 200)
	if !strings.Contains(result, `"status":"submitted"`) || !strings.Contains(result, "ABS-TEST-123") {
		t.Fatal(result)
	}
	expect(call(fresh, http.MethodPost, first+"/confirm", bearer, "another-key", ""), 409)
	if got := expect(call(fresh, http.MethodPost, first+"/cancel", bearer, "", ""), 200); !strings.Contains(got, `"status":"cancelled"`) {
		t.Fatal(got)
	}
	if replay := expect(call(fresh, http.MethodPost, first+"/confirm", bearer, key, ""), 200); result != replay {
		t.Fatalf("повтор должен вернуть сохранённый ответ: %s != %s", result, replay)
	}

	// Ошибка до исполнения: после проверки статуса нужно отправить ещё раз с тем же ключом в corp-mock.
	expect(call(handler, http.MethodPost, retry+"/confirm", bearer, key, ""), 503)
	var concurrent sync.WaitGroup
	responses := make(chan *httptest.ResponseRecorder, 2)
	for i := 0; i < 2; i++ {
		concurrent.Add(1)
		go func() {
			defer concurrent.Done()
			responses <- call(newHandler(), http.MethodPost, retry+"/confirm", bearer, "confirmation-02", "")
		}()
	}
	concurrent.Wait()
	if one, two := expect(<-responses, 200), expect(<-responses, 200); one != two {
		t.Fatalf("параллельные повторы вернули разные ответы: %s != %s", one, two)
	}
	expect(call(handler, http.MethodPost, cancelPath+"/cancel", bearer, "", ""), 200)
	expect(call(handler, http.MethodPost, cancelPath+"/confirm", bearer, key, ""), 409)
	corp.mu.Lock()
	defer corp.mu.Unlock()
	if got := corp.submits[flowDraft]; len(got) != 1 || got[0] == "" {
		t.Fatalf("потерянный ответ вызвал лишнюю отправку: %v", got)
	}
	if got := corp.submits[flowRetry]; len(got) != 2 || got[0] == "" || got[0] != got[1] {
		t.Fatalf("ключ в corp-mock должен совпадать при повторе: %v", got)
	}
	if got := corp.submits[flowCancel]; len(got) != 0 {
		t.Fatalf("отменённая заявка не должна отправляться: %v", got)
	}
}

type flowCorp struct {
	*httptest.Server
	mu      sync.Mutex
	submits map[string][]string
}

func newFlowCorp(t *testing.T) *flowCorp {
	t.Helper()
	corp := &flowCorp{submits: map[string][]string{}}
	statuses := map[string]string{flowDraft: "draft", flowRetry: "draft", flowCancel: "draft"}
	failedRead := false
	corp.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		corp.mu.Lock()
		defer corp.mu.Unlock()
		id, op, _ := strings.Cut(strings.TrimPrefix(r.URL.Path, "/api/v1/requests/"), "/")
		status, found := statuses[id]
		if !found || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") || r.Header.Get("X-Request-Id") == "" {
			t.Errorf("некорректный запрос corp-mock: %s %s", r.Method, r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
			return
		}
		switch op {
		case "":
			if id == flowDraft && failedRead {
				failedRead = false
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
		case "submit":
			corp.submits[id] = append(corp.submits[id], r.Header.Get("Idempotency-Key"))
			first := len(corp.submits[id]) == 1
			if id == flowRetry && first {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			status = "submitted"
			statuses[id] = status
			if id == flowDraft && first {
				failedRead = true
				conn, _, err := w.(http.Hijacker).Hijack()
				if err != nil {
					t.Error(err)
					w.WriteHeader(http.StatusServiceUnavailable)
					return
				}
				_ = conn.Close()
				return
			}
		case "cancel":
			status = "cancelled"
			statuses[id] = status
		default:
			t.Errorf("неизвестная операция corp-mock: %s", op)
		}
		kind := "absence_request"
		if id == flowRetry {
			kind = "access_request"
		}
		ref := "ABS-TEST-123"
		WriteJSON(w, http.StatusOK, clients.CorpRequest{
			ID: id, Type: kind, OwnerID: flowUser, Status: status, ExternalRef: &ref,
			UpdatedAt: time.Now(), Approver: &store.Ref{ID: "u_olga", Name: "Ольга Крылова"},
		})
	}))
	return corp
}
