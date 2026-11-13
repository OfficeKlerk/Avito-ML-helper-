package httpapi

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/store"
)

const statusOwner = "u_c7c9"

func TestPostgresStatusRemindersAndTrace(t *testing.T) {
	url := os.Getenv("CORE_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("CORE_TEST_DATABASE_URL не задан")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	if err := store.Initialize(ctx, db, "../../../data/seed"); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ExecContext(ctx, `
		INSERT INTO core.users (id, login, password_hash, name, role, team_id, start_date)
		SELECT 'u_c7c9', 'test_status', password_hash, 'Тест C7–C9', 'intern', team_id, start_date
		FROM core.users WHERE id = 'u_anna';
		INSERT INTO core.tasks (owner_id, id, stage_id, title, description, status, due_date, position, related_action_type)
		VALUES ('u_c7c9', 't_request_accesses', 'st_week1', 'Инструменты', '', 'todo', NULL, 1, 'access_request'),
		       ('u_c7c9', 't_team_space', 'st_week1', 'Пространство', '', 'todo', NULL, 2, 'access_request'),
		       ('u_c7c9', 't_overdue', 'st_week1', 'Просроченная задача', '', 'blocked', '2026-11-10', 3, NULL),
		       ('u_c7c9', 't_today', 'st_week1', 'Задача на сегодня', '', 'todo', '2026-11-11', 4, NULL),
		       ('u_c7c9', 't_done', 'st_week1', 'Выполненная задача', '', 'done', '2026-11-10', 5, NULL);
		INSERT INTO core.actions (id, owner_id, type, status, title, external_id, created_at)
		VALUES ('act_status_jira', 'u_c7c9', 'access_request', 'draft', 'Доступ Jira', 'req_status_jira', '2026-11-11T07:00:00Z'),
		       ('act_status_gitlab', 'u_c7c9', 'access_request', 'draft', 'Доступ GitLab', 'req_status_gitlab', '2026-11-11T07:00:01Z'),
		       ('act_status_space', 'u_c7c9', 'access_request', 'draft', 'Доступ к пространству', 'req_status_space', '2026-11-11T07:00:02Z');
	`); err != nil {
		t.Fatal(err)
	}
	defer func() {
		if _, err := db.Exec(`
			DELETE FROM core.tasks WHERE owner_id = 'u_c7c9';
			DELETE FROM core.actions WHERE owner_id = 'u_c7c9';
			DELETE FROM core.users WHERE id = 'u_c7c9';
		`); err != nil {
			t.Error(err)
		}
	}()
	const secret = "jwt-secret-must-not-appear-in-logs"
	const idempotencyKey = "key-must-not-appear-in-logs"
	const foreignTrace = "incoming-secret-must-not-appear-in-logs"
	const upstreamBody = "upstream-body-must-not-appear-in-logs"
	const loginPassword = "buddy2026"
	now := time.Date(2026, time.November, 11, 0, 5, 0, 0, time.FixedZone("Europe/Moscow", 3*3600))
	var mu sync.Mutex
	type upstreamAction struct {
		system    string
		status    string
		fulfilled bool
	}
	actions := map[string]upstreamAction{
		"req_status_jira":   {system: "jira", status: "draft"},
		"req_status_gitlab": {system: "gitlab", status: "draft"},
		"req_status_space":  {system: "team_space", status: "draft"},
	}
	corpCalls := 0
	updated := now
	failure := false
	setRemote := func(id, status string, fulfilled bool) {
		mu.Lock()
		defer mu.Unlock()
		item := actions[id]
		item.status, item.fulfilled = status, fulfilled
		actions[id] = item
		updated = updated.Add(time.Minute)
	}
	corp := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		corpCalls++
		id, op, _ := strings.Cut(strings.TrimPrefix(r.URL.Path, "/api/v1/requests/"), "/")
		item, ok := actions[id]
		if !ok || r.Header.Get("X-Request-Id") == "" || !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
			t.Errorf("некорректный запрос corp-mock: %s", r.URL.Path)
			w.WriteHeader(404)
			return
		}
		if failure {
			w.WriteHeader(503)
			_, _ = io.WriteString(w, upstreamBody)
			return
		}
		if op == "submit" {
			item.status = "submitted"
			actions[id] = item
			updated = updated.Add(time.Minute)
		}
		value := clients.CorpRequest{ID: id, Type: "access_request", OwnerID: statusOwner,
			Status: item.status, UpdatedAt: updated}
		value.Payload.System = item.system
		if item.fulfilled {
			instant := updated
			value.FulfilledAt = &instant
		}
		WriteJSON(w, 200, value)
	}))
	defer corp.Close()
	data := store.New(db)
	var logs bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	handler := NewHandler("0.1.0", data, secret, func() time.Time { return now },
		Dependencies{Corp: clients.NewCorp(corp.URL), Logger: logger})

	call := func(method, path, token, key, body string, want int) *httptest.ResponseRecorder {
		t.Helper()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		if key != "" {
			req.Header.Set("Idempotency-Key", key)
		}
		req.Header.Set("X-Request-Id", foreignTrace)
		rec := httptest.NewRecorder()
		handler.ServeHTTP(rec, req)
		if rec.Code != want || rec.Header().Get("X-Request-Id") == "" || rec.Header().Get("X-Request-Id") == foreignTrace {
			t.Fatalf("%s %s: ожидался %d и новый request_id, получили %d %s", method, path, want, rec.Code, rec.Body)
		}
		return rec
	}
	login := func(user string) string {
		t.Helper()
		rec := call("POST", "/api/auth/login", "", "", `{"login":"`+user+`","password":"`+loginPassword+`"}`, 200)
		var response struct{ Token string }
		if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil || response.Token == "" {
			t.Fatal("токен не получен")
		}
		return response.Token
	}
	owner, foreign := login("test_status"), login("intern_max")

	checkTask := func(taskID, want string) {
		t.Helper()
		rec := call("GET", "/api/onboarding", owner, "", "", 200)
		var state struct {
			Stages []struct{ Tasks []struct{ ID, Status string } }
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &state); err != nil {
			t.Fatal(err)
		}
		for _, stage := range state.Stages {
			for _, task := range stage.Tasks {
				if task.ID == taskID && task.Status == want {
					return
				}
			}
		}
		t.Fatalf("ожидалась задача %s в статусе %s: %s", taskID, want, rec.Body)
	}
	const jira = "/api/actions/act_status_jira"
	const gitlab = "/api/actions/act_status_gitlab"
	const space = "/api/actions/act_status_space"
	call("GET", "/api/notifications", "", "", "", 401)
	first := call("POST", jira+"/confirm", owner, idempotencyKey, "", 200)
	call("POST", gitlab+"/confirm", owner, "confirm-gitlab", "", 200)
	call("POST", space+"/confirm", owner, "confirm-space", "", 200)
	checkTask("t_request_accesses", "in_progress")
	checkTask("t_team_space", "in_progress")
	call("PATCH", "/api/onboarding/tasks/t_request_accesses", owner, "", `{"status":"done"}`, 422)
	mu.Lock()
	before := corpCalls
	mu.Unlock()
	call("GET", jira, foreign, "", "", 404)
	mu.Lock()
	after := corpCalls
	mu.Unlock()
	if before != after {
		t.Fatal("чужая карточка вызвала обращение к corp-mock")
	}

	// Сбой внешнего сервиса не скрывает сохранённые данные и диагностируется без тела ответа.
	mu.Lock()
	failure = true
	mu.Unlock()
	failedRead := call("GET", space, owner, "", "", 200)
	mu.Lock()
	failure = false
	mu.Unlock()
	if !strings.Contains(failedRead.Body.String(), `"status":"submitted"`) {
		t.Fatal(failedRead.Body)
	}

	setRemote("req_status_jira", "approved", false)
	rec := call("GET", jira, owner, "", "", 200)
	if !strings.Contains(rec.Body.String(), `"status":"approved"`) {
		t.Fatal(rec.Body)
	}
	checkTask("t_request_accesses", "in_progress")
	setRemote("req_status_jira", "approved", true)
	checkTask("t_request_accesses", "in_progress")
	setRemote("req_status_gitlab", "approved", true)
	setRemote("req_status_space", "cancelled", false)
	checkTask("t_request_accesses", "done")
	checkTask("t_team_space", "blocked")
	replay := call("POST", jira+"/confirm", owner, idempotencyKey, "", 200)
	if first.Body.String() != replay.Body.String() {
		t.Fatal("синхронизация изменила сохранённый ответ подтверждения")
	}

	var wg sync.WaitGroup
	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := data.CreateOverdueReminders(ctx, now); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if _, err := data.CreateOverdueReminders(ctx, now); err != nil {
		t.Fatal(err)
	}
	list := call("GET", "/api/notifications", owner, "", "", 200)
	var notices struct {
		Items []struct {
			ID, Kind, Text string
			TaskID         *string `json:"task_id"`
			ActionID       *string `json:"action_id"`
		}
	}
	if err := json.Unmarshal(list.Body.Bytes(), &notices); err != nil {
		t.Fatal(err)
	}
	reminders, statusEvents := 0, 0
	ids := make(map[string]bool)
	for _, item := range notices.Items {
		if ids[item.ID] || !strings.HasPrefix(item.ID, "ntf_") {
			t.Fatalf("неверный ID уведомления: %s", item.ID)
		}
		ids[item.ID] = true
		if item.Kind == "reminder" {
			reminders++
			if item.TaskID == nil || *item.TaskID != "t_overdue" || item.ActionID != nil {
				t.Fatalf("неверное напоминание: %+v", item)
			}
		} else {
			statusEvents++
			if item.ActionID == nil || item.TaskID == nil {
				t.Fatalf("нет связи уведомления с задачей и действием: %+v", item)
			}
		}
	}
	if reminders != 1 || statusEvents != 7 {
		t.Fatalf("ожидались 1 напоминание и 7 изменений: %s", list.Body)
	}
	foreignNotices := call("GET", "/api/notifications", foreign, "", "", 200)
	if strings.Contains(foreignNotices.Body.String(), "act_status_") || strings.Contains(foreignNotices.Body.String(), "t_overdue") {
		t.Fatal("в ленту попали чужие уведомления")
	}

	for _, value := range []string{secret, owner, foreign, loginPassword, idempotencyKey, foreignTrace, upstreamBody} {
		if strings.Contains(logs.String(), value) {
			t.Fatal("конфиденциальное значение попало в логи")
		}
	}
	type entry struct {
		ID        string `json:"request_id"`
		Event     string `json:"msg"`
		ErrorCode string `json:"error_code"`
		Duration  *int64 `json:"duration_ms"`
	}
	firstID := first.Header().Get("X-Request-Id")
	failedID := failedRead.Header().Get("X-Request-Id")
	found := map[string]bool{}
	for _, line := range strings.Split(strings.TrimSpace(logs.String()), "\n") {
		var item entry
		if err := json.Unmarshal([]byte(line), &item); err != nil {
			t.Fatal(err)
		}
		if item.ID == firstID && (item.Event == "status_changed" || item.Duration != nil) {
			found[item.Event] = true
		}
		if item.ID == failedID && item.Event == "upstream_call" && item.ErrorCode == "upstream_http" && item.Duration != nil {
			found["upstream_error"] = true
		}
	}
	for _, event := range []string{"http_request", "upstream_call", "status_changed", "upstream_error"} {
		if !found[event] {
			t.Fatalf("нет события %s с нужным request_id", event)
		}
	}
}
