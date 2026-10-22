package orchestrator

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHostPreflightRequiresExactFilesModesAndTypes(t *testing.T) {
	root := t.TempDir()
	uid := uint32(os.Getuid())
	gid := uint32(os.Getgid())
	requirements := []struct {
		path      string
		mode      os.FileMode
		directory bool
	}{
		{"/etc/deployment-orchestrator", 0700, true},
		{"/etc/deployment-orchestrator/config.json", 0600, false},
		{"/etc/deployment-orchestrator/services.json", 0600, false},
		{"/etc/deployment-orchestrator/webhook.secret", 0600, false},
		{"/etc/deployment-orchestrator/anvil.token", 0600, false},
		{"/usr/local/libexec/deployment-orchestrator/runner", 0755, false},
		{"/var/lib/deployment-orchestrator", 0710, true},
		{"/var/lib/deployment-orchestrator/repository", 0750, true},
		{"/var/lib/deployment-orchestrator/offline.lock", 0600, false},
		{"/var/lib/deployment-orchestrator/state.json", 0600, false},
		{"/var/lib/deployment-orchestrator/audit.jsonl", 0600, false},
	}
	for _, requirement := range requirements {
		path := filepath.Join(root, strings.TrimPrefix(requirement.path, "/"))
		if requirement.directory {
			if err := os.MkdirAll(path, requirement.mode); err != nil {
				t.Fatal(err)
			}
			if err := os.Chmod(path, requirement.mode); err != nil {
				t.Fatal(err)
			}
		} else {
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("fixture\n"), requirement.mode); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := validateHostPaths(root, uid, gid, uid, gid); err != nil {
		t.Fatal(err)
	}
	config := filepath.Join(root, "etc/deployment-orchestrator/config.json")
	if err := os.Chmod(config, 0644); err != nil {
		t.Fatal(err)
	}
	if err := validateHostPaths(root, uid, gid, uid, gid); err == nil {
		t.Fatal("world-readable configuration passed host preflight")
	}
	if err := os.Chmod(config, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(config); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("services.json", config); err != nil {
		t.Fatal(err)
	}
	if err := validateHostPaths(root, uid, gid, uid, gid); err == nil {
		t.Fatal("symlinked configuration passed host preflight")
	}
}
