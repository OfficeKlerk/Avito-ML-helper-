package corporate

import (
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

var ErrUnauthorized = errors.New("unauthorized")

type claims struct {
	jwt.RegisteredClaims
	Login string          `json:"login"`
	Role  string          `json:"role"`
	Team  json.RawMessage `json:"team_id"`
}

type Authenticator struct {
	directory *Directory
	secret    []byte
	now       func() time.Time
}

func NewAuthenticator(directory *Directory, secret string, now func() time.Time) (*Authenticator, error) {
	if strings.TrimSpace(secret) == "" {
		return nil, errors.New("JWT_SECRET is required")
	}
	return &Authenticator{directory: directory, secret: []byte(secret), now: now}, nil
}

func (a *Authenticator) Authenticate(headers []string) (User, error) {
	if len(headers) != 1 {
		return User{}, ErrUnauthorized
	}
	parts := strings.Fields(headers[0])
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return User{}, ErrUnauthorized
	}
	var c claims
	_, err := jwt.ParseWithClaims(parts[1], &c, func(*jwt.Token) (any, error) {
		return a.secret, nil
	}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithExpirationRequired(), jwt.WithTimeFunc(a.now))
	if err != nil || len(c.Team) == 0 || c.Login == "" ||
		!slices.Contains([]string{"intern", "mentor", "manager", "hr"}, c.Role) {
		return User{}, ErrUnauthorized
	}
	var team *string
	if err := json.Unmarshal(c.Team, &team); err != nil {
		return User{}, ErrUnauthorized
	}
	u, ok := a.directory.User(c.Subject)
	if !ok || c.Login != u.Login || c.Role != u.Role ||
		!((team == nil && u.TeamID == nil) || sameTeam(team, u.TeamID)) {
		return User{}, ErrUnauthorized
	}
	return u, nil
}
