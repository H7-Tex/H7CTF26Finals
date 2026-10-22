package orchestrator

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Server struct {
	Config *Config
	Store  *Store
	Engine *Engine
}

type pushPayload struct {
	Ref        string `json:"ref"`
	Before     string `json:"before"`
	After      string `json:"after"`
	Repository struct {
		FullName string `json:"full_name"`
	} `json:"repository"`
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.health)
	mux.HandleFunc("POST /v1/webhooks/gitea", s.webhook)
	mux.Handle("GET /v1/status", s.authenticate(http.HandlerFunc(s.status)))
	mux.Handle("GET /v1/audit", s.authenticate(http.HandlerFunc(s.audit)))
	mux.Handle("POST /v1/rollback/{service}", s.authenticate(http.HandlerFunc(s.rollback)))
	mux.Handle("POST /v1/health-observations", s.authenticate(http.HandlerFunc(s.observeHealth)))
	return securityHeaders(mux)
}

func (s *Server) HTTPServer() *http.Server {
	return &http.Server{
		Addr: s.Config.ListenAddress, Handler: s.Handler(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 30 * time.Second,
		MaxHeaderBytes: 16 * 1024,
	}
}

func (s *Server) webhook(response http.ResponseWriter, request *http.Request) {
	request.Body = http.MaxBytesReader(response, request.Body, s.Config.MaximumBodyBytes)
	body, err := io.ReadAll(request.Body)
	if err != nil {
		writeError(response, http.StatusBadRequest, "invalid request")
		return
	}
	deliveryID := request.Header.Get("X-Gitea-Delivery")
	if request.Header.Get("X-Gitea-Event") != "push" || !validTraceID(deliveryID) || !verifySignature(s.Config.WebhookSecret, body, request.Header.Get("X-Gitea-Signature")) {
		log.Printf("rejected unauthenticated deployment webhook")
		writeError(response, http.StatusNotFound, "not found")
		return
	}
	bodyDigest := sha256.Sum256(body)
	bodyHash := hex.EncodeToString(bodyDigest[:])
	if previous, ok := s.Store.delivery(deliveryID); ok {
		if previous.BodyHash != bodyHash {
			_ = s.Store.Update(AuditEvent{Action: "webhook", Outcome: "replay-rejected", ActorID: "gitea", TraceID: deliveryID, Message: "Delivery identifier was reused with a different body."}, nil)
			writeError(response, http.StatusConflict, "delivery conflict")
			return
		}
		response.WriteHeader(http.StatusAccepted)
		return
	}
	var payload pushPayload
	decoder := json.NewDecoder(strings.NewReader(string(body)))
	decodeErr := decoder.Decode(&payload)
	if decodeErr == nil && decoder.Decode(&struct{}{}) != io.EOF {
		decodeErr = errors.New("multiple JSON values")
	}
	if decodeErr != nil || payload.Ref != "refs/heads/main" || payload.Repository.FullName != s.Config.Repository.ExpectedFullName || !commitPattern.MatchString(payload.Before) || !commitPattern.MatchString(payload.After) {
		_ = s.Store.Update(AuditEvent{Action: "webhook", Outcome: "identity-rejected", ActorID: "gitea", TraceID: deliveryID, Message: "Webhook repository, branch or commit identity did not match."}, nil)
		writeError(response, http.StatusUnprocessableEntity, "webhook identity mismatch")
		return
	}
	if err := s.Store.Update(AuditEvent{Action: "webhook", Outcome: "accepted", ActorID: "gitea", TraceID: deliveryID, Commit: payload.After}, func(next *PersistentState) error {
		rememberDelivery(next, DeliveryRecord{ID: deliveryID, BodyHash: bodyHash, SeenAt: time.Now().UTC()})
		return nil
	}); err != nil {
		writeError(response, http.StatusServiceUnavailable, "state unavailable")
		return
	}
	s.Engine.Trigger()
	response.WriteHeader(http.StatusAccepted)
}

func (s *Server) status(response http.ResponseWriter, _ *http.Request) {
	writeJSON(response, http.StatusOK, s.Store.Snapshot())
}

func (s *Server) audit(response http.ResponseWriter, request *http.Request) {
	after, err := strconv.ParseUint(defaultValue(request.URL.Query().Get("after"), "0"), 10, 64)
	if err != nil {
		writeError(response, http.StatusBadRequest, "invalid after sequence")
		return
	}
	limit, err := strconv.Atoi(defaultValue(request.URL.Query().Get("limit"), "100"))
	if err != nil {
		writeError(response, http.StatusBadRequest, "invalid limit")
		return
	}
	events, err := s.Store.Audit(after, limit)
	if err != nil {
		writeError(response, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(response, http.StatusOK, map[string]any{"events": events})
}

func (s *Server) rollback(response http.ResponseWriter, request *http.Request) {
	request.Body = http.MaxBytesReader(response, request.Body, 16*1024)
	var body struct {
		Target  string `json:"target"`
		ActorID string `json:"actor_id"`
		TraceID string `json:"trace_id"`
	}
	if err := decodeJSON(request.Body, &body); err != nil {
		writeError(response, http.StatusBadRequest, "invalid rollback request")
		return
	}
	if err := s.Engine.ManualRollback(request.Context(), request.PathValue("service"), body.Target, body.ActorID, body.TraceID); err != nil {
		writeError(response, http.StatusConflict, "rollback rejected")
		return
	}
	writeJSON(response, http.StatusAccepted, map[string]bool{"queued": true})
}

func (s *Server) observeHealth(response http.ResponseWriter, request *http.Request) {
	request.Body = http.MaxBytesReader(response, request.Body, 16*1024)
	var observation HealthObservation
	if err := decodeJSON(request.Body, &observation); err != nil {
		writeError(response, http.StatusBadRequest, "invalid health observation")
		return
	}
	if err := s.Engine.ObserveHealth(request.Context(), observation); err != nil {
		writeError(response, http.StatusConflict, "health observation rejected")
		return
	}
	writeJSON(response, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) health(response http.ResponseWriter, _ *http.Request) {
	if !s.Store.Healthy() {
		writeError(response, http.StatusServiceUnavailable, "state unavailable")
		return
	}
	writeJSON(response, http.StatusOK, map[string]any{"ok": true, "component": "Deployment Orchestrator"})
}

func (s *Server) authenticate(next http.Handler) http.Handler {
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		authorization := request.Header.Get("Authorization")
		provided, ok := strings.CutPrefix(authorization, "Bearer ")
		if !ok || len(provided) != len(s.Config.InternalToken) || subtle.ConstantTimeCompare([]byte(provided), s.Config.InternalToken) != 1 {
			writeError(response, http.StatusNotFound, "not found")
			return
		}
		next.ServeHTTP(response, request)
	})
}

func verifySignature(secret, body []byte, signature string) bool {
	provided, err := hex.DecodeString(signature)
	if err != nil || len(provided) != sha256.Size {
		return false
	}
	mac := hmac.New(sha256.New, secret)
	_, _ = mac.Write(body)
	return hmac.Equal(provided, mac.Sum(nil))
}

func decodeJSON(reader io.Reader, destination any) error {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	if decoder.Decode(&struct{}{}) != io.EOF {
		return errors.New("request must contain one JSON value")
	}
	return nil
}

func writeJSON(response http.ResponseWriter, status int, value any) {
	response.Header().Set("Content-Type", "application/json")
	response.WriteHeader(status)
	_ = json.NewEncoder(response).Encode(value)
}

func writeError(response http.ResponseWriter, status int, message string) {
	writeJSON(response, status, map[string]string{"error": boundedMessage(message)})
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.Header().Set("Cache-Control", "no-store")
		response.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
		response.Header().Set("X-Content-Type-Options", "nosniff")
		response.Header().Set("X-Frame-Options", "DENY")
		response.Header().Set("Referrer-Policy", "no-referrer")
		next.ServeHTTP(response, request)
	})
}

func defaultValue(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func shutdownHTTP(ctx context.Context, server *http.Server) error { return server.Shutdown(ctx) }
