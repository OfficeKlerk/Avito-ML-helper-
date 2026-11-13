// Команда corp-mock запускает HTTP-сервер сервиса.
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

	"aibuddy/corp-mock/internal/corporate"
	"aibuddy/corp-mock/internal/httpapi"
	"aibuddy/corp-mock/internal/store"
)

const version = "0.1.0"

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, logger); err != nil {
		logger.Error("corp-mock остановлен", "error_code", err.Error())
		os.Exit(1)
	}
}

func run(ctx context.Context, logger *slog.Logger) error {
	dsn := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if dsn == "" {
		return errors.New("database_url_missing")
	}
	seedDir := os.Getenv("SEED_DIR")
	if seedDir == "" {
		seedDir = "/data/seed"
	}
	directory, err := corporate.LoadDirectory(seedDir)
	if err != nil {
		return errors.New("directory_load_failed")
	}
	rules, catalog, err := corporate.LoadServices(seedDir)
	if err != nil {
		return errors.New("service_catalog_load_failed")
	}
	moscow, err := time.LoadLocation("Europe/Moscow")
	if err != nil {
		return errors.New("timezone_load_failed")
	}
	auth, err := corporate.NewAuthenticator(directory, os.Getenv("JWT_SECRET"), time.Now)
	if err != nil {
		return err
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return errors.New("database_config_invalid")
	}
	defer db.Close()
	data := store.New(db)
	startup, cancel := context.WithTimeout(ctx, 30*time.Second)
	err = data.Initialize(startup, seedDir, directory)
	cancel()
	if err != nil {
		return errors.New("database_initialize_failed")
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8070"
	}
	api := &httpapi.API{
		Auth: auth, Directory: directory, Requests: data, Drafts: data, Rules: rules, Access: catalog,
		Now:    func() time.Time { return time.Now().In(moscow) },
		Faults: httpapi.NewFaults(os.Getenv("CORP_FAULT_TOKEN"), logger),
	}
	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           httpapi.NewHandler(version, api),
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
