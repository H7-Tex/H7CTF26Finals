package orchestrator

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"time"
)

const (
	stateSchemaVersion = 1
	maximumDeliveries  = 2048
	maximumHistory     = 16
)

type Artifact struct {
	Commit  string    `json:"commit"`
	Digest  string    `json:"digest"`
	GreenAt time.Time `json:"green_at"`
	Factory bool      `json:"factory,omitempty"`
}

type ServiceState struct {
	Status              string           `json:"status"`
	PublicMessage       string           `json:"public_message,omitempty"`
	Intent              *OperationIntent `json:"intent,omitempty"`
	CandidateCommit     string           `json:"candidate_commit,omitempty"`
	CandidateDigest     string           `json:"candidate_digest,omitempty"`
	CurrentCommit       string           `json:"current_commit"`
	CurrentDigest       string           `json:"current_digest"`
	LastKnownGoodCommit string           `json:"last_known_good_commit"`
	LastKnownGoodDigest string           `json:"last_known_good_digest"`
	FactoryCommit       string           `json:"factory_commit"`
	FactoryDigest       string           `json:"factory_digest"`
	GateDataCopyID      string           `json:"gate_data_copy_id,omitempty"`
	RecoverySnapshotID  string           `json:"recovery_snapshot_id,omitempty"`
	PromotionTick       int64            `json:"promotion_tick,omitempty"`
	LastHealthTick      int64            `json:"last_health_tick,omitempty"`
	CausalFailures      int              `json:"causal_failures,omitempty"`
	ConsecutiveHealthy  int              `json:"consecutive_healthy,omitempty"`
	History             []Artifact       `json:"history"`
	UpdatedAt           time.Time        `json:"updated_at"`
}

type OperationIntent struct {
	Stage        string     `json:"stage"`
	Request      RunRequest `json:"request"`
	Action       string     `json:"action,omitempty"`
	ActorID      string     `json:"actor_id,omitempty"`
	TraceID      string     `json:"trace_id,omitempty"`
	TargetCommit string     `json:"target_commit,omitempty"`
}

type DeliveryRecord struct {
	ID       string    `json:"id"`
	BodyHash string    `json:"body_hash"`
	SeenAt   time.Time `json:"seen_at"`
}

type PersistentState struct {
	SchemaVersion    int                     `json:"schema_version"`
	TeamNumber       int                     `json:"team_number"`
	TeamID           string                  `json:"team_id"`
	ManifestSHA256   string                  `json:"manifest_sha256"`
	RepositoryHead   string                  `json:"repository_head"`
	RejectedHead     string                  `json:"rejected_repository_head,omitempty"`
	Pending          map[string]string       `json:"pending"`
	Services         map[string]ServiceState `json:"services"`
	Deliveries       []DeliveryRecord        `json:"deliveries"`
	NextSequence     uint64                  `json:"next_sequence"`
	ReportedSequence uint64                  `json:"reported_sequence,omitempty"`
}

type AuditEvent struct {
	Sequence           uint64    `json:"sequence"`
	At                 time.Time `json:"at"`
	TeamID             string    `json:"team_id"`
	Service            string    `json:"service,omitempty"`
	Action             string    `json:"action"`
	Outcome            string    `json:"outcome"`
	ActorID            string    `json:"actor_id"`
	TraceID            string    `json:"trace_id"`
	Commit             string    `json:"commit,omitempty"`
	Digest             string    `json:"digest,omitempty"`
	PreviousDigest     string    `json:"previous_digest,omitempty"`
	DataCopyID         string    `json:"data_copy_id,omitempty"`
	RecoverySnapshotID string    `json:"recovery_snapshot_id,omitempty"`
	Message            string    `json:"message,omitempty"`
}

type Store struct {
	mu        sync.Mutex
	directory string
	statePath string
	auditPath string
	state     PersistentState
	poisoned  error
}

func InitialState(cfg *Config, manifest *Manifest, manifestHash string) PersistentState {
	now := time.Now().UTC()
	state := PersistentState{
		SchemaVersion: stateSchemaVersion, TeamNumber: cfg.TeamNumber, TeamID: cfg.TeamID,
		ManifestSHA256: manifestHash, RepositoryHead: cfg.Repository.InitialCommit,
		Pending: make(map[string]string), Services: make(map[string]ServiceState, len(manifest.Services)),
	}
	for _, service := range manifest.Services {
		factory := Artifact{Commit: service.BaseCommit, Digest: service.FactoryDigest, GreenAt: now, Factory: true}
		state.Services[service.Slug] = ServiceState{
			Status: "healthy", CurrentCommit: service.BaseCommit, CurrentDigest: service.FactoryDigest,
			LastKnownGoodCommit: service.BaseCommit, LastKnownGoodDigest: service.FactoryDigest,
			FactoryCommit: service.BaseCommit, FactoryDigest: service.FactoryDigest,
			History: []Artifact{factory}, UpdatedAt: now,
		}
	}
	return state
}

func InitializeStore(directory string, initial PersistentState) error {
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	if _, err := os.Lstat(filepath.Join(directory, restoreMarkerName)); err == nil {
		return errors.New("offline restore is incomplete")
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	statePath := filepath.Join(directory, "state.json")
	auditPath := filepath.Join(directory, "audit.jsonl")
	stateExists, err := initializationStateMatches(statePath, initial)
	if err != nil {
		return err
	}
	auditExists, err := emptyRegularFile(auditPath)
	if err != nil {
		return err
	}
	if !auditExists {
		audit, err := os.OpenFile(auditPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			return err
		}
		if err := audit.Chmod(0600); err != nil {
			audit.Close()
			return err
		}
		if err := audit.Sync(); err != nil {
			audit.Close()
			return err
		}
		if err := audit.Close(); err != nil {
			return err
		}
		if err := syncDirectory(directory); err != nil {
			return err
		}
	}
	if !stateExists {
		if err := writeState(statePath, initial); err != nil {
			return err
		}
	}
	return nil
}

func initializationStateMatches(path string, initial PersistentState) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0600 {
		return false, errors.New("existing initialization state is not a private regular file")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return false, err
	}
	var existing PersistentState
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&existing); err != nil {
		return false, fmt.Errorf("decode existing initialization state: %w", err)
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return false, errors.New("existing initialization state must contain one JSON value")
	}
	if !samePristineState(existing, initial) {
		return false, errors.New("state already exists")
	}
	return true, nil
}

func emptyRegularFile(path string) (bool, error) {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || info.Size() != 0 {
		return false, errors.New("audit already exists and is not an empty private regular file")
	}
	return true, nil
}

func samePristineState(existing, initial PersistentState) bool {
	if existing.NextSequence != 0 || len(existing.Deliveries) != 0 || len(existing.Pending) != 0 || existing.RejectedHead != "" {
		return false
	}
	normalize := func(state PersistentState) PersistentState {
		state = cloneState(state)
		for slug, service := range state.Services {
			service.UpdatedAt = time.Time{}
			for index := range service.History {
				service.History[index].GreenAt = time.Time{}
			}
			state.Services[slug] = service
		}
		return state
	}
	return reflect.DeepEqual(normalize(existing), normalize(initial))
}

func OpenStore(cfg *Config, manifestHash string) (*Store, error) {
	if _, err := os.Lstat(filepath.Join(cfg.StateDirectory, restoreMarkerName)); err == nil {
		return nil, errors.New("offline restore is incomplete")
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	statePath := filepath.Join(cfg.StateDirectory, "state.json")
	auditPath := filepath.Join(cfg.StateDirectory, "audit.jsonl")
	data, err := os.ReadFile(statePath)
	if err != nil {
		return nil, fmt.Errorf("read state: %w; run the explicit initialize command first", err)
	}
	var state PersistentState
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&state); err != nil {
		return nil, fmt.Errorf("decode state: %w", err)
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return nil, errors.New("state must contain one JSON value")
	}
	if state.SchemaVersion != stateSchemaVersion || state.TeamID != cfg.TeamID || state.TeamNumber != cfg.TeamNumber || state.ManifestSHA256 != manifestHash {
		return nil, errors.New("state identity or manifest hash does not match configuration")
	}
	if state.ReportedSequence > state.NextSequence {
		return nil, errors.New("reported audit sequence is ahead of durable state")
	}
	if err := validateIntents(state, cfg); err != nil {
		return nil, err
	}
	lastSequence, err := recoverAuditTail(auditPath, state.NextSequence)
	if err != nil {
		return nil, err
	}
	if lastSequence != state.NextSequence {
		return nil, fmt.Errorf("audit/state sequence mismatch: audit=%d state=%d", lastSequence, state.NextSequence)
	}
	return &Store{directory: cfg.StateDirectory, statePath: statePath, auditPath: auditPath, state: state}, nil
}

func (s *Store) Snapshot() PersistentState {
	s.mu.Lock()
	defer s.mu.Unlock()
	return cloneState(s.state)
}

func (s *Store) Healthy() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.poisoned == nil
}

func (s *Store) AcknowledgeReported(sequence uint64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.poisoned != nil {
		return s.poisoned
	}
	if sequence == s.state.ReportedSequence {
		return nil
	}
	if sequence != s.state.ReportedSequence+1 || sequence > s.state.NextSequence {
		return errors.New("invalid reported audit sequence")
	}
	next := cloneState(s.state)
	next.ReportedSequence = sequence
	if err := writeState(s.statePath, next); err != nil {
		s.poisoned = fmt.Errorf("persist reported audit sequence %d: %w", sequence, err)
		return s.poisoned
	}
	s.state = next
	return nil
}

func (s *Store) Update(event AuditEvent, mutate func(*PersistentState) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.poisoned != nil {
		return s.poisoned
	}
	next := cloneState(s.state)
	if mutate != nil {
		if err := mutate(&next); err != nil {
			return err
		}
	}
	next.NextSequence++
	event.Sequence = next.NextSequence
	event.At = time.Now().UTC()
	event.TeamID = next.TeamID
	if err := appendAudit(s.auditPath, event); err != nil {
		s.poisoned = fmt.Errorf("append audit sequence %d: %w", event.Sequence, err)
		return s.poisoned
	}
	if err := writeState(s.statePath, next); err != nil {
		s.poisoned = fmt.Errorf("persist state after audit sequence %d: %w", event.Sequence, err)
		return s.poisoned
	}
	s.state = next
	return nil
}

func (s *Store) Audit(after uint64, limit int) ([]AuditEvent, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if limit < 1 || limit > 500 {
		return nil, errors.New("audit limit must be between 1 and 500")
	}
	file, err := os.Open(s.auditPath)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	var events []AuditEvent
	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)
	for scanner.Scan() {
		var event AuditEvent
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			return nil, fmt.Errorf("decode audit event: %w", err)
		}
		if event.Sequence > after {
			events = append(events, event)
			if len(events) == limit {
				break
			}
		}
	}
	return events, scanner.Err()
}

func (s *Store) delivery(id string) (DeliveryRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.state.Deliveries {
		if record.ID == id {
			return record, true
		}
	}
	return DeliveryRecord{}, false
}

func rememberDelivery(state *PersistentState, record DeliveryRecord) {
	state.Deliveries = append(state.Deliveries, record)
	if len(state.Deliveries) > maximumDeliveries {
		state.Deliveries = append([]DeliveryRecord(nil), state.Deliveries[len(state.Deliveries)-maximumDeliveries:]...)
	}
}

func addHistory(service *ServiceState, artifact Artifact) {
	for _, existing := range service.History {
		if existing.Digest == artifact.Digest {
			return
		}
	}
	service.History = append(service.History, artifact)
	if len(service.History) > maximumHistory {
		factory := service.History[0]
		for _, existing := range service.History {
			if existing.Factory {
				factory = existing
				break
			}
		}
		latest := append([]Artifact(nil), service.History[len(service.History)-(maximumHistory-1):]...)
		service.History = append([]Artifact{factory}, latest...)
	}
}

func cloneState(state PersistentState) PersistentState {
	data, err := json.Marshal(state)
	if err != nil {
		panic(err)
	}
	var copy PersistentState
	if err := json.Unmarshal(data, &copy); err != nil {
		panic(err)
	}
	return copy
}

func writeState(path string, state PersistentState) error {
	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	temporary, err := os.CreateTemp(filepath.Dir(path), ".state-*")
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

func appendAudit(path string, event AuditEvent) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	defer file.Close()
	if _, err := file.Write(append(data, '\n')); err != nil {
		return err
	}
	return file.Sync()
}

func recoverAuditTail(path string, stateSequence uint64) (uint64, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	var sequence uint64
	lastCompleteOffset := 0
	previousCompleteOffset := 0
	for offset := 0; offset < len(data); {
		end := bytes.IndexByte(data[offset:], '\n')
		if end < 0 {
			if sequence != stateSequence || offset == len(data) {
				return 0, errors.New("audit contains an unrecoverable partial record")
			}
			if err := truncateAudit(path, int64(offset)); err != nil {
				return 0, err
			}
			return sequence, nil
		}
		end += offset
		if end == offset {
			return 0, errors.New("audit contains an empty record")
		}
		var event AuditEvent
		if err := json.Unmarshal(data[offset:end], &event); err != nil {
			return 0, fmt.Errorf("decode audit event: %w", err)
		}
		if event.Sequence != sequence+1 {
			return 0, errors.New("audit sequence is not contiguous")
		}
		previousCompleteOffset = lastCompleteOffset
		lastCompleteOffset = end + 1
		sequence = event.Sequence
		offset = end + 1
	}
	if sequence == stateSequence {
		return sequence, nil
	}
	if sequence == stateSequence+1 {
		if err := truncateAudit(path, int64(previousCompleteOffset)); err != nil {
			return 0, err
		}
		return stateSequence, nil
	}
	return 0, fmt.Errorf("audit/state sequence mismatch: audit=%d state=%d", sequence, stateSequence)
}

func truncateAudit(path string, size int64) error {
	file, err := os.OpenFile(path, os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	if err := file.Truncate(size); err != nil {
		file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(path))
}

func syncDirectory(path string) error {
	directory, err := os.Open(path)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func validateIntents(state PersistentState, cfg *Config) error {
	for slug, service := range state.Services {
		if service.Intent == nil {
			continue
		}
		intent := service.Intent
		expectedOperation := intent.Stage
		switch intent.Stage {
		case "build", "gate", "promote":
		case "recovery", "manual-rollback", "auto-rollback":
			expectedOperation = "rollback"
		default:
			return fmt.Errorf("service %s has an invalid persisted intent stage", slug)
		}
		request := intent.Request
		if request.SchemaVersion != 1 || request.Operation != expectedOperation || !validTraceID(request.OperationID) || request.Service != slug || request.TeamID != cfg.TeamID || request.TeamNumber != cfg.TeamNumber || !commitPattern.MatchString(request.Commit) || !digestPattern.MatchString(request.FactoryDigest) || request.Resources.NetworkMode != "none" || request.Resources.TimeoutSeconds < 1 {
			return fmt.Errorf("service %s has an invalid persisted runner request", slug)
		}
		switch intent.Stage {
		case "gate":
			if !digestPattern.MatchString(request.CandidateDigest) || request.DataMode != "copy-current" {
				return fmt.Errorf("service %s has an invalid persisted gate request", slug)
			}
		case "promote":
			if !digestPattern.MatchString(request.CandidateDigest) || !digestPattern.MatchString(request.CurrentDigest) || !digestPattern.MatchString(request.LastKnownGoodDigest) || request.DataMode != "preserve-current" || !commitPattern.MatchString(intent.TargetCommit) {
				return fmt.Errorf("service %s has an invalid persisted promotion request", slug)
			}
		case "recovery", "manual-rollback", "auto-rollback":
			if !digestPattern.MatchString(request.TargetDigest) || !digestPattern.MatchString(request.CurrentDigest) || request.DataMode != "preserve-current" || !commitPattern.MatchString(intent.TargetCommit) {
				return fmt.Errorf("service %s has an invalid persisted rollback request", slug)
			}
		}
		if (intent.Stage == "manual-rollback" || intent.Stage == "auto-rollback") && (intent.Action != intent.Stage || !validActorID(intent.ActorID) || !validTraceID(intent.TraceID)) {
			return fmt.Errorf("service %s has invalid persisted rollback attribution", slug)
		}
	}
	return nil
}
