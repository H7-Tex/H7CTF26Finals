package orchestrator

import (
	"errors"
	"fmt"
	"os"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

type hostPath struct {
	path      string
	mode      os.FileMode
	uid       uint32
	gid       uint32
	directory bool
}

func ValidateInstalledHost() error {
	account, err := user.Lookup("deploy-orchestrator")
	if err != nil {
		return fmt.Errorf("deployment account: %w", err)
	}
	uid, err := strconv.ParseUint(account.Uid, 10, 32)
	if err != nil {
		return errors.New("deployment account has an invalid uid")
	}
	gid, err := strconv.ParseUint(account.Gid, 10, 32)
	if err != nil {
		return errors.New("deployment account has an invalid gid")
	}
	return validateHostPaths("/", 0, 0, uint32(uid), uint32(gid))
}

func validateHostPaths(root string, rootUID, rootGID, serviceUID, serviceGID uint32) error {
	requirements := []hostPath{
		{path: "/etc/deployment-orchestrator", mode: 0700, uid: rootUID, gid: serviceGID, directory: true},
		{path: "/etc/deployment-orchestrator/config.json", mode: 0600, uid: rootUID, gid: rootGID},
		{path: "/etc/deployment-orchestrator/services.json", mode: 0600, uid: rootUID, gid: rootGID},
		{path: "/etc/deployment-orchestrator/webhook.secret", mode: 0600, uid: rootUID, gid: rootGID},
		{path: "/etc/deployment-orchestrator/anvil.token", mode: 0600, uid: rootUID, gid: rootGID},
		{path: "/usr/local/libexec/deployment-orchestrator/runner", mode: 0755, uid: rootUID, gid: rootGID},
		{path: "/var/lib/deployment-orchestrator", mode: 0700, uid: serviceUID, gid: serviceGID, directory: true},
		{path: "/var/lib/deployment-orchestrator/repository", mode: 0700, uid: serviceUID, gid: serviceGID, directory: true},
		{path: "/var/lib/deployment-orchestrator/state.json", mode: 0600, uid: serviceUID, gid: serviceGID},
		{path: "/var/lib/deployment-orchestrator/audit.jsonl", mode: 0600, uid: serviceUID, gid: serviceGID},
	}
	for _, requirement := range requirements {
		path := filepath.Join(root, strings.TrimPrefix(requirement.path, "/"))
		info, err := os.Lstat(path)
		if err != nil {
			return fmt.Errorf("required host path %s: %w", requirement.path, err)
		}
		if info.Mode()&os.ModeSymlink != 0 || info.IsDir() != requirement.directory || (!requirement.directory && !info.Mode().IsRegular()) {
			return fmt.Errorf("required host path %s has the wrong type", requirement.path)
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !ok || stat.Uid != requirement.uid || stat.Gid != requirement.gid || info.Mode().Perm() != requirement.mode {
			return fmt.Errorf("required host path %s has unsafe ownership or mode", requirement.path)
		}
	}
	return nil
}
