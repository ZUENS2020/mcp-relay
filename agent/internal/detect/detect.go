package detect

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/zuens2020/mcp-relay/agent/internal/paths"
)

type DetectedAgent struct {
	ID      string `json:"id"`
	Path    string `json:"path,omitempty"`
	Present bool   `json:"present"`
}

type Result struct {
	Profile  string          `json:"profile"`
	Targets  []string        `json:"targets"`
	Detected []DetectedAgent `json:"detected,omitempty"`
	Notes    []string        `json:"notes,omitempty"`
}

func Profile(home string) string {
	if forced := os.Getenv("RELAY_PROFILE"); forced != "" {
		return forced
	}
	switch runtime.GOOS {
	case "windows":
		return "windows-desktop"
	case "darwin":
		return "mac-laptop"
	default:
		return "linux-server"
	}
}

func inPATH(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func Targets(r *paths.Resolver) ([]string, []string) {
	home := r.Home()
	usePATH := r.Mode != paths.ModeSandbox // sandbox: only fake home tree
	var found []string
	var notes []string

	if exists(filepath.Join(home, ".cursor")) || exists(filepath.Join(home, ".cursor", "mcp.json")) || (usePATH && inPATH("cursor")) {
		found = append(found, "cursor")
	}
	hermesHome := os.Getenv("HERMES_HOME")
	if hermesHome == "" || r.Mode == paths.ModeSandbox {
		hermesHome = filepath.Join(home, ".hermes")
	}
	if exists(filepath.Join(hermesHome, "config.yaml")) || exists(hermesHome) || exists(filepath.Join(hermesHome, "bin", "hermes")) || (usePATH && inPATH("hermes")) {
		found = append(found, "hermes")
	}
	piDir := os.Getenv("PI_CODING_AGENT_DIR")
	if piDir == "" || r.Mode == paths.ModeSandbox {
		piDir = filepath.Join(home, ".pi", "agent")
	}
	if exists(piDir) || (usePATH && inPATH("pi")) {
		found = append(found, "pi")
		ext := filepath.Join(piDir, "extensions")
		if exists(ext) {
			entries, _ := os.ReadDir(ext)
			hasAdapter := false
			for _, e := range entries {
				n := strings.ToLower(e.Name())
				if strings.Contains(n, "mcp") {
					hasAdapter = true
					break
				}
			}
			if !hasAdapter {
				notes = append(notes, "pi: mcp.json will be written; install pi-mcp-adapter to load MCP")
			}
		} else {
			notes = append(notes, "pi: mcp.json will be written; install pi-mcp-adapter to load MCP")
		}
	}
	if exists(filepath.Join(home, ".codex", "config.toml")) || exists(filepath.Join(home, ".codex")) || (usePATH && inPATH("codex")) {
		found = append(found, "codex")
	}
	// Claude Code: ~/.claude.json or ~/.claude/ or claude binary.
	// Do NOT treat Claude Desktop (%APPDATA%/Claude) as claude-code.
	if exists(filepath.Join(home, ".claude.json")) || exists(filepath.Join(home, ".claude")) || (usePATH && inPATH("claude")) {
		found = append(found, "claude-code")
	}

	return found, notes
}

func Run(r *paths.Resolver) Result {
	t, notes := Targets(r)
	detected := make([]DetectedAgent, 0, len(t))
	for _, id := range t {
		path, err := r.MCPPath(id)
		if err != nil {
			path = ""
		}
		detected = append(detected, DetectedAgent{ID: id, Path: path, Present: true})
	}
	return Result{Profile: Profile(r.RealHome), Targets: t, Detected: detected, Notes: notes}
}
