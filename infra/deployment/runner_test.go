package orchestrator

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestCommandRunnerCancellationKillsProcessGroup(t *testing.T) {
	directory := t.TempDir()
	marker := filepath.Join(directory, "orphan-ran")
	runnerPath := filepath.Join(directory, "runner")
	script := "#!/bin/sh\n(sleep 0.4; printf orphan > '" + marker + "') &\nwait\n"
	if err := os.WriteFile(runnerPath, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Millisecond)
	defer cancel()
	_, err := (CommandRunner{Command: runnerPath}).Run(ctx, RunRequest{Operation: "build"})
	if err == nil {
		t.Fatal("timed-out runner returned nil")
	}
	time.Sleep(500 * time.Millisecond)
	if _, statErr := os.Stat(marker); !errors.Is(statErr, os.ErrNotExist) {
		t.Fatalf("runner descendant survived cancellation: %v", statErr)
	}
}
