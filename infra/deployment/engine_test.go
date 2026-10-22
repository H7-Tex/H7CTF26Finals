package orchestrator

import (
	"context"
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"
)

const (
	baseCommit      = "1111111111111111111111111111111111111111"
	candidateCommit = "2222222222222222222222222222222222222222"
	factoryDigest   = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
	candidateDigest = "sha256:2222222222222222222222222222222222222222222222222222222222222222"
)

type fakeRepository struct {
	head     string
	paths    map[string][]string
	size     int64
	err      error
	ancestor bool
}

func (r *fakeRepository) FetchRemoteHead(context.Context) (string, error) { return r.head, r.err }

func (r *fakeRepository) IsAncestor(context.Context, string, string) (bool, error) {
	if r.err != nil {
		return false, r.err
	}
	return r.ancestor, nil
}

func (r *fakeRepository) DiffPaths(_ context.Context, _, _, scope string) ([]string, error) {
	return append([]string(nil), r.paths[scope]...), r.err
}

func (r *fakeRepository) TreeSize(context.Context, string, string) (int64, error) {
	return r.size, r.err
}

type fakeRunner struct {
	mu       sync.Mutex
	results  map[string][]RunResult
	errors   map[string]error
	requests []RunRequest
	before   func(RunRequest)
}

func (r *fakeRunner) Run(_ context.Context, request RunRequest) (RunResult, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.requests = append(r.requests, request)
	if r.before != nil {
		r.before(request)
	}
	if err := r.errors[request.Operation]; err != nil {
		return RunResult{}, err
	}
	queue := r.results[request.Operation]
	if len(queue) == 0 {
		return RunResult{}, errors.New("unexpected runner operation")
	}
	result := queue[0]
	r.results[request.Operation] = queue[1:]
	return result, nil
}

type fakeQuiet struct{ tick int64 }

func (q fakeQuiet) Wait(_ context.Context, after int64) (int64, error) {
	if q.tick <= after {
		return 0, errors.New("stale tick")
	}
	return q.tick, nil
}

func boolPointer(value bool) *bool { return &value }

func testFixture(t *testing.T) (*Config, *Manifest, *Store) {
	t.Helper()
	cfg := &Config{
		TeamNumber: 1, TeamID: "11111111-1111-4111-8111-111111111111",
		StateDirectory: t.TempDir(), Repository: RepositoryConfig{Path: "/var/lib/deployment-orchestrator/repository", InitialCommit: baseCommit},
		PollInterval: Duration(15 * time.Second),
	}
	manifest := &Manifest{SchemaVersion: 1, PolicyVersion: "policy-1", Services: []ServiceManifest{{
		Slug: "service-one", BaseCommit: baseCommit, FactoryDigest: factoryDigest,
		BundleSHA256: "1111111111111111111111111111111111111111111111111111111111111111",
		AllowedPaths: []string{"src/"}, MaximumContext: 1024 * 1024,
		MemoryBytes: 128 * 1024 * 1024, CPUMillis: 500, PIDs: 64,
		BuildTimeout: Duration(time.Second), GateTimeout: Duration(time.Second),
		PromotionTimeout: Duration(time.Second), HealthTimeout: Duration(time.Second), PreviousFlagTicks: 5,
	}}}
	if err := InitializeStore(cfg.StateDirectory, InitialState(cfg, manifest, "manifest")); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(cfg, "manifest")
	if err != nil {
		t.Fatal(err)
	}
	return cfg, manifest, store
}

func TestReconcileBuildGatePromoteByDigest(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/src/main.go"}, "service-one": {"service-one/src/main.go"}},
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"build":   {{OK: true, Digest: candidateDigest, RunnerPolicyVersion: "policy-1"}},
		"gate":    {{OK: true, DataCopyID: "copy-01", RunnerPolicyVersion: "policy-1"}},
		"promote": {{OK: true, Digest: candidateDigest, Healthy: boolPointer(true), RecoverySnapshotID: "snapshot-01", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	runner.before = func(request RunRequest) {
		intent := store.Snapshot().Services[request.Service].Intent
		if intent == nil || !reflect.DeepEqual(intent.Request, request) {
			t.Fatalf("runner effect was not preceded by its exact durable intent: intent=%+v request=%+v", intent, request)
		}
	}
	engine := NewEngine(cfg, manifest, store, repository, runner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	state := store.Snapshot()
	service := state.Services["service-one"]
	if service.CurrentDigest != candidateDigest || service.LastKnownGoodDigest != factoryDigest || service.GateDataCopyID != "copy-01" || service.RecoverySnapshotID != "snapshot-01" || service.PromotionTick != 42 {
		t.Fatalf("unexpected promoted state: %+v", service)
	}
	if len(state.Pending) != 0 || service.Status != "watching" {
		t.Fatalf("candidate was not finalized: %+v", state)
	}
	if len(runner.requests) != 3 || runner.requests[0].Resources.NetworkMode != "none" || runner.requests[1].DataMode != "copy-current" || runner.requests[1].PreviousFlagTicks != 5 || runner.requests[2].DataMode != "preserve-current" {
		t.Fatalf("runner contract was not enforced: %+v", runner.requests)
	}
	seen := make(map[string]struct{}, len(runner.requests))
	for _, request := range runner.requests {
		if _, exists := seen[request.OperationID]; exists {
			t.Fatalf("operation id reused across distinct requests: %+v", runner.requests)
		}
		seen[request.OperationID] = struct{}{}
	}
}

func TestGateFailureLeavesProductionUntouched(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/src/main.go"}, "service-one": {"service-one/src/main.go"}},
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"build": {{OK: true, Digest: candidateDigest, RunnerPolicyVersion: "policy-1"}},
		"gate":  {{OK: false, PublicMessage: "Feature check failed.", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, repository, runner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	service := store.Snapshot().Services["service-one"]
	if service.CurrentDigest != factoryDigest || service.Status != "rejected" || service.PublicMessage != "Feature check failed." {
		t.Fatalf("gate failure changed production: %+v", service)
	}
	for _, request := range runner.requests {
		if request.Operation == "promote" {
			t.Fatal("gate failure invoked promotion")
		}
	}
}

func TestTwoCausalFailuresAutoRollbackAndPreserveData(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "test-seed"}, func(next *PersistentState) error {
		service := next.Services["service-one"]
		service.Status = "watching"
		service.CurrentCommit = candidateCommit
		service.CurrentDigest = candidateDigest
		service.LastKnownGoodCommit = baseCommit
		service.LastKnownGoodDigest = factoryDigest
		service.PromotionTick = 10
		next.Services["service-one"] = service
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{}, runner, fakeQuiet{})
	first := HealthObservation{Service: "service-one", Digest: candidateDigest, PreviousDigest: factoryDigest, Tick: 11, CurrentStatus: "DOWN", PreviousStatus: "OK", TraceID: "health-tick-11"}
	if err := engine.ObserveHealth(context.Background(), first); err != nil {
		t.Fatal(err)
	}
	first.TraceID = "health-tick-12"
	first.Tick = 12
	if err := engine.ObserveHealth(context.Background(), first); err != nil {
		t.Fatal(err)
	}
	service := store.Snapshot().Services["service-one"]
	if service.CurrentDigest != candidateDigest || service.Status != "rolling-back" || service.Intent == nil || service.Intent.Stage != "auto-rollback" {
		t.Fatalf("auto rollback was not durably queued: %+v", service)
	}
	if len(runner.requests) != 0 {
		t.Fatalf("health request executed runner work synchronously: %+v", runner.requests)
	}
	if err := engine.resumeService(context.Background(), "service-one"); err != nil {
		t.Fatal(err)
	}
	service = store.Snapshot().Services["service-one"]
	if service.CurrentDigest != factoryDigest || service.Status != "healthy" {
		t.Fatalf("auto rollback did not restore last known good: %+v", service)
	}
	if len(runner.requests) != 1 || runner.requests[0].Operation != "rollback" || runner.requests[0].DataMode != "preserve-current" || runner.requests[0].TargetDigest != factoryDigest {
		t.Fatalf("rollback contract did not preserve data: %+v", runner.requests)
	}
}

func TestProtectedPathRejectedBeforeRunner(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/Dockerfile"}, "service-one": {"service-one/Dockerfile"}},
	}
	runner := &fakeRunner{results: map[string][]RunResult{}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, repository, runner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(runner.requests) != 0 {
		t.Fatal("protected path reached runner")
	}
	if store.Snapshot().Services["service-one"].Status != "rejected" {
		t.Fatal("protected path was not rejected")
	}
}
