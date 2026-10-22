package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	orchestrator "github.com/h7tex/h7ctf26finals/infra/deployment"
)

const (
	policyPath     = "/etc/deployment-executor/policy.json"
	stateDirectory = "/var/lib/deployment-executor"
)

func main() {
	if err := run(); err != nil {
		log.Printf("Deployment Executor stopped: %v", err)
		os.Exit(1)
	}
}

func run() error {
	validateOnly := len(os.Args) == 2 && os.Args[1] == "validate"
	if len(os.Args) != 1 && !validateOnly {
		return errors.New("usage: deployment-executor [validate]")
	}
	policy, err := orchestrator.LoadExecutorPolicy(policyPath)
	if err != nil {
		return err
	}
	lock, err := orchestrator.AcquireStateLock(stateDirectory)
	if err != nil {
		return err
	}
	defer lock.Close()
	executor, err := orchestrator.NewExecutor(policy, stateDirectory)
	if err != nil {
		return err
	}
	if validateOnly {
		return nil
	}
	listener, err := activatedListener()
	if err != nil {
		return err
	}
	defer listener.Close()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	return orchestrator.ServeExecutor(ctx, listener, executor)
}

func activatedListener() (*net.UnixListener, error) {
	pid, err := strconv.Atoi(os.Getenv("LISTEN_PID"))
	if err != nil || pid != os.Getpid() || os.Getenv("LISTEN_FDS") != "1" || os.Getenv("LISTEN_FDNAMES") != "control" {
		return nil, errors.New("exactly one named systemd socket is required")
	}
	file := os.NewFile(3, "deployment-executor.socket")
	if file == nil {
		return nil, errors.New("systemd socket descriptor is unavailable")
	}
	defer file.Close()
	listener, err := net.FileListener(file)
	if err != nil {
		return nil, err
	}
	unixListener, ok := listener.(*net.UnixListener)
	if !ok {
		listener.Close()
		return nil, fmt.Errorf("activated listener is %T, not AF_UNIX", listener)
	}
	return unixListener, nil
}
