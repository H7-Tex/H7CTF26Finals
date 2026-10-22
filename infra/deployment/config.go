package orchestrator

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

var (
	commitPattern = regexp.MustCompile(`^(?:[0-9a-f]{40}|[0-9a-f]{64})$`)
	teamIDPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	repoPattern   = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	slugPattern   = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)
	digestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
)

type Config struct {
	TeamNumber        int              `json:"team_number"`
	TeamID            string           `json:"team_id"`
	ListenAddress     string           `json:"listen_address"`
	StateDirectory    string           `json:"state_directory"`
	Repository        RepositoryConfig `json:"repository"`
	ServicesFile      string           `json:"services_file"`
	WebhookSecretFile string           `json:"webhook_secret_file"`
	InternalTokenFile string           `json:"internal_token_file"`
	RunnerCommand     string           `json:"runner_command"`
	TickURL           string           `json:"tick_url"`
	PollInterval      Duration         `json:"poll_interval"`
	MaximumBodyBytes  int64            `json:"maximum_body_bytes"`
	ExpectedServices  int              `json:"expected_services"`

	WebhookSecret []byte `json:"-"`
	InternalToken []byte `json:"-"`
}

type RepositoryConfig struct {
	Path             string `json:"path"`
	RemoteURL        string `json:"remote_url"`
	ExpectedFullName string `json:"expected_full_name"`
	Branch           string `json:"branch"`
	InitialCommit    string `json:"initial_commit"`
}

type Duration time.Duration

func (d *Duration) UnmarshalJSON(data []byte) error {
	var value string
	if err := json.Unmarshal(data, &value); err != nil {
		return errors.New("duration must be a quoted Go duration")
	}
	parsed, err := time.ParseDuration(value)
	if err != nil {
		return err
	}
	*d = Duration(parsed)
	return nil
}

func (d Duration) Value() time.Duration { return time.Duration(d) }

func LoadConfig(path string) (*Config, *Manifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, nil, fmt.Errorf("read config: %w", err)
	}
	var cfg Config
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&cfg); err != nil {
		return nil, nil, fmt.Errorf("decode config: %w", err)
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return nil, nil, errors.New("config must contain one JSON value")
	}
	if err := cfg.validate(); err != nil {
		return nil, nil, err
	}
	if cfg.WebhookSecret, err = readSecret(cfg.WebhookSecretFile); err != nil {
		return nil, nil, fmt.Errorf("webhook secret: %w", err)
	}
	if cfg.InternalToken, err = readSecret(cfg.InternalTokenFile); err != nil {
		return nil, nil, fmt.Errorf("internal token: %w", err)
	}
	manifest, err := LoadManifest(cfg.ServicesFile, cfg.ExpectedServices)
	if err != nil {
		return nil, nil, err
	}
	if err := validateRunner(cfg.RunnerCommand); err != nil {
		return nil, nil, err
	}
	return &cfg, manifest, nil
}

func (c *Config) validate() error {
	if c.TeamNumber < 1 || c.TeamNumber > 15 {
		return errors.New("team_number must be between 1 and 15")
	}
	if !teamIDPattern.MatchString(c.TeamID) {
		return errors.New("team_id must be a lowercase UUID")
	}
	_, port, err := net.SplitHostPort(c.ListenAddress)
	if err != nil || port != "9300" {
		return errors.New("listen_address must use TCP port 9300")
	}
	for name, path := range map[string]string{
		"state_directory": c.StateDirectory, "repository.path": c.Repository.Path,
		"services_file": c.ServicesFile, "webhook_secret_file": c.WebhookSecretFile,
		"internal_token_file": c.InternalTokenFile, "runner_command": c.RunnerCommand,
	} {
		if !filepath.IsAbs(path) {
			return fmt.Errorf("%s must be an absolute path", name)
		}
	}
	if c.Repository.Branch != "main" {
		return errors.New("repository.branch must be main")
	}
	if !repoPattern.MatchString(c.Repository.ExpectedFullName) {
		return errors.New("repository.expected_full_name must be owner/name")
	}
	if !commitPattern.MatchString(c.Repository.InitialCommit) {
		return errors.New("repository.initial_commit must be an exact lowercase Git object ID")
	}
	if c.Repository.RemoteURL == "" {
		return errors.New("repository.remote_url is required")
	}
	parsedTick, err := url.Parse(c.TickURL)
	if err != nil || parsedTick.Scheme != "https" || parsedTick.Host == "" {
		return errors.New("tick_url must be an absolute HTTPS URL")
	}
	if c.PollInterval.Value() < 5*time.Second || c.PollInterval.Value() > time.Minute {
		return errors.New("poll_interval must be between 5s and 1m")
	}
	if c.MaximumBodyBytes < 1024 || c.MaximumBodyBytes > 4*1024*1024 {
		return errors.New("maximum_body_bytes must be between 1 KiB and 4 MiB")
	}
	if c.ExpectedServices < 1 || c.ExpectedServices > 6 {
		return errors.New("expected_services must be between 1 and 6")
	}
	return nil
}

func readSecret(path string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode()&0077 != 0 {
		return nil, errors.New("secret must be a regular file with mode 0600 or stricter")
	}
	value, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	value = []byte(strings.TrimSpace(string(value)))
	if len(value) < 32 {
		return nil, errors.New("secret must contain at least 32 bytes")
	}
	return value, nil
}

func validateRunner(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("runner command: %w", err)
	}
	if !info.Mode().IsRegular() || info.Mode()&0111 == 0 || info.Mode()&0022 != 0 {
		return errors.New("runner command must be an executable regular file not writable by group or other")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat.Uid != 0 {
		return errors.New("runner command must be owned by root")
	}
	return nil
}

func fileSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:]), nil
}

func ManifestHash(path string) (string, error) { return fileSHA256(path) }
