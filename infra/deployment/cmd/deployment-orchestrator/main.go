package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	orchestrator "github.com/h7tex/h7ctf26finals/infra/deployment"
)

func main() {
	if err := run(); err != nil {
		log.Printf("Deployment Orchestrator stopped: %v", err)
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) < 2 {
		return errors.New("usage: deployment-orchestrator <host-preflight|validate|initialize|serve> --config PATH")
	}
	command := os.Args[1]
	if command == "host-preflight" {
		if len(os.Args) != 2 {
			return errors.New("host-preflight takes no arguments")
		}
		return orchestrator.ValidateInstalledHost()
	}
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	configPath := flags.String("config", "/etc/deployment-orchestrator/config.json", "configuration file")
	if err := flags.Parse(os.Args[2:]); err != nil {
		return err
	}
	cfg, manifest, err := orchestrator.LoadConfig(*configPath)
	if err != nil {
		return err
	}
	manifestHash, err := orchestrator.ManifestHash(cfg.ServicesFile)
	if err != nil {
		return err
	}
	validationContext, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	if err := orchestrator.ValidateRepository(validationContext, cfg.Repository); err != nil {
		return err
	}

	switch command {
	case "validate":
		fmt.Println("Deployment Orchestrator configuration is valid")
		return nil
	case "initialize":
		initializeContext, initializeCancel := context.WithTimeout(context.Background(), 10*time.Minute)
		defer initializeCancel()
		return initialize(initializeContext, cfg, manifest, manifestHash)
	case "serve":
		return serve(cfg, manifest, manifestHash)
	default:
		return fmt.Errorf("unknown command %q", command)
	}
}

func initialize(ctx context.Context, cfg *orchestrator.Config, manifest *orchestrator.Manifest, manifestHash string) error {
	lock, err := orchestrator.AcquireStateLock(cfg.StateDirectory)
	if err != nil {
		return err
	}
	defer lock.Close()
	repository := orchestrator.GitRepository{Config: cfg.Repository}
	head, err := repository.FetchRemoteHead(ctx)
	if err != nil {
		return err
	}
	if head != cfg.Repository.InitialCommit {
		return errors.New("remote main no longer matches the approved initial commit")
	}
	runner := orchestrator.CommandRunner{Command: cfg.RunnerCommand}
	if err := orchestrator.VerifyFactoryState(ctx, cfg, manifest, runner); err != nil {
		return err
	}
	if err := orchestrator.InitializeStore(cfg.StateDirectory, orchestrator.InitialState(cfg, manifest, manifestHash)); err != nil {
		return err
	}
	store, err := orchestrator.OpenStore(cfg, manifestHash)
	if err != nil {
		return err
	}
	return store.Update(orchestrator.AuditEvent{Action: "commissioning", Outcome: "initialized", ActorID: "operator", TraceID: "commissioning-initialize", Commit: head}, nil)
}

func serve(cfg *orchestrator.Config, manifest *orchestrator.Manifest, manifestHash string) error {
	lock, err := orchestrator.AcquireStateLock(cfg.StateDirectory)
	if err != nil {
		return err
	}
	defer lock.Close()
	store, err := orchestrator.OpenStore(cfg, manifestHash)
	if err != nil {
		return err
	}
	engine := orchestrator.NewEngine(
		cfg, manifest, store, orchestrator.GitRepository{Config: cfg.Repository},
		orchestrator.CommandRunner{Command: cfg.RunnerCommand},
		orchestrator.HTTPQuietWindow{URL: cfg.TickURL},
	)
	server := (&orchestrator.Server{Config: cfg, Store: store, Engine: engine}).HTTPServer()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	engineDone := make(chan struct{})
	go func() {
		defer close(engineDone)
		engine.Run(ctx)
	}()
	errorsChannel := make(chan error, 1)
	go func() {
		log.Printf("Deployment Orchestrator ready team=%d address=%s", cfg.TeamNumber, cfg.ListenAddress)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errorsChannel <- err
		}
	}()
	var listenerErr error
	select {
	case <-ctx.Done():
	case err := <-errorsChannel:
		listenerErr = err
	}
	stop()
	shutdownContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	shutdownErr := server.Shutdown(shutdownContext)
	<-engineDone
	if listenerErr != nil {
		return listenerErr
	}
	return shutdownErr
}
