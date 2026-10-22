package orchestrator

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

type Repository interface {
	FetchRemoteHead(context.Context) (string, error)
	IsAncestor(context.Context, string, string) (bool, error)
	DiffPaths(context.Context, string, string, string) ([]string, error)
	TreeSize(context.Context, string, string) (int64, error)
}

func (g GitRepository) IsAncestor(ctx context.Context, ancestor, descendant string) (bool, error) {
	if !commitPattern.MatchString(ancestor) || !commitPattern.MatchString(descendant) {
		return false, errors.New("ancestry requires exact commit IDs")
	}
	command := exec.CommandContext(ctx, "/usr/bin/git", "-C", g.Config.Path, "merge-base", "--is-ancestor", ancestor, descendant)
	command.Env = []string{
		"PATH=/usr/bin:/bin", "HOME=" + filepath.Dir(g.Config.Path),
		"GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_SYSTEM=/dev/null", "LANG=C.UTF-8",
	}
	err := command.Run()
	if err == nil {
		return true, nil
	}
	if exit, ok := err.(*exec.ExitError); ok && exit.ExitCode() == 1 {
		return false, nil
	}
	return false, fmt.Errorf("check commit ancestry: %w", err)
}

type GitRepository struct {
	Config RepositoryConfig
}

func (g GitRepository) FetchRemoteHead(ctx context.Context) (string, error) {
	ref := "refs/heads/" + g.Config.Branch
	remoteOutput, err := g.run(ctx, 1024*1024, "ls-remote", "--exit-code", g.Config.RemoteURL, ref)
	if err != nil {
		return "", fmt.Errorf("read remote head: %w", err)
	}
	fields := strings.Fields(string(remoteOutput))
	if len(fields) != 2 || fields[1] != ref || !commitPattern.MatchString(fields[0]) {
		return "", errors.New("remote returned an invalid branch head")
	}
	if _, err := g.run(ctx, 1024*1024, "fetch", "--no-tags", "--force", "origin", ref); err != nil {
		return "", fmt.Errorf("fetch remote head: %w", err)
	}
	fetched, err := g.run(ctx, 1024, "rev-parse", "--verify", "FETCH_HEAD^{commit}")
	if err != nil {
		return "", err
	}
	fetchedHead := strings.TrimSpace(string(fetched))
	if fetchedHead != fields[0] {
		return "", errors.New("fetched commit does not match advertised head")
	}
	return fetchedHead, nil
}

func (g GitRepository) DiffPaths(ctx context.Context, from, to, scope string) ([]string, error) {
	if !commitPattern.MatchString(from) || !commitPattern.MatchString(to) {
		return nil, errors.New("diff requires exact commit IDs")
	}
	arguments := []string{"diff", "--name-only", "-z", "--no-renames", from, to, "--"}
	if scope != "" {
		if !slugPattern.MatchString(scope) {
			return nil, errors.New("invalid diff scope")
		}
		arguments = append(arguments, scope+"/")
	}
	output, err := g.run(ctx, 8*1024*1024, arguments...)
	if err != nil {
		return nil, err
	}
	return splitNUL(output), nil
}

func (g GitRepository) TreeSize(ctx context.Context, commit, service string) (int64, error) {
	if !commitPattern.MatchString(commit) || !slugPattern.MatchString(service) {
		return 0, errors.New("invalid tree request")
	}
	output, err := g.run(ctx, 16*1024*1024, "ls-tree", "-lr", "-z", commit, "--", service+"/")
	if err != nil {
		return 0, err
	}
	var total int64
	for _, line := range splitNUL(output) {
		metadata, _, ok := strings.Cut(line, "\t")
		if !ok {
			return 0, errors.New("invalid git tree output")
		}
		fields := strings.Fields(metadata)
		if len(fields) != 4 || fields[0] == "120000" || fields[1] != "blob" {
			return 0, errors.New("service tree contains a symlink, submodule or invalid entry")
		}
		size, err := strconv.ParseInt(fields[3], 10, 64)
		if err != nil || size < 0 {
			return 0, errors.New("invalid service tree size")
		}
		total += size
	}
	return total, nil
}

func (g GitRepository) run(ctx context.Context, maximum int, arguments ...string) ([]byte, error) {
	command := exec.CommandContext(ctx, "/usr/bin/git", append([]string{"-C", g.Config.Path}, arguments...)...)
	command.Env = []string{
		"PATH=/usr/bin:/bin", "HOME=" + filepath.Dir(g.Config.Path),
		"GIT_CONFIG_GLOBAL=/dev/null", "GIT_CONFIG_SYSTEM=/dev/null", "GIT_TERMINAL_PROMPT=0",
		"LANG=C.UTF-8",
	}
	stdout := &cappedBuffer{maximum: maximum}
	stderr := &cappedBuffer{maximum: 64 * 1024}
	command.Stdout = stdout
	command.Stderr = stderr
	if err := command.Run(); err != nil {
		return nil, fmt.Errorf("git %s: %w: %s", arguments[0], err, boundedMessage(stderr.String()))
	}
	if stdout.exceeded {
		return nil, errors.New("git output exceeded its safety limit")
	}
	return bytes.Clone(stdout.Bytes()), nil
}

func ValidateRepository(ctx context.Context, config RepositoryConfig) error {
	info, err := os.Stat(config.Path)
	if err != nil || !info.IsDir() {
		return errors.New("repository path is not a directory")
	}
	repository := GitRepository{Config: config}
	remote, err := repository.run(ctx, 4096, "remote", "get-url", "origin")
	if err != nil {
		return err
	}
	if strings.TrimSpace(string(remote)) != config.RemoteURL {
		return errors.New("repository origin does not match configured remote_url")
	}
	return nil
}

func splitNUL(data []byte) []string {
	parts := bytes.Split(data, []byte{0})
	result := make([]string, 0, len(parts))
	for _, part := range parts {
		if len(part) != 0 {
			result = append(result, string(part))
		}
	}
	return result
}

func changedServices(paths []string, manifest *Manifest) ([]string, error) {
	set := make(map[string]struct{})
	for _, changed := range paths {
		first, remainder, ok := strings.Cut(changed, "/")
		if !ok || remainder == "" || !validRelativePath(changed) {
			return nil, fmt.Errorf("protected repository path changed: %s", changed)
		}
		if _, exists := manifest.Service(first); !exists {
			return nil, fmt.Errorf("unknown service path changed: %s", changed)
		}
		set[first] = struct{}{}
	}
	services := make([]string, 0, len(set))
	for _, service := range manifest.Services {
		if _, ok := set[service.Slug]; ok {
			services = append(services, service.Slug)
		}
	}
	return services, nil
}

func checkAllowedPaths(service string, paths []string, allowed []string) error {
	prefix := service + "/"
	for _, changed := range paths {
		if !strings.HasPrefix(changed, prefix) {
			return fmt.Errorf("protected path modified: %s", changed)
		}
		relative := strings.TrimPrefix(changed, prefix)
		if !validRelativePath(relative) || !pathAllowed(relative, allowed) {
			return fmt.Errorf("protected path modified: %s", changed)
		}
	}
	return nil
}
