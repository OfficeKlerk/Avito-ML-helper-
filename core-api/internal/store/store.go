// Package store хранит данные core-api в PostgreSQL.
package store

import (
	"context"
	"database/sql"
	"embed"
	"fmt"

	_ "github.com/lib/pq"
)

//go:embed migrations/*.sql
var migrations embed.FS

// Initialize применяет новые миграции и загружает демоданные в одной транзакции.
func Initialize(ctx context.Context, db *sql.DB, seedDir string) error {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()

	// Одинаковый ключ у всех экземпляров core-api. Сериализует и миграции, и загрузку.
	if _, err := tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(52801908)`); err != nil {
		return fmt.Errorf("блокировка миграций: %w", err)
	}
	if err := migrate(ctx, tx); err != nil {
		return err
	}
	if err := seed(ctx, tx, seedDir); err != nil {
		return fmt.Errorf("загрузка демоданных: %w", err)
	}
	return tx.Commit()
}

func migrate(ctx context.Context, tx *sql.Tx) error {
	if _, err := tx.ExecContext(ctx, `
		CREATE SCHEMA IF NOT EXISTS core;
		CREATE TABLE IF NOT EXISTS core.schema_migrations (version text PRIMARY KEY)
	`); err != nil {
		return fmt.Errorf("подготовка схемы core: %w", err)
	}
	files, err := migrations.ReadDir("migrations")
	if err != nil {
		return err
	}
	for _, file := range files {
		name := file.Name()
		var applied bool
		err := tx.QueryRowContext(ctx,
			`SELECT EXISTS (SELECT 1 FROM core.schema_migrations WHERE version = $1)`, name).Scan(&applied)
		if err != nil {
			return err
		}
		if applied {
			continue
		}
		body, err := migrations.ReadFile("migrations/" + name)
		if err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, string(body)); err != nil {
			return fmt.Errorf("миграция %s: %w", name, err)
		}
		if _, err := tx.ExecContext(ctx, `INSERT INTO core.schema_migrations (version) VALUES ($1)`, name); err != nil {
			return err
		}
	}
	return nil
}

type Store struct {
	db *sql.DB
}

func New(db *sql.DB) *Store {
	return &Store{db: db}
}
