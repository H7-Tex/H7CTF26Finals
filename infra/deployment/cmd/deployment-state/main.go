package main

import (
	"errors"
	"flag"
	"fmt"
	"log"
	"os"

	orchestrator "github.com/h7tex/h7ctf26finals/infra/deployment"
)

func main() {
	if err := run(); err != nil {
		log.Printf("Deployment state operation failed: %v", err)
		os.Exit(1)
	}
}

func run() error {
	if os.Geteuid() != 0 {
		return errors.New("deployment state operations require root")
	}
	if len(os.Args) < 2 {
		return errors.New("usage: deployment-orchestrator-state <backup|restore>")
	}
	switch os.Args[1] {
	case "backup":
		flags := flag.NewFlagSet("backup", flag.ContinueOnError)
		config := flags.String("config", "/etc/deployment-orchestrator/config.json", "orchestrator configuration")
		services := flags.String("services", "/etc/deployment-orchestrator/services.json", "reviewed services manifest")
		destination := flags.String("destination", "", "root-owned backup destination")
		if err := flags.Parse(os.Args[2:]); err != nil {
			return err
		}
		if flags.NArg() != 0 || *destination == "" {
			return errors.New("backup requires --destination and no positional arguments")
		}
		path, err := orchestrator.BackupState(*config, *services, *destination)
		if err != nil {
			return err
		}
		fmt.Println(path)
		return nil
	case "restore":
		flags := flag.NewFlagSet("restore", flag.ContinueOnError)
		config := flags.String("config", "/etc/deployment-orchestrator/config.json", "orchestrator configuration")
		services := flags.String("services", "/etc/deployment-orchestrator/services.json", "reviewed services manifest")
		backup := flags.String("backup", "", "exact backup directory")
		confirmTeam := flags.String("confirm-team", "", "exact team UUID confirmation")
		if err := flags.Parse(os.Args[2:]); err != nil {
			return err
		}
		if flags.NArg() != 0 || *backup == "" || *confirmTeam == "" {
			return errors.New("restore requires --backup and --confirm-team with no positional arguments")
		}
		return orchestrator.RestoreState(*config, *services, *backup, *confirmTeam)
	default:
		return fmt.Errorf("unknown state operation %q", os.Args[1])
	}
}
