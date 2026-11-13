package httpapi

import (
	"database/sql"
	"errors"
	"net/http"
	"strings"
	"time"

	"aibuddy/core-api/internal/store"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

// Сравнение с фиктивным хэшем занимает столько же времени, когда логина нет в БД.
const dummyHash = "$2a$10$7EqJtq98hPqEX7fNZaFWoOhi.F5N4osH7n8OFN6.V83F5dYJMH0oi"

func (a api) login(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Login    string `json:"login"`
		Password string `json:"password"`
	}
	if !readJSON(w, r, 4096, &body) || strings.TrimSpace(body.Login) == "" || body.Password == "" {
		WriteError(w, http.StatusUnprocessableEntity, "validation", "Укажи логин и пароль.")
		return
	}

	id, hash, err := a.db.Credentials(r.Context(), body.Login)
	missing := errors.Is(err, sql.ErrNoRows)
	if missing {
		hash = dummyHash
	} else if err != nil {
		internalError(w)
		return
	}
	passwordOK := len(body.Password) <= 72 && bcrypt.CompareHashAndPassword([]byte(hash), []byte(body.Password)) == nil
	if missing || !passwordOK {
		WriteError(w, http.StatusUnauthorized, "unauthorized", "Неверный логин или пароль.")
		return
	}

	u, err := a.db.User(r.Context(), id)
	if err != nil {
		internalError(w)
		return
	}
	now := a.now()
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": u.ID, "login": u.Login, "role": u.Role, "team_id": teamClaim(u),
		"exp": now.Add(24 * time.Hour).Unix(),
	}).SignedString(a.secret)
	if err != nil {
		internalError(w)
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	WriteJSON(w, http.StatusOK, struct {
		Token string     `json:"token"`
		User  store.User `json:"user"`
	}{Token: token, User: u.ProfileAt(now)})
}

func teamClaim(u store.User) any {
	if u.Team == nil {
		return nil
	}
	return u.Team.ID
}

func (a api) requireUser(next func(http.ResponseWriter, *http.Request, store.User)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		headers := r.Header.Values("Authorization")
		if len(headers) != 1 {
			unauthorized(w)
			return
		}
		parts := strings.Fields(headers[0])
		if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
			unauthorized(w)
			return
		}
		claims := jwt.MapClaims{}
		_, err := jwt.ParseWithClaims(parts[1], claims, func(*jwt.Token) (any, error) {
			return a.secret, nil
		}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithExpirationRequired(), jwt.WithTimeFunc(a.now))
		sub, ok := claims["sub"].(string)
		if err != nil || !ok || sub == "" {
			unauthorized(w)
			return
		}
		u, err := a.db.User(r.Context(), sub)
		if errors.Is(err, sql.ErrNoRows) {
			unauthorized(w)
			return
		}
		if err != nil {
			internalError(w)
			return
		}
		team, present := claims["team_id"]
		if !present || team != teamClaim(u) || claims["login"] != u.Login || claims["role"] != u.Role {
			unauthorized(w)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		r.Header.Set("Authorization", "Bearer "+parts[1])
		next(w, r, u)
	}
}

func unauthorized(w http.ResponseWriter) {
	w.Header().Set("WWW-Authenticate", "Bearer")
	WriteError(w, http.StatusUnauthorized, "unauthorized", "Нужно войти заново.")
}

func (a api) me(w http.ResponseWriter, _ *http.Request, u store.User) {
	WriteJSON(w, http.StatusOK, u.ProfileAt(a.now()))
}
