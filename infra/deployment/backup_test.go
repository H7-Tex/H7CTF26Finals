package orchestrator

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func backupFixture(t *testing.T) (string, string, *Config, *Store, string, string) {
	t.Helper()
	root := t.TempDir()
	stateDirectory := filepath.Join(root, "state")
	if err := os.Mkdir(stateDirectory, 0710); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(stateDirectory, "offline.lock"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	executorStateDirectory := filepath.Join(root, "executor")
	if err := os.Mkdir(executorStateDirectory, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(executorStateDirectory, "offline.lock"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	servicesPath := filepath.Join(root, "services.json")
	services := `{
  "schema_version": 1,
  "policy_version": "finals-1",
  "services": [{
    "slug": "sign-me-in",
    "base_commit": "1111111111111111111111111111111111111111",
    "bundle_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "factory_digest": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
    "allowed_paths": ["src/"],
    "maximum_context_bytes": 1048576,
    "memory_bytes": 134217728,
    "cpu_millis": 500,
    "pids": 64,
    "build_timeout": "5s",
    "gate_timeout": "5s",
    "promotion_timeout": "5s",
    "health_timeout": "5s",
    "previous_flag_ticks": 5
  }]
}`
	if err := os.WriteFile(servicesPath, []byte(services), 0600); err != nil {
		t.Fatal(err)
	}
	configPath := filepath.Join(root, "config.json")
	config := map[string]any{
		"team_number": 1, "team_id": "11111111-1111-4111-8111-111111111111", "listen_address": "0.0.0.0:9300",
		"state_directory": stateDirectory,
		"repository":      map[string]any{"path": "/var/lib/deployment-orchestrator/repository", "remote_url": "ssh://git@10.60.201.30/team-01/services.git", "expected_full_name": "team-01/services", "branch": "main", "initial_commit": "1111111111111111111111111111111111111111"},
		"services_file":   servicesPath, "webhook_secret_file": "/etc/deployment-orchestrator/webhook.secret", "internal_token_file": "/etc/deployment-orchestrator/anvil.token", "runner_command": "/usr/local/libexec/deployment-orchestrator/runner",
		"tick_url": "https://finals.h7tex.com/api/v1/arena/tick", "poll_interval": "15s", "maximum_body_bytes": 1048576, "expected_services": 1,
	}
	data, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(configPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	cfg, err := loadConfigMetadata(configPath)
	if err != nil {
		t.Fatal(err)
	}
	manifest, err := LoadManifest(servicesPath, 1)
	if err != nil {
		t.Fatal(err)
	}
	manifestHash, err := ManifestHash(servicesPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := InitializeStore(stateDirectory, InitialState(cfg, manifest, manifestHash)); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(cfg, manifestHash)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Update(AuditEvent{Action: "test", Outcome: "first", ActorID: "test", TraceID: "backup-first"}, nil); err != nil {
		t.Fatal(err)
	}
	return configPath, servicesPath, cfg, store, manifestHash, executorStateDirectory
}

func TestOfflineBackupAndRestorePreserveStateAuditPair(t *testing.T) {
	configPath, servicesPath, cfg, store, manifestHash, executorStateDirectory := backupFixture(t)
	destination := t.TempDir()
	if err := os.Chmod(destination, 0700); err != nil {
		t.Fatal(err)
	}
	uid, gid := uint32(os.Getuid()), uint32(os.Getgid())
	backup, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Update(AuditEvent{Action: "test", Outcome: "second", ActorID: "test", TraceID: "backup-second"}, nil); err != nil {
		t.Fatal(err)
	}
	if err := restoreState(configPath, servicesPath, backup, cfg.TeamID, uid, gid, executorStateDirectory); err != nil {
		t.Fatal(err)
	}
	restored, err := OpenStore(cfg, manifestHash)
	if err != nil {
		t.Fatal(err)
	}
	if restored.Snapshot().NextSequence != 1 {
		t.Fatalf("restore did not recover the backed-up sequence: %d", restored.Snapshot().NextSequence)
	}
	events, err := restored.Audit(0, 10)
	if err != nil || len(events) != 1 || events[0].TraceID != "backup-first" {
		t.Fatalf("restore did not recover matching audit: %+v, %v", events, err)
	}
}

func TestOfflineBackupRequiresExclusiveLockAndPrivateUntamperedInput(t *testing.T) {
	configPath, servicesPath, cfg, _, _, executorStateDirectory := backupFixture(t)
	destination := t.TempDir()
	if err := os.Chmod(destination, 0700); err != nil {
		t.Fatal(err)
	}
	uid, gid := uint32(os.Getuid()), uint32(os.Getgid())
	lock, err := AcquireStateLock(cfg.StateDirectory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory); err == nil || !strings.Contains(err.Error(), "in use") {
		t.Fatalf("backup ran while state was active: %v", err)
	}
	if err := lock.Close(); err != nil {
		t.Fatal(err)
	}
	executorLock, err := AcquireStateLock(executorStateDirectory)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory); err == nil || !strings.Contains(err.Error(), "executor: deployment state is in use") {
		t.Fatalf("backup ran while executor was active: %v", err)
	}
	if err := executorLock.Close(); err != nil {
		t.Fatal(err)
	}
	backup, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory)
	if err != nil {
		t.Fatal(err)
	}
	statePath := filepath.Join(backup, "state.json")
	if err := os.WriteFile(statePath, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := restoreState(configPath, servicesPath, backup, cfg.TeamID, uid, gid, executorStateDirectory); err == nil || !strings.Contains(err.Error(), "digest mismatch") {
		t.Fatalf("tampered backup was accepted: %v", err)
	}
	if err := restoreState(configPath, servicesPath, backup, "22222222-2222-4222-8222-222222222222", uid, gid, executorStateDirectory); err == nil || !strings.Contains(err.Error(), "confirmation") {
		t.Fatalf("wrong team confirmation was accepted: %v", err)
	}
}

func TestRestoreMarkerFailsClosedAndMatchingRetryCompletes(t *testing.T) {
	configPath, servicesPath, cfg, _, manifestHash, executorStateDirectory := backupFixture(t)
	destination := t.TempDir()
	if err := os.Chmod(destination, 0700); err != nil {
		t.Fatal(err)
	}
	uid, gid := uint32(os.Getuid()), uint32(os.Getgid())
	backup, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory)
	if err != nil {
		t.Fatal(err)
	}
	_, metadataHash, err := validateBackupDirectory(backup, cfg, manifestHash, uid, gid)
	if err != nil {
		t.Fatal(err)
	}
	marker := restoreMarker{SchemaVersion: 1, BackupSHA256: metadataHash}
	if err := writePrivateJSON(filepath.Join(cfg.StateDirectory, restoreMarkerName), marker, uid, gid); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, manifestHash); err == nil || !strings.Contains(err.Error(), "restore is incomplete") {
		t.Fatalf("store opened across incomplete restore: %v", err)
	}
	if _, err := backupState(configPath, servicesPath, destination, uid, gid, executorStateDirectory); err == nil || !strings.Contains(err.Error(), "restore is incomplete") {
		t.Fatalf("backup ignored incomplete restore: %v", err)
	}
	if err := restoreState(configPath, servicesPath, backup, cfg.TeamID, uid, gid, executorStateDirectory); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenStore(cfg, manifestHash); err != nil {
		t.Fatal(err)
	}
}
