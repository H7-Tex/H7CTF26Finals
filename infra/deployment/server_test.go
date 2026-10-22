package orchestrator

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
)

func TestWebhookSignatureIdentityAndReplay(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	cfg.MaximumBodyBytes = 1024 * 1024
	cfg.Repository.ExpectedFullName = "team-01/services"
	cfg.WebhookSecret = []byte("0123456789abcdef0123456789abcdef")
	cfg.InternalToken = []byte("abcdef0123456789abcdef0123456789")
	engine := NewEngine(cfg, manifest, store, nil, nil, nil)
	server := &Server{Config: cfg, Store: store, Engine: engine}
	body := []byte(`{"ref":"refs/heads/main","before":"` + baseCommit + `","after":"` + candidateCommit + `","repository":{"full_name":"team-01/services"}}`)

	request := signedWebhook(t, body, "delivery-0001", cfg.WebhookSecret)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusAccepted || len(store.Snapshot().Deliveries) != 1 {
		t.Fatalf("valid webhook rejected: status=%d body=%s", response.Code, response.Body.String())
	}
	sequence := store.Snapshot().NextSequence
	request = signedWebhook(t, body, "delivery-0001", cfg.WebhookSecret)
	response = httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusAccepted || store.Snapshot().NextSequence != sequence {
		t.Fatal("idempotent replay changed durable state")
	}

	conflict := []byte(`{"ref":"refs/heads/main","before":"` + baseCommit + `","after":"` + baseCommit + `","repository":{"full_name":"team-01/services"}}`)
	request = signedWebhook(t, conflict, "delivery-0001", cfg.WebhookSecret)
	response = httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusConflict {
		t.Fatalf("conflicting replay status=%d", response.Code)
	}
}

func TestInternalAPIIsFailClosed(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	cfg.InternalToken = []byte("abcdef0123456789abcdef0123456789")
	server := &Server{Config: cfg, Store: store, Engine: NewEngine(cfg, manifest, store, nil, nil, nil)}
	request := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusNotFound {
		t.Fatalf("missing token returned %d", response.Code)
	}
	request = httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	request.Header.Set("Authorization", "Bearer "+string(cfg.InternalToken))
	response = httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("valid token returned %d", response.Code)
	}
}

func TestHealthFailsClosedAfterDurableStatePoison(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	server := &Server{Config: cfg, Store: store, Engine: NewEngine(cfg, manifest, store, nil, nil, nil)}
	request := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("healthy store returned %d", response.Code)
	}

	store.auditPath = filepath.Join(t.TempDir(), "missing", "audit.jsonl")
	if err := store.Update(AuditEvent{Action: "test", Outcome: "poison", ActorID: "test", TraceID: "health-poison-test"}, nil); err == nil {
		t.Fatal("durable write failure did not poison the store")
	}
	request = httptest.NewRequest(http.MethodGet, "/healthz", nil)
	response = httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("poisoned store returned %d", response.Code)
	}
	body := response.Body.String()
	if body != "{\"error\":\"state unavailable\"}\n" || strings.Contains(body, store.auditPath) {
		t.Fatalf("health response exposed internal failure: %s", body)
	}
}

func TestRollbackEndpointDurablyQueuesBeforeReconciliation(t *testing.T) {
	cfg, manifest, store := testFixture(t)
	cfg.InternalToken = []byte("abcdef0123456789abcdef0123456789")
	runner := &fakeRunner{results: map[string][]RunResult{
		"rollback": {{OK: true, Digest: factoryDigest, Healthy: boolPointer(true), RunnerPolicyVersion: "policy-1"}},
	}, errors: map[string]error{}}
	engine := NewEngine(cfg, manifest, store, &fakeRepository{}, runner, fakeQuiet{})
	server := &Server{Config: cfg, Store: store, Engine: engine}
	request := httptest.NewRequest(http.MethodPost, "/v1/rollback/service-one", strings.NewReader(`{"target":"factory","actor_id":"operator-01","trace_id":"rollback-request-01"}`))
	request.Header.Set("Authorization", "Bearer "+string(cfg.InternalToken))
	response := httptest.NewRecorder()
	server.Handler().ServeHTTP(response, request)
	if response.Code != http.StatusAccepted || response.Body.String() != "{\"queued\":true}\n" {
		t.Fatalf("rollback queue response=%d body=%s", response.Code, response.Body.String())
	}
	service := store.Snapshot().Services["service-one"]
	if service.Intent == nil || service.Intent.Stage != "manual-rollback" || service.Status != "rolling-back" || len(runner.requests) != 0 {
		t.Fatalf("rollback was not durably queued before execution: service=%+v requests=%+v", service, runner.requests)
	}
	if err := engine.resumeService(context.Background(), "service-one"); err != nil {
		t.Fatal(err)
	}
	service = store.Snapshot().Services["service-one"]
	if service.Intent != nil || service.Status != "healthy" || len(runner.requests) != 1 {
		t.Fatalf("reconciliation did not execute queued rollback: service=%+v requests=%+v", service, runner.requests)
	}
}

func signedWebhook(t *testing.T, body []byte, delivery string, secret []byte) *http.Request {
	t.Helper()
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write(body)
	request := httptest.NewRequest(http.MethodPost, "/v1/webhooks/gitea", bytes.NewReader(body))
	request.Header.Set("X-Gitea-Event", "push")
	request.Header.Set("X-Gitea-Delivery", delivery)
	request.Header.Set("X-Gitea-Signature", hex.EncodeToString(mac.Sum(nil)))
	return request
}
