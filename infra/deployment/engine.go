package orchestrator

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"log"
	"sort"
	"sync"
	"time"
)

const requiredHealthyObservations = 2

type Engine struct {
	Config     *Config
	Manifest   *Manifest
	Store      *Store
	Repository Repository
	Runner     Runner
	Quiet      QuietWindow

	trigger     chan struct{}
	serviceMu   map[string]*sync.Mutex
	serviceWake map[string]chan struct{}
	waitMu      sync.Mutex
	waitCancel  map[string]context.CancelFunc
}

func NewEngine(cfg *Config, manifest *Manifest, store *Store, repository Repository, runner Runner, quiet QuietWindow) *Engine {
	serviceMu := make(map[string]*sync.Mutex, len(manifest.Services))
	serviceWake := make(map[string]chan struct{}, len(manifest.Services))
	for _, service := range manifest.Services {
		serviceMu[service.Slug] = &sync.Mutex{}
		serviceWake[service.Slug] = make(chan struct{}, 1)
	}
	return &Engine{
		Config: cfg, Manifest: manifest, Store: store, Repository: repository,
		Runner: runner, Quiet: quiet, trigger: make(chan struct{}, 1), serviceMu: serviceMu,
		serviceWake: serviceWake, waitCancel: make(map[string]context.CancelFunc),
	}
}

func (e *Engine) Trigger() {
	select {
	case e.trigger <- struct{}{}:
	default:
	}
}

func (e *Engine) Run(ctx context.Context) {
	workerContext, cancelWorkers := context.WithCancel(ctx)
	var workers sync.WaitGroup
	for _, service := range e.Manifest.Services {
		workers.Add(1)
		go func(slug string) {
			defer workers.Done()
			e.runServiceWorker(workerContext, slug)
		}(service.Slug)
	}
	defer func() {
		cancelWorkers()
		workers.Wait()
	}()

	ticker := time.NewTicker(e.Config.PollInterval.Value())
	defer ticker.Stop()
	reconcile := func() {
		if err := e.discover(workerContext); err != nil && !errors.Is(err, context.Canceled) {
			log.Printf("deployment discovery failed")
		}
		e.signalAllServices()
	}
	reconcile()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		case <-e.trigger:
		}
		reconcile()
	}
}

func (e *Engine) runServiceWorker(ctx context.Context, slug string) {
	wake := e.serviceWake[slug]
	for {
		select {
		case <-ctx.Done():
			return
		case <-wake:
			if err := e.resumeService(ctx, slug); err != nil && !errors.Is(err, context.Canceled) {
				log.Printf("deployment failed service=%s", slug)
			}
		}
	}
}

func (e *Engine) signalService(slug string) {
	wake, ok := e.serviceWake[slug]
	if !ok {
		return
	}
	select {
	case wake <- struct{}{}:
	default:
	}
}

func (e *Engine) signalAllServices() {
	for _, service := range e.Manifest.Services {
		e.signalService(service.Slug)
	}
}

func (e *Engine) reconcile(ctx context.Context) error {
	discoveryErr := e.discover(ctx)
	state := e.Store.Snapshot()
	queued := make(map[string]struct{}, len(state.Pending))
	for service := range state.Pending {
		queued[service] = struct{}{}
	}
	for service, current := range state.Services {
		if current.Intent != nil {
			queued[service] = struct{}{}
		}
	}
	services := make([]string, 0, len(queued))
	for service := range queued {
		services = append(services, service)
	}
	sort.Strings(services)
	var workers sync.WaitGroup
	for _, service := range services {
		workers.Add(1)
		go func(slug string) {
			defer workers.Done()
			if err := e.resumeService(ctx, slug); err != nil && !errors.Is(err, context.Canceled) {
				log.Printf("deployment failed service=%s", slug)
			}
		}(service)
	}
	workers.Wait()
	return discoveryErr
}

func (e *Engine) discover(ctx context.Context) error {
	head, err := e.Repository.FetchRemoteHead(ctx)
	if err != nil {
		return err
	}
	state := e.Store.Snapshot()
	if head == state.RepositoryHead || head == state.RejectedHead {
		return nil
	}
	ancestor, err := e.Repository.IsAncestor(ctx, state.RepositoryHead, head)
	if err != nil {
		return err
	}
	if !ancestor {
		return e.Store.Update(AuditEvent{Action: "repository", Outcome: "rejected", ActorID: "gitea", TraceID: newOperationID(), Commit: head, Message: "Remote main is not a descendant of the approved repository head."}, func(next *PersistentState) error {
			next.RejectedHead = head
			return nil
		})
	}
	paths, err := e.Repository.DiffPaths(ctx, state.RepositoryHead, head, "")
	if err != nil {
		return err
	}
	services, policyErr := changedServices(paths, e.Manifest)
	traceID := newOperationID()
	if policyErr != nil {
		return e.Store.Update(AuditEvent{Action: "repository", Outcome: "rejected", ActorID: "gitea", TraceID: traceID, Commit: head, Message: boundedMessage(policyErr.Error())}, func(next *PersistentState) error {
			next.RejectedHead = head
			return nil
		})
	}
	return e.Store.Update(AuditEvent{Action: "repository", Outcome: "queued", ActorID: "gitea", TraceID: traceID, Commit: head}, func(next *PersistentState) error {
		next.RepositoryHead = head
		next.RejectedHead = ""
		for _, service := range services {
			next.Pending[service] = head
		}
		return nil
	})
}

func (e *Engine) resumeService(ctx context.Context, slug string) error {
	manifest, ok := e.Manifest.Service(slug)
	if !ok {
		return errors.New("unknown service")
	}
	lock := e.serviceMu[slug]
	for {
		lock.Lock()
		state := e.Store.Snapshot()
		service := state.Services[slug]
		if service.Intent != nil {
			err := e.executeIntent(ctx, manifest, *service.Intent)
			lock.Unlock()
			if err != nil {
				return err
			}
			if next := e.Store.Snapshot().Services[slug]; next.Status == "waiting" && next.Intent == nil {
				continue
			}
			return nil
		}
		if service.Status == "waiting" {
			waitContext, cancel := context.WithCancel(ctx)
			e.waitMu.Lock()
			e.waitCancel[slug] = cancel
			e.waitMu.Unlock()
			lock.Unlock()

			promotionTick, err := e.Quiet.Wait(waitContext, service.PromotionTick)
			cancel()
			lock.Lock()
			e.waitMu.Lock()
			delete(e.waitCancel, slug)
			e.waitMu.Unlock()
			if err != nil {
				lock.Unlock()
				return err
			}
			current := e.Store.Snapshot().Services[slug]
			if current.Intent != nil || current.Status != "waiting" || !sameWaitingCandidate(service, current) {
				lock.Unlock()
				continue
			}
			err = e.promoteAt(ctx, manifest, current, promotionTick)
			lock.Unlock()
			return err
		}
		if service.Status == "watching" || service.Status == "operator-intervention" {
			lock.Unlock()
			return nil
		}
		commit, pending := state.Pending[slug]
		if !pending {
			lock.Unlock()
			return nil
		}
		if service.CurrentDigest != service.LastKnownGoodDigest {
			lock.Unlock()
			return errors.New("current image has not completed health observation")
		}
		err := e.beginCandidate(ctx, manifest, commit)
		lock.Unlock()
		if err != nil {
			return err
		}
		if next := e.Store.Snapshot().Services[slug]; next.Status == "waiting" && next.Intent == nil {
			continue
		}
		return nil
	}
}

func sameWaitingCandidate(before, after ServiceState) bool {
	return before.CandidateCommit == after.CandidateCommit &&
		before.CandidateDigest == after.CandidateDigest &&
		before.CurrentCommit == after.CurrentCommit &&
		before.CurrentDigest == after.CurrentDigest &&
		before.LastKnownGoodDigest == after.LastKnownGoodDigest &&
		before.GateDataCopyID == after.GateDataCopyID &&
		before.PromotionTick == after.PromotionTick
}

func (e *Engine) cancelQuietWait(slug string) {
	e.waitMu.Lock()
	cancel := e.waitCancel[slug]
	e.waitMu.Unlock()
	if cancel != nil {
		cancel()
	}
}

func (e *Engine) beginCandidate(ctx context.Context, manifest ServiceManifest, commit string) error {
	paths, err := e.Repository.DiffPaths(ctx, manifest.BaseCommit, commit, manifest.Slug)
	if err != nil {
		return err
	}
	if err := checkAllowedPaths(manifest.Slug, paths, manifest.AllowedPaths); err != nil {
		return e.reject(manifest.Slug, commit, newOperationID(), "policy", err.Error())
	}
	size, err := e.Repository.TreeSize(ctx, commit, manifest.Slug)
	if err != nil {
		return err
	}
	if size > manifest.MaximumContext {
		return e.reject(manifest.Slug, commit, newOperationID(), "policy", "Service source exceeds the approved build context.")
	}
	request := e.runRequest("build", newOperationID(), manifest, commit)
	intent := OperationIntent{Stage: "build", Request: request}
	if err := e.Store.Update(AuditEvent{Service: manifest.Slug, Action: "candidate", Outcome: "building", ActorID: "gitea", TraceID: request.OperationID, Commit: commit}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "building"
		service.PublicMessage = ""
		service.Intent = &intent
		service.CandidateCommit = commit
		service.CandidateDigest = ""
		service.GateDataCopyID = ""
		service.RecoverySnapshotID = ""
		service.ConsecutiveHealthy = 0
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	}); err != nil {
		return err
	}
	return e.executeIntent(ctx, manifest, intent)
}

func (e *Engine) executeIntent(ctx context.Context, manifest ServiceManifest, intent OperationIntent) error {
	request := intent.Request
	runContext, cancel := context.WithTimeout(ctx, time.Duration(request.Resources.TimeoutSeconds)*time.Second)
	result, err := e.Runner.Run(runContext, request)
	cancel()
	if err != nil {
		return err
	}
	switch intent.Stage {
	case "build":
		if !result.OK {
			return e.reject(manifest.Slug, request.Commit, request.OperationID, "build", publicOr(result.PublicMessage, "Build failed."))
		}
		if !validRunnerResult(result, e.Manifest.PolicyVersion) || !digestPattern.MatchString(result.Digest) {
			return errors.New("build runner returned an invalid success result")
		}
		return e.beginGate(ctx, manifest, request, result.Digest)
	case "gate":
		if !result.OK {
			return e.reject(manifest.Slug, request.Commit, request.OperationID, "gate", publicOr(result.PublicMessage, "Deployment Gate failed."))
		}
		if !validRunnerResult(result, e.Manifest.PolicyVersion) || result.DataCopyID == "" {
			return errors.New("gate runner returned an invalid success result")
		}
		return e.finishGate(ctx, manifest, request, result.DataCopyID)
	case "promote":
		if !result.OK || !validRunnerResult(result, e.Manifest.PolicyVersion) || result.Digest != request.CandidateDigest || result.Healthy == nil || !*result.Healthy || result.RecoverySnapshotID == "" {
			return e.beginRecovery(ctx, manifest, intent)
		}
		return e.finishPromotion(manifest, intent, result)
	case "recovery":
		if !result.OK || !validRunnerResult(result, e.Manifest.PolicyVersion) || result.Digest != request.TargetDigest || result.Healthy == nil || !*result.Healthy {
			return e.operatorIntervention(manifest.Slug, intent, "Promotion recovery requires operator intervention.")
		}
		return e.reject(manifest.Slug, request.Commit, request.OperationID, "promotion", "Promotion failed; the previous image was restored.")
	case "manual-rollback", "auto-rollback":
		if !result.OK || !validRunnerResult(result, e.Manifest.PolicyVersion) || result.Digest != request.TargetDigest || result.Healthy == nil || !*result.Healthy {
			return e.operatorIntervention(manifest.Slug, intent, "Rollback requires operator intervention.")
		}
		return e.finishRollback(manifest, intent)
	default:
		return errors.New("invalid persisted intent")
	}
}

func (e *Engine) beginGate(ctx context.Context, manifest ServiceManifest, buildRequest RunRequest, digest string) error {
	request := e.runRequest("gate", newOperationID(), manifest, buildRequest.Commit)
	request.CandidateDigest = digest
	request.DataMode = "copy-current"
	request.PreviousFlagTicks = manifest.PreviousFlagTicks
	intent := OperationIntent{Stage: "gate", Request: request}
	if err := e.Store.Update(AuditEvent{Service: manifest.Slug, Action: "build", Outcome: "built", ActorID: "orchestrator", TraceID: buildRequest.OperationID, Commit: buildRequest.Commit, Digest: digest}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "validating"
		service.CandidateDigest = digest
		service.Intent = &intent
		service.PublicMessage = ""
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	}); err != nil {
		return err
	}
	return e.executeIntent(ctx, manifest, intent)
}

func (e *Engine) finishGate(ctx context.Context, manifest ServiceManifest, gateRequest RunRequest, dataCopyID string) error {
	if err := e.Store.Update(AuditEvent{Service: manifest.Slug, Action: "gate", Outcome: "passed", ActorID: "orchestrator", TraceID: gateRequest.OperationID, Commit: gateRequest.Commit, Digest: gateRequest.CandidateDigest, DataCopyID: dataCopyID}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "waiting"
		service.Intent = nil
		service.GateDataCopyID = dataCopyID
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	}); err != nil {
		return err
	}
	return nil
}

func (e *Engine) promoteAt(ctx context.Context, manifest ServiceManifest, before ServiceState, promotionTick int64) error {
	request := e.runRequest("promote", newOperationID(), manifest, before.CandidateCommit)
	request.CandidateDigest = before.CandidateDigest
	request.CurrentDigest = before.CurrentDigest
	request.LastKnownGoodDigest = before.LastKnownGoodDigest
	request.DataMode = "preserve-current"
	request.PromotionTick = promotionTick
	intent := OperationIntent{Stage: "promote", Request: request, TargetCommit: before.CurrentCommit}
	if err := e.Store.Update(AuditEvent{Service: manifest.Slug, Action: "promotion", Outcome: "started", ActorID: "orchestrator", TraceID: request.OperationID, Commit: request.Commit, Digest: request.CandidateDigest, PreviousDigest: request.CurrentDigest, DataCopyID: before.GateDataCopyID}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "promoting"
		service.Intent = &intent
		service.PromotionTick = promotionTick
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	}); err != nil {
		return err
	}
	return e.executeIntent(ctx, manifest, intent)
}

func (e *Engine) finishPromotion(manifest ServiceManifest, intent OperationIntent, result RunResult) error {
	request := intent.Request
	now := time.Now().UTC()
	return e.Store.Update(AuditEvent{
		Service: manifest.Slug, Action: "promotion", Outcome: "promoted", ActorID: "orchestrator", TraceID: request.OperationID,
		Commit: request.Commit, Digest: request.CandidateDigest, PreviousDigest: request.CurrentDigest,
		RecoverySnapshotID: result.RecoverySnapshotID,
	}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "watching"
		service.PublicMessage = "Deployment promoted and under enhanced health observation."
		service.Intent = nil
		service.CurrentCommit = request.Commit
		service.CurrentDigest = request.CandidateDigest
		service.LastKnownGoodCommit = intent.TargetCommit
		service.LastKnownGoodDigest = request.CurrentDigest
		service.RecoverySnapshotID = result.RecoverySnapshotID
		service.LastHealthTick = 0
		service.CausalFailures = 0
		service.ConsecutiveHealthy = 0
		service.UpdatedAt = now
		next.Services[manifest.Slug] = service
		deletePending(next, manifest.Slug, request.Commit)
		return nil
	})
}

func (e *Engine) beginRecovery(ctx context.Context, manifest ServiceManifest, promoteIntent OperationIntent) error {
	promote := promoteIntent.Request
	request := e.runRequest("rollback", newOperationID(), manifest, promote.Commit)
	request.TargetDigest = promote.CurrentDigest
	request.CurrentDigest = promote.CandidateDigest
	request.DataMode = "preserve-current"
	intent := OperationIntent{Stage: "recovery", Request: request, TargetCommit: promoteIntent.TargetCommit}
	if err := e.Store.Update(AuditEvent{Service: manifest.Slug, Action: "promotion", Outcome: "recovering", ActorID: "orchestrator", TraceID: request.OperationID, Commit: promote.Commit, Digest: promote.CandidateDigest, PreviousDigest: promote.CurrentDigest}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "recovering"
		service.Intent = &intent
		service.PublicMessage = "Promotion failed; restoring the previous image."
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	}); err != nil {
		return err
	}
	return e.executeIntent(ctx, manifest, intent)
}

func (e *Engine) reject(service, commit, operationID, stage, message string) error {
	message = boundedMessage(message)
	return e.Store.Update(AuditEvent{Service: service, Action: stage, Outcome: "rejected", ActorID: "orchestrator", TraceID: operationID, Commit: commit, Message: message}, func(next *PersistentState) error {
		current := next.Services[service]
		current.Status = "rejected"
		current.PublicMessage = message
		current.Intent = nil
		current.CandidateCommit = ""
		current.CandidateDigest = ""
		current.GateDataCopyID = ""
		current.ConsecutiveHealthy = 0
		current.UpdatedAt = time.Now().UTC()
		next.Services[service] = current
		deletePending(next, service, commit)
		return nil
	})
}

func (e *Engine) operatorIntervention(service string, intent OperationIntent, message string) error {
	if err := e.Store.Update(AuditEvent{Service: service, Action: intent.Stage, Outcome: "operator-intervention", ActorID: "orchestrator", TraceID: intent.Request.OperationID, Commit: intent.Request.Commit, Digest: intent.Request.CurrentDigest, PreviousDigest: intent.Request.TargetDigest, Message: message}, func(next *PersistentState) error {
		current := next.Services[service]
		current.Status = "operator-intervention"
		current.PublicMessage = message
		current.Intent = nil
		current.UpdatedAt = time.Now().UTC()
		next.Services[service] = current
		return nil
	}); err != nil {
		return err
	}
	return errors.New("operator intervention required")
}

func deletePending(state *PersistentState, service, commit string) {
	if state.Pending[service] == commit {
		delete(state.Pending, service)
	}
}

func (e *Engine) runRequest(operation, operationID string, manifest ServiceManifest, commit string) RunRequest {
	timeout := manifest.BuildTimeout.Value()
	switch operation {
	case "gate":
		timeout = manifest.GateTimeout.Value()
	case "promote", "rollback":
		timeout = manifest.PromotionTimeout.Value()
	case "health":
		timeout = manifest.HealthTimeout.Value()
	}
	return RunRequest{
		SchemaVersion: 1, Operation: operation, OperationID: operationID,
		TeamID: e.Config.TeamID, TeamNumber: e.Config.TeamNumber, Service: manifest.Slug,
		RepositoryPath: e.Config.Repository.Path, Commit: commit, BaseCommit: manifest.BaseCommit,
		BundleSHA256: manifest.BundleSHA256, PolicyVersion: e.Manifest.PolicyVersion, FactoryDigest: manifest.FactoryDigest,
		Resources: ResourceContract{
			NetworkMode: "none", MaximumContextBytes: manifest.MaximumContext,
			MemoryBytes: manifest.MemoryBytes, CPUMillis: manifest.CPUMillis, PIDs: manifest.PIDs,
			TimeoutSeconds: int64(timeout / time.Second),
		},
	}
}

func validRunnerResult(result RunResult, policy string) bool {
	return result.RunnerPolicyVersion == policy
}

func VerifyFactoryState(ctx context.Context, cfg *Config, manifest *Manifest, runner Runner) error {
	for _, service := range manifest.Services {
		request := RunRequest{
			SchemaVersion: 1, Operation: "health", OperationID: newOperationID(),
			TeamID: cfg.TeamID, TeamNumber: cfg.TeamNumber, Service: service.Slug,
			PolicyVersion: manifest.PolicyVersion, TargetDigest: service.FactoryDigest,
			FactoryDigest: service.FactoryDigest, DataMode: "preserve-current",
			Resources: ResourceContract{NetworkMode: "none", TimeoutSeconds: int64(service.HealthTimeout.Value() / time.Second)},
		}
		healthContext, cancel := context.WithTimeout(ctx, service.HealthTimeout.Value())
		result, err := runner.Run(healthContext, request)
		cancel()
		if err != nil || !result.OK || !validRunnerResult(result, manifest.PolicyVersion) || result.Digest != service.FactoryDigest || result.Healthy == nil || !*result.Healthy {
			return errors.New("factory image health does not match the services manifest")
		}
	}
	return nil
}

func publicOr(message, fallback string) string {
	if bounded := boundedMessage(message); bounded != "" {
		return bounded
	}
	return fallback
}

func newOperationID() string {
	value := make([]byte, 16)
	if _, err := rand.Read(value); err != nil {
		panic(err)
	}
	return hex.EncodeToString(value)
}

type HealthObservation struct {
	Service        string `json:"service"`
	Digest         string `json:"digest"`
	PreviousDigest string `json:"previous_digest"`
	Tick           int64  `json:"tick"`
	CurrentStatus  string `json:"current_status"`
	PreviousStatus string `json:"previous_status"`
	TraceID        string `json:"trace_id"`
}

func (e *Engine) ObserveHealth(ctx context.Context, observation HealthObservation) error {
	manifest, ok := e.Manifest.Service(observation.Service)
	if !ok || !validHealthStatus(observation.CurrentStatus) || !validHealthStatus(observation.PreviousStatus) || observation.Tick < 0 || !validTraceID(observation.TraceID) {
		return errors.New("invalid health observation")
	}
	lock := e.serviceMu[observation.Service]
	lock.Lock()
	defer lock.Unlock()
	service := e.Store.Snapshot().Services[observation.Service]
	if service.Status != "watching" || service.Intent != nil || observation.Digest != service.CurrentDigest || observation.PreviousDigest != service.LastKnownGoodDigest || observation.Tick <= service.PromotionTick || observation.Tick > service.PromotionTick+5 || observation.Tick <= service.LastHealthTick {
		return errors.New("health observation does not match active promotion")
	}
	failures := 0
	healthy := 0
	if observation.CurrentStatus == "DOWN" && observation.PreviousStatus == "OK" {
		failures = 1
		if service.CausalFailures > 0 && observation.Tick == service.LastHealthTick+1 {
			failures = service.CausalFailures + 1
		}
	} else if observation.CurrentStatus == "OK" {
		healthy = 1
		if service.ConsecutiveHealthy > 0 && observation.Tick == service.LastHealthTick+1 {
			healthy = service.ConsecutiveHealthy + 1
		}
	}
	var rollbackIntent *OperationIntent
	if failures >= 2 {
		intent := e.rollbackIntent(manifest, service, service.LastKnownGoodDigest, "auto-rollback", "anvil", observation.TraceID)
		rollbackIntent = &intent
	}
	if err := e.Store.Update(AuditEvent{Service: observation.Service, Action: "health-observation", Outcome: stringsLower(observation.CurrentStatus), ActorID: "anvil", TraceID: observation.TraceID, Digest: observation.Digest, PreviousDigest: observation.PreviousDigest}, func(next *PersistentState) error {
		current := next.Services[observation.Service]
		current.LastHealthTick = observation.Tick
		current.CausalFailures = failures
		current.ConsecutiveHealthy = healthy
		if rollbackIntent != nil {
			current.Status = "rolling-back"
			current.Intent = rollbackIntent
		} else if healthy >= requiredHealthyObservations {
			current.Status = "healthy"
			current.PublicMessage = "Deployment passed post-promotion health observation."
			current.LastKnownGoodCommit = current.CurrentCommit
			current.LastKnownGoodDigest = current.CurrentDigest
			current.CandidateCommit = ""
			current.CandidateDigest = ""
			current.GateDataCopyID = ""
			addHistory(&current, Artifact{Commit: current.CurrentCommit, Digest: current.CurrentDigest, GreenAt: time.Now().UTC()})
		}
		current.UpdatedAt = time.Now().UTC()
		next.Services[observation.Service] = current
		return nil
	}); err != nil {
		return err
	}
	if rollbackIntent != nil {
		e.signalService(observation.Service)
	}
	return nil
}

func (e *Engine) ManualRollback(ctx context.Context, service, target, actorID, traceID string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	manifest, ok := e.Manifest.Service(service)
	if !ok || !validActorID(actorID) || !validTraceID(traceID) {
		return errors.New("invalid rollback request")
	}
	lock := e.serviceMu[service]
	lock.Lock()
	defer lock.Unlock()
	state := e.Store.Snapshot().Services[service]
	if state.Intent != nil {
		return errors.New("service already has an in-flight operation")
	}
	digest := target
	switch target {
	case "last-known-good":
		digest = state.LastKnownGoodDigest
	case "factory":
		digest = state.FactoryDigest
	}
	found := false
	for _, artifact := range state.History {
		if artifact.Digest == digest {
			found = true
			break
		}
	}
	if !found {
		return errors.New("rollback target is not a previously green digest")
	}
	intent := e.rollbackIntent(manifest, state, digest, "manual-rollback", actorID, traceID)
	if err := e.Store.Update(AuditEvent{Service: service, Action: "manual-rollback", Outcome: "started", ActorID: actorID, TraceID: traceID, Digest: digest, PreviousDigest: state.CurrentDigest}, func(next *PersistentState) error {
		current := next.Services[service]
		current.Status = "rolling-back"
		current.Intent = &intent
		current.UpdatedAt = time.Now().UTC()
		next.Services[service] = current
		return nil
	}); err != nil {
		return err
	}
	e.cancelQuietWait(service)
	e.signalService(service)
	return nil
}

func (e *Engine) rollbackIntent(manifest ServiceManifest, before ServiceState, target, action, actorID, traceID string) OperationIntent {
	request := e.runRequest("rollback", newOperationID(), manifest, before.CurrentCommit)
	request.TargetDigest = target
	request.CurrentDigest = before.CurrentDigest
	request.DataMode = "preserve-current"
	commit := before.FactoryCommit
	for _, artifact := range before.History {
		if artifact.Digest == target {
			commit = artifact.Commit
			break
		}
	}
	return OperationIntent{Stage: action, Request: request, Action: action, ActorID: actorID, TraceID: traceID, TargetCommit: commit}
}

func (e *Engine) finishRollback(manifest ServiceManifest, intent OperationIntent) error {
	request := intent.Request
	return e.Store.Update(AuditEvent{Service: manifest.Slug, Action: intent.Action, Outcome: "rolled-back", ActorID: intent.ActorID, TraceID: intent.TraceID, Commit: intent.TargetCommit, Digest: request.TargetDigest, PreviousDigest: request.CurrentDigest}, func(next *PersistentState) error {
		service := next.Services[manifest.Slug]
		service.Status = "healthy"
		service.PublicMessage = "A known-good image was restored; live data was preserved."
		service.Intent = nil
		service.CurrentCommit = intent.TargetCommit
		service.CurrentDigest = request.TargetDigest
		service.LastKnownGoodCommit = intent.TargetCommit
		service.LastKnownGoodDigest = request.TargetDigest
		service.CandidateCommit = ""
		service.CandidateDigest = ""
		service.GateDataCopyID = ""
		service.CausalFailures = 0
		service.ConsecutiveHealthy = 0
		service.LastHealthTick = 0
		service.UpdatedAt = time.Now().UTC()
		next.Services[manifest.Slug] = service
		return nil
	})
}

func validHealthStatus(value string) bool {
	return value == "OK" || value == "DOWN" || value == "ERROR"
}

func validTraceID(value string) bool {
	if len(value) < 8 || len(value) > 128 {
		return false
	}
	for _, character := range value {
		if !(character == '-' || character == '_' || character == '.' || character >= '0' && character <= '9' || character >= 'A' && character <= 'Z' || character >= 'a' && character <= 'z') {
			return false
		}
	}
	return true
}

func validActorID(value string) bool { return validTraceID(value) }

func stringsLower(value string) string {
	switch value {
	case "OK":
		return "ok"
	case "DOWN":
		return "down"
	default:
		return "error"
	}
}
