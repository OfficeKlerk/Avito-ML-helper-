package corporate

import (
	"errors"
	"os"
	"testing"
	"time"
)

func TestAbsenceDates(t *testing.T) {
	dir := os.Getenv("SEED_DIR")
	if dir == "" {
		dir = "../../../data/seed"
	}
	rules, _, err := LoadServices(dir)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 13, 0, 5, 0, 0, time.FixedZone("MSK", 3*3600))
	for _, test := range []struct {
		name, kind, from, to string
		valid                bool
	}{
		{"two days", "day_off", "2026-11-14", "2026-11-15", true},
		{"today in Moscow", "day_off", "2026-11-13", "2026-11-13", false},
		{"past", "day_off", "2026-11-12", "2026-11-12", false},
		{"too long", "day_off", "2026-11-14", "2026-11-16", false},
		{"reversed", "day_off", "2026-11-15", "2026-11-14", false},
		{"malformed", "day_off", "2026-11-31", "2026-11-31", false},
		{"vacation notice", "vacation", "2026-11-26", "2026-11-26", false},
		{"vacation boundary", "vacation", "2026-11-27", "2026-12-10", true},
	} {
		t.Run(test.name, func(t *testing.T) {
			_, err := rules.ValidateDates(AbsencePayload{Kind: test.kind, DateFrom: test.from, DateTo: test.to}, now)
			if test.valid && err != nil || !test.valid && !errors.Is(err, ErrValidation) {
				t.Fatalf("valid=%v, err=%v", test.valid, err)
			}
		})
	}
}
