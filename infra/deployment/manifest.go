package orchestrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"sort"
	"strings"
	"time"
)

type Manifest struct {
	SchemaVersion int               `json:"schema_version"`
	PolicyVersion string            `json:"policy_version"`
	Services      []ServiceManifest `json:"services"`
}

type ServiceManifest struct {
	Slug              string   `json:"slug"`
	BaseCommit        string   `json:"base_commit"`
	BundleSHA256      string   `json:"bundle_sha256"`
	FactoryDigest     string   `json:"factory_digest"`
	AllowedPaths      []string `json:"allowed_paths"`
	MaximumContext    int64    `json:"maximum_context_bytes"`
	MemoryBytes       int64    `json:"memory_bytes"`
	CPUMillis         int      `json:"cpu_millis"`
	PIDs              int      `json:"pids"`
	BuildTimeout      Duration `json:"build_timeout"`
	GateTimeout       Duration `json:"gate_timeout"`
	PromotionTimeout  Duration `json:"promotion_timeout"`
	HealthTimeout     Duration `json:"health_timeout"`
	PreviousFlagTicks int      `json:"previous_flag_ticks"`
}

func LoadManifest(file string, expected int) (*Manifest, error) {
	data, err := os.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("read services manifest: %w", err)
	}
	var manifest Manifest
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&manifest); err != nil {
		return nil, fmt.Errorf("decode services manifest: %w", err)
	}
	if dec.Decode(&struct{}{}) != io.EOF {
		return nil, errors.New("services manifest must contain one JSON value")
	}
	if err := manifest.validate(expected); err != nil {
		return nil, err
	}
	sort.Slice(manifest.Services, func(i, j int) bool { return manifest.Services[i].Slug < manifest.Services[j].Slug })
	return &manifest, nil
}

func (m *Manifest) validate(expected int) error {
	if m.SchemaVersion != 1 || !slugPattern.MatchString(m.PolicyVersion) {
		return errors.New("services manifest requires schema_version 1 and a slug policy_version")
	}
	if len(m.Services) != expected {
		return fmt.Errorf("services manifest has %d services, expected %d", len(m.Services), expected)
	}
	seen := make(map[string]struct{}, len(m.Services))
	for i := range m.Services {
		s := &m.Services[i]
		if !slugPattern.MatchString(s.Slug) {
			return fmt.Errorf("service %d has an invalid slug", i)
		}
		if _, ok := seen[s.Slug]; ok {
			return fmt.Errorf("duplicate service %q", s.Slug)
		}
		seen[s.Slug] = struct{}{}
		if !commitPattern.MatchString(s.BaseCommit) || !digestPattern.MatchString("sha256:"+s.BundleSHA256) || !digestPattern.MatchString(s.FactoryDigest) {
			return fmt.Errorf("service %q requires exact base, bundle and factory identities", s.Slug)
		}
		if len(s.AllowedPaths) == 0 {
			return fmt.Errorf("service %q has no allowed paths", s.Slug)
		}
		for _, allowed := range s.AllowedPaths {
			if !validRelativePath(allowed) {
				return fmt.Errorf("service %q has invalid allowed path %q", s.Slug, allowed)
			}
		}
		if s.MaximumContext < 1024 || s.MaximumContext > 100*1024*1024 || s.MemoryBytes < 64*1024*1024 || s.CPUMillis < 100 || s.CPUMillis > 4000 || s.PIDs < 16 || s.PIDs > 1024 {
			return fmt.Errorf("service %q has invalid resource bounds", s.Slug)
		}
		for name, duration := range map[string]time.Duration{
			"build": s.BuildTimeout.Value(), "gate": s.GateTimeout.Value(),
			"promotion": s.PromotionTimeout.Value(), "health": s.HealthTimeout.Value(),
		} {
			if duration < time.Second || duration > 10*time.Minute {
				return fmt.Errorf("service %q has invalid %s timeout", s.Slug, name)
			}
		}
		if s.PreviousFlagTicks != 5 {
			return fmt.Errorf("service %q must test the previous five ticks", s.Slug)
		}
	}
	return nil
}

func validRelativePath(value string) bool {
	if value == "" || strings.HasPrefix(value, "/") || strings.Contains(value, "\\") {
		return false
	}
	clean := path.Clean(value)
	return clean == strings.TrimSuffix(value, "/") && clean != "." && clean != ".." && !strings.HasPrefix(clean, "../")
}

func (m *Manifest) Service(slug string) (ServiceManifest, bool) {
	for _, service := range m.Services {
		if service.Slug == slug {
			return service, true
		}
	}
	return ServiceManifest{}, false
}

func pathAllowed(relative string, allowed []string) bool {
	for _, rule := range allowed {
		if strings.HasSuffix(rule, "/") && strings.HasPrefix(relative, rule) {
			return true
		}
		if relative == rule {
			return true
		}
	}
	return false
}
