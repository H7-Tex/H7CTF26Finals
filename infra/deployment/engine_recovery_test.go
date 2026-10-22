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
	newerCommit = "3333333333333333333333333333333333333333"
	newerDigest = "sha256:3333333333333333333333333333333333333333333333333333333333333333"
)

func TestRetryableBuildAndQuietFailuresRetainExactWork(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/src/main.go"}, "service-one": {"service-one/src/main.go"}},
	}
	firstRunner := &fakeRunner{results: map[string][]RunResult{}, errors: map[string]error{"build": context.DeadlineExceeded}}
	engine := NewEngine(cfg, manifest, store, repository, firstRunner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	state := store.Snapshot()
	intent := state.Services["service-one"].Intent
	if intent == nil || intent.Stage != "build" || state.Pending["service-one"] != candidateCommit {
		t.Fatalf("retryable build failure discarded work: %+v", state)
	}
	firstRequest := firstRunner.requests[0]

	secondRunner := &fakeRunner{results: map[string][]RunResult{
		"build": {{OK: true, Digest: candidateDigest, RunnerPolicyVersion: "policy-1"}},
		"gate":  {{OK: true, DataCopyID: "copy-01", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine = NewEngine(cfg, manifest, store, repository, secondRunner, fakeQuiet{})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(firstRequest, secondRunner.requests[0]) {
		t.Fatalf("build retry changed request: first=%+v retry=%+v", firstRequest, secondRunner.requests[0])
	}
	state = store.Snapshot()
	if state.Services["service-one"].Status != "waiting" || state.Services["service-one"].Intent != nil || state.Pending["service-one"] != candidateCommit {
		t.Fatalf("quiet outage discarded candidate: %+v", state)
	}

	thirdRunner := &fakeRunner{results: map[string][]RunResult{
		"promote": {{OK: true, Digest: candidateDigest, Healthy: boolPointer(true), RecoverySnapshotID: "snapshot-01", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine = NewEngine(cfg, manifest, store, repository, thirdRunner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(thirdRunner.requests) != 1 || thirdRunner.requests[0].Operation != "promote" {
		t.Fatalf("quiet retry rebuilt candidate: %+v", thirdRunner.requests)
	}
}

func TestEveryPersistedRunnerStageRetriesExactRequestAfterRestart(t *testing.T) {
	tests := []struct {
		stage     string
		operation string
		result    RunResult
	}{
		{stage: "build", operation: "build", result: RunResult{OK: true, Digest: candidateDigest, RunnerPolicyVersion: "policy-1"}},
		{stage: "gate", operation: "gate", result: RunResult{OK: true, DataCopyID: "copy-01", RunnerPolicyVersion: "policy-1"}},
		{stage: "promote", operation: "promote", result: RunResult{OK: true, Digest: candidateDigest, Healthy: boolPointer(true), RecoverySnapshotID: "snapshot-01", RunnerPolicyVersion: "policy-1"}},
		{stage: "recovery", operation: "rollback", result: RunResult{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
		{stage: "manual-rollback", operation: "rollback", result: RunResult{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}
	for _, test := range tests {
		t.Run(test.stage, func(t *testing.T) {
			cfg, manifest, store := testFixture(t)
			seedEngine := NewEngine(cfg, manifest, store, &fakeRepository{}, &fakeRunner{}, fakeQuiet{})
			serviceManifest := manifest.Services[0]
			commit := candidateCommit
			if test.stage == "manual-rollback" {
				commit = baseCommit
			}
			request := seedEngine.runRequest(test.operation, test.stage+"-operation-0001", serviceManifest, commit)
			switch test.stage {
			case "gate":
				request.CandidateDigest = candidateDigest
				request.DataMode = "copy-current"
				request.PreviousFlagTicks = 5
			case "promote":
				request.CandidateDigest = candidateDigest
				request.CurrentDigest = factoryDigest
				request.LastKnownGoodDigest = factoryDigest
				request.DataMode = "preserve-current"
				request.PromotionTick = 42
			case "recovery", "manual-rollback":
				request.CurrentDigest = candidateDigest
				request.TargetDigest = factoryDigest
				request.DataMode = "preserve-current"
			}
			intent := OperationIntent{Stage: test.stage, Request: request, Action: test.stage, ActorID: "operator-01", TraceID: "rollback-trace-01", TargetCommit: baseCommit}
			if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-intent-01"}, func(next *PersistentState) error {
				service := next.Services["service-one"]
				service.Status = test.stage
				service.Intent = &intent
				service.CandidateCommit = candidateCommit
				service.CandidateDigest = candidateDigest
				service.GateDataCopyID = "copy-01"
				service.PromotionTick = 42
				next.Services["service-one"] = service
				next.Pending["service-one"] = candidateCommit
				return nil
			}); err != nil {
				t.Fatal(err)
			}

			failedRunner := &fakeRunner{results: map[string][]RunResult{}, errors: map[string]error{test.operation: errors.New("transport unavailable")}}
			engine := NewEngine(cfg, manifest, store, &fakeRepository{}, failedRunner, fakeQuiet{})
			if err := engine.resumeService(context.Background(), "service-one"); err == nil {
				t.Fatal("retryable runner failure returned nil")
			}
			persisted := store.Snapshot().Services["service-one"].Intent
			if persisted == nil || !reflect.DeepEqual(persisted.Request, request) {
				t.Fatalf("failed request was not retained exactly: %+v", persisted)
			}

			reopened, err := OpenStore(cfg, "manifest")
			if err != nil {
				t.Fatal(err)
			}
			restartedRunner := &fakeRunner{results: map[string][]RunResult{test.operation: {test.result}}, errors: map[string]error{}}
			restarted := NewEngine(cfg, manifest, reopened, &fakeRepository{}, restartedRunner, fakeQuiet{})
			_ = restarted.resumeService(context.Background(), "service-one")
			if len(restartedRunner.requests) == 0 || !reflect.DeepEqual(restartedRunner.requests[0], request) {
				t.Fatalf("restart did not replay exact request: want=%+v got=%+v", request, restartedRunner.requests)
			}
		})
	}
}

func TestRepositoryOutageDoesNotBlockPersistedIntentRecovery(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	seed := NewEngine(cfg, manifest, store, &fakeRepository{}, &fakeRunner{}, fakeQuiet{})
	request := seed.runRequest("rollback", "recovery-operation-0001", manifest.Services[0], candidateCommit)
	request.TargetDigest = factoryDigest
	request.CurrentDigest = candidateDigest
	request.DataMode = "preserve-current"
	intent := OperationIntent{Stage: "recovery", Request: request, TargetCommit: baseCommit}
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-recovery-01"}, func(next *PersistentState) error {
		service := next.Services["service-one"]
		service.Status = "recovering"
		service.Intent = &intent
		service.CandidateCommit = candidateCommit
		service.CandidateDigest = candidateDigest
		next.Services["service-one"] = service
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{err: errors.New("gitea unavailable")}, runner, fakeQuiet{})
	if err := engine.reconcile(context.Background()); err == nil {
		t.Fatal("repository outage was not reported")
	}
	if len(runner.requests) != 1 || !reflect.DeepEqual(runner.requests[0], request) {
		t.Fatalf("repository outage blocked exact recovery intent: %+v", runner.requests)
	}
}

func TestPromotionFailurePersistsDistinctRecoveryRequest(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	repository := &fakeRepository{
		head: candidateCommit, size: 2048, ancestor: true,
		paths: map[string][]string{"": {"service-one/src/main.go"}, "service-one": {"service-one/src/main.go"}},
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"build":    {{OK: true, Digest: candidateDigest, RunnerPolicyVersion: "policy-1"}},
		"gate":     {{OK: true, DataCopyID: "copy-01", RunnerPolicyVersion: "policy-1"}},
		"promote":  {{OK: false, RunnerPolicyVersion: "policy-1"}},
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	runner.before = func(request RunRequest) {
		intent := store.Snapshot().Services[request.Service].Intent
		if intent == nil || !reflect.DeepEqual(intent.Request, request) {
			t.Fatalf("runner effect lacked exact durable intent: intent=%+v request=%+v", intent, request)
		}
	}
	engine := NewEngine(cfg, manifest, store, repository, runner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(runner.requests) != 4 || runner.requests[2].Operation != "promote" || runner.requests[3].Operation != "rollback" || runner.requests[2].OperationID == runner.requests[3].OperationID {
		t.Fatalf("promotion and recovery identities are not distinct: %+v", runner.requests)
	}
	service := store.Snapshot().Services["service-one"]
	if service.Status != "rejected" || service.CurrentDigest != factoryDigest || len(service.History) != 1 {
		t.Fatalf("promotion recovery changed proven state: %+v", service)
	}
}

func TestCandidateBecomesGreenOnlyAfterTwoConsecutiveHealthyTicks(t *testing.T) {
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
	engine := NewEngine(cfg, manifest, store, repository, runner, fakeQuiet{tick: 42})
	if err := engine.reconcile(context.Background()); err != nil {
		t.Fatal(err)
	}
	service := store.Snapshot().Services["service-one"]
	if service.Status != "watching" || len(service.History) != 1 || service.LastKnownGoodDigest != factoryDigest {
		t.Fatalf("unproven candidate became green: %+v", service)
	}
	if err := store.Update(AuditEvent{Action: "test", Outcome: "newer", ActorID: "test", TraceID: "newer-push-01"}, func(next *PersistentState) error {
		next.Pending["service-one"] = newerCommit
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := engine.resumeService(context.Background(), "service-one"); err != nil {
		t.Fatal(err)
	}
	if store.Snapshot().Pending["service-one"] != newerCommit {
		t.Fatal("new candidate was lost while current image was under observation")
	}

	observation := HealthObservation{Service: "service-one", Digest: candidateDigest, PreviousDigest: factoryDigest, Tick: 43, CurrentStatus: "OK", PreviousStatus: "OK", TraceID: "health-tick-43"}
	if err := engine.ObserveHealth(context.Background(), observation); err != nil {
		t.Fatal(err)
	}
	service = store.Snapshot().Services["service-one"]
	if service.Status != "watching" || len(service.History) != 1 || service.LastKnownGoodDigest != factoryDigest {
		t.Fatalf("one observation marked candidate green: %+v", service)
	}
	observation.Tick = 44
	observation.TraceID = "health-tick-44"
	if err := engine.ObserveHealth(context.Background(), observation); err != nil {
		t.Fatal(err)
	}
	service = store.Snapshot().Services["service-one"]
	if service.Status != "healthy" || len(service.History) != 2 || service.LastKnownGoodDigest != candidateDigest {
		t.Fatalf("consecutive health window did not mark candidate green: %+v", service)
	}
	secondRunner := &fakeRunner{results: map[string][]RunResult{
		"build":   {{OK: true, Digest: newerDigest, RunnerPolicyVersion: "policy-1"}},
		"gate":    {{OK: true, DataCopyID: "copy-02", RunnerPolicyVersion: "policy-1"}},
		"promote": {{OK: true, Digest: newerDigest, Healthy: boolPointer(true), RecoverySnapshotID: "snapshot-02", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	secondEngine := NewEngine(cfg, manifest, store, repository, secondRunner, fakeQuiet{tick: 45})
	if err := secondEngine.resumeService(context.Background(), "service-one"); err != nil {
		t.Fatal(err)
	}
	if len(secondRunner.requests) != 3 || secondRunner.requests[2].LastKnownGoodDigest != candidateDigest {
		t.Fatalf("later promotion did not use proven current image as LKG: %+v", secondRunner.requests)
	}
	service = store.Snapshot().Services["service-one"]
	if service.Status != "watching" || service.LastKnownGoodDigest != candidateDigest || len(service.History) != 2 {
		t.Fatalf("second unproven candidate changed LKG/history: %+v", service)
	}
}

type blockingQuiet struct {
	once    sync.Once
	entered chan struct{}
	release chan struct{}
}

func (q *blockingQuiet) Wait(ctx context.Context, _ int64) (int64, error) {
	q.once.Do(func() { close(q.entered) })
	select {
	case <-q.release:
		return 42, nil
	case <-ctx.Done():
		return 0, ctx.Err()
	}
}

func TestBlockedQuietWindowDoesNotBlockOtherServiceRollback(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	second := manifest.Services[0]
	second.Slug = "service-two"
	manifest.Services = append(manifest.Services, second)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-service-two"}, func(next *PersistentState) error {
		first := next.Services["service-one"]
		first.Status = "waiting"
		first.CandidateCommit = candidateCommit
		first.CandidateDigest = candidateDigest
		first.GateDataCopyID = "copy-01"
		next.Services["service-one"] = first
		next.Pending["service-one"] = candidateCommit
		factory := first.History[0]
		next.Services["service-two"] = ServiceState{
			Status: "healthy", CurrentCommit: baseCommit, CurrentDigest: factoryDigest,
			LastKnownGoodCommit: baseCommit, LastKnownGoodDigest: factoryDigest,
			FactoryCommit: baseCommit, FactoryDigest: factoryDigest, History: []Artifact{factory}, UpdatedAt: time.Now().UTC(),
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	quiet := &blockingQuiet{entered: make(chan struct{}), release: make(chan struct{})}
	rollbackInvoked := make(chan struct{}, 1)
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
		"promote":  {{OK: true, Digest: candidateDigest, Healthy: boolPointer(true), RecoverySnapshotID: "snapshot-01", RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	runner.before = func(request RunRequest) {
		if request.Service == "service-two" && request.Operation == "rollback" {
			rollbackInvoked <- struct{}{}
		}
	}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{head: baseCommit}, runner, quiet)
	ctx, cancel := context.WithCancel(context.Background())
	runDone := make(chan struct{})
	go func() {
		engine.Run(ctx)
		close(runDone)
	}()
	var releaseOnce sync.Once
	releaseQuiet := func() { releaseOnce.Do(func() { close(quiet.release) }) }
	defer func() {
		cancel()
		releaseQuiet()
		<-runDone
	}()
	select {
	case <-quiet.entered:
	case <-time.After(time.Second):
		t.Fatal("service one did not enter quiet wait")
	}
	if err := engine.ManualRollback(ctx, "service-two", "factory", "operator-01", "rollback-trace-01"); err != nil {
		t.Fatal(err)
	}
	select {
	case <-rollbackInvoked:
	case <-time.After(time.Second):
		t.Fatal("service two runner was not invoked while service one remained in quiet wait")
	}
	select {
	case <-quiet.release:
		t.Fatal("test released service one before service two rollback invocation")
	default:
	}
}

func TestManualRollbackInterruptsSameServiceQuietWait(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-waiting-service"}, func(next *PersistentState) error {
		service := next.Services["service-one"]
		service.Status = "waiting"
		service.CandidateCommit = candidateCommit
		service.CandidateDigest = candidateDigest
		service.GateDataCopyID = "copy-01"
		next.Services["service-one"] = service
		next.Pending["service-one"] = candidateCommit
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	quiet := &blockingQuiet{entered: make(chan struct{}), release: make(chan struct{})}
	rollbackInvoked := make(chan struct{}, 1)
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	runner.before = func(request RunRequest) {
		if request.Operation == "rollback" {
			rollbackInvoked <- struct{}{}
		}
	}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{head: baseCommit}, runner, quiet)
	ctx, cancel := context.WithCancel(context.Background())
	runDone := make(chan struct{})
	go func() {
		engine.Run(ctx)
		close(runDone)
	}()
	defer func() {
		cancel()
		close(quiet.release)
		<-runDone
	}()
	select {
	case <-quiet.entered:
	case <-time.After(time.Second):
		t.Fatal("service did not enter quiet wait")
	}
	if err := engine.ManualRollback(context.Background(), "service-one", "factory", "operator-01", "rollback-trace-01"); err != nil {
		t.Fatal(err)
	}
	select {
	case <-rollbackInvoked:
	case <-time.After(time.Second):
		t.Fatal("same-service rollback did not interrupt quiet wait")
	}
}

func TestBlockedQuietWindowDoesNotBlockOtherServiceAutoRollback(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	second := manifest.Services[0]
	second.Slug = "service-two"
	manifest.Services = append(manifest.Services, second)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-auto-rollback"}, func(next *PersistentState) error {
		first := next.Services["service-one"]
		first.Status = "waiting"
		first.CandidateCommit = candidateCommit
		first.CandidateDigest = candidateDigest
		first.GateDataCopyID = "copy-01"
		next.Services["service-one"] = first
		next.Pending["service-one"] = candidateCommit
		factory := first.History[0]
		next.Services["service-two"] = ServiceState{
			Status: "watching", CurrentCommit: candidateCommit, CurrentDigest: candidateDigest,
			LastKnownGoodCommit: baseCommit, LastKnownGoodDigest: factoryDigest,
			FactoryCommit: baseCommit, FactoryDigest: factoryDigest, PromotionTick: 10,
			History: []Artifact{factory}, UpdatedAt: time.Now().UTC(),
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	quiet := &blockingQuiet{entered: make(chan struct{}), release: make(chan struct{})}
	rollbackInvoked := make(chan struct{}, 1)
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	runner.before = func(request RunRequest) {
		if request.Service == "service-two" && request.Operation == "rollback" {
			rollbackInvoked <- struct{}{}
		}
	}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{head: baseCommit}, runner, quiet)
	ctx, cancel := context.WithCancel(context.Background())
	runDone := make(chan struct{})
	go func() {
		engine.Run(ctx)
		close(runDone)
	}()
	defer func() {
		cancel()
		close(quiet.release)
		<-runDone
	}()
	select {
	case <-quiet.entered:
	case <-time.After(time.Second):
		t.Fatal("service one did not enter quiet wait")
	}
	observation := HealthObservation{Service: "service-two", Digest: candidateDigest, PreviousDigest: factoryDigest, Tick: 11, CurrentStatus: "DOWN", PreviousStatus: "OK", TraceID: "health-auto-11"}
	if err := engine.ObserveHealth(context.Background(), observation); err != nil {
		t.Fatal(err)
	}
	observation.Tick = 12
	observation.TraceID = "health-auto-12"
	if err := engine.ObserveHealth(context.Background(), observation); err != nil {
		t.Fatal(err)
	}
	select {
	case <-rollbackInvoked:
	case <-time.After(time.Second):
		t.Fatal("service two automatic rollback runner was not invoked while service one remained in quiet wait")
	}
	select {
	case <-quiet.release:
		t.Fatal("test released service one before service two automatic rollback invocation")
	default:
	}
}

func TestOperatorInterventionKeepsNewerPendingCandidate(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "seed", ActorID: "test", TraceID: "seed-operator-intervention"}, func(next *PersistentState) error {
		service := next.Services["service-one"]
		service.Status = "watching"
		service.CurrentCommit = candidateCommit
		service.CurrentDigest = candidateDigest
		service.LastKnownGoodCommit = baseCommit
		service.LastKnownGoodDigest = factoryDigest
		next.Services["service-one"] = service
		next.Pending["service-one"] = newerCommit
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: false, RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{}, runner, fakeQuiet{})
	if err := engine.ManualRollback(context.Background(), "service-one", "factory", "operator-01", "manual-rollback-01"); err != nil {
		t.Fatal(err)
	}
	queued := store.Snapshot().Services["service-one"]
	if queued.Status != "rolling-back" || queued.Intent == nil || queued.Intent.Stage != "manual-rollback" {
		t.Fatalf("manual rollback was not durably queued: %+v", queued)
	}
	if err := engine.resumeService(context.Background(), "service-one"); err == nil {
		t.Fatal("failed rollback did not require operator intervention")
	}
	state := store.Snapshot()
	service := state.Services["service-one"]
	if service.Status != "operator-intervention" || service.Intent != nil {
		t.Fatalf("failed rollback did not stop for operator intervention: %+v", service)
	}
	if state.Pending["service-one"] != newerCommit {
		t.Fatalf("operator intervention lost newer pending candidate: %+v", state.Pending)
	}
	if len(service.History) != 1 || service.History[0].Digest != factoryDigest {
		t.Fatalf("operator intervention changed proven history: %+v", service.History)
	}
}
