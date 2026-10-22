package orchestrator

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestHTTPQuietWindowRequiresLivePhaseAndIncludesHoldFrom(t *testing.T) {
	holdFrom := time.Date(2026, 10, 22, 12, 0, 0, 0, time.UTC)
	server := tickServer(t, tickResponse{Tick: 42, HoldFrom: holdFrom, EndsAt: holdFrom.Add(time.Second), Phase: "live"})
	defer server.Close()
	window := HTTPQuietWindow{URL: server.URL, Client: server.Client(), Now: func() time.Time { return holdFrom }}
	tick, err := window.Wait(context.Background(), 41)
	if err != nil || tick != 42 {
		t.Fatalf("hold_from boundary rejected: tick=%d err=%v", tick, err)
	}
}

func TestHTTPQuietWindowRejectsNonLivePhase(t *testing.T) {
	now := time.Now().UTC()
	server := tickServer(t, tickResponse{Tick: 42, HoldFrom: now.Add(-time.Second), EndsAt: now.Add(time.Second), Phase: "paused"})
	defer server.Close()
	window := HTTPQuietWindow{URL: server.URL, Client: server.Client(), Now: func() time.Time { return now }}
	if tick, err := window.Wait(context.Background(), 41); err == nil || tick != 0 {
		t.Fatalf("non-live phase accepted: tick=%d err=%v", tick, err)
	}
}

func TestHTTPQuietWindowExcludesEndsAt(t *testing.T) {
	endsAt := time.Date(2026, 10, 22, 12, 0, 1, 0, time.UTC)
	server := tickServer(t, tickResponse{Tick: 42, HoldFrom: endsAt.Add(-time.Second), EndsAt: endsAt, Phase: "live"})
	defer server.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	window := HTTPQuietWindow{URL: server.URL, Client: server.Client(), Now: func() time.Time { return endsAt }}
	if tick, err := window.Wait(ctx, 41); err == nil || tick != 0 {
		t.Fatalf("ends_at boundary accepted: tick=%d err=%v", tick, err)
	}
}

func tickServer(t *testing.T, response tickResponse) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		writer.Header().Set("Content-Type", "application/json")
		if err := json.NewEncoder(writer).Encode(response); err != nil {
			t.Errorf("encode tick response: %v", err)
		}
	}))
}
