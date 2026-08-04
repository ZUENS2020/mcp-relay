package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/zuens2020/mcp-relay/agent/internal/config"
	"github.com/zuens2020/mcp-relay/agent/internal/detect"
	"github.com/zuens2020/mcp-relay/agent/internal/fsutil"
	"github.com/zuens2020/mcp-relay/agent/internal/paths"
	syncer "github.com/zuens2020/mcp-relay/agent/internal/sync"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	sandbox := fs.Bool("sandbox", false, "force sandbox mode")
	dryRun := fs.Bool("dry-run", false, "diff only, no writes")
	live := fs.Bool("live", false, "write real home (requires allow_live_writes)")
	relayURL := fs.String("relay-url", "", "override relay URL")
	skillsRoot := fs.String("skills-root", "", "local skills-repo path for pack install")
	interval := fs.Duration("interval", 15*time.Minute, "watch interval")
	_ = fs.Parse(os.Args[2:])

	mode := paths.Mode("")
	switch {
	case *dryRun:
		mode = paths.ModeDryRun
	case *live:
		mode = paths.ModeLive
	case *sandbox:
		mode = paths.ModeSandbox
	}

	res, err := paths.Create(mode, "", "")
	must(err)
	must(res.EnsureLayout())

	cfg, err := config.Load(res.ConfigPath())
	must(err)
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
	case "watch":
		for {
			if err := doSync(res, cfg, *skillsRoot); err != nil {
				fmt.Fprintf(os.Stderr, "sync error: %v\n", err)
			}
			time.Sleep(*interval)
		}
	case "init-sandbox":
		must(cmdInitSandbox(res))
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `relay-agent — MCP Relay client (default mode: sandbox)

Commands:
  doctor [--sandbox|--dry-run|--live]
  detect
  register [--relay-url URL]
  sync [--dry-run|--live|--sandbox] [--skills-root DIR]
  watch [--interval 15m]
  init-sandbox

Env:
  RELAY_MODE=sandbox|dry-run|live
  RELAY_ROOT, RELAY_SANDBOX_ROOT, RELAY_PROFILE
`)
}

func cmdDoctor(res *paths.Resolver, cfg *config.Config) {
	fmt.Printf("mode=%s home=%s sandbox_root=%s relay_root=%s\n", res.Mode, res.Home(), res.SandboxRoot, res.RelayRoot)
	fmt.Printf("relay_url=%s allow_live_writes=%v device_id=%s\n", cfg.RelayURL, cfg.AllowLiveWrites, cfg.DeviceID)
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
		{filepath.Join(res.RealHome, ".hermes", "config.yaml"), filepath.Join(res.Home(), ".hermes", "config.yaml")},
		{filepath.Join(res.RealHome, ".pi", "agent", "mcp.json"), filepath.Join(res.Home(), ".pi", "agent", "mcp.json")},
	}
	for _, p := range pairs {
		b, err := os.ReadFile(p[0])
		if err != nil {
			continue
		}
		s := strings.ReplaceAll(string(b), "Bearer ", "Bearer ***")
		if err := fsutil.AtomicWrite(res, p[1], []byte(s)); err != nil {
			return err
		}
		fmt.Printf("copied %s -> %s\n", p[0], p[1])
	}
	for _, d := range []string{
		filepath.Join(res.Home(), ".pi", "agent"),
		filepath.Join(res.Home(), ".cursor"),
		filepath.Join(res.Home(), ".codex"),
		filepath.Join(res.Home(), ".claude"),
	} {
		_ = os.MkdirAll(d, 0o755)
	}
	return nil
}

func contains(xs []string, v string) bool {
	for _, x := range xs {
		if x == v {
			return true
		}
	}
	return false
}

func must(err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}
