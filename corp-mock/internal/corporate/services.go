package corporate

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
	"unicode/utf8"
)

type AbsenceRule struct {
	Kind          string   `json:"kind"`
	Title         string   `json:"title"`
	MaxDays       int      `json:"max_days"`
	MinNoticeDays int      `json:"min_notice_days"`
	ApproverRole  string   `json:"approver_role"`
	Steps         []string `json:"steps"`
}

type AbsenceRules struct {
	Rules      []AbsenceRule `json:"rules"`
	Disclaimer string        `json:"disclaimer"`
}

type AccessSystem struct {
	System string `json:"system"`
	Title  string `json:"title"`
}

type AccessCatalog struct {
	Systems []AccessSystem               `json:"systems"`
	ByTeam  map[string][]string          `json:"required_by_team"`
	ByUser  map[string]map[string]string `json:"user_accesses"`
}

type AccessItem struct {
	AccessSystem
	Required  bool    `json:"required"`
	Status    string  `json:"status"`
	RequestID *string `json:"request_id"`
}

func LoadServices(dir string) (AbsenceRules, AccessCatalog, error) {
	var rules AbsenceRules
	var catalog AccessCatalog
	for _, file := range []struct {
		name string
		dest any
	}{{"absence_rules.json", &rules}, {"accesses.json", &catalog}} {
		data, err := os.ReadFile(filepath.Join(dir, file.name))
		if err != nil {
			return rules, catalog, err
		}
		if err := json.Unmarshal(data, file.dest); err != nil {
			return rules, catalog, fmt.Errorf("%s: %w", file.name, err)
		}
	}
	return rules, catalog, nil
}

func (r AbsenceRules) ValidateDates(payload AbsencePayload, now time.Time) (AbsenceRule, error) {
	var rule AbsenceRule
	for _, item := range r.Rules {
		if item.Kind == payload.Kind {
			rule = item
			break
		}
	}
	if rule.Kind == "" {
		return rule, Deny(ErrValidation, "Выбери отгул или отпуск.")
	}
	from, fromErr := time.Parse(time.DateOnly, payload.DateFrom)
	to, toErr := time.Parse(time.DateOnly, payload.DateTo)
	if fromErr != nil || toErr != nil || to.Before(from) {
		return rule, Deny(ErrValidation, "Укажи корректный период в формате ГГГГ-ММ-ДД.")
	}
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	if from.Before(today) {
		return rule, Deny(ErrValidation, "Дата начала уже прошла.")
	}
	if from.Before(today.AddDate(0, 0, rule.MinNoticeDays)) {
		return rule, Deny(ErrValidation, fmt.Sprintf("Заявку нужно подать не менее чем за %d дн. до начала.", rule.MinNoticeDays))
	}
	if !to.Before(from.AddDate(0, 0, rule.MaxDays)) {
		return rule, Deny(ErrValidation, fmt.Sprintf("Выбери период не длиннее %d дн.", rule.MaxDays))
	}
	if payload.Comment != nil && (utf8.RuneCountInString(*payload.Comment) > 500 || strings.ContainsRune(*payload.Comment, 0)) {
		return rule, Deny(ErrValidation, "Комментарий должен содержать до 500 символов.")
	}
	return rule, nil
}

func (c AccessCatalog) Required(user User, system string) bool {
	return user.TeamID != nil && slices.Contains(c.ByTeam[*user.TeamID], system)
}

func (c AccessCatalog) System(system string) (AccessSystem, bool) {
	for _, item := range c.Systems {
		if item.System == system {
			return item, true
		}
	}
	return AccessSystem{}, false
}

func (c AccessCatalog) SeedStatus(user User, system string) string {
	if status := c.ByUser[user.ID][system]; status != "" {
		return status
	}
	return "missing"
}

func (d *Directory) Approver(user User, role string) (*Ref, error) {
	if user.TeamID != nil && user.ManagerID != nil {
		manager, ok := d.User(*user.ManagerID)
		if ok && manager.ID != user.ID && manager.Role == role && sameTeam(user.TeamID, manager.TeamID) {
			return &manager.Ref, nil
		}
	}
	return nil, Deny(ErrForbidden, "Для заявки нужен назначенный руководитель команды.")
}

type PolicyError struct {
	Kind error
	Text string
}

func (e *PolicyError) Error() string { return e.Text }
func (e *PolicyError) Unwrap() error { return e.Kind }

func Deny(kind error, message string) error { return &PolicyError{Kind: kind, Text: message} }
