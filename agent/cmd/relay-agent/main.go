package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/zuens2020/mcp-relay/agent/internal/backup"
	"github.com/zuens2020/mcp-relay/agent/internal/config"
	"github.com/zuens2020/mcp-relay/agent/internal/detect"
	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
	syncer "github.com/zuens2020/mcp-relay/agent/internal/sync"
	"github.com/zuens2020/mcp-relay/agent/internal/wsclient"
)

const agentVersion = "0.2.5"

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cmd := os.Args[1]
	if cmd == "version" || cmd == "-v" || cmd == "--version" {
		fmt.Printf("relay-agent %s\n", agentVersion)
		return
	}

	// backup subcommands share flag parsing lightly
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	sandbox := fs.Bool("sandbox", false, "force sandbox mode")
	dryRun := fs.Bool("dry-run", false, "diff only, no writes")
	live := fs.Bool("live", false, "force live mode (default)")
	relayURL := fs.String("relay-url", "", "override relay URL")
	skillsRoot := fs.String("skills-root", "", "local skills-repo path for pack install")
	interval := fs.Duration("interval", 15*time.Minute, "watch interval")
	latest := fs.Bool("latest", false, "use latest backup (restore)")
	_ = fs.Parse(os.Args[2:])

	mode := paths.Mode("")
	switch {
	case *dryRun:
		mode = paths.ModeDryRun
	case *sandbox:
		mode = paths.ModeSandbox
	case *live:
		mode = paths.ModeLive
	}

	res, err := paths.Create(mode, "", "")
	must(err)
	must(res.EnsureLayout())

	cfg, err := config.Load(res.ConfigPath())
	must(err)
	if cfg.AgentVersion == "" || cfg.AgentVersion == "0.1.0" {
		cfg.AgentVersion = agentVersion
	}
	if *relayURL != "" {
		cfg.RelayURL = *relayURL
	}

	switch cmd {
	case "doctor":
		cmdDoctor(res, cfg)
	case "detect":
		cmdDetect(res)
	case "register":
		must(doRegister(res, cfg))
	case "sync":
		must(doSync(res, cfg, *skillsRoot))
	case "connect":
		cl := syncer.New(cfg, res)
		for {
			if err := wsclient.Run(cl); err != nil {
				fmt.Fprintf(os.Stderr, "connect error: %v\n", err)
			}
			time.Sleep(5 * time.Second)
		}
	case "watch":
		cl := syncer.New(cfg, res)
		go func() {
			for {
				if err := wsclient.Run(cl); err != nil {
					fmt.Fprintf(os.Stderr, "ws error: %v\n", err)
				}
				time.Sleep(5 * time.Second)
			}
		}()
		for {
			if err := doSync(res, cfg, *skillsRoot); err != nil {
				fmt.Fprintf(os.Stderr, "sync error: %v\n", err)
			}
			time.Sleep(*interval)
		}
	case "init-sandbox":
		must(cmdInitSandbox(res))
	case "backup":
		must(cmdBackup(res, fs.Args(), *latest))
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `relay-agent — MCP Relay client (default mode: live)

Commands:
  doctor [--sandbox|--dry-run|--live]
  detect
  register [--relay-url URL]
  sync [--dry-run|--sandbox] [--skills-root DIR]
       backup local MCP configs, bootstrap empty server configs, then pull
  connect
       maintain WebSocket for push delivery
  watch [--interval 15m]
       WebSocket push + periodic sync fallback
  backup list
  backup restore --latest
  init-sandbox
  version

Env:
  RELAY_MODE=sandbox|dry-run|live   (default live)
  RELAY_ROOT                        (default ~/.mcp-relay)
  RELAY_SANDBOX_ROOT, RELAY_PROFILE
`)
}

func cmdBackup(res *paths.Resolver, args []string, latestFlag bool) error {
	sub := "list"
	if len(args) > 0 {
		sub = args[0]
	}
	switch sub {
	case "list":
		list, err := backup.List(res)
		if err != nil {
			return err
		}
		if len(list) == 0 {
			fmt.Println("(no backups)")
			return nil
		}
		for _, p := range list {
			fmt.Println(p)
		}
		return nil
	case "restore":
		dir := ""
		if latestFlag || (len(args) > 1 && args[1] == "--latest") {
			var err error
			dir, err = backup.Latest(res)
			if err != nil {
				return err
			}
		} else if len(args) > 1 {
			dir = args[1]
		} else {
			return fmt.Errorf("usage: backup restore --latest | backup restore <dir>")
		}
		if err := backup.Restore(res, dir); err != nil {
			return err
		}
		fmt.Printf("restored from %s\n", dir)
		return nil
	case "run":
		dir, err := backup.Run(res, nil)
		if err != nil {
			return err
		}
		fmt.Println(dir)
		return nil
	default:
		return fmt.Errorf("unknown backup subcommand %s", sub)
	}
}

func cmdDoctor(res *paths.Resolver, cfg *config.Config) {
	fmt.Printf("mode=%s home=%s sandbox_root=%s relay_root=%s\n", res.Mode, res.Home(), res.SandboxRoot, res.RelayRoot)
	fmt.Printf("relay_url=%s allow_live_writes=%v device_id=%s version=%s\n", cfg.RelayURL, cfg.AllowLiveWrites, cfg.DeviceID, agentVersion)
	det := detect.Run(res)
	fmt.Printf("profile=%s\n", det.Profile)
	for _, t := range paths.Targets {
		path, _ := res.MCPPath(t)
		detected := contains(det.Targets, t)
		fmt.Printf("  %-12s detected=%-5v path=%s\n", t, detected, path)
	}
	for _, n := range det.Notes {
		fmt.Printf("note: %s\n", n)
	}
}

func cmdDetect(res *paths.Resolver) {
	det := detect.Run(res)
	b, _ := json.MarshalIndent(det, "", "  ")
	fmt.Println(string(b))
}

func doRegister(res *paths.Resolver, cfg *config.Config) error {
	det := detect.Run(res)
	c := syncer.New(cfg, res)
	if err := c.Register(det); err != nil {
		return err
	}
	fmt.Printf("registered device_id=%s targets=%v\n", cfg.DeviceID, cfg.Targets)
	return nil
}

func doSync(res *paths.Resolver, cfg *config.Config, skillsRoot string) error {
	if cfg.DeviceToken == "" {
		if err := doRegister(res, cfg); err != nil {
			return err
		}
	}
	if skillsRoot == "" {
		wd, _ := os.Getwd()
		cand := filepath.Join(wd, "skills-repo")
		if st, err := os.Stat(cand); err == nil && st.IsDir() {
			skillsRoot = cand
		}
	}
	return syncer.New(cfg, res).Sync(skillsRoot)
}

func cmdInitSandbox(res *paths.Resolver) error {
	res.Mode = paths.ModeSandbox
	if err := res.EnsureLayout(); err != nil {
		return err
	}
	pairs := [][2]string{
		{filepath.Join(res.RealHome, ".cursor", "mcp.json"), filepath.Join(res.Home(), ".cursor", "mcp.json")},
		{filepath.Join(res.RealHome, ".codex", "config.toml"), filepath.Join(res.Home(), ".codex", "config.toml")},
		{filepath.Join(res.RealHome, ".claude.json"), filepath.Join(res.Home(), ".claude.json")},
		{filepath.Join(res.RealHome, ".pi", "agent", "mcp.json"), filepath.Join(res.Home(), ".pi", "agent", "mcp.json")},
		{filepath.Join(res.RealHome, ".hermes", "config.yaml"), filepath.Join(res.Home(), ".hermes", "config.yaml")},
	}
	for _, p := range pairs {
		src, dst := p[0], p[1]
		if _, err := os.Stat(src); err != nil {
			continue
		}
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return err
		}
		b, err := os.ReadFile(src)
		if err != nil {
			return err
		}
		if err := fsutil.AtomicWrite(res, dst, b); err != nil {
			return err
		}
		fmt.Printf("copied %s -> %s\n", src, dst)
	}
	return nil
}

func must(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

func contains(ss []string, want string) bool {
	for _, s := range ss {
		if strings.EqualFold(s, want) {
			return true
		}
	}
	return false
}
