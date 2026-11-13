package clients

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"aibuddy/core-api/internal/onboarding"
	"aibuddy/core-api/internal/store"
)

type Agent struct {
	endpoint
}

func NewAgent(baseURL string) *Agent {
	return &Agent{newEndpoint(baseURL, 40*time.Second)}
}

type UserContext struct {
	ID             string     `json:"id"`
	Name           string     `json:"name"`
	Role           string     `json:"role"`
	TeamID         *string    `json:"team_id"`
	TeamName       *string    `json:"team_name"`
	InternshipWeek *int       `json:"internship_week"`
	Mentor         *store.Ref `json:"mentor"`
	Manager        *store.Ref `json:"manager"`
}

type TaskBrief struct {
	ID      string  `json:"id"`
	StageID string  `json:"stage_id"`
	Title   string  `json:"title"`
	Status  string  `json:"status"`
	DueDate *string `json:"due_date"`
}

type OnboardingContext struct {
	Progress  int                   `json:"progress"`
	Tasks     []TaskBrief           `json:"tasks"`
	NextSteps []onboarding.NextStep `json:"next_steps"`
}

type AgentRequest struct {
	RequestID  string              `json:"request_id"`
	Now        time.Time           `json:"now"`
	Timezone   string              `json:"timezone"`
	User       UserContext         `json:"user"`
	Onboarding OnboardingContext   `json:"onboarding"`
	History    []store.HistoryItem `json:"history"`
	State      json.RawMessage     `json:"state"`
	Message    string              `json:"message"`
}

type AgentResponse struct {
	Text        string             `json:"text"`
	Sources     []store.Source     `json:"sources"`
	Drafts      []store.Draft      `json:"proposed_actions"`
	TaskUpdates []store.TaskUpdate `json:"task_updates"`
	Suggestions []string           `json:"suggestions"`
	State       json.RawMessage    `json:"state"`
	Status      string             `json:"status"`
}

var (
	requestIDPattern = regexp.MustCompile(`^req_[a-z0-9_]+$`)
	docIDPattern     = regexp.MustCompile(`^kb_[a-z0-9_]+$`)
	chunkIDPattern   = regexp.MustCompile(`^kb_[a-z0-9_]+#[a-z0-9_-]+$`)
)

func (a *Agent) Chat(ctx context.Context, bearer string, req AgentRequest) (out AgentResponse, err error) {
	started := time.Now()
	defer func() { logCall(ctx, "agent", "chat", started, err) }()
	err = a.request(ctx, http.MethodPost, "/v1/chat", bearer, req.RequestID, "", req, &out)
	if err != nil {
		return AgentResponse{}, err
	}
	if strings.TrimSpace(out.Text) == "" || (out.Status != "ok" && out.Status != "degraded") ||
		out.Sources == nil || out.Suggestions == nil || out.Drafts == nil || out.TaskUpdates == nil ||
		(len(out.State) == 0 || (out.State[0] != '{' && string(out.State) != "null")) {
		return AgentResponse{}, errors.New("ответ агента не соответствует контракту чата")
	}
	for _, draft := range out.Drafts {
		if (draft.Type != "absence_request" && draft.Type != "access_request") ||
			!requestIDPattern.MatchString(draft.ExternalID) || draft.Fields == nil {
			return AgentResponse{}, errors.New("некорректный черновик в ответе агента")
		}
	}
	for _, source := range out.Sources {
		if !docIDPattern.MatchString(source.DocID) || !chunkIDPattern.MatchString(source.ChunkID) {
			return AgentResponse{}, errors.New("некорректный источник в ответе агента")
		}
	}
	return out, nil
}
