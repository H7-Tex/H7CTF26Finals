package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"
)

type QuietWindow interface {
	Wait(context.Context, int64) (int64, error)
}

type HTTPQuietWindow struct {
	URL    string
	Client *http.Client
	Now    func() time.Time
}

type tickResponse struct {
	Tick     int64     `json:"tick"`
	EndsAt   time.Time `json:"ends_at"`
	HoldFrom time.Time `json:"hold_from"`
	Phase    string    `json:"phase"`
}

func (q HTTPQuietWindow) Wait(ctx context.Context, after int64) (int64, error) {
	client := q.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Second}
	}
	for {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, q.URL, nil)
		if err != nil {
			return 0, err
		}
		response, err := client.Do(request)
		if err != nil {
			return 0, err
		}
		var tick tickResponse
		decodeErr := json.NewDecoder(io.LimitReader(response.Body, 64*1024)).Decode(&tick)
		response.Body.Close()
		if response.StatusCode != http.StatusOK || decodeErr != nil || tick.Phase != "live" || tick.Tick < 0 || tick.HoldFrom.IsZero() || !tick.EndsAt.After(tick.HoldFrom) {
			return 0, errors.New("invalid checker quiet-window response")
		}
		now := time.Now()
		if q.Now != nil {
			now = q.Now()
		}
		if tick.Tick > after && !now.Before(tick.HoldFrom) && now.Before(tick.EndsAt) {
			return tick.Tick, nil
		}
		wait := time.Second
		if now.Before(tick.HoldFrom) {
			wait = time.Until(tick.HoldFrom)
			if wait > 5*time.Second {
				wait = 5 * time.Second
			}
		} else if tick.Tick <= after && now.Before(tick.EndsAt) {
			wait = time.Until(tick.EndsAt) + 100*time.Millisecond
		}
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return 0, ctx.Err()
		case <-timer.C:
		}
	}
}
