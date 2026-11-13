package corporate

import (
	"encoding/json"
	"errors"
	"testing"
	"time"
)

func TestTransitions(t *testing.T) {
	now := time.Now()
	valid := map[Status]map[Operation]Status{
		Draft:     {Submit: Submitted, Cancel: Cancelled},
		Submitted: {Approve: Approved, Reject: Rejected, Cancel: Cancelled},
	}
	for _, state := range []Status{Draft, Submitted, Approved, Rejected, Cancelled} {
		for _, op := range []Operation{Submit, Approve, Reject, Cancel} {
			r := Request{Status: state, UpdatedAt: now.Add(-time.Second)}
			out, err := r.Transition(op, now)
			want, allowed := valid[state][op]
			if allowed {
				if err != nil || out.Status != want || !out.UpdatedAt.Equal(now) || r.Status != state {
					t.Errorf("%s / %s: %s, %v", state, op, out.Status, err)
				}
			} else if !errors.Is(err, ErrConflict) {
				t.Errorf("%s / %s: expected conflict, got %v", state, op, err)
			}
		}
	}
}

func TestRequestPolicy(t *testing.T) {
	team, other := "team_delivery", "team_auto"
	r := Request{OwnerID: "u_anna", TeamID: team, Approver: &Ref{ID: "u_olga"}}
	users := []struct {
		user    User
		allowed map[Operation]bool
	}{
		{User{Ref: Ref{ID: "u_anna"}, Role: "intern", TeamID: &team}, map[Operation]bool{Read: true, Submit: true, Cancel: true}},
		{User{Ref: Ref{ID: "u_olga"}, Role: "manager", TeamID: &team}, map[Operation]bool{Approve: true, Reject: true}},
		{User{Ref: Ref{ID: "u_peer"}, Role: "intern", TeamID: &team}, nil},
		{User{Ref: Ref{ID: "u_other_manager"}, Role: "manager", TeamID: &team}, nil},
		{User{Ref: Ref{ID: "u_olga"}, Role: "manager", TeamID: &other}, nil},
		{User{Ref: Ref{ID: "u_olga"}, Role: "mentor", TeamID: &team}, nil},
		{User{Ref: Ref{ID: "u_hr"}, Role: "hr"}, nil},
	}
	for _, tc := range users {
		for _, op := range []Operation{Read, Submit, Cancel, Approve, Reject} {
			err := r.Authorize(tc.user, op)
			if tc.allowed[op] && err != nil || !tc.allowed[op] && !errors.Is(err, ErrForbidden) {
				t.Errorf("%s / %s: %v", tc.user.ID, op, err)
			}
		}
	}
	r.OwnerID = "u_olga"
	if err := r.Authorize(users[1].user, Approve); !errors.Is(err, ErrForbidden) {
		t.Fatal("самосогласование должно быть запрещено")
	}
}

func TestPayloadMatchesType(t *testing.T) {
	now := time.Now()
	r := Request{ID: "req_test", OwnerID: "u_anna", TeamID: "team_delivery", Type: "absence_request",
		Status: Draft, Summary: "Отгул", CreatedAt: now, UpdatedAt: now}
	for _, tc := range []struct {
		body  string
		valid bool
	}{
		{`{"kind":"day_off","date_from":"2026-11-13","date_to":"2026-11-13"}`, true},
		{`{"kind":"vacation","date_from":"2026-11-14","date_to":"2026-11-13"}`, false},
		{`{"system":"jira","reason":"test"}`, false},
		{`null`, false},
	} {
		r.Payload = json.RawMessage(tc.body)
		if got := r.Validate() == nil; got != tc.valid {
			t.Errorf("payload %s: valid=%v", tc.body, got)
		}
	}
}
