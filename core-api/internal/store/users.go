package store

import (
	"context"
	"time"
)

type Ref struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type User struct {
	ID             string  `json:"id"`
	Login          string  `json:"login"`
	Name           string  `json:"name"`
	Role           string  `json:"role"`
	Team           *Ref    `json:"team"`
	Mentor         *Ref    `json:"mentor"`
	Manager        *Ref    `json:"manager"`
	StartDate      *string `json:"start_date"`
	InternshipWeek *int    `json:"internship_week"`
	Program        *string `json:"program"`
}

func (s *Store) Credentials(ctx context.Context, login string) (id, hash string, err error) {
	err = s.db.QueryRowContext(ctx, `SELECT id, password_hash FROM core.users WHERE login = $1`, login).Scan(&id, &hash)
	return
}

func (s *Store) User(ctx context.Context, id string) (User, error) {
	var u User
	var teamID, teamName, mentorID, mentorName, managerID, managerName *string
	err := s.db.QueryRowContext(ctx, `
		SELECT u.id, u.login, u.name, u.role, to_char(u.start_date, 'YYYY-MM-DD'), u.program,
		       team.id, team.name, mentor.id, mentor.name, manager.id, manager.name
		FROM core.users u
		LEFT JOIN core.teams team ON team.id = u.team_id
		LEFT JOIN core.users mentor ON mentor.id = u.mentor_id
		LEFT JOIN core.users manager ON manager.id = u.manager_id
		WHERE u.id = $1
	`, id).Scan(&u.ID, &u.Login, &u.Name, &u.Role, &u.StartDate, &u.Program,
		&teamID, &teamName, &mentorID, &mentorName, &managerID, &managerName)
	if err != nil {
		return User{}, err
	}
	u.Team = ref(teamID, teamName)
	u.Mentor = ref(mentorID, mentorName)
	u.Manager = ref(managerID, managerName)
	return u, nil
}

func ref(id, name *string) *Ref {
	if id == nil {
		return nil
	}
	return &Ref{ID: *id, Name: *name}
}

func (u User) ProfileAt(now time.Time) User {
	if u.Role == "intern" && u.StartDate != nil {
		start, err := time.Parse(time.DateOnly, *u.StartDate)
		if err == nil {
			today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
			week := max(0, int(today.Sub(start).Hours()/24))/7 + 1
			u.InternshipWeek = &week
		}
	}
	return u
}
