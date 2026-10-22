package orchestrator

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

const (
	restoreMarkerName             = ".restore-pending.json"
	defaultExecutorStateDirectory = "/var/lib/deployment-executor"
)

type StateLock struct {
	file *os.File
}

func AcquireStateLock(directory string) (*StateLock, error) {
	path := filepath.Join(directory, "offline.lock")
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, fmt.Errorf("open offline state lock: %w", err)
	}
	file := os.NewFile(uintptr(fd), path)
	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, err
	}
	directoryInfo, err := os.Lstat(directory)
	if err != nil {
		file.Close()
		return nil, err
	}
	fileStat, fileOK := info.Sys().(*syscall.Stat_t)
	directoryStat, directoryOK := directoryInfo.Sys().(*syscall.Stat_t)
	if !fileOK || !directoryOK || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || fileStat.Uid != directoryStat.Uid || fileStat.Gid != directoryStat.Gid {
		file.Close()
		return nil, errors.New("offline state lock has unsafe ownership, mode or type")
	}
	if err := syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		file.Close()
		return nil, errors.New("deployment state is in use")
	}
	return &StateLock{file: file}, nil
}

func (l *StateLock) Close() error {
	if l == nil || l.file == nil {
		return nil
	}
	err := syscall.Flock(int(l.file.Fd()), syscall.LOCK_UN)
	closeErr := l.file.Close()
	l.file = nil
	if err != nil {
		return err
	}
	return closeErr
}

type stateBackupMetadata struct {
	SchemaVersion  int       `json:"schema_version"`
	CreatedAt      time.Time `json:"created_at"`
	TeamID         string    `json:"team_id"`
	TeamNumber     int       `json:"team_number"`
	ManifestSHA256 string    `json:"manifest_sha256"`
	StateSHA256    string    `json:"state_sha256"`
	AuditSHA256    string    `json:"audit_sha256"`
}

type restoreMarker struct {
	SchemaVersion int    `json:"schema_version"`
	BackupSHA256  string `json:"backup_sha256"`
}

func BackupState(configPath, servicesPath, destination string) (string, error) {
	return backupState(configPath, servicesPath, destination, 0, 0, defaultExecutorStateDirectory)
}

func backupState(configPath, servicesPath, destination string, backupUID, backupGID uint32, executorStateDirectory string) (string, error) {
	cfg, manifestHash, err := loadBackupInputs(configPath, servicesPath)
	if err != nil {
		return "", err
	}
	lock, err := AcquireStateLock(cfg.StateDirectory)
	if err != nil {
		return "", err
	}
	defer lock.Close()
	executorLock, err := AcquireStateLock(executorStateDirectory)
	if err != nil {
		return "", fmt.Errorf("executor: %w", err)
	}
	defer executorLock.Close()
	if _, err := os.Lstat(filepath.Join(cfg.StateDirectory, restoreMarkerName)); err == nil {
		return "", errors.New("offline restore is incomplete")
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if err := validateOwnedDirectory(destination, backupUID, backupGID); err != nil {
		return "", fmt.Errorf("backup destination: %w", err)
	}
	stateUID, stateGID, err := stateOwner(cfg.StateDirectory)
	if err != nil {
		return "", err
	}
	temporary, err := os.MkdirTemp(destination, ".backup-*")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(temporary)
	if err := os.Chmod(temporary, 0700); err != nil {
		return "", err
	}
	if err := copyPrivateFile(filepath.Join(cfg.StateDirectory, "state.json"), filepath.Join(temporary, "state.json"), stateUID, stateGID, backupUID, backupGID); err != nil {
		return "", err
	}
	if err := copyPrivateFile(filepath.Join(cfg.StateDirectory, "audit.jsonl"), filepath.Join(temporary, "audit.jsonl"), stateUID, stateGID, backupUID, backupGID); err != nil {
		return "", err
	}
	validationConfig := *cfg
	validationConfig.StateDirectory = temporary
	if _, err := OpenStore(&validationConfig, manifestHash); err != nil {
		return "", fmt.Errorf("validate backup state pair: %w", err)
	}
	stateHash, err := fileSHA256(filepath.Join(temporary, "state.json"))
	if err != nil {
		return "", err
	}
	auditHash, err := fileSHA256(filepath.Join(temporary, "audit.jsonl"))
	if err != nil {
		return "", err
	}
	metadata := stateBackupMetadata{
		SchemaVersion: 1, CreatedAt: time.Now().UTC(), TeamID: cfg.TeamID, TeamNumber: cfg.TeamNumber,
		ManifestSHA256: manifestHash, StateSHA256: stateHash, AuditSHA256: auditHash,
	}
	if err := writePrivateJSON(filepath.Join(temporary, "metadata.json"), metadata, backupUID, backupGID); err != nil {
		return "", err
	}
	if err := syncDirectory(temporary); err != nil {
		return "", err
	}
	suffix, err := randomSuffix()
	if err != nil {
		return "", err
	}
	final := filepath.Join(destination, "backup-"+metadata.CreatedAt.Format("20060102T150405Z")+"-"+suffix)
	if err := os.Rename(temporary, final); err != nil {
		return "", err
	}
	if err := syncDirectory(destination); err != nil {
		return "", err
	}
	return final, nil
}

func RestoreState(configPath, servicesPath, backupDirectory, confirmTeamID string) error {
	return restoreState(configPath, servicesPath, backupDirectory, confirmTeamID, 0, 0, defaultExecutorStateDirectory)
}

func restoreState(configPath, servicesPath, backupDirectory, confirmTeamID string, backupUID, backupGID uint32, executorStateDirectory string) error {
	cfg, manifestHash, err := loadBackupInputs(configPath, servicesPath)
	if err != nil {
		return err
	}
	if confirmTeamID != cfg.TeamID {
		return errors.New("restore confirmation does not match configured team")
	}
	lock, err := AcquireStateLock(cfg.StateDirectory)
	if err != nil {
		return err
	}
	defer lock.Close()
	executorLock, err := AcquireStateLock(executorStateDirectory)
	if err != nil {
		return fmt.Errorf("executor: %w", err)
	}
	defer executorLock.Close()
	_, metadataHash, err := validateBackupDirectory(backupDirectory, cfg, manifestHash, backupUID, backupGID)
	if err != nil {
		return err
	}
	stateUID, stateGID, err := stateOwner(cfg.StateDirectory)
	if err != nil {
		return err
	}
	staging, err := os.MkdirTemp(cfg.StateDirectory, ".restore-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(staging)
	if err := os.Chmod(staging, 0700); err != nil {
		return err
	}
	if err := chownPathIfNeeded(staging, stateUID, stateGID); err != nil {
		return err
	}
	if err := copyPrivateFile(filepath.Join(backupDirectory, "state.json"), filepath.Join(staging, "state.json"), backupUID, backupGID, stateUID, stateGID); err != nil {
		return err
	}
	if err := copyPrivateFile(filepath.Join(backupDirectory, "audit.jsonl"), filepath.Join(staging, "audit.jsonl"), backupUID, backupGID, stateUID, stateGID); err != nil {
		return err
	}
	validationConfig := *cfg
	validationConfig.StateDirectory = staging
	if _, err := OpenStore(&validationConfig, manifestHash); err != nil {
		return fmt.Errorf("validate restore state pair: %w", err)
	}
	markerPath := filepath.Join(cfg.StateDirectory, restoreMarkerName)
	marker := restoreMarker{SchemaVersion: 1, BackupSHA256: metadataHash}
	if existing, err := readRestoreMarker(markerPath, backupUID, backupGID); err == nil {
		if existing != marker {
			return errors.New("a different offline restore is incomplete")
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	} else if err := writePrivateJSON(markerPath, marker, backupUID, backupGID); err != nil {
		return err
	}
	if err := replaceFromStaging(filepath.Join(staging, "audit.jsonl"), filepath.Join(cfg.StateDirectory, "audit.jsonl")); err != nil {
		return err
	}
	if err := replaceFromStaging(filepath.Join(staging, "state.json"), filepath.Join(cfg.StateDirectory, "state.json")); err != nil {
		return err
	}
	if err := os.Remove(markerPath); err != nil {
		return err
	}
	if err := syncDirectory(cfg.StateDirectory); err != nil {
		return err
	}
	return nil
}

func loadBackupInputs(configPath, servicesPath string) (*Config, string, error) {
	cfg, err := loadConfigMetadata(configPath)
	if err != nil {
		return nil, "", err
	}
	if _, err := LoadManifest(servicesPath, cfg.ExpectedServices); err != nil {
		return nil, "", err
	}
	manifestHash, err := ManifestHash(servicesPath)
	if err != nil {
		return nil, "", err
	}
	return cfg, manifestHash, nil
}

func validateBackupDirectory(path string, cfg *Config, manifestHash string, ownerUID, ownerGID uint32) (stateBackupMetadata, string, error) {
	if err := validateOwnedDirectory(path, ownerUID, ownerGID); err != nil {
		return stateBackupMetadata{}, "", fmt.Errorf("backup directory: %w", err)
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return stateBackupMetadata{}, "", err
	}
	if len(entries) != 3 || entries[0].Name() != "audit.jsonl" || entries[1].Name() != "metadata.json" || entries[2].Name() != "state.json" {
		return stateBackupMetadata{}, "", errors.New("backup directory must contain exactly audit.jsonl, metadata.json and state.json")
	}
	metadataPath := filepath.Join(path, "metadata.json")
	metadataData, err := readPrivateFile(metadataPath, ownerUID, ownerGID)
	if err != nil {
		return stateBackupMetadata{}, "", err
	}
	var metadata stateBackupMetadata
	if err := decodeStrict(bytes.NewReader(metadataData), maximumExecutorMessage, &metadata); err != nil {
		return stateBackupMetadata{}, "", err
	}
	if metadata.SchemaVersion != 1 || metadata.TeamID != cfg.TeamID || metadata.TeamNumber != cfg.TeamNumber || metadata.ManifestSHA256 != manifestHash || !digestPattern.MatchString("sha256:"+metadata.StateSHA256) || !digestPattern.MatchString("sha256:"+metadata.AuditSHA256) || metadata.CreatedAt.IsZero() {
		return stateBackupMetadata{}, "", errors.New("backup identity does not match configuration")
	}
	for name, expected := range map[string]string{"state.json": metadata.StateSHA256, "audit.jsonl": metadata.AuditSHA256} {
		data, err := readPrivateFile(filepath.Join(path, name), ownerUID, ownerGID)
		if err != nil {
			return stateBackupMetadata{}, "", err
		}
		digest := sha256.Sum256(data)
		if hex.EncodeToString(digest[:]) != expected {
			return stateBackupMetadata{}, "", fmt.Errorf("backup %s digest mismatch", name)
		}
	}
	digest := sha256.Sum256(metadataData)
	return metadata, hex.EncodeToString(digest[:]), nil
}

func stateOwner(directory string) (uint32, uint32, error) {
	info, err := os.Lstat(directory)
	if err != nil {
		return 0, 0, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.IsDir() || info.Mode().Perm() != 0710 {
		return 0, 0, errors.New("state directory has unsafe ownership, mode or type")
	}
	return stat.Uid, stat.Gid, nil
}

func readPrivateFile(path string, uid, gid uint32) ([]byte, error) {
	file, err := openPrivateFile(path, uid, gid)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	return io.ReadAll(file)
}

func copyPrivateFile(source, destination string, sourceUID, sourceGID, destinationUID, destinationGID uint32) error {
	input, err := openPrivateFile(source, sourceUID, sourceGID)
	if err != nil {
		return fmt.Errorf("source %s: %w", filepath.Base(source), err)
	}
	defer input.Close()
	output, err := os.OpenFile(destination, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	failed := true
	defer func() {
		output.Close()
		if failed {
			os.Remove(destination)
		}
	}()
	if err := chownFileIfNeeded(output, destinationUID, destinationGID); err != nil {
		return err
	}
	if _, err := io.Copy(output, input); err != nil {
		return err
	}
	if err := output.Sync(); err != nil {
		return err
	}
	if err := output.Close(); err != nil {
		return err
	}
	failed = false
	return nil
}

func openPrivateFile(path string, uid, gid uint32) (*os.File, error) {
	fd, err := syscall.Open(path, syscall.O_RDONLY|syscall.O_CLOEXEC|syscall.O_NOFOLLOW, 0)
	if err != nil {
		return nil, err
	}
	file := os.NewFile(uintptr(fd), path)
	info, err := file.Stat()
	if err != nil {
		file.Close()
		return nil, err
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || stat.Uid != uid || stat.Gid != gid {
		file.Close()
		return nil, errors.New("file has unsafe ownership, mode or type")
	}
	return file, nil
}

func writePrivateJSON(path string, value any, uid, gid uint32) error {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	file, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	failed := true
	defer func() {
		file.Close()
		if failed {
			os.Remove(path)
		}
	}()
	if err := chownFileIfNeeded(file, uid, gid); err != nil {
		return err
	}
	if _, err := file.Write(data); err != nil {
		return err
	}
	if err := file.Sync(); err != nil {
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	failed = false
	return syncDirectory(filepath.Dir(path))
}

func readRestoreMarker(path string, uid, gid uint32) (restoreMarker, error) {
	data, err := readPrivateFile(path, uid, gid)
	if err != nil {
		return restoreMarker{}, err
	}
	var marker restoreMarker
	if err := decodeStrict(bytes.NewReader(data), maximumExecutorMessage, &marker); err != nil {
		return restoreMarker{}, err
	}
	if marker.SchemaVersion != 1 || !digestPattern.MatchString("sha256:"+marker.BackupSHA256) {
		return restoreMarker{}, errors.New("invalid restore marker")
	}
	return marker, nil
}

func replaceFromStaging(source, destination string) error {
	if err := os.Rename(source, destination); err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(destination))
}

func randomSuffix() (string, error) {
	value := make([]byte, 6)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return hex.EncodeToString(value), nil
}

func chownFileIfNeeded(file *os.File, uid, gid uint32) error {
	if uint32(os.Geteuid()) == uid && uint32(os.Getegid()) == gid {
		return nil
	}
	return file.Chown(int(uid), int(gid))
}

func chownPathIfNeeded(path string, uid, gid uint32) error {
	if uint32(os.Geteuid()) == uid && uint32(os.Getegid()) == gid {
		return nil
	}
	return os.Chown(path, int(uid), int(gid))
}
