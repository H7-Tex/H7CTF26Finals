package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"time"
)

const deploymentEventPath = "/api/v1/internal/arena/deployment-events"

type deploymentEvent struct {
	TeamID         string `json:"team_id"`
	Service        string `json:"service"`
	SourceSequence int64  `json:"source_sequence"`
	State          string `json:"state"`
	ReasonCode     string `json:"reason_code,omitempty"`
}

type DeploymentEventReporter struct {
	URL          string
	TeamID       string
	Token        []byte
	Store        *Store
	Client       *http.Client
	PollInterval time.Duration
}

func NewDeploymentEventReporter(cfg *Config, store *Store) (*DeploymentEventReporter, error) {
	target, err := url.Parse(cfg.TickURL)
	if err != nil || target.Scheme != "https" || target.Host == "" || target.User != nil {
		return nil, errors.New("tick_url cannot identify the Anvil deployment event endpoint")
	}
	target.Path = deploymentEventPath
	target.RawPath = ""
	target.RawQuery = ""
	target.Fragment = ""
	return &DeploymentEventReporter{
		URL: target.String(), TeamID: cfg.TeamID, Token: cfg.InternalToken, Store: store,
		Client: &http.Client{
			Timeout:       5 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
		},
		PollInterval: cfg.PollInterval.Value(),
	}, nil
}

func (r *DeploymentEventReporter) Run(ctx context.Context) {
	backoff := time.Second
	for {
		err := r.Reconcile(ctx)
		if ctx.Err() != nil {
			return
		}
		wait := r.PollInterval
		if err != nil {
			log.Printf("deployment event reconciliation failed")
			wait = backoff
			backoff *= 2
			if backoff > 30*time.Second {
				backoff = 30 * time.Second
			}
		} else {
			backoff = time.Second
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
	}
}

func (r *DeploymentEventReporter) Reconcile(ctx context.Context) error {
	for {
		cursor := r.Store.Snapshot().ReportedSequence
		events, err := r.Store.Audit(cursor, 100)
		if err != nil {
			return err
		}
		if len(events) == 0 {
			return nil
		}
		for _, event := range events {
			payload, report, err := normalizedDeploymentEvent(r.TeamID, event)
			if err != nil {
				return err
			}
			if report {
				if err := r.send(ctx, payload); err != nil {
					return err
				}
			}
			if err := r.Store.AcknowledgeReported(event.Sequence); err != nil {
				return err
			}
		}
	}
}

func (r *DeploymentEventReporter) send(ctx context.Context, event deploymentEvent) error {
	body, err := json.Marshal(event)
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, r.URL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", "Bearer "+string(r.Token))
	request.Header.Set("Content-Type", "application/json")
	response, err := r.Client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK && response.StatusCode != http.StatusCreated {
		return errors.New("Anvil rejected a deployment event")
	}
	var acknowledgement struct {
		ID int64 `json:"id"`
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 4*1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&acknowledgement); err != nil || acknowledgement.ID < 1 || decoder.Decode(&struct{}{}) != io.EOF {
		return errors.New("Anvil returned an invalid deployment event acknowledgement")
	}
	return nil
}

func normalizedDeploymentEvent(teamID string, event AuditEvent) (deploymentEvent, bool, error) {
	if event.Service == "" {
		return deploymentEvent{}, false, nil
	}
	if event.Sequence > math.MaxInt64 {
		return deploymentEvent{}, false, errors.New("audit sequence exceeds the Anvil event contract")
	}
	payload := deploymentEvent{TeamID: teamID, Service: event.Service, SourceSequence: int64(event.Sequence)}
	switch {
	case event.Action == "candidate" && event.Outcome == "queued":
		payload.State = "queued"
	case event.Action == "candidate" && event.Outcome == "building":
		payload.State = "building"
	case event.Action == "build" && event.Outcome == "built":
		payload.State = "gating"
	case event.Action == "gate" && event.Outcome == "passed":
		payload.State = "waiting_quiet_window"
	case event.Action == "promotion" && event.Outcome == "promoted":
		payload.State = "promoted"
	case (event.Action == "manual-rollback" || event.Action == "auto-rollback") && event.Outcome == "rolled-back":
		payload.State = "rolled_back"
	case event.Outcome == "rejected":
		payload.State = "failed"
		payload.ReasonCode = deploymentFailureReason(event.Action)
	case event.Outcome == "operator-intervention":
		payload.State = "failed"
		payload.ReasonCode = "operator"
	default:
		return deploymentEvent{}, false, nil
	}
	return payload, true, nil
}

func deploymentFailureReason(action string) string {
	switch action {
	case "policy", "build", "gate", "promotion", "health":
		return action
	case "recovery", "manual-rollback", "auto-rollback", "rollback":
		return "rollback"
	default:
		return "unknown"
	}
}
