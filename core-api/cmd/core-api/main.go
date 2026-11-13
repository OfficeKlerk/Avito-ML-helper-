// Команда core-api запускает HTTP-сервер сервиса.
package main

import (
	"context"
	"database/sql"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
	_ "time/tzdata"

	"aibuddy/core-api/internal/clients"
	"aibuddy/core-api/internal/httpapi"
	"aibuddy/core-api/internal/store"
)

const version = "0.1.0"

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, logger); err != nil {
		logger.Error("core-api остановлен", "error_code", err.Error())
		os.Exit(1)
	}
}

func run(ctx context.Context, logger *slog.Logger) error {
	dbURL, secret := os.Getenv("DATABASE_URL"), os.Getenv("JWT_SECRET")
	if strings.TrimSpace(dbURL) == "" || strings.TrimSpace(secret) == "" {
		return errors.New("database_url_or_jwt_secret_missing")
	}
	seedDir := os.Getenv("SEED_DIR")
	if seedDir == "" {
		seedDir = "/data/seed"
	}
	location, err := time.LoadLocation("Europe/Moscow")
	if err != nil {
		return errors.New("timezone_load_failed")
	}
	db, err := sql.Open("postgres", dbURL)
	if err != nil {
		return errors.New("database_config_invalid")
	}
	defer db.Close()
	// Каждый идущий разговор держит соединение, пока ждёт агента (блокировка диалога в PostgreSQL),
	// поэтому запас нужен и на чаты, и на остальные запросы. У PostgreSQL по умолчанию 100 соединений.
	db.SetMaxOpenConns(40)
	startup, cancel := context.WithTimeout(ctx, 45*time.Second)
	err = store.Initialize(startup, db, seedDir)
	cancel()
	if err != nil {
		return errors.New("database_initialize_failed")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	deps := httpapi.Dependencies{
		Logger: logger,
		Agent:  clients.NewAgent(envURL("AGENT_URL", "http://agent:8090")),
		Corp:   clients.NewCorp(envURL("CORP_MOCK_URL", "http://corp-mock:8070")),
	}
	data := store.New(db)
	now := func() time.Time { return time.Now().In(location) }
	workerCtx, stopWorker := context.WithCancel(ctx)
	workerDone := make(chan struct{})
	go func() {
		defer close(workerDone)
		runReminders(workerCtx, data, logger, now)
	}()
	defer func() {
		stopWorker()
		<-workerDone
	}()
	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           httpapi.NewHandler(version, data, secret, now, deps),
		ReadHeaderTimeout: 5 * time.Second,
	}

	serverErr := make(chan error, 1)
	go func() {
		logger.Info("сервис запущен", "service", httpapi.ServiceName)
		serverErr <- srv.ListenAndServe()
	}()
	select {
	case err := <-serverErr:
		if !errors.Is(err, http.ErrServerClosed) {
			return errors.New("http_serve_failed")
		}
		return nil
	case <-ctx.Done():
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := srv.Shutdown(shutdown); err != nil {
			return errors.New("http_shutdown_failed")
		}
		return nil
	}
}

func envURL(name, fallback string) string {
	if url := strings.TrimSpace(os.Getenv(name)); url != "" {
		return url
	}
	return fallback
}
