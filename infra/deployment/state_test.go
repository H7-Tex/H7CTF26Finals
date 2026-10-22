package orchestrator

import (
	"os"
	"path/filepath"
	"testing"
)

func newInitializationFixture(t *testing.T) (*Config, *Manifest, PersistentState) {
	t.Helper()
	cfg, manifest, _ := testFixture(t)
	cfg.StateDirectory = t.TempDir()
	return cfg, manifest, InitialState(cfg, manifest, "manifest")
}

func TestInitializeStoreIsRetrySafeAfterCompleteInitialization(t *testing.T) {
	cfg, manifest, initial := newInitializationFixture(t)
	if err := InitializeStore(cfg.StateDirectory, initial); err != nil {
		t.Fatal(err)
	}
	if err := InitializeStore(cfg.StateDirectory, InitialState(cfg, manifest, "manifest")); err != nil {
		t.Fatalf("retry of pristine initialization failed: %v", err)
	}
	if _, err := OpenStore(cfg, "manifest"); err != nil {
		t.Fatal(err)
	}
}

func TestInitializeStoreRecoversStateOnlyPartialCreation(t *testing.T) {
	cfg, _, initial := newInitializationFixture(t)
	if err := writeState(filepath.Join(cfg.StateDirectory, "state.json"), initial); err != nil {
		t.Fatal(err)
	}
	if err := InitializeStore(cfg.StateDirectory, initial); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, "manifest"); err != nil {
		t.Fatal(err)
	}
}

func TestInitializeStoreRecoversAuditOnlyPartialCreation(t *testing.T) {
	cfg, _, initial := newInitializationFixture(t)
	audit, err := os.OpenFile(filepath.Join(cfg.StateDirectory, "audit.jsonl"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if err := audit.Close(); err != nil {
		t.Fatal(err)
	}
	if err := InitializeStore(cfg.StateDirectory, initial); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, "manifest"); err != nil {
		t.Fatal(err)
	}
}

func TestInitializeStoreRejectsNonPristineExistingStore(t *testing.T) {
	cfg, _, initial := newInitializationFixture(t)
	if err := InitializeStore(cfg.StateDirectory, initial); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(cfg, "manifest")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Update(AuditEvent{Action: "test", Outcome: "changed", ActorID: "test", TraceID: "changed-state"}, nil); err != nil {
		t.Fatal(err)
	}
	if err := InitializeStore(cfg.StateDirectory, initial); err == nil {
		t.Fatal("non-pristine store was accepted as an initialization retry")
	}
}

func TestOpenStoreTruncatesOneCompleteAuditTail(t *testing.T) {
	cfg, _, store := testFixture(t)
	if err := store.Update(AuditEvent{Action: "test", Outcome: "first", ActorID: "test", TraceID: "audit-first"}, nil); err != nil {
		t.Fatal(err)
	}
	event := AuditEvent{Sequence: 2, Action: "test", Outcome: "orphan", ActorID: "test", TraceID: "audit-orphan", TeamID: cfg.TeamID}
	if err := appendAudit(filepath.Join(cfg.StateDirectory, "audit.jsonl"), event); err != nil {
		t.Fatal(err)
	}
	reopened, err := OpenStore(cfg, "manifest")
	if err != nil {
		t.Fatal(err)
	}
	events, err := reopened.Audit(0, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 1 || events[0].Sequence != 1 || reopened.Snapshot().NextSequence != 1 {
		t.Fatalf("complete orphan tail was not truncated: events=%+v state=%+v", events, reopened.Snapshot())
	}
	if err := reopened.Update(AuditEvent{Action: "test", Outcome: "second", ActorID: "test", TraceID: "audit-second"}, nil); err != nil {
		t.Fatal(err)
	}
	again, err := OpenStore(cfg, "manifest")
	if err != nil {
		t.Fatal(err)
	}
	if again.Snapshot().NextSequence != 2 {
		t.Fatalf("store did not advance after tail recovery: %+v", again.Snapshot())
	}
}

func TestOpenStoreTruncatesOnePartialAuditTail(t *testing.T) {
	cfg, _, _ := testFixture(t)
	auditPath := filepath.Join(cfg.StateDirectory, "audit.jsonl")
	file, err := os.OpenFile(auditPath, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.WriteString(`{"sequence":1,"team_id":"` + cfg.TeamID); err != nil {
		file.Close()
		t.Fatal(err)
	}
	if err := file.Sync(); err != nil {
		file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, "manifest"); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(auditPath)
	if err != nil {
		t.Fatal(err)
	}
	if info.Size() != 0 {
		t.Fatalf("partial audit tail remains: size=%d", info.Size())
	}
}

func TestOpenStoreRejectsNonTailAuditDivergence(t *testing.T) {
	cfg, _, _ := testFixture(t)
	auditPath := filepath.Join(cfg.StateDirectory, "audit.jsonl")
	for sequence := uint64(1); sequence <= 2; sequence++ {
		if err := appendAudit(auditPath, AuditEvent{Sequence: sequence, Action: "test", Outcome: "orphan", ActorID: "test", TraceID: "audit-orphan", TeamID: cfg.TeamID}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := OpenStore(cfg, "manifest"); err == nil {
		t.Fatal("two audit records ahead of state were accepted")
	}
}

func TestOpenStoreRejectsMalformedCompleteAuditRecord(t *testing.T) {
	cfg, _, _ := testFixture(t)
	auditPath := filepath.Join(cfg.StateDirectory, "audit.jsonl")
	file, err := os.OpenFile(auditPath, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.WriteString("not-json\n"); err != nil {
		file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, "manifest"); err == nil {
		t.Fatal("malformed complete audit record was accepted")
	}
}
