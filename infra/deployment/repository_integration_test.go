package orchestrator

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestGitRepositoryLostWebhookReconciliation(t *testing.T) {
	if _, err := os.Stat("/usr/bin/git"); err != nil {
		t.Skip("git is unavailable")
	}
	root := t.TempDir()
	remote := filepath.Join(root, "remote.git")
	work := filepath.Join(root, "work")
	local := filepath.Join(root, "local")
	runGit(t, root, "init", "--bare", "--initial-branch=main", remote)
	runGit(t, root, "clone", remote, work)
	runGit(t, work, "config", "user.email", "test@example.invalid")
	runGit(t, work, "config", "user.name", "Test")
	if err := os.MkdirAll(filepath.Join(work, "service-one", "src"), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(work, "service-one", "src", "main.go"), []byte("package main\n"), 0644); err != nil {
		t.Fatal(err)
	}
	runGit(t, work, "add", ".")
	runGit(t, work, "commit", "-m", "initial")
	runGit(t, work, "push", "origin", "main")
	initial := strings.TrimSpace(runGit(t, work, "rev-parse", "HEAD"))
	runGit(t, root, "clone", remote, local)

	if err := os.WriteFile(filepath.Join(work, "service-one", "src", "main.go"), []byte("package main\nfunc main() {}\n"), 0644); err != nil {
		t.Fatal(err)
	}
	runGit(t, work, "add", ".")
	runGit(t, work, "commit", "-m", "patch")
	runGit(t, work, "push", "origin", "main")
	patched := strings.TrimSpace(runGit(t, work, "rev-parse", "HEAD"))

	repository := GitRepository{Config: RepositoryConfig{Path: local, RemoteURL: remote, Branch: "main"}}
	head, err := repository.FetchRemoteHead(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if head != patched {
		t.Fatalf("remote head=%s want=%s", head, patched)
	}
	ancestor, err := repository.IsAncestor(context.Background(), initial, patched)
	if err != nil || !ancestor {
		t.Fatalf("ancestry=%v err=%v", ancestor, err)
	}
	paths, err := repository.DiffPaths(context.Background(), initial, patched, "service-one")
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) != 1 || paths[0] != "service-one/src/main.go" {
		t.Fatalf("unexpected paths: %v", paths)
	}
	if size, err := repository.TreeSize(context.Background(), patched, "service-one"); err != nil || size == 0 {
		t.Fatalf("tree size=%d err=%v", size, err)
	}
}

func runGit(t *testing.T, directory string, arguments ...string) string {
	t.Helper()
	command := exec.Command("/usr/bin/git", arguments...)
	command.Dir = directory
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", arguments, err, output)
	}
	return string(output)
}
