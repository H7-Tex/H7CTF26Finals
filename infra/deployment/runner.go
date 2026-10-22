package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

type ResourceContract struct {
	NetworkMode         string `json:"network_mode"`
	MaximumContextBytes int64  `json:"maximum_context_bytes"`
	MemoryBytes         int64  `json:"memory_bytes"`
	CPUMillis           int    `json:"cpu_millis"`
	PIDs                int    `json:"pids"`
	TimeoutSeconds      int64  `json:"timeout_seconds"`
}

type RunRequest struct {
	SchemaVersion       int              `json:"schema_version"`
	Operation           string           `json:"operation"`
	OperationID         string           `json:"operation_id"`
	TeamID              string           `json:"team_id"`
	TeamNumber          int              `json:"team_number"`
	Service             string           `json:"service"`
	RepositoryPath      string           `json:"repository_path,omitempty"`
	Commit              string           `json:"commit,omitempty"`
	BaseCommit          string           `json:"base_commit,omitempty"`
	BundleSHA256        string           `json:"bundle_sha256,omitempty"`
	PolicyVersion       string           `json:"policy_version"`
	CandidateDigest     string           `json:"candidate_digest,omitempty"`
	TargetDigest        string           `json:"target_digest,omitempty"`
	CurrentDigest       string           `json:"current_digest,omitempty"`
	LastKnownGoodDigest string           `json:"last_known_good_digest,omitempty"`
	FactoryDigest       string           `json:"factory_digest"`
	DataMode            string           `json:"data_mode,omitempty"`
	PreviousFlagTicks   int              `json:"previous_flag_ticks,omitempty"`
	PromotionTick       int64            `json:"promotion_tick,omitempty"`
	Resources           ResourceContract `json:"resources"`
}

type RunResult struct {
	OK                  bool   `json:"ok"`
	Digest              string `json:"digest,omitempty"`
	Healthy             *bool  `json:"healthy,omitempty"`
	DataCopyID          string `json:"data_copy_id,omitempty"`
	RecoverySnapshotID  string `json:"recovery_snapshot_id,omitempty"`
	PublicMessage       string `json:"public_message,omitempty"`
	RunnerPolicyVersion string `json:"runner_policy_version"`
}

type Runner interface {
	Run(context.Context, RunRequest) (RunResult, error)
}

type CommandRunner struct {
	Command string
}

func (r CommandRunner) Run(ctx context.Context, request RunRequest) (RunResult, error) {
	if !validOperation(request.Operation) {
		return RunResult{}, errors.New("invalid runner operation")
	}
	payload, err := json.Marshal(request)
	if err != nil {
		return RunResult{}, err
	}
	command := exec.CommandContext(ctx, r.Command, request.Operation)
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	command.Cancel = func() error {
		if command.Process == nil {
			return os.ErrProcessDone
		}
		if err := syscall.Kill(-command.Process.Pid, syscall.SIGKILL); err != nil {
			if errors.Is(err, syscall.ESRCH) {
				return os.ErrProcessDone
			}
			return err
		}
		return nil
	}
	command.WaitDelay = 2 * time.Second
	command.Stdin = bytes.NewReader(payload)
	stdout := &cappedBuffer{maximum: 64 * 1024}
	stderr := &cappedBuffer{maximum: 64 * 1024}
	command.Stdout = stdout
	command.Stderr = stderr
	if err := command.Run(); err != nil {
		return RunResult{}, fmt.Errorf("runner %s failed: %w: %s", request.Operation, err, boundedMessage(stderr.String()))
	}
	if stdout.exceeded {
		return RunResult{}, errors.New("runner output exceeded 64 KiB")
	}
	var result RunResult
	decoder := json.NewDecoder(bytes.NewReader(stdout.Bytes()))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&result); err != nil {
		return RunResult{}, fmt.Errorf("decode runner output: %w", err)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return RunResult{}, errors.New("runner returned multiple JSON values")
	}
	result.PublicMessage = boundedMessage(result.PublicMessage)
	return result, nil
}

func validOperation(value string) bool {
	switch value {
	case "build", "gate", "promote", "rollback", "health":
		return true
	default:
		return false
	}
}

func boundedMessage(value string) string {
	value = strings.Map(func(r rune) rune {
		if r == '\n' || r == '\r' || r == '\t' || r < 0x20 || r == 0x7f {
			return ' '
		}
		return r
	}, value)
	value = strings.TrimSpace(value)
	if len(value) > 512 {
		value = value[:512]
	}
	return value
}

type cappedBuffer struct {
	buffer   bytes.Buffer
	maximum  int
	exceeded bool
}

func (b *cappedBuffer) Write(value []byte) (int, error) {
	remaining := b.maximum - b.buffer.Len()
	if remaining > 0 {
		write := len(value)
		if write > remaining {
			write = remaining
		}
		_, _ = b.buffer.Write(value[:write])
	}
	if len(value) > remaining {
		b.exceeded = true
	}
	return len(value), nil
}

func (b *cappedBuffer) Bytes() []byte  { return b.buffer.Bytes() }
func (b *cappedBuffer) String() string { return b.buffer.String() }
