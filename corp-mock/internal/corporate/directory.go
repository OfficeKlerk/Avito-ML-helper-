// Package corporate содержит модель заявок, справочник и политики corp-mock.
package corporate

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

type Ref struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type User struct {
	Ref
	Login     string  `json:"login"`
	Role      string  `json:"role"`
	TeamID    *string `json:"team_id"`
	MentorID  *string `json:"mentor_id"`
	ManagerID *string `json:"manager_id"`
}

type Profile struct {
	Ref
	Role    string `json:"role"`
	Team    *Ref   `json:"team"`
	Mentor  *Ref   `json:"mentor"`
	Manager *Ref   `json:"manager"`
}

type Contact struct {
	ID        *string `json:"id"`
	Name      string  `json:"name"`
	RoleTitle string  `json:"role_title"`
	Channel   *string `json:"channel"`
}

type contactEntry struct {
	Contact
	Topic  string  `json:"topic"`
	TeamID *string `json:"team_id"`
}

type ContactList struct {
	Topic    string    `json:"topic"`
	Contacts []Contact `json:"contacts"`
}

type Directory struct {
	teams    map[string]Ref
	users    map[string]User
	contacts []contactEntry
}

func LoadDirectory(dir string) (*Directory, error) {
	var teams []Ref
	var users []User
	var contacts []contactEntry
	for _, file := range []struct {
		name string
		dest any
	}{{"teams.json", &teams}, {"users.json", &users}, {"contacts.json", &contacts}} {
		data, err := os.ReadFile(filepath.Join(dir, file.name))
		if err != nil {
			return nil, err
		}
		if err := json.Unmarshal(data, file.dest); err != nil {
			return nil, fmt.Errorf("%s: %w", file.name, err)
		}
	}
	d := &Directory{teams: make(map[string]Ref), users: make(map[string]User), contacts: contacts}
	for _, team := range teams {
		d.teams[team.ID] = team
	}
	for _, user := range users {
		d.users[user.ID] = user
	}
	return d, nil
}

func (d *Directory) User(id string) (User, bool) {
	u, ok := d.users[id]
	return u, ok
}

func (d *Directory) Profile(u User) Profile {
	var team *Ref
	if u.TeamID != nil {
		if entry, ok := d.teams[*u.TeamID]; ok {
			team = &entry
		}
	}
	return Profile{Ref: u.Ref, Role: u.Role, Team: team, Mentor: d.person(u.MentorID), Manager: d.person(u.ManagerID)}
}

func (d *Directory) person(id *string) *Ref {
	if id != nil {
		if u, ok := d.User(*id); ok {
			return &u.Ref
		}
	}
	return nil
}

func (d *Directory) FindContacts(u User, topic string) (ContactList, error) {
	switch topic {
	case "accesses", "absence", "onboarding":
	default:
		return ContactList{}, ErrValidation
	}
	list := ContactList{Topic: topic, Contacts: []Contact{}}
	for _, entry := range d.contacts {
		if entry.Topic == topic && (entry.TeamID == nil || sameTeam(entry.TeamID, u.TeamID)) {
			list.Contacts = append(list.Contacts, entry.Contact)
		}
	}
	return list, nil
}

func sameTeam(a, b *string) bool {
	return a != nil && b != nil && *a == *b
}
