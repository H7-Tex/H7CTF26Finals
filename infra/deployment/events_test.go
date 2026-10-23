package orchestrator

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync"
	"testing"
	"time"
)

func TestDeploymentEventMapping(t *testing.T) {
	tests := []struct {
		name, action, outcome, state, reason string
	}{
		{name: "queued", action: "candidate", outcome: "queued", state: "queued"},
		{name: "building", action: "candidate", outcome: "building", state: "building"},
		{name: "gating", action: "build", outcome: "built", state: "gating"},
		{name: "waiting", action: "gate", outcome: "passed", state: "waiting_quiet_window"},
		{name: "promoted", action: "promotion", outcome: "promoted", state: "promoted"},
		{name: "rolled back", action: "manual-rollback", outcome: "rolled-back", state: "rolled_back"},
		{name: "policy failure", action: "policy", outcome: "rejected", state: "failed", reason: "policy"},
		{name: "build failure", action: "build", outcome: "rejected", state: "failed", reason: "build"},
		{name: "gate failure", action: "gate", outcome: "rejected", state: "failed", reason: "gate"},
		{name: "promotion failure", action: "promotion", outcome: "rejected", state: "failed", reason: "promotion"},
		{name: "health failure", action: "health", outcome: "rejected", state: "failed", reason: "health"},
		{name: "rollback failure", action: "auto-rollback", outcome: "rejected", state: "failed", reason: "rollback"},
		{name: "operator failure", action: "gate", outcome: "operator-intervention", state: "failed", reason: "operator"},
		{name: "unknown failure", action: "unexpected", outcome: "rejected", state: "failed", reason: "unknown"},
	}
	for index, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, report, err := normalizedDeploymentEvent("11111111-1111-4111-8111-111111111111", AuditEvent{
				Sequence: uint64(index + 1), Service: "service-one", Action: test.action, Outcome: test.outcome,
			})
			if err != nil || !report {
				t.Fatalf("event was not mapped: report=%t err=%v", report, err)
			}
			if got.State != test.state || got.ReasonCode != test.reason {
				t.Fatalf("unexpected mapping: %+v", got)
			}
		})
	}

	if _, report, err := normalizedDeploymentEvent("11111111-1111-4111-8111-111111111111", AuditEvent{Sequence: 90, Action: "repository", Outcome: "rejected"}); err != nil || report {
		t.Fatalf("repository audit escaped into the deployment feed: report=%t err=%v", report, err)
	}
}

func TestDeploymentEventReporterRetriesExactRedactedPayload(t *testing.T) {
	_, _, store := testFixture(t)
	if err := store.Update(AuditEvent{Action: "commissioning", Outcome: "initialized", ActorID: "operator", TraceID: "commissioning"}, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.Update(AuditEvent{
		Service: "service-one", Action: "candidate", Outcome: "queued", ActorID: "gitea", TraceID: "private-trace",
		Commit: candidateCommit, Digest: candidateDigest, Message: "H7CTF{0123456789abcdef0123456789abcdef}",
	}, nil); err != nil {
		t.Fatal(err)
	}

	var mu sync.Mutex
	var received []map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != deploymentEventPath || request.Header.Get("Authorization") != "Bearer internal-token-value-that-is-long-enough" || request.Header.Get("Content-Type") != "application/json" {
			t.Errorf("unexpected request identity: path=%s auth=%q type=%q", request.URL.Path, request.Header.Get("Authorization"), request.Header.Get("Content-Type"))
		}
		var body map[string]any
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Errorf("decode event: %v", err)
		}
		mu.Lock()
		received = append(received, body)
		attempt := len(received)
		mu.Unlock()
		if attempt == 1 {
			response.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		response.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(response).Encode(map[string]int64{"id": 7})
	}))
	defer server.Close()

	reporter := &DeploymentEventReporter{
		URL: server.URL + deploymentEventPath, TeamID: "11111111-1111-4111-8111-111111111111",
		Token: []byte("internal-token-value-that-is-long-enough"), Store: store,
		Client: server.Client(), PollInterval: time.Second,
	}
	if err := reporter.Reconcile(context.Background()); err == nil {
		t.Fatal("rejected event was acknowledged")
	}
	if got := store.Snapshot().ReportedSequence; got != 1 {
		t.Fatalf("rejected event advanced the durable cursor: %d", got)
	}
	if err := reporter.Reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := store.Snapshot().ReportedSequence; got != 2 {
		t.Fatalf("accepted retry did not advance the durable cursor: %d", got)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(received) != 2 || !reflect.DeepEqual(received[0], received[1]) {
		t.Fatalf("retry changed payload: %+v", received)
	}
	wantKeys := map[string]bool{"team_id": true, "service": true, "source_sequence": true, "state": true}
	if len(received[0]) != len(wantKeys) {
		t.Fatalf("private audit fields entered payload: %+v", received[0])
	}
	for key := range received[0] {
		if !wantKeys[key] {
			t.Fatalf("private field %q entered payload: %+v", key, received[0])
		}
	}
}

func TestDeploymentEventReporterRejectsInvalidSuccessBody(t *testing.T) {
	_, _, store := testFixture(t)
	if err := store.Update(AuditEvent{Service: "service-one", Action: "candidate", Outcome: "building", ActorID: "gitea", TraceID: "building"}, nil); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write([]byte(`{"ok":true}`))
	}))
	defer server.Close()
	reporter := &DeploymentEventReporter{
		URL: server.URL, TeamID: "11111111-1111-4111-8111-111111111111", Token: []byte("internal-token-value-that-is-long-enough"),
		Store: store, Client: server.Client(), PollInterval: time.Second,
	}
	if err := reporter.Reconcile(context.Background()); err == nil {
		t.Fatal("invalid success body was acknowledged")
	}
	if store.Snapshot().ReportedSequence != 0 {
		t.Fatal("invalid success body advanced the durable cursor")
	}
}

func TestDiscoveryWritesOneQueuedEventPerChangedService(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/src/main.go"}, "service-one": {"service-one/src/main.go"}},
	}
	engine := NewEngine(cfg, manifest, store, repository, &fakeRunner{}, fakeQuiet{})
	if err := engine.discover(context.Background()); err != nil {
		t.Fatal(err)
	}
	events, err := store.Audit(0, 10)
	if err != nil {
		t.Fatal(err)
	}
	var queued int
	for _, event := range events {
		if event.Service == "service-one" && event.Action == "candidate" && event.Outcome == "queued" {
			queued++
		}
	}
	if queued != 1 {
		t.Fatalf("expected one durable queued event, got %d: %+v", queued, events)
	}
}

func TestReportedSequencePersistsAndRejectsInvalidMovement(t *testing.T) {
	cfg, _, store := testFixture(t)
	if err := store.Update(AuditEvent{Service: "service-one", Action: "candidate", Outcome: "queued", ActorID: "gitea", TraceID: "queued"}, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.AcknowledgeReported(1); err != nil {
		t.Fatal(err)
	}
	if err := store.AcknowledgeReported(0); err == nil {
		t.Fatal("reported cursor moved backwards")
	}
	if err := store.AcknowledgeReported(2); err == nil {
		t.Fatal("reported cursor moved beyond the durable audit")
	}
	reopened, err := OpenStore(cfg, "manifest")
	if err != nil {
		t.Fatal(err)
	}
	if got := reopened.Snapshot().ReportedSequence; got != 1 {
		t.Fatalf("reported cursor was not durable: %d", got)
	}
}

func TestDeploymentEventURLUsesAnvilOriginOnly(t *testing.T) {
	cfg := &Config{
		TeamID: "11111111-1111-4111-8111-111111111111", TickURL: "https://finals.h7tex.com/api/v1/arena/tick?private=value#fragment",
		InternalToken: []byte("internal-token-value-that-is-long-enough"), PollInterval: Duration(15 * time.Second),
	}
	reporter, err := NewDeploymentEventReporter(cfg, nil)
	if err != nil {
		t.Fatal(err)
	}
	if reporter.URL != "https://finals.h7tex.com"+deploymentEventPath {
		t.Fatalf("unexpected endpoint: %s", reporter.URL)
	}
}
