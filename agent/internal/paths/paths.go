package paths

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type Mode string

const (
	ModeSandbox Mode = "sandbox"
	ModeDryRun  Mode = "dry-run"
	ModeLive    Mode = "live"
)

var Targets = []string{"cursor", "hermes", "pi", "codex", "claude-code"}

type Resolver struct {
	Mode         Mode
	RealHome     string
	RelayRoot    string
	SandboxRoot  string
}

func Create(mode Mode, home, sandboxRoot string) (*Resolver, error) {
	if home == "" {
		h, err := os.UserHomeDir()
		if err != nil {
			return nil, err
		}
		home = h
	}
	relayRoot := os.Getenv("RELAY_ROOT")
	if relayRoot == "" {
		relayRoot = filepath.Join(home, ".mcp-relay")
	}
	if sandboxRoot == "" {
		sandboxRoot = os.Getenv("RELAY_SANDBOX_ROOT")
	}
	if sandboxRoot == "" {
		sandboxRoot = filepath.Join(relayRoot, "sandbox")
	}
	if mode == "" {
		env := strings.ToLower(strings.TrimSpace(os.Getenv("RELAY_MODE")))
		switch Mode(env) {
		case ModeSandbox, ModeDryRun, ModeLive:
			mode = Mode(env)
		default:
			mode = ModeLive
		}
	}
	return &Resolver{Mode: mode, RealHome: home, RelayRoot: relayRoot, SandboxRoot: sandboxRoot}, nil
}

func (r *Resolver) Home() string {
	if r.Mode == ModeSandbox {
		return filepath.Join(r.SandboxRoot, "home")
	}
	return r.RealHome
}

func (r *Resolver) ManagedDir() string {
	if r.Mode == ModeSandbox {
		return filepath.Join(r.SandboxRoot, "managed")
	}
	return filepath.Join(r.RelayRoot, "managed")
}

func (r *Resolver) BackupsDir() string {
	if r.Mode == ModeSandbox {
		return filepath.Join(r.SandboxRoot, "backups")
	}
	return filepath.Join(r.RelayRoot, "backups")
}

func (r *Resolver) StatePath() string {
	if r.Mode == ModeSandbox {
		return filepath.Join(r.SandboxRoot, "state.json")
	}
	return filepath.Join(r.RelayRoot, "state.json")
}

func (r *Resolver) ConfigPath() string {
	return filepath.Join(r.RelayRoot, "config.yaml")
}

func (r *Resolver) EnsureLayout() error {
	dirs := []string{r.RelayRoot, r.BackupsDir(), r.ManagedDir(), filepath.Join(r.RelayRoot, "logs")}
	if r.Mode == ModeSandbox {
		dirs = append(dirs, r.Home())
	}
	for _, d := range dirs {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	return nil
}

func (r *Resolver) AssertWritable(path string) error {
	abs, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	if r.Mode == ModeDryRun {
		return fmt.Errorf("dry-run: refuse write to %s", abs)
	}
	if r.Mode == ModeSandbox {
		root, err := filepath.Abs(r.SandboxRoot)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, abs)
		if err != nil || strings.HasPrefix(rel, "..") {
			return fmt.Errorf("sandbox gate: %s not under %s", abs, root)
		}
		return nil
	}
	// live
	home, _ := filepath.Abs(r.RealHome)
	relay, _ := filepath.Abs(r.RelayRoot)
	relH, errH := filepath.Rel(home, abs)
	relR, errR := filepath.Rel(relay, abs)
	okH := errH == nil && !strings.HasPrefix(relH, "..")
	okR := errR == nil && !strings.HasPrefix(relR, "..")
	if !okH && !okR {
		return fmt.Errorf("live gate: %s outside allowed roots", abs)
	}
	return nil
}

func (r *Resolver) MCPPath(target string) (string, error) {
	h := r.Home()
	switch target {
	case "cursor":
		return filepath.Join(h, ".cursor", "mcp.json"), nil
	case "hermes":
		return filepath.Join(h, ".hermes", "config.yaml"), nil
	case "pi":
		return filepath.Join(h, ".pi", "agent", "mcp.json"), nil
	case "codex":
		return filepath.Join(h, ".codex", "config.toml"), nil
	case "claude-code":
		return filepath.Join(h, ".claude.json"), nil
	default:
		return "", fmt.Errorf("unknown target %s", target)
	}
}

func (r *Resolver) SkillsPath(target, packID string) (string, error) {
	h := r.Home()
	switch target {
	case "cursor":
		return filepath.Join(h, ".cursor", "skills", packID), nil
	case "hermes":
		return filepath.Join(h, ".hermes", "skills", "relay", packID), nil
	case "pi":
		return filepath.Join(h, ".pi", "agent", "skills", packID), nil
	case "codex":
		return filepath.Join(h, ".codex", "skills", packID), nil
	case "claude-code":
		return filepath.Join(h, ".claude", "skills", packID), nil
	default:
		return "", fmt.Errorf("unknown target %s", target)
	}
}
