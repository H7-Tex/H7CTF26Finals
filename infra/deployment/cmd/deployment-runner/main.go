package main

import (
	"context"
	"errors"
	"log"
	"os"

	orchestrator "github.com/h7tex/h7ctf26finals/infra/deployment"
)

const executorSocket = "/run/deployment-executor/control.sock"

func main() {
	if err := run(); err != nil {
		log.Printf("deployment runner failed")
		os.Exit(1)
	}
}

func run() error {
	if len(os.Args) != 2 {
		return errors.New("usage: runner <build|gate|promote|rollback|health>")
	}
	return orchestrator.RunAdapter(context.Background(), executorSocket, os.Args[1], os.Stdin, os.Stdout)
}
