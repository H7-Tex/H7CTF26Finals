package orchestrator

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	maximumExecutorMessage   = 64 * 1024
	executorCommandDirectory = "/usr/local/libexec/deployment-executor/commands"
)

var (
	operationIDPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)
	opaqueIDPattern    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`)
	imagePattern       = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$`)
	environmentPattern = regexp.MustCompile(`^[A-Z][A-Z0-9_]*$`)
)

type ExecutorCommands struct {
	Build    string `json:"build"`
	Gate     string `json:"gate"`
	Promote  string `json:"promote"`
	Rollback string `json:"rollback"`
	Health   string `json:"health"`
}

func (c ExecutorCommands) command(operation string) string {
	switch operation {
	case "build":
		return c.Build
	case "gate":
		return c.Gate
	case "promote":
		return c.Promote
	case "rollback":
		return c.Rollback
	case "health":
		return c.Health
	default:
		return ""
	}
}

type ExecutorServicePolicy struct {
	BaseCommit           string              `json:"base_commit"`
	BundleSHA256         string              `json:"bundle_sha256"`
	FactoryDigest        string              `json:"factory_digest"`
	FactoryImage         string              `json:"factory_image"`
	PrivateGateArtifact  string              `json:"private_gate_artifact"`
	Protocol             string              `json:"protocol"`
	Port                 int                 `json:"port"`
	Build                ExecutorBuild       `json:"build"`
	Runtime              ExecutorRuntime     `json:"runtime"`
	Quota                ExecutorQuota       `json:"quota"`
	Generations          ExecutorGenerations `json:"generations"`
	Backends             ExecutorBackends    `json:"backends"`
	Resources            ResourceContract    `json:"resources"`
	BuildTimeoutSeconds  int64               `json:"build_timeout_seconds"`
	GateTimeoutSeconds   int64               `json:"gate_timeout_seconds"`
	DeployTimeoutSeconds int64               `json:"deploy_timeout_seconds"`
	HealthTimeoutSeconds int64               `json:"health_timeout_seconds"`
	PreviousFlagTicks    int                 `json:"previous_flag_ticks"`
}

type ExecutorBuild struct {
	Context             string   `json:"context"`
	Dockerfile          string   `json:"dockerfile"`
	BaseImages          []string `json:"base_images"`
	AllowedPaths        []string `json:"allowed_paths"`
	MaximumContextBytes int64    `json:"maximum_context_bytes"`
}

type ExecutorRuntime struct {
	UID                 uint32            `json:"uid"`
	ContainerDataPath   string            `json:"container_data_path"`
	Environment         map[string]string `json:"environment"`
	HealthCommand       []string          `json:"health_command"`
	ReadOnly            bool              `json:"read_only"`
	NoNewPrivileges     bool              `json:"no_new_privileges"`
	DropAllCapabilities bool              `json:"drop_all_capabilities"`
	OutboundNetwork     bool              `json:"outbound_network"`
	TmpfsBytes          int64             `json:"tmpfs_bytes"`
	MemoryBytes         int64             `json:"memory_bytes"`
	CPUMillis           int               `json:"cpu_millis"`
	PIDs                int               `json:"pids"`
}

type ExecutorQuota struct {
	Bytes  int64 `json:"bytes"`
	Inodes int64 `json:"inodes"`
}

type ExecutorGeneration struct {
	Path        string `json:"path"`
	ProjectName string `json:"project_name"`
	ProjectID   int    `json:"project_id"`
}

type ExecutorGenerations struct {
	Live     ExecutorGeneration `json:"live"`
	Gate     ExecutorGeneration `json:"gate"`
	Recovery ExecutorGeneration `json:"recovery"`
}

type ExecutorBackends struct {
	LiveAPort int `json:"live_a_port"`
	LiveBPort int `json:"live_b_port"`
	GatePort  int `json:"gate_port"`
}

type ExecutorPolicy struct {
	SchemaVersion  int                              `json:"schema_version"`
	AllowedUID     uint32                           `json:"allowed_uid"`
	TeamID         string                           `json:"team_id"`
	TeamNumber     int                              `json:"team_number"`
	RepositoryPath string                           `json:"repository_path"`
	PolicyVersion  string                           `json:"policy_version"`
	LiveAddress    string                           `json:"live_address"`
	StagingAddress string                           `json:"staging_address"`
	ProxySocket    string                           `json:"proxy_socket"`
	Commands       ExecutorCommands                 `json:"commands"`
	Services       map[string]ExecutorServicePolicy `json:"services"`
}

func LoadExecutorPolicy(path string) (*ExecutorPolicy, error) {
	return loadExecutorPolicy(path, 0, 0, executorCommandDirectory)
}

func loadExecutorPolicy(path string, ownerUID, ownerGID uint32, commandDirectory string) (*ExecutorPolicy, error) {
	if err := validateOwnedDirectory(commandDirectory, ownerUID, ownerGID); err != nil {
		return nil, fmt.Errorf("executor command directory: %w", err)
	}
	data, err := readPrivateFile(path, ownerUID, ownerGID)
	if err != nil {
		return nil, fmt.Errorf("executor policy: %w", err)
	}
	var policy ExecutorPolicy
	if err := decodeStrict(bytes.NewReader(data), int64(maximumExecutorMessage), &policy); err != nil {
		return nil, fmt.Errorf("decode executor policy: %w", err)
	}
	if err := policy.validate(ownerUID, ownerGID, commandDirectory); err != nil {
		return nil, err
	}
	return &policy, nil
}

func (p *ExecutorPolicy) validate(ownerUID, ownerGID uint32, commandDirectory string) error {
	if p.SchemaVersion != 2 || p.AllowedUID == 0 || !teamIDPattern.MatchString(p.TeamID) || p.TeamNumber < 1 || p.TeamNumber > 15 || p.RepositoryPath != "/var/lib/deployment-orchestrator/repository" || !slugPattern.MatchString(p.PolicyVersion) || len(p.Services) != 6 {
		return errors.New("executor policy has invalid identity")
	}
	if p.LiveAddress != fmt.Sprintf("10.60.%d.2", p.TeamNumber) || p.StagingAddress != fmt.Sprintf("10.60.%d.3", p.TeamNumber) || p.ProxySocket != "/run/finals-service-proxy/control.sock" {
		return errors.New("executor policy has invalid fixed traffic endpoints")
	}
	for _, operation := range []string{"build", "gate", "promote", "rollback", "health"} {
		command := p.Commands.command(operation)
		if command != filepath.Join(commandDirectory, operation) {
			return fmt.Errorf("executor %s command does not match the fixed trusted adapter", operation)
		}
		if err := validateOwnedFile(command, ownerUID, ownerGID, 0700, true); err != nil {
			return fmt.Errorf("executor %s command: %w", operation, err)
		}
	}
	ports := make(map[int]struct{}, len(p.Services))
	uids := make(map[uint32]struct{}, len(p.Services))
	projectIDs := make(map[int]struct{}, len(p.Services)*3)
	backendPorts := make(map[int]struct{}, len(p.Services)*3)
	var quotaBytes, quotaInodes int64
	for slug, service := range p.Services {
		if !slugPattern.MatchString(slug) || !commitPattern.MatchString(service.BaseCommit) || !digestPattern.MatchString("sha256:"+service.BundleSHA256) || !digestPattern.MatchString(service.FactoryDigest) || service.PreviousFlagTicks != 5 {
			return fmt.Errorf("executor service %q has invalid immutable identity", slug)
		}
		if !imagePattern.MatchString(service.FactoryImage) || !strings.HasSuffix(service.FactoryImage, "@"+service.FactoryDigest) || !imagePattern.MatchString(service.PrivateGateArtifact) || (service.Protocol != "http" && service.Protocol != "tcp") || service.Port < 7001 || service.Port > 7006 {
			return fmt.Errorf("executor service %q has invalid release artifacts or endpoint", slug)
		}
		if _, exists := ports[service.Port]; exists {
			return fmt.Errorf("executor service %q repeats a service port", slug)
		}
		ports[service.Port] = struct{}{}
		if _, exists := uids[service.Runtime.UID]; exists {
			return fmt.Errorf("executor service %q repeats a runtime UID", slug)
		}
		uids[service.Runtime.UID] = struct{}{}
		if !validRelativePath(service.Build.Context) || !validRelativePath(service.Build.Dockerfile) || !strings.HasPrefix(service.Build.Dockerfile, service.Build.Context+"/") || len(service.Build.BaseImages) == 0 || len(service.Build.BaseImages) > 8 || len(service.Build.AllowedPaths) == 0 || service.Build.MaximumContextBytes != service.Resources.MaximumContextBytes {
			return fmt.Errorf("executor service %q has invalid build policy", slug)
		}
		baseImages := make(map[string]struct{}, len(service.Build.BaseImages))
		for _, image := range service.Build.BaseImages {
			if !imagePattern.MatchString(image) {
				return fmt.Errorf("executor service %q has a mutable base image", slug)
			}
			if _, exists := baseImages[image]; exists {
				return fmt.Errorf("executor service %q repeats a base image", slug)
			}
			baseImages[image] = struct{}{}
		}
		allowedPaths := make(map[string]struct{}, len(service.Build.AllowedPaths))
		for _, allowed := range service.Build.AllowedPaths {
			if !validRelativePath(allowed) || !strings.HasPrefix(allowed, service.Build.Context+"/") {
				return fmt.Errorf("executor service %q has an invalid patch path", slug)
			}
			if _, exists := allowedPaths[allowed]; exists {
				return fmt.Errorf("executor service %q repeats a patch path", slug)
			}
			allowedPaths[allowed] = struct{}{}
		}
		if service.Runtime.UID < 10000 || service.Runtime.ContainerDataPath != "/data" || !service.Runtime.ReadOnly || !service.Runtime.NoNewPrivileges || !service.Runtime.DropAllCapabilities || service.Runtime.OutboundNetwork || service.Runtime.TmpfsBytes < 1024*1024 || service.Runtime.TmpfsBytes > 64*1024*1024 || service.Runtime.MemoryBytes != service.Resources.MemoryBytes || service.Runtime.CPUMillis != service.Resources.CPUMillis || service.Runtime.PIDs != service.Resources.PIDs || len(service.Runtime.HealthCommand) == 0 || len(service.Runtime.HealthCommand) > 16 || len(service.Runtime.Environment) > 16 {
			return fmt.Errorf("executor service %q has invalid runtime policy", slug)
		}
		for name, value := range service.Runtime.Environment {
			if !environmentPattern.MatchString(name) || len(value) > 256 {
				return fmt.Errorf("executor service %q has an invalid environment", slug)
			}
		}
		for _, value := range service.Runtime.HealthCommand {
			if value == "" || len(value) > 512 {
				return fmt.Errorf("executor service %q has an invalid health command", slug)
			}
		}
		if service.Quota.Bytes < 64*1024*1024 || service.Quota.Bytes > 4*1024*1024*1024 || service.Quota.Inodes < 1024 || service.Quota.Inodes > 262144 {
			return fmt.Errorf("executor service %q has invalid storage quota", slug)
		}
		quotaBytes += service.Quota.Bytes * 3
		quotaInodes += service.Quota.Inodes * 3
		expectedGenerations := []struct {
			Name       string
			Generation ExecutorGeneration
			Offset     int
		}{
			{"live", service.Generations.Live, 0},
			{"gate", service.Generations.Gate, 10000},
			{"recovery", service.Generations.Recovery, 20000},
		}
		for _, expected := range expectedGenerations {
			if expected.Generation.Path != fmt.Sprintf("/srv/finals/service-data/%d/%s", service.Port, expected.Name) || expected.Generation.ProjectName != fmt.Sprintf("finals-%d-%s", service.Port, expected.Name) || expected.Generation.ProjectID != service.Port+expected.Offset {
				return fmt.Errorf("executor service %q has invalid %s generation", slug, expected.Name)
			}
			if _, exists := projectIDs[expected.Generation.ProjectID]; exists {
				return fmt.Errorf("executor service %q repeats a project ID", slug)
			}
			projectIDs[expected.Generation.ProjectID] = struct{}{}
		}
		if service.Backends.LiveAPort != service.Port+10000 || service.Backends.LiveBPort != service.Port+11000 || service.Backends.GatePort != service.Port+12000 {
			return fmt.Errorf("executor service %q has invalid fixed backend ports", slug)
		}
		for _, port := range []int{service.Backends.LiveAPort, service.Backends.LiveBPort, service.Backends.GatePort} {
			if _, exists := backendPorts[port]; exists {
				return fmt.Errorf("executor service %q repeats a backend port", slug)
			}
			backendPorts[port] = struct{}{}
		}
		if service.Resources.NetworkMode != "none" || service.Resources.MaximumContextBytes < 1024 || service.Resources.MaximumContextBytes > 100*1024*1024 || service.Resources.MemoryBytes < 64*1024*1024 || service.Resources.MemoryBytes > maximumServiceMemoryBytes || service.Resources.CPUMillis < 100 || service.Resources.CPUMillis > 4000 || service.Resources.PIDs < 16 || service.Resources.PIDs > 1024 || service.Resources.TimeoutSeconds != 0 {
			return fmt.Errorf("executor service %q has invalid resources", slug)
		}
		for _, seconds := range []int64{service.BuildTimeoutSeconds, service.GateTimeoutSeconds, service.DeployTimeoutSeconds, service.HealthTimeoutSeconds} {
			if seconds < 1 || seconds > 600 {
				return fmt.Errorf("executor service %q has invalid timeout", slug)
			}
		}
	}
	for port := 7001; port <= 7006; port++ {
		if _, exists := ports[port]; !exists {
			return errors.New("executor policy has incomplete fixed service ports")
		}
	}
	if quotaBytes > 32*1024*1024*1024 || quotaInodes > 2_000_000 {
		return errors.New("executor policy exceeds the production volume reserve")
	}
	return nil
}

func validateOwnedFile(path string, uid, gid uint32, mode os.FileMode, executable bool) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || info.Mode().Perm() != mode || stat.Uid != uid || stat.Gid != gid {
		return errors.New("must be a regular file with exact trusted ownership and mode")
	}
	if executable && info.Mode()&0111 == 0 {
		return errors.New("must be executable")
	}
	return nil
}

func ValidateAdapterRequest(request RunRequest, operation string) error {
	if request.SchemaVersion != 1 || request.Operation != operation || !validOperation(operation) || !operationIDPattern.MatchString(request.OperationID) || !teamIDPattern.MatchString(request.TeamID) || request.TeamNumber < 1 || request.TeamNumber > 15 || !slugPattern.MatchString(request.Service) || !slugPattern.MatchString(request.PolicyVersion) || !digestPattern.MatchString(request.FactoryDigest) || request.Resources.NetworkMode != "none" || request.Resources.TimeoutSeconds < 1 || request.Resources.TimeoutSeconds > 600 {
		return errors.New("invalid executor request envelope")
	}
	return validateOperationShape(request)
}

func validateOperationShape(request RunRequest) error {
	buildIdentity := filepath.IsAbs(request.RepositoryPath) && commitPattern.MatchString(request.Commit) && commitPattern.MatchString(request.BaseCommit) && digestPattern.MatchString("sha256:"+request.BundleSHA256)
	fullResources := request.Resources.MaximumContextBytes >= 1024 && request.Resources.MaximumContextBytes <= 100*1024*1024 && request.Resources.MemoryBytes >= 64*1024*1024 && request.Resources.MemoryBytes <= maximumServiceMemoryBytes && request.Resources.CPUMillis >= 100 && request.Resources.CPUMillis <= 4000 && request.Resources.PIDs >= 16 && request.Resources.PIDs <= 1024
	sparseResources := request.Resources.MaximumContextBytes == 0 && request.Resources.MemoryBytes == 0 && request.Resources.CPUMillis == 0 && request.Resources.PIDs == 0
	switch request.Operation {
	case "build":
		if !buildIdentity || !fullResources || request.CandidateDigest != "" || request.TargetDigest != "" || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid build request shape")
		}
	case "gate":
		if !buildIdentity || !fullResources || !digestPattern.MatchString(request.CandidateDigest) || request.TargetDigest != "" || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "copy-current" || request.PreviousFlagTicks < 1 || request.PromotionTick != 0 {
			return errors.New("invalid gate request shape")
		}
	case "promote":
		if !buildIdentity || !fullResources || !digestPattern.MatchString(request.CandidateDigest) || request.TargetDigest != "" || !digestPattern.MatchString(request.CurrentDigest) || !digestPattern.MatchString(request.LastKnownGoodDigest) || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick < 1 {
			return errors.New("invalid promote request shape")
		}
	case "rollback":
		if !buildIdentity || !fullResources || request.CandidateDigest != "" || !digestPattern.MatchString(request.TargetDigest) || !digestPattern.MatchString(request.CurrentDigest) || request.LastKnownGoodDigest != "" || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid rollback request shape")
		}
	case "health":
		if !sparseResources || request.RepositoryPath != "" || request.Commit != "" || request.BaseCommit != "" || request.BundleSHA256 != "" || request.CandidateDigest != "" || !digestPattern.MatchString(request.TargetDigest) || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid health request shape")
		}
	}
	return nil
}

func (p *ExecutorPolicy) ValidateRequest(request RunRequest) error {
	if err := ValidateAdapterRequest(request, request.Operation); err != nil {
		return err
	}
	service, ok := p.Services[request.Service]
	if !ok || request.TeamID != p.TeamID || request.TeamNumber != p.TeamNumber || request.PolicyVersion != p.PolicyVersion || request.FactoryDigest != service.FactoryDigest {
		return errors.New("executor request is not authorized by policy")
	}
	expected := service.Resources
	expected.TimeoutSeconds = timeoutForOperation(service, request.Operation)
	if request.Operation == "health" {
		expected = ResourceContract{NetworkMode: "none", TimeoutSeconds: service.HealthTimeoutSeconds}
	}
	if !reflect.DeepEqual(request.Resources, expected) {
		return errors.New("executor request resources do not match policy")
	}
	buildIdentity := request.RepositoryPath == p.RepositoryPath && commitPattern.MatchString(request.Commit) && request.BaseCommit == service.BaseCommit && request.BundleSHA256 == service.BundleSHA256
	switch request.Operation {
	case "build":
		if !buildIdentity || request.CandidateDigest != "" || request.TargetDigest != "" || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid build request")
		}
	case "gate":
		if !buildIdentity || !digestPattern.MatchString(request.CandidateDigest) || request.TargetDigest != "" || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "copy-current" || request.PreviousFlagTicks != service.PreviousFlagTicks || request.PromotionTick != 0 {
			return errors.New("invalid gate request")
		}
	case "promote":
		if !buildIdentity || !digestPattern.MatchString(request.CandidateDigest) || request.TargetDigest != "" || !digestPattern.MatchString(request.CurrentDigest) || !digestPattern.MatchString(request.LastKnownGoodDigest) || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick < 1 {
			return errors.New("invalid promote request")
		}
	case "rollback":
		if !buildIdentity || request.CandidateDigest != "" || !digestPattern.MatchString(request.TargetDigest) || !digestPattern.MatchString(request.CurrentDigest) || request.LastKnownGoodDigest != "" || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid rollback request")
		}
	case "health":
		if request.RepositoryPath != "" || request.Commit != "" || request.BaseCommit != "" || request.BundleSHA256 != "" || request.CandidateDigest != "" || !digestPattern.MatchString(request.TargetDigest) || request.CurrentDigest != "" || request.LastKnownGoodDigest != "" || request.DataMode != "preserve-current" || request.PreviousFlagTicks != 0 || request.PromotionTick != 0 {
			return errors.New("invalid health request")
		}
	}
	return nil
}

func timeoutForOperation(service ExecutorServicePolicy, operation string) int64 {
	switch operation {
	case "build":
		return service.BuildTimeoutSeconds
	case "gate":
		return service.GateTimeoutSeconds
	case "promote", "rollback":
		return service.DeployTimeoutSeconds
	case "health":
		return service.HealthTimeoutSeconds
	default:
		return 0
	}
}

type executorRecord struct {
	SchemaVersion int        `json:"schema_version"`
	RequestSHA256 string     `json:"request_sha256"`
	Request       RunRequest `json:"request"`
	Status        string     `json:"status"`
	Result        *RunResult `json:"result,omitempty"`
}

type Executor struct {
	Policy         *ExecutorPolicy
	StateDirectory string
	ownerUID       uint32
	ownerGID       uint32
	mu             sync.Mutex
	operationMu    map[string]*sync.Mutex
	serviceMu      map[string]*sync.Mutex
}

type executorResponse struct {
	Result *RunResult `json:"result,omitempty"`
	Failed bool       `json:"failed,omitempty"`
}

func NewExecutor(policy *ExecutorPolicy, stateDirectory string) (*Executor, error) {
	return newExecutor(policy, stateDirectory, 0, 0)
}

func newExecutor(policy *ExecutorPolicy, stateDirectory string, ownerUID, ownerGID uint32) (*Executor, error) {
	if !filepath.IsAbs(stateDirectory) {
		return nil, errors.New("executor state directory must be absolute")
	}
	if err := validateOwnedDirectory(stateDirectory, ownerUID, ownerGID); err != nil {
		return nil, fmt.Errorf("executor state directory: %w", err)
	}
	operations := filepath.Join(stateDirectory, "operations")
	if err := os.Mkdir(operations, 0700); err != nil && !errors.Is(err, os.ErrExist) {
		return nil, err
	}
	if err := validateOwnedDirectory(operations, ownerUID, ownerGID); err != nil {
		return nil, fmt.Errorf("executor operations directory: %w", err)
	}
	return &Executor{Policy: policy, StateDirectory: stateDirectory, ownerUID: ownerUID, ownerGID: ownerGID, operationMu: make(map[string]*sync.Mutex), serviceMu: make(map[string]*sync.Mutex)}, nil
}

func validateOwnedDirectory(path string, uid, gid uint32) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.IsDir() || info.Mode().Perm() != 0700 || stat.Uid != uid || stat.Gid != gid {
		return errors.New("must be a private directory with exact trusted ownership")
	}
	return nil
}

func (e *Executor) lockFor(values map[string]*sync.Mutex, key string) *sync.Mutex {
	e.mu.Lock()
	defer e.mu.Unlock()
	lock := values[key]
	if lock == nil {
		lock = &sync.Mutex{}
		values[key] = lock
	}
	return lock
}

func (e *Executor) Execute(ctx context.Context, peerUID uint32, request RunRequest) (RunResult, error) {
	if peerUID != e.Policy.AllowedUID {
		return RunResult{}, errors.New("executor peer is not authorized")
	}
	if err := e.Policy.ValidateRequest(request); err != nil {
		return RunResult{}, err
	}
	payload, err := json.Marshal(request)
	if err != nil {
		return RunResult{}, err
	}
	digest := sha256.Sum256(payload)
	hash := hex.EncodeToString(digest[:])
	operationLock := e.lockFor(e.operationMu, request.OperationID)
	operationLock.Lock()
	defer operationLock.Unlock()

	recordPath := filepath.Join(e.StateDirectory, "operations", request.OperationID+".json")
	record, exists, err := readExecutorRecord(recordPath, e.ownerUID, e.ownerGID)
	if err != nil {
		return RunResult{}, err
	}
	if exists {
		if record.RequestSHA256 != hash || !reflect.DeepEqual(record.Request, request) {
			return RunResult{}, errors.New("operation_id was reused with a different request")
		}
		if record.Status == "completed" && record.Result != nil {
			if err := validateExecutorResult(request, *record.Result); err != nil {
				return RunResult{}, fmt.Errorf("invalid completed executor record: %w", err)
			}
			return *record.Result, nil
		}
		if record.Status != "pending" || record.Result != nil {
			return RunResult{}, errors.New("invalid executor operation record")
		}
	} else {
		record = executorRecord{SchemaVersion: 1, RequestSHA256: hash, Request: request, Status: "pending"}
		if err := writeExecutorRecord(recordPath, record); err != nil {
			return RunResult{}, err
		}
	}

	serviceLock := e.lockFor(e.serviceMu, request.Service)
	serviceLock.Lock()
	defer serviceLock.Unlock()
	timeout := time.Duration(request.Resources.TimeoutSeconds) * time.Second
	runContext, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	result, err := (CommandRunner{Command: e.Policy.Commands.command(request.Operation)}).Run(runContext, request)
	if err != nil {
		return RunResult{}, err
	}
	if err := validateExecutorResult(request, result); err != nil {
		return RunResult{}, err
	}
	record.Status = "completed"
	record.Result = &result
	if err := writeExecutorRecord(recordPath, record); err != nil {
		return RunResult{}, err
	}
	return result, nil
}

func validateExecutorResult(request RunRequest, result RunResult) error {
	if result.RunnerPolicyVersion != request.PolicyVersion || result.PublicMessage != boundedMessage(result.PublicMessage) {
		return errors.New("backend result does not match executor policy")
	}
	if !result.OK {
		if result.Digest != "" || result.Healthy != nil || result.DataCopyID != "" || result.RecoverySnapshotID != "" {
			return errors.New("negative backend result contains privileged fields")
		}
		return nil
	}
	trueValue := func(value *bool) bool { return value != nil && *value }
	switch request.Operation {
	case "build":
		if !digestPattern.MatchString(result.Digest) || result.Healthy != nil || result.DataCopyID != "" || result.RecoverySnapshotID != "" {
			return errors.New("invalid build result")
		}
	case "gate":
		if result.Digest != "" || result.Healthy != nil || !opaqueIDPattern.MatchString(result.DataCopyID) || result.RecoverySnapshotID != "" {
			return errors.New("invalid gate result")
		}
	case "promote":
		if result.Digest != request.CandidateDigest || !trueValue(result.Healthy) || result.DataCopyID != "" || !opaqueIDPattern.MatchString(result.RecoverySnapshotID) {
			return errors.New("invalid promote result")
		}
	case "rollback", "health":
		if result.Digest != request.TargetDigest || !trueValue(result.Healthy) || result.DataCopyID != "" || result.RecoverySnapshotID != "" {
			return errors.New("invalid digest health result")
		}
	}
	return nil
}

func readExecutorRecord(path string, ownerUID, ownerGID uint32) (executorRecord, bool, error) {
	data, err := readPrivateFile(path, ownerUID, ownerGID)
	if errors.Is(err, os.ErrNotExist) {
		return executorRecord{}, false, nil
	}
	if err != nil {
		return executorRecord{}, false, err
	}
	var record executorRecord
	if err := decodeStrict(bytes.NewReader(data), int64(maximumExecutorMessage), &record); err != nil {
		return executorRecord{}, false, err
	}
	if record.SchemaVersion != 1 || !digestPattern.MatchString("sha256:"+record.RequestSHA256) {
		return executorRecord{}, false, errors.New("invalid executor operation record identity")
	}
	return record, true, nil
}

func writeExecutorRecord(path string, record executorRecord) error {
	data, err := json.MarshalIndent(record, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	temporary, err := os.CreateTemp(filepath.Dir(path), ".operation-*")
	if err != nil {
		return err
	}
	temporaryPath := temporary.Name()
	defer os.Remove(temporaryPath)
	if err := temporary.Chmod(0600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(data); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return err
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryPath, path); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(path))
}

func RunAdapter(ctx context.Context, socketPath, operation string, input io.Reader, output io.Writer) error {
	var request RunRequest
	if err := decodeStrict(input, maximumExecutorMessage, &request); err != nil {
		return err
	}
	if err := ValidateAdapterRequest(request, operation); err != nil {
		return err
	}
	dialer := net.Dialer{}
	connection, err := dialer.DialContext(ctx, "unix", socketPath)
	if err != nil {
		return err
	}
	defer connection.Close()
	if deadline, ok := ctx.Deadline(); ok {
		_ = connection.SetDeadline(deadline)
	}
	if err := json.NewEncoder(connection).Encode(request); err != nil {
		return err
	}
	unixConnection, ok := connection.(*net.UnixConn)
	if !ok {
		return errors.New("executor connection is not AF_UNIX")
	}
	if err := unixConnection.CloseWrite(); err != nil {
		return err
	}
	var response executorResponse
	if err := decodeStrict(connection, maximumExecutorMessage, &response); err != nil {
		return err
	}
	if response.Failed || response.Result == nil {
		return errors.New("deployment executor rejected request")
	}
	result := *response.Result
	if err := validateExecutorResult(request, result); err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(result)
}

func ServeExecutor(ctx context.Context, listener *net.UnixListener, executor *Executor) error {
	for {
		connection, err := listener.AcceptUnix()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		go handleExecutorConnection(ctx, connection, executor)
	}
}

func handleExecutorConnection(ctx context.Context, connection *net.UnixConn, executor *Executor) {
	defer connection.Close()
	peerUID, err := unixPeerUID(connection)
	if err != nil {
		return
	}
	var request RunRequest
	if err := decodeStrict(connection, maximumExecutorMessage, &request); err != nil {
		return
	}
	result, err := executor.Execute(ctx, peerUID, request)
	if err != nil {
		_ = json.NewEncoder(connection).Encode(executorResponse{Failed: true})
		return
	}
	_ = json.NewEncoder(connection).Encode(executorResponse{Result: &result})
}

func unixPeerUID(connection *net.UnixConn) (uint32, error) {
	raw, err := connection.SyscallConn()
	if err != nil {
		return 0, err
	}
	var credential *syscall.Ucred
	var socketErr error
	if err := raw.Control(func(fd uintptr) {
		credential, socketErr = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}); err != nil {
		return 0, err
	}
	if socketErr != nil {
		return 0, socketErr
	}
	return credential.Uid, nil
}

func decodeStrict(reader io.Reader, maximum int64, target any) error {
	limited := io.LimitReader(reader, maximum+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return err
	}
	if int64(len(data)) > maximum {
		return errors.New("JSON message exceeded limit")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return errors.New("JSON message must contain one value")
	}
	return nil
}
