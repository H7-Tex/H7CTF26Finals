package orchestrator

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

const (
	testCommit  = "1111111111111111111111111111111111111111"
	testBase    = "2222222222222222222222222222222222222222"
	testBundle  = "3333333333333333333333333333333333333333333333333333333333333333"
	testFactory = "sha256:4444444444444444444444444444444444444444444444444444444444444444"
	testBuilt   = "sha256:5555555555555555555555555555555555555555555555555555555555555555"
)

func executorFixture(t *testing.T) (*Executor, RunRequest, string) {
	t.Helper()
	directory := t.TempDir()
	if err := os.Chmod(directory, 0700); err != nil {
		t.Fatal(err)
	}
	counter := filepath.Join(directory, "counter")
	backend := filepath.Join(directory, "backend")
	script := "#!/bin/sh\nset -eu\ncat >/dev/null\ncount=0\n[ ! -f '" + counter + "' ] || count=$(cat '" + counter + "')\ncount=$((count + 1))\nprintf '%s\\n' \"$count\" > '" + counter + "'\ncase \"$1\" in\n  build) result='{\"ok\":true,\"digest\":\"" + testBuilt + "\",\"runner_policy_version\":\"finals-1\"}' ;;\n  gate) result='{\"ok\":true,\"data_copy_id\":\"copy-01\",\"runner_policy_version\":\"finals-1\"}' ;;\n  promote) result='{\"ok\":true,\"digest\":\"" + testBuilt + "\",\"healthy\":true,\"recovery_snapshot_id\":\"snapshot-01\",\"runner_policy_version\":\"finals-1\"}' ;;\n  rollback|health) result='{\"ok\":true,\"digest\":\"" + testFactory + "\",\"healthy\":true,\"runner_policy_version\":\"finals-1\"}' ;;\n  *) exit 2 ;;\nesac\nprintf '%s\\n' \"$result\"\n"
	if err := os.WriteFile(backend, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	policy := &ExecutorPolicy{
		SchemaVersion: 1, AllowedUID: uint32(os.Getuid()), TeamID: "11111111-1111-4111-8111-111111111111", TeamNumber: 1,
		RepositoryPath: "/var/lib/deployment-orchestrator/repository", PolicyVersion: "finals-1",
		Commands: ExecutorCommands{Build: backend, Gate: backend, Promote: backend, Rollback: backend, Health: backend},
		Services: map[string]ExecutorServicePolicy{"sign-me-in": {
			BaseCommit: testBase, BundleSHA256: testBundle, FactoryDigest: testFactory,
			Resources:           ResourceContract{NetworkMode: "none", MaximumContextBytes: 1024, MemoryBytes: 64 * 1024 * 1024, CPUMillis: 100, PIDs: 16},
			BuildTimeoutSeconds: 5, GateTimeoutSeconds: 5, DeployTimeoutSeconds: 5, HealthTimeoutSeconds: 5, PreviousFlagTicks: 5,
		}},
	}
	executor, err := newExecutor(policy, directory, uint32(os.Getuid()), uint32(os.Getgid()))
	if err != nil {
		t.Fatal(err)
	}
	request := RunRequest{
		SchemaVersion: 1, Operation: "build", OperationID: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		TeamID: policy.TeamID, TeamNumber: 1, Service: "sign-me-in", RepositoryPath: policy.RepositoryPath,
		Commit: testCommit, BaseCommit: testBase, BundleSHA256: testBundle, PolicyVersion: "finals-1", FactoryDigest: testFactory,
		Resources: ResourceContract{NetworkMode: "none", MaximumContextBytes: 1024, MemoryBytes: 64 * 1024 * 1024, CPUMillis: 100, PIDs: 16, TimeoutSeconds: 5},
	}
	return executor, request, counter
}

func TestExecutorAuthorizesSchemaAndReplaysCompletedOperation(t *testing.T) {
	executor, request, counter := executorFixture(t)
	result, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, request)
	if err != nil {
		t.Fatal(err)
	}
	if !result.OK || result.Digest != testBuilt {
		t.Fatalf("unexpected result: %#v", result)
	}
	if _, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, request); err != nil {
		t.Fatal(err)
	}
	count, err := os.ReadFile(counter)
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(count)) != "1" {
		t.Fatalf("backend ran %q times", count)
	}

	different := request
	different.Commit = "6666666666666666666666666666666666666666"
	if _, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, different); err == nil || !strings.Contains(err.Error(), "reused") {
		t.Fatalf("operation ID conflict was accepted: %v", err)
	}
}

func TestExecutorRunsEveryDigestOnlyBackendOperation(t *testing.T) {
	executor, build, counter := executorFixture(t)
	requests := []RunRequest{build}
	gate := build
	gate.Operation, gate.OperationID = "gate", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	gate.CandidateDigest, gate.DataMode, gate.PreviousFlagTicks = testBuilt, "copy-current", 5
	requests = append(requests, gate)
	promote := build
	promote.Operation, promote.OperationID = "promote", "cccccccccccccccccccccccccccccccc"
	promote.CandidateDigest, promote.CurrentDigest, promote.LastKnownGoodDigest = testBuilt, testFactory, testFactory
	promote.DataMode, promote.PromotionTick = "preserve-current", 42
	requests = append(requests, promote)
	rollback := build
	rollback.Operation, rollback.OperationID = "rollback", "dddddddddddddddddddddddddddddddd"
	rollback.TargetDigest, rollback.CurrentDigest, rollback.DataMode = testFactory, testBuilt, "preserve-current"
	requests = append(requests, rollback)
	health := RunRequest{
		SchemaVersion: 1, Operation: "health", OperationID: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
		TeamID: build.TeamID, TeamNumber: build.TeamNumber, Service: build.Service, PolicyVersion: build.PolicyVersion,
		TargetDigest: testFactory, FactoryDigest: testFactory, DataMode: "preserve-current",
		Resources: ResourceContract{NetworkMode: "none", TimeoutSeconds: 5},
	}
	requests = append(requests, health)
	for _, request := range requests {
		result, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, request)
		if err != nil || !result.OK {
			t.Fatalf("%s failed: %#v, %v", request.Operation, result, err)
		}
	}
	count, err := os.ReadFile(counter)
	if err != nil || strings.TrimSpace(string(count)) != "5" {
		t.Fatalf("fake container backend count=%q error=%v", count, err)
	}
}

func TestExecutorBlockedServiceDoesNotDelayOtherService(t *testing.T) {
	executor, base, _ := executorFixture(t)
	directory := executor.StateDirectory
	started := filepath.Join(directory, "gate-started")
	unblock := filepath.Join(directory, "gate-unblock")
	gateBackend := filepath.Join(directory, "gate-backend")
	gateScript := "#!/bin/sh\nset -eu\ncat >/dev/null\n: > '" + started + "'\nwhile [ ! -f '" + unblock + "' ]; do sleep 0.01; done\nprintf '%s\\n' '{\"ok\":true,\"data_copy_id\":\"copy-01\",\"runner_policy_version\":\"finals-1\"}'\n"
	if err := os.WriteFile(gateBackend, []byte(gateScript), 0700); err != nil {
		t.Fatal(err)
	}
	executor.Policy.Commands.Gate = gateBackend
	second := executor.Policy.Services[base.Service]
	executor.Policy.Services["service-two"] = second
	gate := base
	gate.Operation, gate.OperationID = "gate", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	gate.CandidateDigest, gate.DataMode, gate.PreviousFlagTicks = testBuilt, "copy-current", 5
	gateDone := make(chan error, 1)
	go func() {
		_, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, gate)
		gateDone <- err
	}()
	deadline := time.Now().Add(2 * time.Second)
	for {
		if _, err := os.Stat(started); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("blocking gate backend did not start")
		}
		time.Sleep(5 * time.Millisecond)
	}
	rollback := base
	rollback.Operation, rollback.OperationID, rollback.Service = "rollback", "cccccccccccccccccccccccccccccccc", "service-two"
	rollback.TargetDigest, rollback.CurrentDigest, rollback.DataMode = testFactory, testBuilt, "preserve-current"
	rollbackContext, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	result, err := executor.Execute(rollbackContext, executor.Policy.AllowedUID, rollback)
	if err != nil || !result.OK {
		t.Fatalf("other-service rollback was delayed by blocked gate: %#v, %v", result, err)
	}
	if err := os.WriteFile(unblock, nil, 0600); err != nil {
		t.Fatal(err)
	}
	select {
	case err := <-gateDone:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("gate backend did not finish")
	}
}

func TestExecutorRetriesExactPendingOperationAndRejectsUnauthorizedPeer(t *testing.T) {
	executor, request, counter := executorFixture(t)
	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256Bytes(payload)
	record := executorRecord{SchemaVersion: 1, RequestSHA256: digest, Request: request, Status: "pending"}
	path := filepath.Join(executor.StateDirectory, "operations", request.OperationID+".json")
	if err := writeExecutorRecord(path, record); err != nil {
		t.Fatal(err)
	}
	if _, err := executor.Execute(context.Background(), executor.Policy.AllowedUID+1, request); err == nil || !strings.Contains(err.Error(), "not authorized") {
		t.Fatalf("unauthorized peer was accepted: %v", err)
	}
	if _, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, request); err != nil {
		t.Fatal(err)
	}
	count, err := os.ReadFile(counter)
	if err != nil || strings.TrimSpace(string(count)) != "1" {
		t.Fatalf("pending operation did not execute exactly once: %q, %v", count, err)
	}
}

func TestExecutorRejectsPolicyAndOperationShapeChanges(t *testing.T) {
	executor, request, _ := executorFixture(t)
	tests := []func(*RunRequest){
		func(value *RunRequest) { value.SchemaVersion = 2 },
		func(value *RunRequest) { value.Operation = "shell" },
		func(value *RunRequest) { value.TeamNumber = 2 },
		func(value *RunRequest) { value.Service = "unknown" },
		func(value *RunRequest) { value.FactoryDigest = "latest" },
		func(value *RunRequest) { value.Resources.NetworkMode = "host" },
		func(value *RunRequest) { value.DataMode = "preserve-current" },
	}
	for index, mutate := range tests {
		candidate := request
		candidate.OperationID = strings.Repeat(strconv.FormatInt(int64(index+1), 16), 32)[:32]
		mutate(&candidate)
		if _, err := executor.Execute(context.Background(), executor.Policy.AllowedUID, candidate); err == nil {
			t.Fatalf("invalid request %d was accepted", index)
		}
	}
}

func TestExecutorPolicyRequiresPrivatePolicyAndRootOnlyCommands(t *testing.T) {
	directory := t.TempDir()
	if err := os.Chmod(directory, 0700); err != nil {
		t.Fatal(err)
	}
	backend := filepath.Join(directory, "backend")
	if err := os.WriteFile(backend, []byte("#!/bin/sh\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	policy := ExecutorPolicy{
		SchemaVersion: 1, AllowedUID: 1234, TeamID: "11111111-1111-4111-8111-111111111111", TeamNumber: 1,
		RepositoryPath: "/var/lib/deployment-orchestrator/repository", PolicyVersion: "finals-1",
		Commands: ExecutorCommands{Build: backend, Gate: backend, Promote: backend, Rollback: backend, Health: backend},
		Services: map[string]ExecutorServicePolicy{"sign-me-in": {
			BaseCommit: testBase, BundleSHA256: testBundle, FactoryDigest: testFactory,
			Resources:           ResourceContract{NetworkMode: "none", MaximumContextBytes: 1024, MemoryBytes: 64 * 1024 * 1024, CPUMillis: 100, PIDs: 16},
			BuildTimeoutSeconds: 5, GateTimeoutSeconds: 5, DeployTimeoutSeconds: 5, HealthTimeoutSeconds: 5, PreviousFlagTicks: 5,
		}},
	}
	data, err := json.Marshal(policy)
	if err != nil {
		t.Fatal(err)
	}
	policyPath := filepath.Join(directory, "policy.json")
	if err := os.WriteFile(policyPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	uid, gid := uint32(os.Getuid()), uint32(os.Getgid())
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err != nil {
		t.Fatal(err)
	}
	partial := policy
	partial.Commands.Health = ""
	partialData, err := json.Marshal(partial)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(policyPath, partialData, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err == nil {
		t.Fatal("partial executor command set was accepted")
	}
	if err := os.WriteFile(policyPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	oversized := policy
	service := oversized.Services["sign-me-in"]
	service.Resources.MemoryBytes = maximumServiceMemoryBytes + 1
	oversized.Services["sign-me-in"] = service
	oversizedData, err := json.Marshal(oversized)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(policyPath, oversizedData, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err == nil {
		t.Fatal("unbounded executor memory policy was accepted")
	}
	if err := os.WriteFile(policyPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(policyPath, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err == nil {
		t.Fatal("world-readable executor policy was accepted")
	}
	if err := os.Chmod(policyPath, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(backend, 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err == nil {
		t.Fatal("non-private backend command was accepted")
	}
	if err := os.Chmod(backend, 0700); err != nil {
		t.Fatal(err)
	}
	data = append(data[:len(data)-1], []byte(`,"unknown":true}`)...)
	if err := os.WriteFile(policyPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := loadExecutorPolicy(policyPath, uid, gid, directory); err == nil {
		t.Fatal("unknown executor policy field was accepted")
	}
}

func TestAdapterUsesUnixSocketAndRejectsUnknownFields(t *testing.T) {
	executor, request, counter := executorFixture(t)
	socket := filepath.Join(t.TempDir(), "executor.sock")
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socket, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- ServeExecutor(ctx, listener, executor) }()
	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err := RunAdapter(context.Background(), socket, "build", bytes.NewReader(payload), &output); err != nil {
		t.Fatal(err)
	}
	var result RunResult
	if err := json.Unmarshal(output.Bytes(), &result); err != nil || result.Digest != testBuilt {
		t.Fatalf("unexpected adapter output: %s: %v", output.String(), err)
	}
	count, _ := os.ReadFile(counter)
	if strings.TrimSpace(string(count)) != "1" {
		t.Fatalf("adapter did not invoke backend once: %q", count)
	}
	invalid := append(payload[:len(payload)-1], []byte(`,"unknown":true}`)...)
	if err := RunAdapter(context.Background(), socket, "build", bytes.NewReader(invalid), &bytes.Buffer{}); err == nil {
		t.Fatal("adapter accepted an unknown request field")
	}
	if err := RunAdapter(context.Background(), socket, "gate", bytes.NewReader(payload), &bytes.Buffer{}); err == nil {
		t.Fatal("adapter accepted argv/request operation mismatch")
	}
	invalidShape := request
	invalidShape.OperationID = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
	invalidShape.DataMode = "preserve-current"
	invalidPayload, err := json.Marshal(invalidShape)
	if err != nil {
		t.Fatal(err)
	}
	if err := RunAdapter(context.Background(), socket, "build", bytes.NewReader(invalidPayload), &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "shape") {
		t.Fatalf("adapter accepted an operation-invalid shape: %v", err)
	}
	executor.Policy.AllowedUID++
	request.OperationID = "ffffffffffffffffffffffffffffffff"
	payload, err = json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	if err := RunAdapter(context.Background(), socket, "build", bytes.NewReader(payload), &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "rejected") {
		t.Fatalf("AF_UNIX peer authorization was not enforced: %v", err)
	}
	cancel()
	_ = listener.Close()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("executor did not stop")
	}
}

func sha256Bytes(value []byte) string {
	digest := sha256.Sum256(value)
	return hex.EncodeToString(digest[:])
}
